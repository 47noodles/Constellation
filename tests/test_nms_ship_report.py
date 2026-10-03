"""Offline tests for the NMS adapter's ship state report.

The velocity is a finite difference of the ship scene node's absolute position
over real time (never cGcSpaceshipComponent.GetVelocity, which access-violates
on build 180383). The maths lives in adapters/nms/transforms.py as pure
functions; the adapter samples the node and hands the history to
transforms.ship_sample, so the exact wire JSON is asserted here without NMS or
pyMHF.
"""

import ast
import json
import os
import unittest

from adapters.nms import transforms

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WRITTEN = [
    "adapters/nms/constellation_nms.py",
    "adapters/nms/transforms.py",
    "spikes/nms/mods/constellation_nms5.py",
    "tests/test_nms_ship_report.py",
]


def history(*pairs):
    return list(pairs)


class SmoothVelocityTests(unittest.TestCase):
    def test_two_samples_is_a_finite_difference(self):
        vel = transforms.smooth_velocity([(10.0, (0.0, 0.0, 0.0)), (10.5, (5.0, -10.0, 2.0))])
        self.assertAlmostEqual(vel[0], 10.0)
        self.assertAlmostEqual(vel[1], -20.0)
        self.assertAlmostEqual(vel[2], 4.0)

    def test_steady_motion_over_five_frames(self):
        samples = [(100.0 + 0.1 * i, (i * 1.0, i * 2.0, i * 3.0)) for i in range(5)]
        vel = transforms.smooth_velocity(samples)
        for got, want in zip(vel, (10.0, 20.0, 30.0)):
            self.assertAlmostEqual(got, want)

    def test_window_ignores_samples_older_than_five_frames(self):
        samples = [
            (0.0, (1000.0, 0.0, 0.0)),  # outside the 5-frame window
            (1.0, (0.0, 0.0, 0.0)),
            (2.0, (1.0, 0.0, 0.0)),
            (3.0, (2.0, 0.0, 0.0)),
            (4.0, (3.0, 0.0, 0.0)),
            (5.0, (4.0, 0.0, 0.0)),
        ]
        vel = transforms.smooth_velocity(samples)
        self.assertEqual(vel, (1.0, 0.0, 0.0))

    def test_none_until_two_samples(self):
        self.assertIsNone(transforms.smooth_velocity([]))
        self.assertIsNone(transforms.smooth_velocity([(1.0, (0.0, 0.0, 0.0))]))

    def test_none_when_time_does_not_advance(self):
        self.assertIsNone(transforms.smooth_velocity([(1.0, (0.0, 0.0, 0.0)),
                                                      (1.0, (5.0, 0.0, 0.0))]))


class ShipSampleTests(unittest.TestCase):
    def test_zero_velocity_before_two_samples(self):
        sample = transforms.ship_sample([(100.0, (1.0, 2.0, 3.0))], 7, 100.0, (1.0, 2.0, 3.0))
        self.assertEqual(sample["vel"], [0.0, 0.0, 0.0])
        self.assertEqual(sample["pos"], [1.0, 2.0, 3.0])
        self.assertEqual(sample["frame"], 7)
        self.assertEqual(sample["real_t"], 100.0)

    def test_exact_ship_report_json(self):
        hist = history(
            (100.0, (0.0, 0.0, 0.0)),
            (100.1, (1.0, 2.0, 3.0)),
            (100.2, (2.0, 4.0, 6.0)),
            (100.3, (3.0, 6.0, 9.0)),
            (100.4, (4.0, 8.0, 12.0)),
        )
        sample = transforms.ship_sample(hist, 42, 100.4, (4.0, 8.0, 12.0))
        wire = json.dumps(sample, separators=(",", ":"))
        self.assertEqual(
            wire,
            '{"pos":[4.0,8.0,12.0],"vel":[10.0,20.0,30.0],"frame":42,"real_t":100.4}',
        )


class AdapterSourceTests(unittest.TestCase):
    def test_written_files_never_call_the_forbidden_velocity_apis(self):
        forbidden = ("Get" + "Velocity(", "SetLinear" + "Velocity(")
        for rel in WRITTEN:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                text = f.read()
            for token in forbidden:
                self.assertNotIn(token, text, rel)

    def test_nms5_copy_defines_the_renamed_class_and_parses(self):
        path = os.path.join(ROOT, "spikes/nms/mods/constellation_nms5.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        self.assertIn("ConstellationNMS5", classes)
        self.assertNotIn("ConstellationNMS4", classes)

    def test_adapter_report_builds_the_ship_key(self):
        path = os.path.join(ROOT, "adapters/nms/constellation_nms.py")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('msg["ship"] = transforms.ship_sample', text)


if __name__ == "__main__":
    unittest.main()
