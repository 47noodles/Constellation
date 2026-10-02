"""Gate test 2: per-frame ship velocity override (one mod per file - pyMHF rule).

Loaded at runtime with:  python spikes/nms/ctl.py loadmod ctl_ship.py
Commands arrive through ctl_player's UDP channel as  ship cruise|hold|off|spin on|off|status
"""

import builtins
import csv
import ctypes
import logging
import math
import os
import time

from pymhf import Mod

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
logger = logging.getLogger("ctl_ship")
CRUISE_MPS, WEAVE_MPS, WEAVE_PERIOD_S = 60.0, 30.0, 8.0


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


class CtlShip2(Mod):
    __author__ = "Constellation"
    __description__ = "Gate test 2: per-frame ship velocity override"

    def __init__(self):
        super().__init__()
        self.mode = "off"  # off | cruise | hold
        self.zero_spin = False
        self.spin_result = None
        self.fwd = (0.0, 0.0, 1.0)
        self.side = (1.0, 0.0, 0.0)
        self.t0 = 0.0
        self.last_cmd = None
        self.seen_ship = False
        self.vel_errs = []
        self.last_actual = None
        self.f, self.out = _csv("ctl_ship.csv", ["t", "event", "mode", "vel_err_mean", "vel_err_max",
                                                 "cmd_speed", "actual_speed", "note"])
        builtins._constellation_ship = self
        logger.info("ship mod loaded")

    def _row(self, event, note="", em=0.0, ex=0.0, cs=0.0, acts=0.0):
        self.out.writerow([f"{time.time():.3f}", event, self.mode, f"{em:.2f}", f"{ex:.2f}",
                           f"{cs:.1f}", f"{acts:.1f}", note])
        self.f.flush()

    def handle(self, words):
        sub = words[0] if words else "status"
        if sub == "status":
            errs = self.vel_errs or [0.0]
            a = self.last_actual
            return {
                "mode": self.mode,
                "zero_spin": self.zero_spin,
                "spin_result": self.spin_result,
                "seen_player_ship_this_session": self.seen_ship,
                "actual_velocity": a,
                "actual_speed": None if a is None else round(math.sqrt(sum(c * c for c in a)), 2),
                "vel_err_mean": round(sum(errs) / len(errs), 3),
                "vel_err_max": round(max(errs), 3),
                "samples": len(self.vel_errs),
                "frames_controlled": getattr(self, "frames_controlled", 0),
                "last_cmd": self.last_cmd,
            }
        if sub in ("cruise", "hold", "off"):
            if sub == "cruise":
                m = _player_matrix()
                if m is not None:
                    self.fwd = _norm(m.at.x, m.at.y, m.at.z)
                    self.side = _norm(m.right.x, m.right.y, m.right.z)
                self.t0 = time.perf_counter()
            self.mode = sub
            self.last_cmd = None
            self.vel_errs.clear()
            self._row("mode", f"fwd={tuple(round(c, 3) for c in self.fwd)}")
            return {"ok": True, "mode": self.mode}
        if sub == "spin":
            self.zero_spin = len(words) < 2 or words[1] == "on"
            self._row("spin", str(self.zero_spin))
            return {"ok": True, "zero_spin": self.zero_spin}
        return {"error": f"unknown ship command {sub!r}"}

    @nms.cGcSpaceshipComponent.UpdateControlled.after
    def after_flight(self, this, lfTimeStep):
        self.seen_ship = True
        ship = this.contents
        # cGcSpaceshipComponent.GetVelocity access-violates on build 180383, so
        # there is no read-back here: the result is judged by eye for now.
        self.frames_controlled = getattr(self, "frames_controlled", 0) + 1
        if self.mode == "off" and not self.zero_spin:
            return
        try:
            rb = ship.mpPhysics.contents.mRigidBody
        except ValueError:  # NULL physics pointer
            return
        if self.mode == "cruise":
            w = WEAVE_MPS * math.sin(2 * math.pi * (time.perf_counter() - self.t0) / WEAVE_PERIOD_S)
            cmd = tuple(CRUISE_MPS * f + w * s for f, s in zip(self.fwd, self.side))
        elif self.mode == "hold":
            cmd = (0.0, 0.0, 0.0)
        else:
            cmd = None
        if cmd is not None:
            rb.SetLinearVelocity(ctypes.byref(basic.cTkVector3(*cmd)), True)
            self.last_cmd = cmd
        if self.zero_spin:
            try:
                rb.SetAngularVelocity(ctypes.byref(basic.cTkVector3(0, 0, 0)), True)
                if self.spin_result is None:
                    self.spin_result = "SetAngularVelocity returned OK"
                    self._row("spin_ok")
            except Exception as e:  # noqa: BLE001 - expected if the pattern did not resolve
                self.zero_spin = False
                self.spin_result = f"failed: {e!r}"
                logger.exception("SetAngularVelocity failed")
                self._row("spin_error", repr(e))
