"""Offline tests for the NMS adapter's ship/player transform.

These exercise the pure decision module the adapter uses (adapters/nms/
transforms.py) with fake game objects - a fake ship scene node with an absolute
position matrix - so the transform from coordinator state to engine calls can be
checked without NMS or pyMHF. The live path (engine calls, SetToPosition) is
marked unverified in the report and covered by spikes/nms/mods/ctl_land.py.
"""

import os
import unittest

from adapters.nms import transforms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeVec3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def __getitem__(self, i):
        return (self.x, self.y, self.z)[i]

    def __len__(self):
        return 3


class FakeMatrix:
    """Stands in for basic.cTkMatrix34 as returned by GetNodeAbsoluteTransMatrix."""

    def __init__(self, pos):
        self.pos = FakeVec3(*pos)


class FakeShipNode:
    """A fake owned ship scene node: the adapter reads its absolute matrix."""

    def __init__(self, pos):
        self.matrix = FakeMatrix(pos)


class ShipTransformTests(unittest.TestCase):
    def test_orbit_shift_is_target_minus_node(self):
        node = FakeShipNode((100.0, 200.0, 300.0))
        ship = {"pos": [110.0, 195.0, 300.0], "vel_per_real_s": [0.0, 0.0, 0.0]}
        action = transforms.plan_ship(ship, "orbit", node_pos=node.matrix.pos)
        self.assertEqual(action.mode, "orbit")
        self.assertEqual(action.delta, (10.0, -5.0, 0.0))

    def test_orbit_extrapolates_send_time_position(self):
        node = FakeShipNode((0.0, 0.0, 0.0))
        ship = {"pos": [0.0, 0.0, 0.0], "vel_per_real_s": [10.0, -4.0, 2.0]}
        action = transforms.plan_ship(ship, "orbit", node_pos=node.matrix.pos, age=0.25)
        self.assertEqual(action.mode, "orbit")
        self.assertAlmostEqual(action.delta[0], 2.5)
        self.assertAlmostEqual(action.delta[1], -1.0)
        self.assertAlmostEqual(action.delta[2], 0.5)

    def test_orbit_without_node_is_none(self):
        action = transforms.plan_ship({"pos": [1.0, 2.0, 3.0]}, "orbit", node_pos=None)
        self.assertEqual(action.mode, "none")

    def test_flight_poses_player_with_forward_and_velocity(self):
        ship = {"pos": [5.0, 0.0, 0.0], "vel_per_real_s": [1.0, 0.0, 0.0],
                "pose": {"forward": [0.0, 0.0, 1.0], "up": [0.0, 1.0, 0.0]}}
        action = transforms.plan_ship(ship, "flight", age=1.0)
        self.assertEqual(action.mode, "flight")
        self.assertEqual(action.pos, (6.0, 0.0, 0.0))
        self.assertEqual(action.forward, (0.0, 0.0, 1.0))
        self.assertEqual(action.up, (0.0, 1.0, 0.0))
        self.assertEqual(action.vel, (1.0, 0.0, 0.0))

    def test_flight_pose_defaults_and_normalisation(self):
        action = transforms.plan_ship({"pos": [0.0, 0.0, 0.0],
                                       "pose": {"forward": [0.0, 0.0, 4.0]}}, "flight")
        self.assertEqual(action.forward, (0.0, 0.0, 1.0))
        self.assertEqual(action.up, (0.0, 1.0, 0.0))

    def test_no_ship_is_none(self):
        self.assertEqual(transforms.plan_ship(None, "orbit").mode, "none")

    def test_guard_allows_small_step_near_player(self):
        self.assertTrue(transforms.guard_allows((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.5, 0.0, 0.0)))

    def test_guard_refuses_big_step_near_player(self):
        self.assertFalse(transforms.guard_allows((100.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))

    def test_guard_allows_big_step_away_from_player(self):
        far = (1_000_000.0, 0.0, 0.0)
        self.assertTrue(transforms.guard_allows((100.0, 0.0, 0.0), far, (0.0, 0.0, 0.0)))


class NoGetVelocityTests(unittest.TestCase):
    def test_new_code_never_calls_getvelocity(self):
        for rel in ("adapters/nms/constellation_nms.py", "adapters/nms/transforms.py",
                    "spikes/nms/mods/ctl_land.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                self.assertNotIn("GetVelocity(", f.read(), rel)


if __name__ == "__main__":
    unittest.main()
