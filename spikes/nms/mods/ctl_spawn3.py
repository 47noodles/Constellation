"""Gate test 3: spawn a visual-only copy of a loaded model and move it every frame.

Load:  python spikes/nms/ctl.py loadmod ctl_spawn.py
  spawn [metres]          copy the player's ship model (scene nodes only, no physics),
                          parented to the planet the player is on, `metres` in front
  spawn info              world positions of everything spawned
  spawn circle on|off     move the newest copy on a 10 m circle, 8 s period, every frame
  spawn many <n>          n more copies in a row (frame-cost test)
"""

import builtins
import ctypes
import logging
import math
import time

from pymhf import Mod

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.data.types import Engine
from nmspy.engine import GetNodeAbsoluteTransMatrix, ShiftAllTransformsForNode

logger = logging.getLogger("ctl_spawn")


def _pos(v):
    return [round(v.x, 2), round(v.y, 2), round(v.z, 2)]


class CtlSpawn3(Mod):
    __author__ = "Constellation"
    __description__ = "Gate test 3: spawn and move visual-only nodes"

    def __init__(self):
        super().__init__()
        self.spawned = []  # TkHandle copies
        self.circle = False
        self.center = None
        self.t0 = 0.0
        self.cost_ms = []
        self.last_error = None
        self.idx = -1  # which copy circles
        prev = getattr(builtins, "_constellation_spawn", None)
        if prev is not None:  # take over copies spawned by an older version
            self.spawned = list(prev.spawned)
            prev.circle = False
        builtins._constellation_spawn = self
        logger.info("spawn probe loaded")

    # ---- helpers -------------------------------------------------------------
    def _player_matrix(self):
        player = gameData.player
        return None if player is None else GetNodeAbsoluteTransMatrix(player.mRootNode)

    def _nearest_planet(self, p):
        sim = gameData.simulation
        best, best_d = None, math.inf
        for planet in sim.mpSolarSystem.contents.maPlanets:
            q = planet.mPosition
            if q.x == 0 and q.y == 0 and q.z == 0:
                continue
            d = math.dist((p.x, p.y, p.z), (q.x, q.y, q.z))
            if d < best_d:
                best, best_d = planet, d
        return best

    def _ship_node(self):
        gs = gameData.game_state
        return gs.mPlayerShipOwnership.mShips[0].mPlayerShipNode

    def _move_node_to(self, node, target):
        cur = GetNodeAbsoluteTransMatrix(node).pos
        ShiftAllTransformsForNode(node, basic.Vector3f(target[0] - cur.x, target[1] - cur.y, target[2] - cur.z))

    # ---- commands --------------------------------------------------------------
    def _spawn_one(self, metres):
        m = self._player_matrix()
        if m is None:
            raise RuntimeError("no player")
        res = ctypes.c_int32(0)
        Engine.GetResourceHandleForNode(ctypes.byref(res), self._ship_node())
        if res.value == 0:
            raise RuntimeError("ship node has no scene resource")
        parent = self._nearest_planet(m.pos).mNode
        out = basic.TkHandle()
        Engine.AddNodes(ctypes.byref(out), parent, res.value)
        if out.lookupInt == 0:
            raise RuntimeError(f"AddNodes returned an empty handle for resource {res.value}")
        up = (m.up.x, m.up.y, m.up.z)
        n = math.sqrt(sum(c * c for c in up)) or 1.0
        target = tuple(m.pos.__getattribute__(k) + metres * getattr(m.at, k) + 3.0 * getattr(m.up, k) / n
                       for k in ("x", "y", "z"))
        self._move_node_to(out, target)
        self.spawned.append(out)
        return {"resource": res.value, "handle": out.lookupInt, "target": [round(c, 2) for c in target],
                "now": _pos(GetNodeAbsoluteTransMatrix(out).pos)}

    def handle(self, words):
        sub = words[0] if words else "info"
        try:
            if sub == "info":
                return {"count": len(self.spawned), "circle": self.circle, "last_error": self.last_error,
                        "cost_ms_median": round(sorted(self.cost_ms)[len(self.cost_ms) // 2], 4) if self.cost_ms else None,
                        "positions": [_pos(GetNodeAbsoluteTransMatrix(h).pos) for h in self.spawned[-5:]]}
            if sub == "move" and len(words) >= 5:
                h = self.spawned[int(words[1])]
                p = GetNodeAbsoluteTransMatrix(h).pos
                self._move_node_to(h, (p.x + float(words[2]), p.y + float(words[3]), p.z + float(words[4])))
                return {"ok": True, "now": _pos(GetNodeAbsoluteTransMatrix(h).pos)}
            if sub == "circle":
                on = len(words) < 2 or words[1] == "on"
                self.idx = int(words[2]) if len(words) > 2 else -1
                if on and self.spawned:
                    self.center = _pos(GetNodeAbsoluteTransMatrix(self.spawned[self.idx]).pos)
                    self.t0 = time.perf_counter()
                self.circle = on and bool(self.spawned)
                return {"ok": True, "circle": self.circle}
            if sub == "many":
                n = int(words[1]) if len(words) > 1 else 10
                return {"ok": True, "spawned": [self._spawn_one(20.0 + 12.0 * k)["handle"] for k in range(n)]}
            metres = float(sub) if sub.lstrip("-").replace(".", "", 1).isdigit() else 15.0
            return {"ok": True, **self._spawn_one(metres)}
        except Exception as e:  # noqa: BLE001 - report to the caller
            self.last_error = repr(e)
            logger.exception("spawn command failed")
            return {"error": repr(e)}

    @nms.cGcApplication.Update.after
    def on_frame(self, this):
        if not self.circle or not self.spawned:
            return
        a = 2 * math.pi * (time.perf_counter() - self.t0) / 8.0
        m = self._player_matrix()
        if m is None:
            return
        r, f = m.right, m.at
        c = self.center
        target = (c[0] + 10 * (math.cos(a) - 1) * r.x + 10 * math.sin(a) * f.x,
                  c[1] + 10 * (math.cos(a) - 1) * r.y + 10 * math.sin(a) * f.y,
                  c[2] + 10 * (math.cos(a) - 1) * r.z + 10 * math.sin(a) * f.z)
        t = time.perf_counter()
        try:
            self._move_node_to(self.spawned[self.idx], target)
        except Exception as e:  # noqa: BLE001
            self.last_error = repr(e)
            self.circle = False
        self.cost_ms.append((time.perf_counter() - t) * 1000)
        self.cost_ms = self.cost_ms[-1000:]
