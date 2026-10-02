"""Constellation's No Man's Sky adapter (pyMHF mod, NMS build 180383).

Every rendered frame, on the game thread:
1. take the coordinator's newest planet targets (UDP 127.0.0.1:47811) and move
   each planet there (scene node + logical position, the method proven on
   2 Oct 2026);
2. every second frame, report the player position and the planets to the
   coordinator (UDP 127.0.0.1:47812).

Safety: a move larger than GUARD_STEP_M in one frame is refused if the planet is,
or would end up, within GUARD_NEAR_M of the player (the planet under you, or one
being moved onto you). Moving a nearby planet *away* is allowed. Refused moves
are counted in `adapter status`. The coordinator anchors the player's planet, so
this should never trigger.

Status through ctl_player's channel:  python spikes/nms/ctl.py adapter status
"""

import builtins
import json
import logging
import math
import socket
import time

from pymhf import Mod

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix, ShiftAllTransformsForNode

logger = logging.getLogger("constellation_nms")

HOST = "127.0.0.1"
CMD_PORT = 47811
STATE_PORT = 47812
GUARD_NEAR_M = 160_000.0  # ~ planet radius (130 km measured) + 30 km of altitude
GUARD_STEP_M = 50.0


def _v3(v):
    return [round(v.x, 3), round(v.y, 3), round(v.z, 3)]


class ConstellationNMS2(Mod):
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
            if self.frame % 2 == 0 and player is not None:
                self._report(sys_key, planets, homes, player)
        except Exception as e:  # noqa: BLE001 - never let the game loop die
            self.last_error = repr(e)
            if self.frame % 300 == 0:
                logger.exception("adapter frame failed")

    def _apply_targets(self, sys_key, planets, player):
        latest = None
        while True:
            try:
                data, _ = self.cmd.recvfrom(65535)
            except (BlockingIOError, ConnectionResetError):
                break
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            if msg.get("t") == "nms_targets":
                latest = msg
        if latest is None or latest.get("sys") != sys_key:
            return
        self.last_target_seq, self.last_target_sys = latest.get("seq", 0), latest.get("sys")
        targets = latest.get("targets", {})
        for slot, planet in planets:
            target = targets.get(str(slot))
            if target is None:
                continue
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

    def _report(self, sys_key, planets, homes, player):
        self.seq += 1
        msg = {
            "t": "nms_state", "seq": self.seq, "sys": sys_key, "frame_ms": round(self.frame_ms, 1),
            "player": [round(c, 3) for c in player],
            "planets": [{"slot": s, "pos": _v3(p.mPosition), "home": homes[s]} for s, p in planets],
        }
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
            "homes": self.homes.get(sys_key), "last_error": self.last_error,
        }
