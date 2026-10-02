"""NMS gate tests, driven over a local UDP command channel.

The channel listens on 127.0.0.1:47801 and is polled once per rendered frame on
the game thread, so commands run exactly where game calls are safe. Send one
command per datagram; the reply is one JSON datagram. Client:
    python spikes/nms/ctl.py <command> [args]

Player (gate test 1):
  status                 position, frame time, mode flags
  nudge [m]              one SetToPosition, m metres along the player's up axis
  hold [secs] [m]        hold the player m metres up for secs; reports the error
                         early vs late in the hold (fixed offset vs lag)
  circle on|off          3 m circle, 10 s period, every frame
Ship (gate test 2), handled by ctl_ship.py (load it with: loadmod ctl_ship.py):
  ship cruise|hold|off   per-frame velocity override after NMS's flight code
  ship spin on|off       per-frame SetAngularVelocity(0)
  ship status

NMS pauses when its window is not focused; commands still arrive, but nothing
moves until the game runs again.
All pyMHF log output is also copied to spikes/nms/logs/pymhf.log.
"""

import csv
import ctypes
import json
import logging
import math
import os
import socket
import time

from pymhf import Mod

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_root = logging.getLogger()
if not any(getattr(h, "_constellation", False) for h in _root.handlers):
    _fh = logging.FileHandler(os.path.join(LOG_DIR, "pymhf.log"), encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _fh._constellation = True
    _root.addHandler(_fh)

logger = logging.getLogger("ctl")

HOST, PORT = "127.0.0.1", 47801
RADIUS_M, PERIOD_S = 3.0, 10.0
CRUISE_MPS, WEAVE_MPS, WEAVE_PERIOD_S = 60.0, 30.0, 8.0


def _v(x, y, z):
    return basic.Vector3f(x, y, z)


def _norm(x, y, z):
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / n, y / n, z / n)


def _player_matrix():
    player = gameData.player
    return None if player is None else GetNodeAbsoluteTransMatrix(player.mRootNode)


def _csv(name, header):
    f = open(os.path.join(LOG_DIR, name), "a", newline="")
    w = csv.writer(f)
    w.writerow(header)
    f.flush()
    return f, w


class CtlPlayer(Mod):
    __author__ = "Constellation"
    __description__ = "Gate test 1 + UDP command channel"

    def __init__(self):
        super().__init__()
        self.sock = None
        self.center = self.up = self.right = self.at = None
        self.circling = False
        self.t0 = 0.0
        self.last_target = None
        self.circle_errs = []
        self.hold_until = 0.0
        self.hold_target = None
        self.hold_frames = 0
        self.hold_errs = []
        self.hold_result = None
        self.frame_dts = []
        self.last_frame = None
        self.last_report = time.perf_counter()
        self.f, self.out = _csv("ctl_player.csv", ["t", "event", "frame_ms_mean", "frame_ms_p95",
                                                   "err_m_mean", "err_m_max", "note"])
        import builtins

        builtins._constellation_gen = id(self)
        self._open_socket()

    def _open_socket(self):
        # "Reload Mod" re-imports this file but the old socket stays bound, so
        # keep one socket for the life of the game process.
        import builtins

        s = getattr(builtins, f"_constellation_ctl_sock_{PORT}", None)
        if s is None:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.bind((HOST, PORT))
                s.setblocking(False)
                setattr(builtins, f"_constellation_ctl_sock_{PORT}", s)
            except OSError:
                logger.exception("could not open the command channel")
                return
        self.sock = s
        logger.info(f"command channel on udp://{HOST}:{PORT}")

    def _row(self, event, note="", fm=0.0, fp=0.0, em=0.0, ex=0.0):
        self.out.writerow([f"{time.time():.3f}", event, f"{fm:.2f}", f"{fp:.2f}", f"{em:.3f}", f"{ex:.3f}", note])
        self.f.flush()

    # ---- game calls ---------------------------------------------------------
    def _capture(self):
        m = _player_matrix()
        if m is None:
            return False
        self.center = (m.pos.x, m.pos.y, m.pos.z)
        self.up, self.right, self.at = m.up, m.right, m.at
        return True

    def _set(self, x, y, z):
        player = gameData.player
        if player is None or self.at is None:
            return False
        pos = basic.cTkBigPos(_v(x, y, z), _v(0, 0, 0))
        direction = _v(self.at.x, self.at.y, self.at.z)
        vel = _v(0, 0, 0)
        player.SetToPosition(ctypes.byref(pos), ctypes.byref(direction), ctypes.byref(vel))
        return True

    def _up_from_center(self, metres):
        cx, cy, cz = self.center
        return (cx + metres * self.up.x, cy + metres * self.up.y, cz + metres * self.up.z)

    # ---- commands -----------------------------------------------------------
    def _handle(self, words):
        cmd = words[0] if words else "status"
        if cmd == "status":
            m = _player_matrix()
            dts = self.frame_dts or [0.0]
            return {
                "pos": None if m is None else [round(m.pos.x, 3), round(m.pos.y, 3), round(m.pos.z, 3)],
                "frame_ms": round(sum(dts) / len(dts), 1),
                "circling": self.circling,
                "holding": bool(self.hold_until),
                "last_hold": self.hold_result,
                "ship_loaded": getattr(__import__("builtins"), "_constellation_ship", None) is not None,
            }
        if cmd == "nudge":
            metres = float(words[1]) if len(words) > 1 else 2.0
            if not self._capture():
                return {"error": "no player"}
            target = self._up_from_center(metres)
            self._set(*target)
            self._row("nudge", f"target={target}")
            return {"ok": True, "target": target}
        if cmd == "hold":
            secs = float(words[1]) if len(words) > 1 else 3.0
            metres = float(words[2]) if len(words) > 2 else 2.0
            if not self._capture():
                return {"error": "no player"}
            self.hold_target = self._up_from_center(metres)
            self.hold_until = time.perf_counter() + secs
            self.hold_frames = 0
            self.hold_errs = []
            self.hold_result = None
            self._row("hold_start", f"target={self.hold_target} secs={secs}")
            return {"ok": True, "target": self.hold_target, "secs": secs}
        if cmd == "circle":
            on = len(words) < 2 or words[1] == "on"
            if on:
                if not self._capture():
                    return {"error": "no player"}
                self.t0 = time.perf_counter()
                self.circle_errs.clear()
                self.last_target = None
            self.circling = on
            self._row("circle", "on" if on else "off")
            return {"ok": True, "circling": on}
        if cmd == "ship":
            mod = getattr(__import__("builtins"), "_constellation_ship", None)
            if mod is None:
                return {"error": "ship mod not loaded - send: loadmod ctl_ship.py (or restart)"}
            return mod.handle(words[1:])
        # Any runtime-loaded mod can register builtins._constellation_<name> with a
        # handle(words) method and receive "<name> ..." commands without reloading this file.
        other = getattr(__import__("builtins"), f"_constellation_{cmd}", None)
        if other is not None and hasattr(other, "handle"):
            return other.handle(words[1:])
        if cmd == "unload" and len(words) > 1:
            # Detach every hook of a loaded mod (by class name) without reloading anything.
            from pymhf.core.mod_loader import mod_manager

            mod = mod_manager.mods.get(words[1])
            if mod is None:
                return {"error": f"no mod {words[1]!r}", "loaded": list(mod_manager.mods)}
            removed = []
            for hook in mod.hooks:
                if (fh := mod_manager.hook_manager._get_funchook(hook)) is not None:
                    fh.remove_detour(hook)
                    removed.append(hook._hook_func_name)
            return {"ok": True, "removed": removed}
        if cmd == "mods":
            from pymhf.core.mod_loader import mod_manager

            return {"loaded": list(mod_manager.mods)}
        if cmd == "loadmod" and len(words) > 1:
            # Load a new mod file into the running game (no restart needed).
            from pymhf.core.mod_loader import mod_manager

            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.path.basename(words[1]))
            result = mod_manager.load_single_mod(path, bind=True)
            return {"ok": True, "path": path, "result": repr(result)}
        return {"error": f"unknown command {cmd!r}"}

    def _poll(self):
        if self.sock is None:
            return
        for _ in range(8):
            try:
                data, addr = self.sock.recvfrom(4096)
            except BlockingIOError:
                return
            except OSError:
                return
            try:
                reply = self._handle(data.decode("utf-8", "replace").split())
            except Exception as e:  # noqa: BLE001 - report errors to the caller
                logger.exception("command failed")
                reply = {"error": repr(e)}
            try:
                self.sock.sendto(json.dumps(reply).encode(), addr)
            except OSError:
                pass

    # ---- per frame ----------------------------------------------------------
    @nms.cGcApplication.Update.after
    def on_frame(self, this):
        # pyMHF's Reload Mod leaves the old copy's hooks running; only the newest copy acts.
        if getattr(__import__("builtins"), "_constellation_gen", None) != id(self):
            return
        now = time.perf_counter()
        if self.last_frame is not None:
            self.frame_dts.append((now - self.last_frame) * 1000.0)
        self.last_frame = now
        self._poll()

        if self.hold_until:
            m = _player_matrix()
            self.hold_frames += 1
            if m is not None and self.hold_frames > 10:
                self.hold_errs.append(math.dist((m.pos.x, m.pos.y, m.pos.z), self.hold_target))
            if now < self.hold_until:
                self._set(*self.hold_target)
            else:
                errs = self.hold_errs or [0.0]
                q = max(1, len(errs) // 4)
                self.hold_result = {
                    "frames": self.hold_frames,
                    "err_first_quarter_m": round(sum(errs[:q]) / q, 3),
                    "err_last_quarter_m": round(sum(errs[-q:]) / q, 3),
                    "err_max_m": round(max(errs), 3),
                }
                self._row("hold_done", json.dumps(self.hold_result), em=sum(errs) / len(errs), ex=max(errs))
                self.hold_until = 0.0

        if self.circling:
            m = _player_matrix()
            if m is not None and self.last_target is not None:
                self.circle_errs.append(math.dist((m.pos.x, m.pos.y, m.pos.z), self.last_target))
            a = 2 * math.pi * (now - self.t0) / PERIOD_S
            cx, cy, cz = self.center
            r, f = self.right, self.at
            target = (
                cx + RADIUS_M * (math.cos(a) * r.x + math.sin(a) * f.x),
                cy + RADIUS_M * (math.cos(a) * r.y + math.sin(a) * f.y),
                cz + RADIUS_M * (math.cos(a) * r.z + math.sin(a) * f.z),
            )
            self._set(*target)
            self.last_target = target

        if now - self.last_report >= 5.0 and self.frame_dts:
            dts = sorted(self.frame_dts)
            fm = sum(dts) / len(dts)
            fp = dts[int(0.95 * (len(dts) - 1))]
            ce = self.circle_errs or [0.0]
            self._row("stats", "circling" if self.circling else "idle", fm, fp,
                      sum(ce) / len(ce), max(ce))
            self.frame_dts.clear()
            self.circle_errs.clear()
            self.last_report = now
