"""Tests for patched-conic propagation in constellation/patched.py."""

import math
import unittest

from constellation.orbits import circular, norm, sub
from constellation.patched import (
    VesselState,
    body_parent,
    find_soi_entry,
    find_soi_exit,
    predict_all_encounters,
    predict_encounter,
    propagate,
    reparent,
    soi_chain,
    state_at,
)
from constellation.universe import STAR, Body, Universe

STAR_MU = 1.0e12
PLANET_MU = 4.0e12
PLANET_RADIUS = 600_000.0
PLANET_SOI = 800_000.0
PLANET_ORBIT_R = 1.0e7


def make_universe() -> Universe:
    orbit = circular(STAR_MU, (PLANET_ORBIT_R, 0.0, 0.0), epoch=0.0)
    body = Body("p0", 0, PLANET_RADIUS, PLANET_MU, orbit, PLANET_SOI,
                (PLANET_ORBIT_R, 0.0, 0.0))
    return Universe(star_mu=STAR_MU, bodies={"p0": body}, anchor=STAR,
                    anchor_nms=(0.0, 0.0, 0.0))


def planet_state(ut: float = 0.0) -> tuple:
    return make_universe().bodies["p0"].orbit.state_at(ut)


class EscapeTests(unittest.TestCase):
    def setUp(self):
        self.u = make_universe()
        self.state = VesselState("p0", (700_000.0, 0.0, 0.0),
                                 (4_000.0, 3_500.0, 0.0), 0.0)

    def test_body_helpers(self):
        self.assertEqual(body_parent(self.u, "p0"), STAR)
        self.assertEqual(soi_chain(self.u, "p0"), [STAR, "p0"])
        self.assertEqual(soi_chain(self.u, STAR), [STAR])

    def test_hyperbolic_state_actually_escapes(self):
        energy = 0.5 * (4_000.0 ** 2 + 3_500.0 ** 2) - PLANET_MU / 700_000.0
        self.assertGreater(energy, 0.0)

    def test_leaves_soi_at_the_right_time(self):
        crossing = find_soi_exit(self.u, self.state, t_max=5_000.0, step=10.0)
        self.assertIsNotNone(crossing)
        self.assertEqual(crossing.body_from, "p0")
        self.assertEqual(crossing.body_to, STAR)
        # radius crosses the SOI radius here, from inside to outside
        self.assertAlmostEqual(norm(crossing.r), PLANET_SOI, delta=1.0)
        before = norm(state_at(self.u, self.state, crossing.ut - 0.01).r)
        after = norm(state_at(self.u, self.state, crossing.ut + 0.01).r)
        self.assertLess(before, PLANET_SOI)
        self.assertGreater(after, PLANET_SOI)

    def test_parent_frame_state_is_continuous(self):
        crossing = find_soi_exit(self.u, self.state, t_max=5_000.0, step=10.0)
        s_cross = state_at(self.u, self.state, crossing.ut)
        rep = reparent(self.u, s_cross, crossing)
        self.assertEqual(rep.body, STAR)
        p_r, p_v = planet_state(crossing.ut)
        expected_r = (p_r[0] + crossing.r[0], p_r[1] + crossing.r[1], p_r[2] + crossing.r[2])
        expected_v = (p_v[0] + crossing.v[0], p_v[1] + crossing.v[1], p_v[2] + crossing.v[2])
        self.assertLess(norm(sub(rep.r, expected_r)), 1.0)
        self.assertLess(norm(sub(rep.v, expected_v)), 1e-3)

    def test_reparent_round_trip(self):
        crossing = find_soi_exit(self.u, self.state, t_max=5_000.0, step=10.0)
        s_cross = state_at(self.u, self.state, crossing.ut)
        rep = reparent(self.u, s_cross, crossing)
        inv_crossing = type(crossing)(crossing.ut, STAR, "p0", rep.r, rep.v)
        back = reparent(self.u, rep, inv_crossing)
        self.assertEqual(back.body, "p0")
        self.assertLess(norm(sub(back.r, s_cross.r)), 1.0)
        self.assertLess(norm(sub(back.v, s_cross.v)), 1e-3)

    def test_propagate_yields_exit_then_end(self):
        segments = propagate(self.u, self.state, t_end=3_000.0, max_crossings=8)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].body, STAR)
        self.assertEqual(segments[-1].ut, 3_000.0)


class EncounterTests(unittest.TestCase):
    def setUp(self):
        self.u = make_universe()
        p_r, p_v = planet_state(0.0)
        start = (p_r[0] + 2.0 * PLANET_SOI, p_r[1], p_r[2])
        closing = (p_v[0] - 2_000.0, p_v[1], p_v[2])
        self.state = VesselState(STAR, start, closing, 0.0)

    def test_moon_encounter_is_predicted(self):
        enc = predict_encounter(self.u, self.state, "p0", t_max=3_000.0, step=10.0)
        self.assertIsNotNone(enc)
        self.assertEqual(enc.body, "p0")
        self.assertLess(enc.miss_m, PLANET_SOI)
        self.assertGreater(enc.rel_speed_mps, 0.0)

    def test_handover_re_expresses_state_in_moon_frame(self):
        entry = find_soi_entry(self.u, self.state, "p0", t_max=3_000.0, step=10.0)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.body_to, "p0")
        s = state_at(self.u, self.state, entry.ut)
        rep = reparent(self.u, s, entry)
        self.assertEqual(rep.body, "p0")
        self.assertLess(norm(rep.r), PLANET_SOI)
        # continuity: converting back to the star frame recovers the star state
        inv = reparent(self.u, rep,
                       type(entry)(entry.ut, "p0", STAR, rep.r, rep.v))
        self.assertLess(norm(sub(inv.r, entry.r)), 1.0)
        self.assertLess(norm(sub(inv.v, entry.v)), 1e-3)

    def test_predict_all_is_time_ordered(self):
        encs = predict_all_encounters(self.u, self.state, t_max=3_000.0, step=10.0)
        self.assertTrue(all(a.ut <= b.ut for a, b in zip(encs, encs[1:])))
        self.assertEqual([e.body for e in encs], ["p0"])


class ClosedOrbitTests(unittest.TestCase):
    def setUp(self):
        self.u = make_universe()
        orbit = circular(PLANET_MU, (700_000.0, 0.0, 0.0), epoch=0.0)
        r, v = orbit.state_at(0.0)
        self.state = VesselState("p0", r, v, 0.0)

    def test_no_soi_exit_over_many_periods(self):
        self.assertIsNone(find_soi_exit(self.u, self.state, t_max=10.0 * 60_000.0))

    def test_no_encounter_event(self):
        self.assertEqual(predict_all_encounters(self.u, self.state, t_max=60_000.0), [])

    def test_propagate_is_a_single_segment(self):
        segments = propagate(self.u, self.state, t_end=60_000.0)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].body, "p0")
        self.assertEqual(segments[0].ut, 60_000.0)


if __name__ == "__main__":
    unittest.main()
