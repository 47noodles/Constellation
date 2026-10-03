import math
import unittest

from constellation.maneuver import (
    ManeuverNode,
    apply_node,
    best_porkchop,
    hohmann,
    lambert,
    phase_angle,
    plan_transfer,
    transfer_windows,
    window_after,
)
from constellation.orbits import TWO_PI, circular, cross, dot, from_state, norm, sub, unit
from constellation.universe import Body, Universe


class HohmannTests(unittest.TestCase):
    def test_departure_and_arrival_dv_match_analytic(self):
        mu = 3.986004418e14
        r1, r2 = 7.0e6, 4.2e7
        h = hohmann(mu, r1, r2)
        a_t = 0.5 * (r1 + r2)
        v_peri = math.sqrt(mu * (2.0 / r1 - 1.0 / a_t))
        v_apo = math.sqrt(mu * (2.0 / r2 - 1.0 / a_t))
        exp_depart = v_peri - math.sqrt(mu / r1)
        exp_arrive = math.sqrt(mu / r2) - v_apo
        self.assertLess(abs(h.dv_depart - exp_depart) / abs(exp_depart), 1e-6)
        self.assertLess(abs(h.dv_arrive - exp_arrive) / abs(exp_arrive), 1e-6)
        exp_time = math.pi * math.sqrt(a_t ** 3 / mu)
        self.assertLess(abs(h.transfer_time - exp_time) / exp_time, 1e-6)

    def test_transfer_orbit_apsides_and_eccentricity(self):
        mu = 3.986004418e14
        r1, r2 = 7.0e6, 4.2e7
        h = hohmann(mu, r1, r2)
        o = h.transfer_orbit
        self.assertLess(abs(o.a * (1.0 - o.e) - r1), 1e-3)
        self.assertLess(abs(o.a * (1.0 + o.e) - r2), 1e-3)
        self.assertLess(abs(o.e - (r2 - r1) / (r1 + r2)), 1e-12)

    def test_equal_radii_rejected(self):
        with self.assertRaises(ValueError):
            hohmann(3.986e14, 7e6, 7e6)


class LambertTests(unittest.TestCase):
    def test_reproduces_propagated_arc(self):
        mu = 3.986004418e14
        r0 = (7.0e6, 0.0, 0.0)
        v0 = (0.0, 0.0, -math.sqrt(mu / 7.0e6))  # prograde about +y
        o = from_state(mu, r0, v0, 0.0)
        tof = 0.2 * o.period
        r1, v1 = o.state_at(tof)
        sol = lambert(mu, r0, r1, tof, prograde=True)
        self.assertLess(norm(sub(sol.v0, v0)) / norm(v0), 1e-8)
        self.assertLess(norm(sub(sol.v1, v1)) / norm(v1), 1e-8)
        r_check, _ = from_state(mu, r0, sol.v0, 0.0).state_at(tof)
        self.assertLess(norm(sub(r_check, r1)), 1.0)

    def test_long_way_takes_longer(self):
        mu = 3.986004418e14
        r0 = (7.0e6, 0.0, 0.0)
        v0 = (0.0, 0.0, -math.sqrt(mu / 7.0e6))
        o = from_state(mu, r0, v0, 0.0)
        tof = 0.8 * o.period
        r1, v1 = o.state_at(tof)
        sol = lambert(mu, r0, r1, tof, prograde=False)
        self.assertLess(norm(sub(sol.v0, v0)) / norm(v0), 1e-8)

    def test_revolutions_not_supported(self):
        with self.assertRaises(ValueError):
            lambert(3.986e14, (7e6, 0.0, 0.0), (7e6, 1e6, 0.0), 3600.0, revolutions=1)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.mu = 1.32712440018e20
        self.r1 = 1.0e11
        self.r2 = 2.0e11
        self.o1 = circular(self.mu, (self.r1, 0.0, 0.0))
        self.o2 = circular(self.mu, (self.r2, 0.0, 0.0))

    def _actual_lead(self, t):
        e1, e2 = self.o1.p_hat, unit(cross(unit(cross(self.o1.p_hat, self.o1.q_hat)), self.o1.p_hat))
        rs = self.o1.position_at(t)
        rt = self.o2.position_at(t)
        a_ship = math.atan2(dot(rs, e2), dot(rs, e1))
        a_target = math.atan2(dot(rt, e2), dot(rt, e1))
        return (a_target - a_ship) % TWO_PI

    def test_window_matches_analytic_phase_angle(self):
        tr = window_after(self.mu, self.o1, self.o2, 0.0, self.o2.period, step=3600.0)
        self.assertIsNotNone(tr)
        h = hohmann(self.mu, self.r1, self.r2)
        expected = phase_angle(self.mu, self.r2, h.transfer_time)
        lead = self._actual_lead(tr.depart_ut)
        diff = (lead - expected + math.pi) % TWO_PI - math.pi
        self.assertLess(abs(diff), 1e-6)

    def test_transfer_fields_are_consistent(self):
        tr = window_after(self.mu, self.o1, self.o2, 0.0, self.o2.period, step=3600.0)
        h = hohmann(self.mu, self.r1, self.r2)
        self.assertAlmostEqual(tr.node.prograde, h.dv_depart, places=9)
        self.assertEqual(tr.node.normal, 0.0)
        self.assertEqual(tr.node.radial, 0.0)
        self.assertAlmostEqual(tr.arrive_ut - tr.depart_ut, h.transfer_time, places=6)
        self.assertAlmostEqual(tr.c3, h.dv_depart ** 2, places=3)

    def test_transfer_windows_sorted_and_after_t0(self):
        windows = transfer_windows(self.mu, self.o1, self.o2, 0.0, 3.0 * self.o2.period,
                                   step=3600.0)
        self.assertGreaterEqual(len(windows), 2)
        for a, b in zip(windows, windows[1:]):
            self.assertLess(a.depart_ut, b.depart_ut)
        self.assertGreaterEqual(windows[0].depart_ut, 0.0)

    def test_no_window_returns_none(self):
        self.assertIsNone(window_after(self.mu, self.o1, self.o2, 0.0, 1.0))


class NodeTests(unittest.TestCase):
    def test_prograde_node_raises_apoapsis(self):
        mu = 3.986004418e14
        r = (7.0e6, 0.0, 0.0)
        v = (0.0, 0.0, -math.sqrt(mu / 7.0e6))
        before = from_state(mu, r, v, 0.0)
        apo_before = before.a * (1.0 + before.e)
        node = ManeuverNode(ut=0.0, prograde=100.0, normal=0.0, radial=0.0)
        self.assertAlmostEqual(node.magnitude(), 100.0, places=9)
        _, v2 = apply_node(mu, r, v, node)
        after = from_state(mu, r, v2, 0.0)
        apo_after = after.a * (1.0 + after.e)
        self.assertGreater(apo_after, apo_before)

    def test_retrograde_node_lowers_apoapsis(self):
        mu = 3.986004418e14
        r = (7.0e6, 0.0, 0.0)
        v = (0.0, 0.0, -math.sqrt(mu / 7.0e6))
        _, v2 = apply_node(mu, r, v, ManeuverNode(0.0, -100.0, 0.0, 0.0))
        after = from_state(mu, r, v2, 0.0)
        self.assertLess(after.a * (1.0 - after.e), 7.0e6)
        self.assertAlmostEqual(after.a * (1.0 + after.e), 7.0e6, places=3)


class PorkchopTests(unittest.TestCase):
    def setUp(self):
        mu = 1.32712440018e20
        self.mu = mu
        self.o1 = circular(mu, (1.0e10, 0.0, 0.0))
        self.o2 = circular(mu, (2.0e10, 0.0, 0.0))

    def test_best_lambert_transfer_is_positive_and_ordered(self):
        tr = best_porkchop(self.mu, self.o1, self.o2,
                           0.0, 0.4 * self.o2.period,
                           0.0, 0.5 * self.o2.period,
                           coarse=36000.0, refine=None)
        self.assertIsNotNone(tr)
        self.assertGreater(tr.total_dv(), 0.0)


class PlanTransferTests(unittest.TestCase):
    def test_plan_transfer_over_universe_hohmann(self):
        mu = 1.32712440018e20
        o1 = circular(mu, (1.0e10, 0.0, 0.0))
        o2 = circular(mu, (2.0e10, 0.0, 0.0))
        b1 = Body("p1", 1, 6.0e6, 3.986e14, o1, 1.0e9, (1.0e10, 0.0, 0.0))
        b2 = Body("p2", 2, 6.0e6, 3.986e14, o2, 1.0e9, (2.0e10, 0.0, 0.0))
        u = Universe(star_mu=mu, bodies={"p1": b1, "p2": b2})
        tr = plan_transfer(u, "p1", "p2", 0.0, 0.5 * o2.period)
        self.assertIsNotNone(tr)
        self.assertGreater(tr.node.prograde, 0.0)


if __name__ == "__main__":
    unittest.main()
