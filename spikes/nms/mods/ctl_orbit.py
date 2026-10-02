"""Option B probe 2: move a planet every frame (a stand-in for a KSP orbit).

Load:  python spikes/nms/ctl.py loadmod ctl_orbit.py
  orbit start <i> [radius_km] [period_s]   circle planet i around where it is now
  orbit stop                               put it back home
  orbit status                             frames moved, cost per move
"""

import builtins
import logging
import math
import time

from pymhf import Mod

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import ShiftAllTransformsForNode

logger = logging.getLogger("ctl_orbit")


class CtlOrbit(Mod):
    __author__ = "Constellation"
    __description__ = "Probe: per-frame planet motion"

    def __init__(self):
        super().__init__()
        self.i = None
        self.home = None
        self.offset = (0.0, 0.0, 0.0)  # current displacement from home
        self.radius = 30000.0
        self.period = 60.0
        self.t0 = 0.0
        self.active = False
        self.restore = False
        self.frames = 0
        self.cost_ms = []
        builtins._constellation_orbit = self
        logger.info("orbit probe loaded")

    def _planet(self):
        sim = gameData.simulation
        if sim is None or not sim.mpSolarSystem or self.i is None:
            return None
        return sim.mpSolarSystem.contents.maPlanets[self.i]

    def _move_to(self, planet, off):
        dx, dy, dz = (off[k] - self.offset[k] for k in range(3))
        ShiftAllTransformsForNode(planet.mNode, basic.Vector3f(dx, dy, dz))
        planet.mPosition.x += dx
        planet.mPosition.y += dy
        planet.mPosition.z += dz
        self.offset = off

    def handle(self, words):
        sub = words[0] if words else "status"
        if sub == "start" and len(words) > 1:
            if self.active:
                return {"error": "already orbiting; orbit stop first"}
            self.i = int(words[1])
            self.radius = float(words[2]) * 1000 if len(words) > 2 else 30000.0
            self.period = float(words[3]) if len(words) > 3 else 60.0
            self.offset = (0.0, 0.0, 0.0)
            self.t0 = time.perf_counter()
            self.frames = 0
            self.cost_ms = []
            self.active = True
            return {"ok": True, "planet": self.i, "radius_m": self.radius, "period_s": self.period}
        if sub == "stop":
            self.active = False
            self.restore = True
            return {"ok": True, "restoring": True}
        costs = sorted(self.cost_ms) or [0.0]
        return {
            "active": self.active,
            "planet": self.i,
            "frames_moved": self.frames,
            "offset_m": [round(c) for c in self.offset],
            "move_cost_ms_median": round(costs[len(costs) // 2], 3),
            "move_cost_ms_p95": round(costs[int(0.95 * (len(costs) - 1))], 3),
        }

    @nms.cGcApplication.Update.after
    def on_frame(self, this):
        if not (self.active or self.restore):
            return
        planet = self._planet()
        if planet is None:
            return
        if self.restore:
            self._move_to(planet, (0.0, 0.0, 0.0))
            self.restore = False
            logger.info("orbit stopped; planet restored")
            return
        a = 2 * math.pi * (time.perf_counter() - self.t0) / self.period
        # circle in the x-z plane, starting at home (offset 0 at a=0)
        off = (self.radius * math.sin(a), 0.0, self.radius * (1 - math.cos(a)))
        t = time.perf_counter()
        self._move_to(planet, off)
        self.cost_ms.append((time.perf_counter() - t) * 1000)
        self.cost_ms = self.cost_ms[-2000:]
        self.frames += 1
