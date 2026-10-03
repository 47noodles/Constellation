"""Offline tests for the pure arithmetic behind the ctl_srt override probe.

``override_relative_pos`` rewrites the relative translation the engine is about
to write so the resulting absolute node position equals a target. A node's
absolute position is ``parent + relative``; given the game's written relative
translation and the node's current absolute position we can recover the parent
offset and solve for the relative translation that lands on the target.
"""

import unittest

from adapters.nms import transforms


class TestOverrideRelativePos(unittest.TestCase):
    def test_parent_offset_is_cancelled(self):
        # parent = current_abs - written = (10, 20, 30); new_rel = target - parent.
        self.assertEqual(
            transforms.override_relative_pos((100.0, 200.0, 300.0), (1.0, 2.0, 3.0), (11.0, 22.0, 33.0)),
            (90.0, 180.0, 270.0),
        )

    def test_zero_parent_is_identity_to_target(self):
        self.assertEqual(
            transforms.override_relative_pos((5.0, 6.0, 7.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            (5.0, 6.0, 7.0),
        )

    def test_target_equal_current_abs_reproduces_written(self):
        # If the target is where the node already is, the engine's own relative
        # translation is the correct answer (parent cancels out).
        written = (4.0, -8.0, 15.0)
        current_abs = (40.0, 80.0, 150.0)
        self.assertEqual(
            transforms.override_relative_pos(current_abs, written, current_abs),
            written,
        )

    def test_resulting_absolute_equals_target(self):
        target = (-12.0, 3.5, 900.0)
        written = (7.0, 7.0, 7.0)
        current_abs = (1000.0, 1000.0, 1000.0)
        new_rel = transforms.override_relative_pos(target, written, current_abs)
        parent = transforms._sub(current_abs, written)
        self.assertEqual(transforms._add(parent, new_rel), (target[0], target[1], target[2]))


if __name__ == "__main__":
    unittest.main()
