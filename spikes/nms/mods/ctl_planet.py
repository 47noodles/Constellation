"""Option B probe: can an NMS planet be moved at runtime (so KSP could own planet orbits)?

No hooks: runs on the game thread through ctl_player's UDP channel.
Load:  python spikes/nms/ctl.py loadmod ctl_planet.py
  planet list                      the 6 planet slots: logical position, node positions, distance to player
  planet shift <i> <dx> <dy> <dz>  shift planet i's root node (and its logical mPosition) by a world vector
  planet watch <i>                 positions of planet i now (call again later to see if the move stuck)
"""

import builtins
import logging
import math

from pymhf import Mod

import nmspy.data.basic_types as basic
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix, ShiftAllTransformsForNode

logger = logging.getLogger("ctl_planet")
NODES = ("mNode", "mPlanetSceneNode", "mPlanetMeshNode", "mAtmosphereNode", "mRegionNode")


def _p(v):
    return [round(v.x, 1), round(v.y, 1), round(v.z, 1)]


class CtlPlanet(Mod):
    __author__ = "Constellation"
    __description__ = "Probe: move a planet at runtime"

    def __init__(self):
        super().__init__()
        builtins._constellation_planet = self
        logger.info("planet probe loaded")

    def _planets(self):
        sim = gameData.simulation
        if sim is None or not sim.mpSolarSystem:
            return None
        return sim.mpSolarSystem.contents.maPlanets

    def _describe(self, i, planet):
        out = {"i": i, "index": planet.miPlanetIndex, "mPosition": _p(planet.mPosition)}
        for name in NODES:
            try:
                out[name] = _p(GetNodeAbsoluteTransMatrix(getattr(planet, name)).pos)
            except Exception as e:  # noqa: BLE001 - invalid handles on empty slots
                out[name] = repr(e)[:40]
        player = gameData.player
        if player is not None:
            pp = GetNodeAbsoluteTransMatrix(player.mRootNode).pos
            mp = planet.mPosition
            out["dist_to_player_km"] = round(math.dist((pp.x, pp.y, pp.z), (mp.x, mp.y, mp.z)) / 1000, 1)
        return out

    def handle(self, words):
        sub = words[0] if words else "list"
        planets = self._planets()
        if planets is None:
            return {"error": "no solar system"}
        if sub == "list":
            return {"planets": [self._describe(i, p) for i, p in enumerate(planets)]}
        if sub == "watch" and len(words) > 1:
            i = int(words[1])
            return self._describe(i, planets[i])
        if sub == "shift" and len(words) >= 5:
            i = int(words[1])
            dx, dy, dz = (float(w) for w in words[2:5])
            planet = planets[i]
            before = self._describe(i, planet)
            ShiftAllTransformsForNode(planet.mNode, basic.Vector3f(dx, dy, dz))
            planet.mPosition.x += dx
            planet.mPosition.y += dy
            planet.mPosition.z += dz
            after = self._describe(i, planet)
            logger.info(f"planet {i} shift {dx},{dy},{dz}: before={before} after={after}")
            return {"ok": True, "before": before, "after_same_frame": after}
        return {"error": f"unknown planet command {sub!r}"}
