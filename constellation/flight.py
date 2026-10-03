"""Powered flight near a body: descent, landing and ascent.

Implements section 3 of ``docs/transfer-land-design.md``. Units are metres,
seconds, kilograms, newtons and m^3/s^2, as in the rest of the package.

The coordinator owns powered flight below ``FLIGHT_ENTER_ALT_M``: it integrates
a state here against a body's surface radius (plus an optional terrain
callback) rather than taking the hidden KSP vessel to the ground. The KSP
vessel stays on rails; the NMS adapter poses the player/ship from the state
returned here.

One interface note: ``derivatives`` and ``step`` as specified in the design do
not carry a surface radius, but drag needs an altitude above the surface. They
gain an optional trailing ``surface_radius_m`` (default 0.0) so callers can
supply it; every positional parameter from the design is unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol

from .orbits import Vec, add, circular, cross, dot, norm, scale, sub, unit
from .universe import STAR, Universe

ZERO: Vec = (0.0, 0.0, 0.0)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _mu_of(u: Universe, body_id: str) -> float:
    return u.star_mu if body_id == STAR else u.bodies[body_id].mu


@dataclass(frozen=True)
class Vehicle:
    dry_mass_kg: float
    fuel_kg: float
    thrust_n: float
    isp_s: float
    drag_area_m2: float = 0.0
    cd: float = 0.0
    g0: float = 9.80665

    @property
    def exhaust_velocity(self) -> float:
        return self.isp_s * self.g0

    @property
    def mass_kg(self) -> float:
        return self.dry_mass_kg + max(self.fuel_kg, 0.0)

    def mass_flow(self, throttle: float) -> float:
        return _clamp(throttle, 0.0, 1.0) * self.thrust_n / self.exhaust_velocity


@dataclass(frozen=True)
class Atmosphere:
    surface_density_kg_m3: float
    scale_height_m: float
    top_m: float

    def density(self, altitude_m: float) -> float:
        return self.surface_density_kg_m3 * math.exp(-altitude_m / self.scale_height_m)


@dataclass(frozen=True)
class FlightState:
    body: str
    r: Vec
    v: Vec
    fuel_kg: float
    ut: float


@dataclass(frozen=True)
class Command:
    throttle: float
    attitude: Vec


TerrainFn = Callable[[Vec], float]
ControlFn = Callable[["FlightState"], Command]


class Guidance(Protocol):
    def command(self, state: FlightState) -> Command: ...


# ---- environment ------------------------------------------------------------


def surface_radius(u: Universe, body_id: str) -> float:
    return u.bodies[body_id].radius


def altitude(u: Universe, body_id: str, r: Vec,
             terrain: TerrainFn | None = None) -> float:
    ground = surface_radius(u, body_id)
    if terrain is not None:
        ground += terrain(r)
    return norm(r) - ground


def gravity(mu: float, r: Vec) -> Vec:
    rn = norm(r)
    return scale(r, -mu / (rn * rn * rn))


def atmosphere_density(atm: Atmosphere | None, altitude_m: float) -> float:
    if atm is None or altitude_m >= atm.top_m:
        return 0.0
    return atm.density(altitude_m)


def drag_force(atm: Atmosphere | None, vehicle: Vehicle, altitude_m: float,
               v_rel: Vec) -> Vec:
    rho = atmosphere_density(atm, altitude_m)
    if rho <= 0.0 or vehicle.cd <= 0.0 or vehicle.drag_area_m2 <= 0.0:
        return ZERO
    speed = norm(v_rel)
    if speed == 0.0:
        return ZERO
    k = -0.5 * rho * speed * vehicle.cd * vehicle.drag_area_m2
    return scale(v_rel, k)


def thrust_force(vehicle: Vehicle, throttle: float, attitude: Vec) -> Vec:
    throttle = _clamp(throttle, 0.0, 1.0)
    if throttle <= 0.0 or norm(attitude) == 0.0:
        return ZERO
    return scale(unit(attitude), throttle * vehicle.thrust_n)


# ---- integration ------------------------------------------------------------


def derivatives(state: FlightState, vehicle: Vehicle, mu: float, throttle: float,
                attitude: Vec, atm: Atmosphere | None = None,
                terrain: TerrainFn | None = None,
                surface_radius_m: float = 0.0) -> tuple[Vec, Vec, float]:
    r, v = state.r, state.v
    ground = surface_radius_m + (terrain(r) if terrain is not None else 0.0)
    alt = norm(r) - ground
    mass = vehicle.dry_mass_kg + max(state.fuel_kg, 0.0)
    if state.fuel_kg <= 0.0:
        throttle = 0.0
    acc = gravity(mu, r)
    if mass > 0.0:
        force = add(thrust_force(vehicle, throttle, attitude),
                    drag_force(atm, vehicle, alt, v))
        acc = add(acc, scale(force, 1.0 / mass))
    return (v, acc, -vehicle.mass_flow(throttle))


def _integrate(state: FlightState, vehicle: Vehicle, mu: float, dt: float,
               throttle: float, attitude: Vec, atm: Atmosphere | None,
               terrain: TerrainFn | None, surface_radius_m: float) -> FlightState:
    def f(s: FlightState):
        return derivatives(s, vehicle, mu, throttle, attitude, atm, terrain,
                           surface_radius_m)

    y = state
    dr1, dv1, dm1 = f(y)
    y2 = FlightState(y.body, add(y.r, scale(dr1, dt / 2.0)),
                     add(y.v, scale(dv1, dt / 2.0)), y.fuel_kg + dm1 * dt / 2.0,
                     y.ut + dt / 2.0)
    dr2, dv2, dm2 = f(y2)
    y3 = FlightState(y.body, add(y.r, scale(dr2, dt / 2.0)),
                     add(y.v, scale(dv2, dt / 2.0)), y.fuel_kg + dm2 * dt / 2.0,
                     y.ut + dt / 2.0)
    dr3, dv3, dm3 = f(y3)
    y4 = FlightState(y.body, add(y.r, scale(dr3, dt)),
                     add(y.v, scale(dv3, dt)), y.fuel_kg + dm3 * dt, y.ut + dt)
    dr4, dv4, dm4 = f(y4)
    r = add(y.r, scale(add(add(dr1, scale(dr2, 2.0)), add(scale(dr3, 2.0), dr4)), dt / 6.0))
    v = add(y.v, scale(add(add(dv1, scale(dv2, 2.0)), add(scale(dv3, 2.0), dv4)), dt / 6.0))
    fuel = y.fuel_kg + (dm1 + 2.0 * dm2 + 2.0 * dm3 + dm4) * dt / 6.0
    return FlightState(y.body, r, v, max(0.0, fuel), y.ut + dt)


def step(state: FlightState, vehicle: Vehicle, mu: float, dt: float,
         throttle: float, attitude: Vec, atm: Atmosphere | None = None,
         terrain: TerrainFn | None = None,
         surface_radius_m: float = 0.0) -> FlightState:
    if dt <= 0.0:
        return state
    throttle = _clamp(throttle, 0.0, 1.0)
    ve = vehicle.exhaust_velocity
    if ve <= 0.0 or vehicle.thrust_n <= 0.0:
        throttle = 0.0
    else:
        flow = vehicle.thrust_n / ve
        allowed = state.fuel_kg / (flow * dt) if flow * dt > 0.0 else 0.0
        throttle = min(throttle, max(0.0, allowed))
    return _integrate(state, vehicle, mu, dt, throttle, attitude, atm, terrain,
                      surface_radius_m)


def simulate(state: FlightState, vehicle: Vehicle, mu: float, control: ControlFn,
             t_end: float, dt: float, atm: Atmosphere | None = None,
             terrain: TerrainFn | None = None, stop_on_landing: bool = True,
             u: Universe | None = None) -> list[FlightState]:
    history = [state]
    cur = state
    sr = surface_radius(u, state.body) if u is not None else 0.0
    while cur.ut < t_end - 1e-9:
        cmd = control(cur)
        nxt = step(cur, vehicle, mu, dt, cmd.throttle, cmd.attitude, atm, terrain, sr)
        history.append(nxt)
        cur = nxt
        if cur.fuel_kg <= 1e-9:
            break
        if stop_on_landing and u is not None and landing_detected(u, cur, terrain):
            break
    return history


def landing_detected(u: Universe, state: FlightState,
                     terrain: TerrainFn | None = None,
                     touchdown_speed_mps: float = 1.0) -> bool:
    alt = altitude(u, state.body, state.r, terrain)
    return alt <= 0.0 and norm(state.v) <= touchdown_speed_mps


# ---- guidance ---------------------------------------------------------------


def ignition_altitude(vehicle: Vehicle, mu: float, surface_radius_m: float,
                      descent_speed_mps: float, gravity_mps2: float,
                      touchdown_speed_mps: float = 1.0) -> float:
    a = vehicle.thrust_n / max(vehicle.mass_kg, 1e-9) - gravity_mps2
    if a <= 0.0:
        return math.inf
    return (descent_speed_mps ** 2 + touchdown_speed_mps ** 2) / (2.0 * a)


class _SuicideBurn:
    """Retrograde descent: full throttle on the stopping curve, throttle to hold
    touchdown speed at the ground."""

    def __init__(self, vehicle: Vehicle, mu: float, surface_radius_m: float,
                 atm: Atmosphere | None, terrain: TerrainFn | None,
                 touchdown_speed_mps: float, max_throttle: float) -> None:
        self.vehicle = vehicle
        self.mu = mu
        self.surface_radius_m = surface_radius_m
        self.atm = atm
        self.terrain = terrain
        self.touchdown = touchdown_speed_mps
        self.max_throttle = max_throttle

    def command(self, state: FlightState) -> Command:
        r, v = state.r, state.v
        rn = norm(r)
        up = unit(r)
        ground = self.surface_radius_m + (self.terrain(r) if self.terrain else 0.0)
        alt = rn - ground
        g = self.mu / (rn * rn)
        mass = self.vehicle.dry_mass_kg + max(state.fuel_kg, 0.0)
        a_full = self.vehicle.thrust_n / mass if mass > 0.0 else 0.0
        a_net = a_full - g
        speed = norm(v)

        if speed <= 1e-6:
            attitude = up
        else:
            attitude = scale(v, -1.0 / speed)

        v_td = self.touchdown
        if a_net > 1e-6 and alt > 0.0:
            # Downward speed that can still be brought to v_td at the ground.
            speed_target = math.sqrt(v_td * v_td + 2.0 * a_net * alt)
        else:
            speed_target = v_td

        # Component of the retrograde thrust that fights gravity.
        cos_theta = dot(attitude, up) if speed > 1e-6 else 1.0
        cos_theta = max(cos_theta, 1e-3)

        if speed > speed_target:
            throttle = self.max_throttle
        else:
            # Track the target vertical speed with a proportional term.
            v_down = -dot(v, up)
            err = v_down - speed_target
            accel_cmd = g + 3.0 * err
            throttle = _clamp(accel_cmd * mass / (self.vehicle.thrust_n * cos_theta),
                              0.0, self.max_throttle)
        return Command(throttle, attitude)


class _GravityTurn:
    """Vertical until ``turn_start_alt_m``, pitched over so the attitude is
    horizontal at ``target_orbit_alt_m``; full throttle below the target.

    The design's signature has no surface radius, so altitude is measured from
    the radius at the first commanded state (the launch point). The prograde
    horizontal is the same direction ``orbits.circular`` picks for a body on
    the ``up`` axis, so the ascent can end in ``circular_orbit_state``.
    """

    def __init__(self, vehicle: Vehicle, mu: float, target_orbit_alt_m: float,
                 atm: Atmosphere | None, turn_start_alt_m: float,
                 max_throttle: float) -> None:
        self.vehicle = vehicle
        self.mu = mu
        self.target = target_orbit_alt_m
        self.atm = atm
        self.turn_start = turn_start_alt_m
        self.max_throttle = max_throttle
        self._r0 = None
        self._cutoff = False

    def _horizontal(self, up: Vec) -> Vec:
        h = cross((1.0, 0.0, 0.0), up)
        if norm(h) < 1e-9:
            h = cross((0.0, 0.0, 1.0), up)
        return unit(h)

    def command(self, state: FlightState) -> Command:
        rn = norm(state.r)
        if self._r0 is None:
            self._r0 = rn
        alt = rn - self._r0
        up = unit(state.r)
        horiz = self._horizontal(up)
        span = max(self.target - self.turn_start, 1.0)
        f = _clamp((alt - self.turn_start) / span, 0.0, 1.0)
        # Ease the pitch over early (f**0.6); the attitude is horizontal exactly
        # at the target altitude, as the design's pitch law requires.
        f = f ** 0.6
        if f <= 0.0:
            attitude = up
        else:
            angle = f * math.pi / 2.0
            attitude = unit(add(scale(up, math.cos(angle)),
                                scale(horiz, math.sin(angle))))
        throttle = self.max_throttle if alt < self.target else 0.0
        if alt >= self.target:
            self._cutoff = True
        if self._cutoff:
            throttle = 0.0
        return Command(throttle, attitude)


def suicide_burn_guidance(vehicle: Vehicle, mu: float, surface_radius_m: float,
                          atm: Atmosphere | None = None,
                          terrain: TerrainFn | None = None,
                          touchdown_speed_mps: float = 1.0,
                          max_throttle: float = 1.0) -> Guidance:
    return _SuicideBurn(vehicle, mu, surface_radius_m, atm, terrain,
                        touchdown_speed_mps, max_throttle)


def gravity_turn_guidance(vehicle: Vehicle, mu: float, target_orbit_alt_m: float,
                          atm: Atmosphere | None = None,
                          turn_start_alt_m: float = 1000.0,
                          max_throttle: float = 1.0) -> Guidance:
    return _GravityTurn(vehicle, mu, target_orbit_alt_m, atm, turn_start_alt_m,
                        max_throttle)


def circular_orbit_state(u: Universe, body_id: str, altitude_m: float,
                         epoch: float = 0.0,
                         terrain: TerrainFn | None = None,
                         up: Vec = (0.0, 1.0, 0.0)) -> FlightState:
    body = u.bodies[body_id]
    up_hat = unit(up)
    base = scale(up_hat, body.radius + altitude_m)
    if terrain is not None:
        base = scale(up_hat, body.radius + altitude_m + terrain(base))
    orbit = circular(body.mu, base, up_hat, epoch)
    r, v = orbit.state_at(epoch)
    return FlightState(body_id, r, v, 0.0, epoch)


def execute_autopilot(u: Universe, state: FlightState, vehicle: Vehicle,
                      guidance: Guidance, t_end: float, dt: float,
                      atm: Atmosphere | None = None,
                      terrain: TerrainFn | None = None,
                      stop_on_landing: bool = True) -> FlightState:
    mu = _mu_of(u, state.body)
    control: ControlFn = lambda s: guidance.command(s)
    history = simulate(state, vehicle, mu, control, t_end, dt, atm, terrain,
                       stop_on_landing, u)
    return history[-1]


def hold_landed(state: FlightState) -> FlightState:
    return FlightState(state.body, state.r, ZERO, state.fuel_kg, state.ut)
