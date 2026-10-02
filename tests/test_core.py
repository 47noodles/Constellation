import math
import unittest

from constellation.clock import Clock
from constellation.orbits import circular, from_state, norm, sub
from constellation.universe import ORBIT_RATIO, STAR, Universe

# The five planets NMS generated in Lachlan's test system on 2 Oct 2026.
NMS_PLANETS = [
    {"slot": 0, "home": [-95000.0, -14000.0, 86000.0]},
    {"slot": 1, "home": [469000.0, -2000.0, -229000.0]},
    {"slot": 2, "home": [324000.0, 111000.0, -96000.0]},
    {"slot": 3, "home": [664000.0, -114000.0, -229000.0]},
    {"slot": 4, "home": [-1298000.0, -6000.0, 51000.0]},
    {"slot": 5, "home": [0.0, 0.0, 0.0]},  # empty slot
]


class OrbitTests(unittest.TestCase):
    def test_circular_returns_to_start_after_one_period(self):
        o = circular(4e14, (7e6, 0.0, 0.0))
        r = o.position_at(o.period)
        self.assertLess(norm(sub(r, (7e6, 0.0, 0.0))), 1e-3)

    def test_circular_speed_matches_vis_viva(self):
        mu, r0 = 4e14, (7e6, 0.0, 0.0)
        _, v = circular(mu, r0).state_at(123.0)
        self.assertAlmostEqual(norm(v), math.sqrt(mu / 7e6), places=6)

    def test_prograde_about_up(self):
        o = circular(4e14, (7e6, 0.0, 0.0))
        r, v = o.state_at(0.0)
        h = (r[1] * v[2] - r[2] * v[1], r[2] * v[0] - r[0] * v[2], r[0] * v[1] - r[1] * v[0])
        self.assertGreater(h[1], 0.0)

    def test_state_roundtrip_elliptic(self):
        mu = 3.5316e12  # Kerbin
        r, v = (700e3, 50e3, -20e3), (100.0, 2400.0, 300.0)
        o = from_state(mu, r, v, epoch=10.0)
        r2, v2 = o.state_at(10.0)
        self.assertLess(norm(sub(r, r2)), 1e-3)
        self.assertLess(norm(sub(v, v2)), 1e-6)
        r3, _ = o.state_at(10.0 + o.period)
        self.assertLess(norm(sub(r, r3)), 1e-2)

    def test_state_roundtrip_hyperbolic(self):
        mu = 3.5316e12
        r, v = (700e3, 0.0, 0.0), (0.0, 0.0, 4500.0)
        o = from_state(mu, r, v, epoch=0.0)
        self.assertGreater(o.e, 1.0)
        r2, v2 = o.state_at(0.0)
        self.assertLess(norm(sub(r, r2)), 1e-3)
        self.assertLess(norm(sub(v, v2)), 1e-6)


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.u = Universe.from_nms_planets(NMS_PLANETS)

    def test_empty_slot_ignored(self):
        self.assertEqual(sorted(self.u.bodies), ["p0", "p1", "p2", "p3", "p4"])

    def test_orbits_never_cross(self):
        radii = sorted(b.orbit.a for b in self.u.bodies.values())
        self.assertTrue(all(abs(b / a - ORBIT_RATIO) < 1e-9 for a, b in zip(radii, radii[1:])))
        gaps = [b - a for a, b in zip(radii, radii[1:])]
        biggest_reach = max(b.radius for b in self.u.bodies.values()) * 2
        self.assertTrue(all(g > biggest_reach for g in gaps))

    def test_spheres_of_influence_never_overlap(self):
        bodies = sorted(self.u.bodies.values(), key=lambda b: b.orbit.a)
        for inner, outer in zip(bodies, bodies[1:]):
            self.assertLess(inner.soi + outer.soi, outer.orbit.a - inner.orbit.a)
        for b in bodies:
            self.assertGreater(b.soi, 2 * b.radius)  # room to orbit above the surface

    def test_deterministic_for_every_client(self):
        other = Universe.from_nms_planets(list(reversed(NMS_PLANETS)))
        for bid, b in self.u.bodies.items():
            self.assertLess(norm(sub(b.orbit.position_at(5000.0), other.bodies[bid].orbit.position_at(5000.0))), 1e-6)

    def test_player_on_planet_keeps_ground_still(self):
        # Lachlan standing on planet 1, which had been parked 20 km off home.
        current = {p["slot"]: tuple(p["home"]) for p in NMS_PLANETS}
        current[1] = (489000.0, -2000.0, -229000.0)
        player = (370982.75, -38610.672, -188338.703)  # 130 km from planet 1's centre
        anchor = self.u.anchor_to_current(player, current, t=0.0)
        self.assertEqual(anchor, "p1")
        for t in (0.0, 600.0, 7200.0):
            self.assertLess(norm(sub(self.u.nms_pos("p1", t), current[1])), 1e-6)
            self.assertFalse(self.u.update_anchor(player, t))

    def test_other_planets_move_relative_to_anchor(self):
        current = {p["slot"]: tuple(p["home"]) for p in NMS_PLANETS}
        self.u.anchor_to_current((469000.0, 120000.0, -229000.0), current, t=0.0)
        a, b = self.u.nms_pos("p3", 0.0), self.u.nms_pos("p3", 600.0)
        self.assertGreater(norm(sub(a, b)), 1000.0)

    def test_anchor_handover_is_continuous(self):
        current = {p["slot"]: tuple(p["home"]) for p in NMS_PLANETS}
        self.u.anchor_to_current((469000.0, 120000.0, -229000.0), current, t=0.0)
        t = 900.0
        before = self.u.nms_targets(t)
        target_body = next(b for b in self.u.bodies.values() if b.id != self.u.anchor)
        inside = self.u.nms_pos(target_body.id, t)
        self.assertTrue(self.u.update_anchor((inside[0], inside[1] + target_body.radius + 10.0, inside[2]), t))
        self.assertEqual(self.u.anchor, target_body.id)
        after = self.u.nms_targets(t)
        for slot in before:
            self.assertLess(norm(sub(before[slot], after[slot])), 1e-6)

    def test_deep_space_anchors_to_star(self):
        self.assertEqual(self.u.body_containing((5e9, 0.0, 0.0), 0.0), STAR)


class ClockTests(unittest.TestCase):
    def test_warp_change_is_continuous(self):
        c = Clock(warp=1.0)
        c.set_time(100.0, real=0.0)
        self.assertAlmostEqual(c.now(real=10.0), 110.0)
        c.set_warp(50.0, real=10.0)
        self.assertAlmostEqual(c.now(real=10.0), 110.0)
        self.assertAlmostEqual(c.now(real=12.0), 210.0)

    def test_pause_holds_time(self):
        c = Clock()
        c.set_time(5.0, real=0.0)
        c.pause(real=1.0)
        self.assertAlmostEqual(c.now(real=100.0), 6.0)
        c.resume(real=100.0)
        self.assertAlmostEqual(c.now(real=101.0), 7.0)


if __name__ == "__main__":
    unittest.main()
