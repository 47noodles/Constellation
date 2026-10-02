import unittest

from constellation.ksp_link import POOL, assignment, ksp_elements, position_from_elements, sync_commands, zup
from constellation.orbits import circular, norm, sub
from constellation.universe import Universe
from tests.test_core import NMS_PLANETS


class KspLinkTests(unittest.TestCase):
    def test_elements_reproduce_positions(self):
        u = Universe.from_nms_planets(NMS_PLANETS)
        for b in u.bodies.values():
            el = ksp_elements(b.orbit)
            for t in (0.0, 1234.5, 50000.0):
                want = zup(b.orbit.position_at(t))
                got = position_from_elements(el, u.star_mu, t)
                self.assertLess(norm(sub(want, got)), 1e-3, (b.id, t))

    def test_inclined_orbit(self):
        o = circular(1e13, (4e6, 1.5e6, -2e6))
        el = ksp_elements(o)
        self.assertGreater(el["inc_deg"], 1.0)
        for t in (0.0, 999.0):
            self.assertLess(norm(sub(zup(o.position_at(t)), position_from_elements(el, 1e13, t))), 1e-3)

    def test_assignment_inner_to_outer(self):
        u = Universe.from_nms_planets(NMS_PLANETS)
        a = assignment(u)
        radii = [u.bodies[bid].orbit.a for bid in sorted(a, key=lambda bid: POOL.index(a[bid]))]
        self.assertEqual(radii, sorted(radii))

    def test_commands_cover_pool(self):
        cmds = sync_commands(Universe.from_nms_planets(NMS_PLANETS), 100.0)
        self.assertEqual(cmds[0], "setut 100.0")
        self.assertEqual(sum(c.startswith("setbody") for c in cmds), len(POOL))
        self.assertEqual(cmds[-1], "parkmoons")


if __name__ == "__main__":
    unittest.main()
