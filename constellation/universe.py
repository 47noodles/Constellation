"""A star system that KSP-style orbits own, displayed through NMS's coordinates.

Option B (Lachlan, 2 Oct 2026): planet positions come from orbits on a shared
clock, and every NMS client moves its planets to match each frame.

Two coordinate spaces:
* orbit space: star at the origin, planets on their orbits (metres);
* NMS space: whatever coordinates NMS uses for the current system.

They are joined by an *anchor*: the body whose sphere of influence the player
is in stays put in NMS space, and every other body is placed relative to it.
That is how KSP frames work too, and it means you never land on a planet that
is moving past at orbital speed. When the player crosses into another sphere
of influence the anchor changes hands at the new body's current NMS position,
so nothing jumps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .orbits import Orbit, Vec, add, circular, norm, soi_radius, sub

STAR = "star"

# Defaults sized from what was measured in NMS on 2 Oct 2026: planet 1 has a
# radius of about 130 km; planets sit 150-1,700 km apart.
DEFAULT_RADIUS_M = 130_000.0
DEFAULT_SURFACE_G = 9.81
# Orbits are spaced geometrically (each ORBIT_RATIO times the last), as real and
# KSP systems roughly are, so one star mass gives every planet the same
# proportion of sphere of influence to orbit gap. SOI_SCALE is (m/M)^0.4:
# each SOI is SOI_SCALE * its orbit radius. With ratio 1.6 two neighbouring
# spheres fill (1 + 1.6) * 0.1 / 0.6 = 43% of the gap between them.
FIRST_ORBIT_M = 3_000_000.0  # innermost SOI = 300 km, clear of a 130 km planet
ORBIT_RATIO = 1.6
SOI_SCALE = 0.1


@dataclass
class Body:
    id: str  # "p<slot>" for NMS planet slots
    slot: int
    radius: float
    mu: float
    orbit: Orbit
    soi: float
    nms_home: Vec  # where NMS generated it; kept for reference only


@dataclass
class Universe:
    """Bodies on orbits plus the anchor that maps them into NMS space."""

    star_mu: float
    bodies: dict[str, Body]
    anchor: str = STAR
    anchor_nms: Vec = (0.0, 0.0, 0.0)  # NMS position of the anchor body (or star)
    history: list[tuple[float, str]] = field(default_factory=list)

    # ---- construction --------------------------------------------------------
    @classmethod
    def from_nms_planets(cls, planets: list[dict], epoch: float = 0.0,
                         star_nms: Vec | None = None) -> "Universe":
        """Build orbits for the planets NMS generated.

        ``planets``: [{"slot": int, "home": [x, y, z], "radius": float?}, ...]
        Planets are given orbits in order of their distance from the system
        centroid, ``ORBIT_RATIO`` apart, so orbits and spheres of influence
        never cross. Each keeps
        the direction it had from the centroid, so the layout still resembles
        what NMS generated. Deterministic: every client builds the same orbits
        from the same planet list.
        """
        real = [p for p in planets if norm(tuple(p["home"])) > 0.0]
        if not real:
            raise ValueError("no planets")
        if star_nms is None:
            n = len(real)
            star_nms = tuple(sum(p["home"][k] for p in real) / n for k in range(3))
        ordered = sorted(real, key=lambda p: (norm(sub(tuple(p["home"]), star_nms)), p["slot"]))
        mu_max = max(DEFAULT_SURFACE_G * float(p.get("radius") or DEFAULT_RADIUS_M) ** 2 for p in ordered)
        star_mu = mu_max / SOI_SCALE ** 2.5
        bodies: dict[str, Body] = {}
        for k, p in enumerate(ordered):
            home = tuple(float(c) for c in p["home"])
            direction = sub(home, star_nms)
            if norm(direction) == 0.0:
                direction = (1.0, 0.0, 0.0)
            radius_orbit = FIRST_ORBIT_M * ORBIT_RATIO ** k
            r0 = tuple(c * radius_orbit / norm(direction) for c in direction)
            radius = float(p.get("radius") or DEFAULT_RADIUS_M)
            mu = DEFAULT_SURFACE_G * radius ** 2
            orbit = circular(star_mu, r0, epoch=epoch)
            bid = f"p{p['slot']}"
            bodies[bid] = Body(bid, int(p["slot"]), radius, mu, orbit,
                               soi_radius(radius_orbit, mu, star_mu), home)
        return cls(star_mu=star_mu, bodies=bodies, anchor=STAR, anchor_nms=star_nms)

    def anchor_to_current(self, player_nms: Vec, current: dict[int, Vec], t: float) -> str:
        """First contact: pin the body the player is in where NMS has it *now*.

        Before the coordinator has ever moved anything, NMS positions are the
        generated ones, not the orbit layout. If the player is inside a body's
        sphere of influence by those positions, that body becomes the anchor
        at its current position, so the ground under the player never moves.
        Otherwise the star stays the anchor and the planets move onto their
        orbits (they are far from the player, so the jump is not felt).
        """
        best, best_d = None, math.inf
        for b in self.bodies.values():
            pos = current.get(b.slot)
            if pos is None:
                continue
            d = norm(sub(player_nms, pos))
            if d < b.soi and d < best_d:
                best, best_d = b, d
        if best is not None:
            self.anchor = best.id
            self.anchor_nms = tuple(current[best.slot])
            self.history.append((t, best.id))
        return self.anchor

    # ---- orbit space ------------------------------------------------------------
    def orbit_pos(self, body_id: str, t: float) -> Vec:
        if body_id == STAR:
            return (0.0, 0.0, 0.0)
        return self.bodies[body_id].orbit.position_at(t)

    # ---- NMS space ----------------------------------------------------------------
    def nms_pos(self, body_id: str, t: float) -> Vec:
        """Where ``body_id`` should be drawn in NMS at time ``t``."""
        offset = sub(self.orbit_pos(body_id, t), self.orbit_pos(self.anchor, t))
        return add(self.anchor_nms, offset)

    def orbit_vel(self, body_id: str, t: float) -> Vec:
        if body_id == STAR:
            return (0.0, 0.0, 0.0)
        return self.bodies[body_id].orbit.state_at(t)[1]

    def nms_vel(self, body_id: str, t: float) -> Vec:
        """Velocity of ``body_id`` in NMS space (game seconds): relative to the anchor."""
        return sub(self.orbit_vel(body_id, t), self.orbit_vel(self.anchor, t))

    def nms_targets(self, t: float) -> dict[int, Vec]:
        """NMS slot -> target position for every body."""
        return {b.slot: self.nms_pos(b.id, t) for b in self.bodies.values()}

    def star_nms(self, t: float) -> Vec:
        return self.nms_pos(STAR, t)

    # ---- anchoring ----------------------------------------------------------------
    def body_containing(self, nms_point: Vec, t: float) -> str:
        """The innermost sphere of influence containing an NMS-space point."""
        best, best_d = STAR, math.inf
        for b in self.bodies.values():
            d = norm(sub(nms_point, self.nms_pos(b.id, t)))
            if d < b.soi and d < best_d:
                best, best_d = b.id, d
        return best

    def update_anchor(self, player_nms: Vec, t: float) -> bool:
        """Re-anchor to the body the player is in. Returns True on a change.

        The new anchor is pinned where it is drawn right now, so the switch is
        continuous for every body.
        """
        new = self.body_containing(player_nms, t)
        if new == self.anchor:
            return False
        self.anchor_nms = self.nms_pos(new, t)
        self.anchor = new
        self.history.append((t, new))
        return True
