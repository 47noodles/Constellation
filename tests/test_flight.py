"""Tests for constellation.flight against docs/transfer-land-design.md.

Everything runs offline: a one-planet Universe stands in for the coordinator's
world, and the KSP/NMS adapters are not touched.
"""

import dataclasses
import math
import unittest

from constellation import flight as F
from constellation.orbits import dot, from_state, norm, scale, sub, unit
from constellation.universe import Universe

# One airless body: radius 130 km, surface gravity 9.81 m/s^2 (Body.mu is set
# by Universe.from_nms_planets as g * radius^2).
PLANETS = [{"slot": 1, "home": [1_000_000.0, 0.0, 0.0], "radius": 130_000.0}]

UP = (0.0, 1.0, 0.0)


def make_universe() -> Universe:
    return Universe.from_nms_planets(PLANETS)


def orbit_state(u: Universe, altitude_m: float, fuel_kg: float) -> F.FlightState:
    """A circular state with the given fuel; circular_orbit_state is kinematic."""
    return dataclasses.replace(
        F.circular_orbit_state(u, "p1", altitude_m), fuel_kg=fuel_kg)


def vertical_horizontal(v, r):
    up = unit(r)
    vr = dot(v, up)
    return vr, norm(sub(v, scale(up, vr)))


# ---- environment ------------------------------------------------

class VehicleTests(unittest.TestCase):
    def test_exhaust_velocity_and_mass_flow(self):
        veh = F.Vehicle(dry_mass_kg=1000.0, fuel_kg=100.0, thrust_n=50_000.0,
                        isp_s=300.0)
        self.assertAlmostEqual(veh.exhaust_velocity, 300.0 * 9.80665)
        self.assertAlmostEqual(veh.mass_flow(1.0), 50_000.0 / veh.exhaust_velocity)
        self.assertEqual(veh.mass_flow(0.0), 0.0)
        self.assertAlmostEqual(veh.mass_kg, 1100.0)

    def test_mass_ignores_negative_fuel(self):
        veh = F.Vehicle(dry_mass_kg=1000.0, fuel_kg=-5.0, thrust_n=1.0, isp_s=300.0)
        self.assertEqual(veh.mass_kg, 1000.0)


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.u = make_universe()
        self.b = self.u.bodies["p1"]

    def test_gravity_points_inward_and_is_inverse_square(self):
        g = F.gravity(self.b.mu, (0.0, self.b.radius, 0.0))
        self.assertAlmostEqual(norm(g), self.b.mu / self.b.radius ** 2, places=6)
        self.assertLess(g[1], 0.0)

    def test_atmosphere_density_and_top(self):
        atm = F.Atmosphere(1.2, 5000.0, 40000.0)
        self.assertAlmostEqual(F.atmosphere_density(atm, 0.0), 1.2)
        self.assertAlmostEqual(F.atmosphere_density(atm, 5000.0), 1.2 / math.e)
        self.assertEqual(F.atmosphere_density(atm, 40000.0), 0.0)
        self.assertEqual(F.atmosphere_density(atm, 50000.0), 0.0)
        self.assertEqual(F.atmosphere_density(None, 0.0), 0.0)

    def test_drag_opposes_motion_and_needs_an_atmosphere(self):
        atm = F.Atmosphere(1.2, 5000.0, 40000.0)
        veh = F.Vehicle(1000.0, 100.0, 50_000.0, 300.0, drag_area_m2=2.0, cd=0.5)
        f = F.drag_force(atm, veh, 1000.0, (0.0, -100.0, 0.0))
        self.assertGreater(f[1], 0.0)  # pushes back against downward motion
        self.assertEqual(F.drag_force(None, veh, 1000.0, (0.0, -100.0, 0.0)), F.ZERO)
        self.assertEqual(F.drag_force(atm, veh, 40000.0, (0.0, -100.0, 0.0)), F.ZERO)

    def test_altitude_and_terrain_callback(self):
        r = scale(UP, self.b.radius + 15000.0)
        self.assertAlmostEqual(F.altitude(self.u, "p1", r), 15000.0)
        self.assertAlmostEqual(F.altitude(self.u, "p1", r, lambda _r: 20000.0),
                               -5000.0)

    def test_circular_orbit_state_is_circular_and_level(self):
        st = F.circular_orbit_state(self.u, "p1", 20000.0)
        rn = norm(st.r)
        self.assertAlmostEqual(rn, self.b.radius + 20000.0, places=6)
        self.assertAlmostEqual(norm(st.v), math.sqrt(self.b.mu / rn), places=6)
        self.assertAlmostEqual(dot(st.r, st.v), 0.0, places=6)


# ---- integration ------------------------------------------------

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.u = make_universe()
        self.b = self.u.bodies["p1"]
        self.mu = self.b.mu

    def test_free_fall_accelerates_under_gravity(self):
        veh = F.Vehicle(dry_mass_kg=1000.0, fuel_kg=1.0, thrust_n=0.0, isp_s=300.0)
        st = F.FlightState("p1", scale(UP, self.b.radius + 20000.0),
                           (0.0, 0.0, 0.0), 1.0, 0.0)
        hist = F.simulate(st, veh, self.mu, lambda s: F.Command(0.0, UP),
                          10.0, 0.1, u=self.u)
        self.assertGreater(norm(hist[-1].v), norm(st.v))
        self.assertLess(norm(hist[-1].r), norm(st.r))

    def test_drag_slows_the_vessel(self):
        u = self.u
        veh = F.Vehicle(dry_mass_kg=1000.0, fuel_kg=1.0, thrust_n=0.0, isp_s=300.0,
                        drag_area_m2=4.0, cd=1.0)
        st = F.FlightState("p1", scale(UP, self.b.radius + 10000.0),
                           (0.0, 0.0, 0.0), 1.0, 0.0)
        atm = F.Atmosphere(1.2, 5000.0, 50000.0)
        ctl = lambda s: F.Command(0.0, UP)
        with_atm = F.simulate(st, veh, self.mu, ctl, 15.0, 0.05, atm=atm, u=u)
        no_atm = F.simulate(st, veh, self.mu, ctl, 15.0, 0.05, u=u)
        self.assertLess(norm(with_atm[-1].v), norm(no_atm[-1].v))

    def test_step_consumes_fuel_at_mass_flow(self):
        veh = F.Vehicle(dry_mass_kg=1000.0, fuel_kg=100.0, thrust_n=50_000.0,
                        isp_s=300.0)
        st = F.FlightState("p1", scale(UP, self.b.radius + 50000.0),
                           (0.0, 0.0, 0.0), 100.0, 0.0)
        nxt = F.step(st, veh, self.mu, 1.0, 1.0, UP)
        self.assertAlmostEqual(nxt.fuel_kg, 100.0 - veh.mass_flow(1.0) * 1.0,
                               places=6)
        self.assertAlmostEqual(nxt.ut, 1.0)

    def test_fuel_out_stops_the_simulation(self):
        veh = F.Vehicle(dry_mass_kg=1000.0, fuel_kg=10.0, thrust_n=50_000.0,
                        isp_s=300.0)
        st = F.FlightState("p1", scale(UP, self.b.radius + 50000.0),
                           (0.0, 0.0, 0.0), 10.0, 0.0)
        hist = F.simulate(st, veh, self.mu, lambda s: F.Command(1.0, UP),
                          1000.0, 0.5, u=self.u)
        self.assertAlmostEqual(hist[-1].fuel_kg, 0.0, places=6)
        self.assertLess(hist[-1].ut, 1000.0)


# ---- landing (acceptance criteria 1, 2, 4, 5) --------------------

class LandingTests(unittest.TestCase):
    def setUp(self):
        self.u = make_universe()
        self.b = self.u.bodies["p1"]
        self.mu = self.b.mu

    def _descent_vehicle(self, fuel=12000.0):
        return F.Vehicle(dry_mass_kg=2000.0, fuel_kg=fuel, thrust_n=400_000.0,
                         isp_s=300.0, drag_area_m2=2.0, cd=0.5)

    def _land(self, vehicle, atm=None, terrain=None, fuel=12000.0):
        st = orbit_state(self.u, 20000.0, fuel)
        g = F.suicide_burn_guidance(vehicle, self.mu, self.b.radius, atm=atm,
                                    terrain=terrain)
        return F.execute_autopilot(self.u, st, vehicle, g, 4000.0, 0.25,
                                   atm=atm, terrain=terrain)

    def test_airless_descent_lands_softly_with_fuel_left(self):
        veh = self._descent_vehicle()
        final = self._land(veh)
        vr, vh = vertical_horizontal(final.v, final.r)
        self.assertTrue(F.landing_detected(self.u, final))
        self.assertLess(abs(vr), 5.0)
        self.assertLess(vh, 2.0)
        self.assertGreater(final.fuel_kg, 0.0)

    def test_atmosphere_drag_slows_and_landing_succeeds(self):
        atm = F.Atmosphere(1.2, 5000.0, 40000.0)
        veh = self._descent_vehicle()
        final = self._land(veh, atm=atm)
        vr, vh = vertical_horizontal(final.v, final.r)
        self.assertTrue(F.landing_detected(self.u, final, None))
        self.assertLess(abs(vr), 5.0)
        self.assertLess(vh, 2.0)
        self.assertGreater(final.fuel_kg, 0.0)
        # Drag does part of the braking: the atmospheric descent saves fuel.
        airless = self._land(self._descent_vehicle())
        self.assertGreater(final.fuel_kg, airless.fuel_kg)

    def test_running_out_of_fuel_is_a_crash_not_a_landing(self):
        veh = F.Vehicle(dry_mass_kg=12_000.0, fuel_kg=500.0, thrust_n=400_000.0,
                        isp_s=300.0)
        st = orbit_state(self.u, 20000.0, 500.0)
        g = F.suicide_burn_guidance(veh, self.mu, self.b.radius)
        final = F.execute_autopilot(self.u, st, veh, g, 4000.0, 0.25)
        self.assertAlmostEqual(final.fuel_kg, 0.0, places=6)
        self.assertFalse(F.landing_detected(self.u, final))

    def test_terrain_callback_raises_the_landing_surface(self):
        plateau = lambda _r: 5000.0
        st = orbit_state(self.u, 20000.0, 12000.0)
        veh = self._descent_vehicle()

        flat = self._land(veh)
        raised = self._land(veh, terrain=plateau)

        self.assertTrue(F.landing_detected(self.u, raised, plateau))
        # Flat ground is at body.radius; the plateau stops the vessel 5 km up.
        self.assertLess(norm(flat.r) - self.b.radius, 100.0)
        self.assertGreater(norm(raised.r) - self.b.radius, 4000.0)
        self.assertLess(norm(raised.r) - self.b.radius, 5200.0)

    def test_hold_landed_settles_the_state(self):
        st = F.FlightState("p1", scale(UP, self.b.radius), (3.0, -2.0, 1.0),
                           10.0, 5.0)
        held = F.hold_landed(st)
        self.assertEqual(held.v, (0.0, 0.0, 0.0))
        self.assertEqual(held.fuel_kg, 10.0)
        self.assertEqual(held.ut, 5.0)

    def test_ignition_altitude_positive_and_finite(self):
        veh = self._descent_vehicle()
        h = F.ignition_altitude(veh, self.mu, self.b.radius, 500.0,
                                self.mu / self.b.radius ** 2)
        self.assertGreater(h, 0.0)
        self.assertTrue(math.isfinite(h))


# ---- ascent (acceptance criterion 3) ----------------------------

class AscentTests(unittest.TestCase):
    def setUp(self):
        self.u = make_universe()
        self.b = self.u.bodies["p1"]
        self.mu = self.b.mu

    def test_ascent_reaches_an_orbit_above_the_terrain(self):
        target_alt = 30000.0
        veh = F.Vehicle(dry_mass_kg=1000.0, fuel_kg=30000.0, thrust_n=300_000.0,
                        isp_s=300.0)
        st = F.FlightState("p1", scale(UP, self.b.radius), (0.0, 0.0, 0.0),
                           30000.0, 0.0)
        guidance = F.gravity_turn_guidance(veh, self.mu, target_alt,
                                           turn_start_alt_m=500.0)
        final = F.execute_autopilot(self.u, st, veh, guidance, 4000.0, 0.25,
                                    stop_on_landing=False)
        orbit = from_state(self.mu, final.r, final.v, final.ut)
        self.assertLess(orbit.e, 1.0)  # a bound orbit
        periapsis = orbit.a * (1.0 - orbit.e)
        self.assertGreater(periapsis, self.b.radius + 1000.0)

    def test_ascent_with_atmosphere_still_reaches_a_bound_orbit(self):
        atm = F.Atmosphere(1.2, 5000.0, 10000.0)
        target_alt = 30000.0
        veh = F.Vehicle(dry_mass_kg=1000.0, fuel_kg=40000.0, thrust_n=400_000.0,
                        isp_s=300.0, drag_area_m2=2.0, cd=0.5)
        st = F.FlightState("p1", scale(UP, self.b.radius), (0.0, 0.0, 0.0),
                           40000.0, 0.0)
        guidance = F.gravity_turn_guidance(veh, self.mu, target_alt, atm=atm,
                                           turn_start_alt_m=500.0)
        final = F.execute_autopilot(self.u, st, veh, guidance, 4000.0, 0.25,
                                    atm=atm, stop_on_landing=False)
        orbit = from_state(self.mu, final.r, final.v, final.ut)
        self.assertLess(orbit.e, 1.0)
        self.assertGreater(orbit.a * (1.0 - orbit.e), self.b.radius + 1000.0)


if __name__ == "__main__":
    unittest.main()
