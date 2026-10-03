"""Constellation's No Man's Sky adapter (pyMHF mod, NMS build 180383).

Every rendered frame, on the game thread:
1. take the coordinator's newest planet targets (UDP 127.0.0.1:47811) and move
   each planet there (scene node + logical position, the method proven on
   2 Oct 2026);
2. move the ship or pose the player for the optional "ship" target, according
   to "mode" ("orbit" shifts the ship scene node; "flight" poses the player);
3. every second frame, report the player, the planets and (when a ship node is
   found) the ship's absolute position and finite-difference velocity to the
   coordinator (UDP 127.0.0.1:47812).

Ship rendering (docs/transfer-land-design.md section 5): cGcSpaceshipComponent.
GetVelocity access-violates on build 180383, so it is never called. Orbit uses
Engine.ShiftAllTransformsForNode on the ship scene node; flight uses cGcPlayer.
SetToPosition, both proven in spikes/nms/mods. The transform maths lives in the
offline-testable adapters/nms/transforms.py.

The state report's optional "ship" key is
{"pos": [x, y, z] absolute NMS metres, "vel": [vx, vy, vz] metres per real
second from finite differences of pos over real time (smoothed over the last
five frames, never from GetVelocity), "frame": adapter frame counter,
"real_t": time.monotonic() at sample}. It is emitted every report while the
owned ship node is found, else omitted. transforms.smooth_velocity does the
finite difference; transforms.ship_sample builds the exact object.

Safety: a move larger than GUARD_STEP_M in one frame is refused if the planet (or
the ship scene node) is, or would end up, within GUARD_NEAR_M of the player (the
body under you, or one being moved onto you). Moving a nearby body *away* is
allowed. Refused moves are counted in `adapter status`. The coordinator anchors
the player's planet, so this should never trigger.

Status through ctl_player's channel:  python spikes/nms/ctl.py adapter status
"""

import sys
import builtins
import ctypes
import importlib.util
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
from nmspy.engine import GetNodeAbsoluteTransMatrix, ShiftAllTransformsForNode


def _load_transforms():
    """Load the pure transform module by path, so it works both as a package
    import (tests) and when this file is loaded directly by pyMHF from anywhere
    (the mods folder) with no package context."""
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(here, "adapters", "nms", "transforms.py")
        if os.path.isfile(candidate):
            spec = importlib.util.spec_from_file_location("constellation_nms_transforms", candidate)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
        parent = os.path.dirname(here)
        if parent == here:
            raise ImportError(f"adapters/nms/transforms.py not found above {__file__}")
        here = parent


transforms = _load_transforms()

logger = logging.getLogger("constellation_nms")

HOST = "127.0.0.1"
CMD_PORT = 47811
STATE_PORT = 47812
GUARD_NEAR_M = 160_000.0  # ~ planet radius (130 km measured) + 30 km of altitude
GUARD_STEP_M = 50.0


def _v3(v):
    return [round(v.x, 3), round(v.y, 3), round(v.z, 3)]


class ConstellationNMS4(Mod):
    __author__ = "Constellation"
    __description__ = "Applies coordinator planet targets; reports player and planets"

    def __init__(self):
        super().__init__()
        builtins._constellation_gen_adapter = id(self)
        builtins._constellation_adapter = self
        self.cmd = getattr(builtins, "_constellation_adapter_sock", None)
        if self.cmd is None:
            self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.cmd.bind((HOST, CMD_PORT))
            self.cmd.setblocking(False)
            builtins._constellation_adapter_sock = self.cmd
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.homes = {}  # sys key -> {slot: [x, y, z]}
        self.seq = 0
        self.frame = 0
        self.last_frame_t = None
        self.frame_ms = 0.0
        self.applied = 0
        self.refused = 0
        self.last_target_seq = 0
        self.last_target_sys = None
        self.last_error = None
        self.applied_game_t = None  # coordinator game time the planets were last placed for
        self.latest = None  # newest target message
        self.latest_at = 0.0  # perf_counter when it arrived
        self.ship_applied = 0
        self.ship_refused = 0
        self.ship_mode = None  # newest ship mode acted on: orbit | flight | none
        self.ship_history = []  # newest-last (real_t, pos) samples for the ship velocity
        self.ship_last = None  # newest (frame, real_t, pos), or None if no ship node
        logger.info("Constellation NMS adapter loaded")

    # ---- game reads ----------------------------------------------------------
    def _system(self):
        sim = gameData.simulation
        if sim is None or not sim.mpSolarSystem:
            return None, None
        ss = sim.mpSolarSystem.contents
        return f"{ss.mUA:016x}", ss

    def _player_pos(self):
        player = gameData.player
        if player is None:
            return None
        m = GetNodeAbsoluteTransMatrix(player.mRootNode)
        return (m.pos.x, m.pos.y, m.pos.z)

    def _planets(self, ss):
        out = []
        for slot, planet in enumerate(ss.maPlanets):
            p = planet.mPosition
            if p.x == 0.0 and p.y == 0.0 and p.z == 0.0:
                continue  # empty slot
            out.append((slot, planet))
        return out

    # ---- ship / player pose --------------------------------------------------
    def _ship_node(self):
        """The owned, valid ship scene node nearest the player (the one being
        flown), from game_state.mPlayerShipOwnership.mShips. None if unavailable.
        Mirrors the proven spikes/nms/mods/ctl_pose3.py lookup."""
        gs = gameData.game_state
        if gs is None:
            return None
        try:
            ships = gs.mPlayerShipOwnership.mShips
        except Exception:  # noqa: BLE001 - a missing/partial struct is not fatal
            return None
        player = gameData.player
        player_pos = None
        if player is not None:
            try:
                m = GetNodeAbsoluteTransMatrix(player.mRootNode)
                player_pos = (m.pos.x, m.pos.y, m.pos.z)
            except Exception:  # noqa: BLE001
                player_pos = None
        best = None
        best_d = None
        for sd in ships:
            try:
                if not sd.mbUnknown0x28:  # "is valid/data"
                    continue
                node = sd.mPlayerShipNode
                m = GetNodeAbsoluteTransMatrix(node)
            except Exception:  # noqa: BLE001 - empty slots hold junk handles
                continue
            if player_pos is None:
                return node
            q = (m.pos.x, m.pos.y, m.pos.z)
            d = (q[0] - player_pos[0]) ** 2 + (q[1] - player_pos[1]) ** 2 + (q[2] - player_pos[2]) ** 2
            if best_d is None or d < best_d:
                best, best_d = node, d
        return best

    def _sample_ship(self):
        """Sample the owned ship's absolute position once a frame so the state
        report can finite-difference a real-time velocity. Clearing the history
        when the node is lost keeps a reacquired ship from showing a bogus jump.
        Never calls GetVelocity."""
        node = self._ship_node()
        if node is None:
            self.ship_history.clear()
            self.ship_last = None
            return
        try:
            m = GetNodeAbsoluteTransMatrix(node)
        except Exception:  # noqa: BLE001 - a stale handle is not fatal
            self.ship_history.clear()
            self.ship_last = None
            return
        pos = (m.pos.x, m.pos.y, m.pos.z)
        real_t = time.monotonic()
        self.ship_history.append((real_t, pos))
        del self.ship_history[:-8]  # keep a little more than the velocity window
        self.ship_last = (self.frame, real_t, pos)

    def _set_pose(self, pos, forward, up, vel=(0.0, 0.0, 0.0)):
        """Pose the player with cGcPlayer.SetToPosition (proven live in
        spikes/nms/mods/ctl_player.py:137). ``up`` is part of the designed
        interface but the native call (types.py:1584) takes only position,
        direction and velocity, so up is carried for callers and not passed.
        None of these calls are GetVelocity."""
        player = gameData.player
        if player is None:
            return False
        del up
        p = basic.cTkBigPos(basic.Vector3f(pos[0], pos[1], pos[2]), basic.Vector3f(0.0, 0.0, 0.0))
        direction = basic.Vector3f(forward[0], forward[1], forward[2])
        velocity = basic.Vector3f(vel[0], vel[1], vel[2])
        player.SetToPosition(ctypes.byref(p), ctypes.byref(direction), ctypes.byref(velocity))
        return True

    def _apply_ship(self, latest, player_pos, age):
        """Move the ship node ("orbit") or pose the player ("flight") per the
        coordinator's optional ship target. Never calls GetVelocity."""
        ship = latest.get("ship")
        mode = latest.get("mode", "orbit")
        node = None
        node_pos = None
        if ship and mode != "flight":
            node = self._ship_node()
            if node is not None:
                m = GetNodeAbsoluteTransMatrix(node)
                node_pos = (m.pos.x, m.pos.y, m.pos.z)
        action = transforms.plan_ship(ship, mode, node_pos=node_pos, age=age)
        self.ship_mode = action.mode
        if action.mode == "orbit" and node is not None:
            if not transforms.guard_allows(action.delta, node_pos, player_pos, GUARD_STEP_M, GUARD_NEAR_M):
                self.ship_refused += 1
                return
            ShiftAllTransformsForNode(node, basic.Vector3f(action.delta[0], action.delta[1], action.delta[2]))
            self.ship_applied += 1
        elif action.mode == "flight":
            if self._set_pose(action.pos, action.forward, action.up, action.vel):
                self.ship_applied += 1

    # ---- per frame -------------------------------------------------------------
    @nms.cGcApplication.Update.after
    def on_frame(self, this):
        if getattr(builtins, "_constellation_gen_adapter", None) != id(self):
            return  # a newer copy of this mod is loaded
        now = time.perf_counter()
        if self.last_frame_t is not None:
            self.frame_ms = 0.9 * self.frame_ms + 0.1 * (now - self.last_frame_t) * 1000.0
        self.last_frame_t = now
        self.frame += 1
        try:
            sys_key, ss = self._system()
            if ss is None:
                return
            planets = self._planets(ss)
            homes = self.homes.setdefault(sys_key, {})
            for slot, planet in planets:
                homes.setdefault(slot, _v3(planet.mPosition))
            player = self._player_pos()
            self._apply_targets(sys_key, planets, player)
            self._sample_ship()
            if self.frame % 2 == 0 and player is not None:
                self._report(sys_key, planets, homes, player)
        except Exception as e:  # noqa: BLE001 - never let the game loop die
            self.last_error = repr(e)
            if self.frame % 300 == 0:
                logger.exception("adapter frame failed")

    def _apply_targets(self, sys_key, planets, player):
        while True:
            try:
                data, _ = self.cmd.recvfrom(65535)
            except (BlockingIOError, ConnectionResetError):
                break
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            if msg.get("t") == "nms_targets" and (self.latest is None or msg.get("seq", 0) > self.latest.get("seq", 0)
                                                  or msg.get("seq", 0) < 10):
                self.latest, self.latest_at = msg, time.perf_counter()
        latest = self.latest
        if latest is None or latest.get("sys") != sys_key:
            return
        age = min(time.perf_counter() - self.latest_at, 0.5)  # never extrapolate far past a stalled coordinator
        self.last_target_seq, self.last_target_sys = latest.get("seq", 0), latest.get("sys")
        targets = latest.get("targets", {})
        vels = latest.get("vel_per_real_s", {})
        self.applied_game_t = latest.get("game_t", 0.0) + age * latest.get("warp", 0.0)
        for slot, planet in planets:
            target = targets.get(str(slot))
            if target is None:
                continue
            v = vels.get(str(slot))
            if v is not None:
                target = [target[0] + v[0] * age, target[1] + v[1] * age, target[2] + v[2] * age]
            cur = planet.mPosition
            dx, dy, dz = target[0] - cur.x, target[1] - cur.y, target[2] - cur.z
            step = math.sqrt(dx * dx + dy * dy + dz * dz)
            if step < 0.001:
                continue
            if player is not None and step > GUARD_STEP_M:
                now_d = math.dist(player, (cur.x, cur.y, cur.z))
                new_d = math.dist(player, tuple(target))
                if min(now_d, new_d) < GUARD_NEAR_M:
                    self.refused += 1
                    continue
            ShiftAllTransformsForNode(planet.mNode, basic.Vector3f(dx, dy, dz))
            cur.x, cur.y, cur.z = target[0], target[1], target[2]
            self.applied += 1
        self._apply_ship(latest, player, age)

    def _report(self, sys_key, planets, homes, player):
        self.seq += 1
        msg = {
            "t": "nms_state", "seq": self.seq, "sys": sys_key, "frame_ms": round(self.frame_ms, 1),
            "player": [round(c, 3) for c in player], "applied_game_t": self.applied_game_t,
            "planets": [{"slot": s, "pos": _v3(p.mPosition), "home": homes[s]} for s, p in planets],
        }
        if self.ship_last is not None:
            frame_i, real_t, pos = self.ship_last
            msg["ship"] = transforms.ship_sample(self.ship_history, frame_i, real_t, pos)
        try:
            self.out.sendto(json.dumps(msg, separators=(",", ":")).encode(), (HOST, STATE_PORT))
        except OSError:
            pass

    # ---- status (via ctl_player's channel: "adapter ...") -----------------------
    def handle(self, words):
        sys_key, _ = self._system()
        return {
            "sys": sys_key, "frame": self.frame, "frame_ms": round(self.frame_ms, 1),
            "applied_moves": self.applied, "refused_moves": self.refused,
            "last_target_seq": self.last_target_seq, "last_target_sys": self.last_target_sys,
            "ship_applied": self.ship_applied, "ship_refused": self.ship_refused,
            "ship_mode": self.ship_mode, "ship_samples": len(self.ship_history),
            "ship_pos": None if self.ship_last is None else [round(c, 3) for c in self.ship_last[2]],
            "homes": self.homes.get(sys_key), "last_error": self.last_error,
        }
