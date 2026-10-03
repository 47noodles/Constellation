# Transfer and landing: fixed interfaces

Goal scenario (Lachlan, 3 Oct 2026): the player starts in orbit of planet A,
opens the KSP map, plans and executes a transfer burn in a window, crosses into
planet B's SOI, descends and lands on B, and can later launch back to orbit.

This document fixes the interfaces before any code is written. It covers six
modules: three new Python modules in `constellation/`, additions to `Bridge.cs`
and `ksp_link.py`, changes to the NMS adapter, and the coordinator wiring.

## 0. Conventions

* Units are metres, seconds, kg, newtons, m^3/s^2 throughout, as in
  `constellation/orbits.py`.
* `Vec = tuple[float, float, float]`; `r` is a position, `v` a velocity.
* Two spaces, as in `universe.py`: **orbit space** (the star at the origin, the
  frame `Orbit` uses) and **NMS space** (NMS's own coordinates, reached through
  the coordinator's anchor). Unless a signature says `_nms`, vectors are orbit
  space in the frame of the named body.
* `Universe`, `Body`, `Orbit`, `STAR` are the existing types in
  `universe.py` / `orbits.py`. `Body.id` is `"p<slot>"`; `STAR = "star"`.
* `Vec`, `add`, `sub`, `scale`, `dot`, `cross`, `norm`, `unit`, `from_state`,
  `circular` come from `orbits.py`.
* A **public function** means a module-level name or a method not prefixed with
  `_`. Every one of them for the three new modules is listed below.

---

## 1. `constellation/maneuver.py`

Maneuver nodes, Hohmann transfer and phase-angle window, a Lambert solver, and a
porkchop/window search between two bodies of the universe.

### Types

```python
@dataclass(frozen=True)
class ManeuverNode:
    ut: float        # absolute game time of the burn (s)
    prograde: float  # m/s along the velocity direction
    normal: float    # m/s along the orbit normal (r x v)
    radial: float    # m/s along the in-plane radial (normal x prograde)

    def dv(self) -> Vec: ...          # node delta-v in coordinator axes
    def magnitude(self) -> float: ... # |dv| (m/s)

@dataclass(frozen=True)
class HohmannTransfer:
    r1: float                  # departure radius (m)
    r2: float                  # arrival radius (m)
    dv_depart: float           # m/s, prograde at departure (can be negative)
    dv_arrive: float           # m/s, prograde at arrival (negative = capture)
    transfer_time: float       # s, half the transfer ellipse period
    transfer_orbit: Orbit      # the transfer ellipse about the central body

@dataclass(frozen=True)
class Transfer:
    depart_ut: float           # s
    arrive_ut: float           # s
    node: ManeuverNode         # departure burn, ready for KSP's map
    dv_arrive: float           # m/s, prograde at arrival (capture burn)
    c3: float                  # m^2/s^2, departure energy

    def total_dv(self) -> float: ...  # |node.dv| + |dv_arrive|

@dataclass(frozen=True)
class LambertSolution:
    v0: Vec    # departure velocity at r0 (m/s)
    v1: Vec    # arrival velocity at r1 (m/s)
    tof: float # time of flight (s)
    revolutions: int
```

### Functions

```python
def orbital_directions(r: Vec, v: Vec) -> tuple[Vec, Vec, Vec]:
    """(prograde, normal, radial) unit vectors at a state. normal = unit(r x v),
    prograde = unit(v), radial = unit(normal x prograde). Raises ValueError on a
    degenerate (radial or zero) state."""

def apply_node(mu: float, r: Vec, v: Vec, node: ManeuverNode) -> tuple[Vec, Vec]:
    """Position, velocity after the node's instantaneous burn at (r, v). Position
    is unchanged; velocity gains node.prograde*p_hat + node.normal*n_hat +
    node.radial*r_hat."""

def hohmann(mu: float, r1: float, r2: float, epoch: float = 0.0) -> HohmannTransfer:
    """The two-impulse transfer between circular radii r1 and r2 about a body of
    parameter mu. transfer_orbit is an Orbit with e = |r2-r1|/(r1+r2) whose
    periapsis/apoapsis match r1, r2. Raises ValueError for r1 == r2."""

def phase_angle(mu: float, r_target: float, transfer_time: float) -> float:
    """Required lead angle (rad, wrapped to [0, 2*pi)) of the target body ahead of
    the vessel at departure: pi - n_target * transfer_time."""

def window_after(mu: float, from_orbit: Orbit, to_orbit: Orbit, t0: float,
                 span: float, step: float = 60.0) -> Transfer | None:
    """First Hohmann window with depart_ut >= t0 within t0 + span, or None. The
    vessel and target are taken on from_orbit and to_orbit. The departure burn is
    prograde, so node.normal = node.radial = 0."""

def transfer_windows(mu: float, from_orbit: Orbit, to_orbit: Orbit, t0: float,
                     span: float, step: float = 60.0) -> list[Transfer]:
    """Every Hohmann window in [t0, t0 + span], in time order."""

def lambert(mu: float, r0: Vec, r1: Vec, tof: float, prograde: bool = True,
            revolutions: int = 0, long_way: bool = False) -> LambertSolution:
    """Universal-variable Lambert solver: the transfer from r0 to r1 in time
    tof. prograde picks the short-way transfer relative to the r0 x r1 normal.
    Raises ValueError when no conic connects the two in that time."""

def dv_for_lambert(mu: float, r0: Vec, v0_current: Vec, r1: Vec, v1_target: Vec,
                   tof: float, prograde: bool = True,
                   revolutions: int = 0) -> Transfer:
    """Wrap lambert: the departure node and the arrival capture delta-v needed to
    go from the current state at r0 to a rendezvous with v1_target at r1."""

def porkchop(mu: float, from_orbit: Orbit, to_orbit: Orbit,
             depart_from: float, depart_to: float,
             arrive_from: float, arrive_to: float,
             coarse: float = 3600.0, refine: float | None = 600.0) -> list[Transfer]:
    """Grid-search departure/arrival times with the Lambert solver. r0 is the
    from_orbit position at depart_ut and r1 the to_orbit position at arrive_ut;
    dv_depart = v0_lambert - v_from, dv_arrive = v_to - v1_lambert, c3 =
    |dv_depart|^2. Returns the coarse grid refined around the best cell, sorted by
    total_dv ascending."""

def best_porkchop(mu: float, from_orbit: Orbit, to_orbit: Orbit,
                  depart_from: float, depart_to: float,
                  arrive_from: float, arrive_to: float,
                  coarse: float = 3600.0, refine: float | None = 600.0) -> Transfer | None:
    """The lowest total_dv entry of porkchop, or None if the grid is empty."""

def plan_transfer(u: Universe, from_id: str, to_id: str, t0: float,
                  span: float, use_lambert: bool = False) -> Transfer | None:
    """Convenience over a Universe: hohmann+window from u.bodies[from_id].orbit to
    u.bodies[to_id].orbit about u.star_mu. When use_lambert is true, uses
    best_porkchop over depart [t0, t0+span] and arrive [t0, t0+2*span]."""
```

---

## 2. `constellation/patched.py`

Patched-conic vessel propagation across SOIs owned by the coordinator: find SOI
exit/entry events, re-express state in the new parent frame, predict encounters.

### Types

```python
@dataclass(frozen=True)
class VesselState:
    body: str   # "star" or "p<slot>": the body the state is relative to
    r: Vec      # position relative to body centre, coordinator axes (m)
    v: Vec      # velocity relative to body centre (m/s)
    ut: float   # s

@dataclass(frozen=True)
class SoiCrossing:
    ut: float          # s
    body_from: str     # SOI left
    body_to: str       # SOI entered
    r: Vec             # position relative to body_from at the crossing (m)
    v: Vec             # velocity relative to body_from at the crossing (m/s)

@dataclass(frozen=True)
class Encounter:
    body: str          # body encountered
    ut: float          # s of closest approach
    miss_m: float      # distance from body centre at closest approach (m)
    rel_speed_mps: float
    impact: bool       # miss_m < body.radius
```

### Functions

```python
def body_mu(u: Universe, body_id: str) -> float:
    """u.star_mu for STAR, else u.bodies[body_id].mu."""

def body_soi(u: Universe, body_id: str) -> float:
    """math.inf for STAR, else u.bodies[body_id].soi."""

def body_parent(u: Universe, body_id: str) -> str:
    """STAR for a planet (single-level hierarchy today)."""

def soi_chain(u: Universe, body_id: str) -> list[str]:
    """The parent chain from STAR down to body_id, e.g. ["star", "p1"]."""

def state_at(u: Universe, state: VesselState, t: float) -> VesselState:
    """Kepler-propagate within the current SOI to time t (from_state + Orbit)."""

def position_nms(u: Universe, state: VesselState, t: float) -> Vec:
    """NMS-space position of the vessel at t: the body's nms_pos plus the
    propagated offset, via universe.nms_pos(state.body, t)."""

def velocity_nms(u: Universe, state: VesselState, t: float) -> Vec:
    """NMS-space velocity of the vessel at t (body nms_vel plus relative v)."""

def find_soi_exit(u: Universe, state: VesselState, t_max: float,
                  step: float = 30.0) -> SoiCrossing | None:
    """First time in (state.ut, t_max] at which |r(t)| reaches the current body's
    SOI radius, found by sign change and bisection. None if it stays inside.
    body_from = state.body, body_to = body_parent(u, state.body)."""

def find_soi_entry(u: Universe, state: VesselState, target_body: str,
                   t_max: float, step: float = 30.0) -> SoiCrossing | None:
    """First time in (state.ut, t_max] at which the vessel comes within
    body_soi(u, target_body) of target_body's centre. body_from = state.body,
    body_to = target_body."""

def reparent(u: Universe, state: VesselState, crossing: SoiCrossing) -> VesselState:
    """Re-express the state in body_to's frame at the crossing UT: the parent's
    own position and velocity are subtracted when going out, added when going in,
    so the state is continuous across the patch. Returns a VesselState relative
    to body_to at the same UT."""

def propagate(u: Universe, state: VesselState, t_end: float,
              max_crossings: int = 8) -> list[VesselState]:
    """Propagate to t_end, applying find_soi_exit/reparent at every crossing.
    Returns the segment states (one per SOI, last ending at t_end)."""

def trajectory(u: Universe, state: VesselState, t_end: float,
               step: float = 60.0) -> list[VesselState]:
    """Sampled path over [state.ut, t_end], crossing SOIs as in propagate."""

def predict_encounter(u: Universe, state: VesselState, target_body: str,
                      t_max: float, step: float = 30.0) -> Encounter | None:
    """Closest approach to target_body over the propagated path, or None if it
    never enters the SOI."""

def predict_all_encounters(u: Universe, state: VesselState, t_max: float,
                           step: float = 30.0) -> list[Encounter]:
    """One Encounter per non-star body whose SOI the path enters, time-ordered."""
```

---

## 3. `constellation/flight.py`

Powered flight near a body for descent, landing and ascent: gravity, optional
exponential atmosphere with drag, thrust and mass flow, landing detection
against surface radius plus an optional terrain-height callback, suicide-burn
descent guidance, and gravity-turn ascent guidance to a circular orbit.

### Types

```python
@dataclass(frozen=True)
class Vehicle:
    dry_mass_kg: float
    fuel_kg: float
    thrust_n: float          # vacuum thrust (N)
    isp_s: float             # specific impulse (s)
    drag_area_m2: float = 0.0
    cd: float = 0.0
    g0: float = 9.80665

    @property
    def exhaust_velocity(self) -> float: ...   # isp_s * g0 (m/s)
    @property
    def mass_kg(self) -> float: ...            # dry + fuel
    def mass_flow(self, throttle: float) -> float: ...  # kg/s, = throttle*T/ve

@dataclass(frozen=True)
class Atmosphere:
    surface_density_kg_m3: float
    scale_height_m: float
    top_m: float             # altitude where the atmosphere ends (m)
    def density(self, altitude_m: float) -> float: ...  # rho0 * exp(-h/H), 0 above top

@dataclass(frozen=True)
class FlightState:
    body: str
    r: Vec            # relative to body centre, coordinator axes (m)
    v: Vec            # relative to body centre (m/s)
    fuel_kg: float
    ut: float

@dataclass(frozen=True)
class Command:
    throttle: float   # 0..1
    attitude: Vec     # unit thrust direction in coordinator axes

TerrainFn = Callable[[Vec], float]          # position -> height above surface radius (m)
ControlFn = Callable[[FlightState], Command]

class Guidance(Protocol):
    def command(self, state: FlightState) -> Command: ...
```

### Functions

```python
def surface_radius(u: Universe, body_id: str) -> float:
    """u.bodies[body_id].radius."""

def altitude(u: Universe, body_id: str, r: Vec,
             terrain: TerrainFn | None = None) -> float:
    """|r| - (surface_radius + terrain(r)) if a terrain callback is given, else
    |r| - surface_radius. Positive above the ground."""

def gravity(mu: float, r: Vec) -> Vec:
    """-mu * r / |r|^3 (m/s^2)."""

def atmosphere_density(atm: Atmosphere | None, altitude_m: float) -> float:
    """0.0 when atm is None or altitude_m >= atm.top_m, else atm.density."""

def drag_force(atm: Atmosphere | None, vehicle: Vehicle, altitude_m: float,
               v_rel: Vec) -> Vec:
    """-0.5 * rho * |v_rel| * v_rel * cd * area (N). Assumes an atmosphere that is
    static in the body frame; rotation is ignored at this stage."""

def thrust_force(vehicle: Vehicle, throttle: float, attitude: Vec) -> Vec:
    """unit(attitude) * throttle * thrust_n (N)."""

def derivatives(state: FlightState, vehicle: Vehicle, mu: float, throttle: float,
                attitude: Vec, atm: Atmosphere | None = None,
                terrain: TerrainFn | None = None) -> tuple[Vec, Vec, float]:
    """(dr/dt, dv/dt, dm/dt): gravity + thrust + drag, and -mass_flow."""

def step(state: FlightState, vehicle: Vehicle, mu: float, dt: float,
         throttle: float, attitude: Vec, atm: Atmosphere | None = None,
         terrain: TerrainFn | None = None) -> FlightState:
    """One RK4 step; fuel and ut updated. Throttle is clamped to what the fuel
    allows."""

def simulate(state: FlightState, vehicle: Vehicle, mu: float, control: ControlFn,
             t_end: float, dt: float, atm: Atmosphere | None = None,
             terrain: TerrainFn | None = None,
             stop_on_landing: bool = True, u: Universe | None = None) -> list[FlightState]:
    """Integrate under a control function until t_end, landing or fuel-out.
    Returns the state history, newest last."""

def landing_detected(u: Universe, state: FlightState,
                     terrain: TerrainFn | None = None,
                     touchdown_speed_mps: float = 1.0) -> bool:
    """True at the first step where altitude <= 0 and |v| <= touchdown_speed_mps;
    the caller records the landing state."""

def ignition_altitude(vehicle: Vehicle, mu: float, surface_radius_m: float,
                      descent_speed_mps: float, gravity_mps2: float,
                      touchdown_speed_mps: float = 1.0) -> float:
    """Suicide-burn ignition altitude (m): v^2/(2*a) with a the net acceleration
    available at full throttle, plus the distance to shed touchdown_speed."""

def suicide_burn_guidance(vehicle: Vehicle, mu: float, surface_radius_m: float,
                          atm: Atmosphere | None = None,
                          terrain: TerrainFn | None = None,
                          touchdown_speed_mps: float = 1.0,
                          max_throttle: float = 1.0) -> Guidance:
    """Retrograde descent: full throttle while altitude <= ignition altitude,
    throttling to hold touchdown_speed at the ground. command() returns attitude
    = -unit(v) (up when nearly stopped)."""

def gravity_turn_guidance(vehicle: Vehicle, mu: float, target_orbit_alt_m: float,
                          atm: Atmosphere | None = None,
                          turn_start_alt_m: float = 1000.0,
                          max_throttle: float = 1.0) -> Guidance:
    """Vertical until turn_start_alt_m, then pitches with altitude so the final
    attitude is horizontal at target_orbit_alt_m; commands full throttle until
    the target altitude, then a cutoff. Suited to reaching a circular orbit when
    paired with circular_orbit_state."""

def circular_orbit_state(u: Universe, body_id: str, altitude_m: float,
                         epoch: float = 0.0,
                         terrain: TerrainFn | None = None,
                         up: Vec = (0.0, 1.0, 0.0)) -> FlightState:
    """A circular, equatorial-ish state at the given altitude, prograde about
    up, using orbits.circular and the body's mu. The seam between flight.py and
    patched.py: the ascent ends here and the orbit module takes over."""

def execute_autopilot(u: Universe, state: FlightState, vehicle: Vehicle,
                      guidance: Guidance, t_end: float, dt: float,
                      atm: Atmosphere | None = None,
                      terrain: TerrainFn | None = None,
                      stop_on_landing: bool = True) -> FlightState:
    """Run guidance.command on every step of simulate and return the final state."""

def hold_landed(state: FlightState) -> FlightState:
    """A settled landed state (v = 0) for the coordinator to sit in until launch."""
```

---

## 4. KSP: `Bridge.cs` and `ksp_link.py`

The map view is KSP's. Planned nodes must appear in it, so the plugin gains
maneuver-node commands. Exact command names (one command per UDP datagram on
127.0.0.1:47821, one JSON reply, as today):

| Command (new) | Arguments | Reply | Meaning |
|---|---|---|---|
| `addnode` | `<ut> <prograde> <normal> <radial>` | `{"ok":true,"node":{...}}` | add a node to the active vessel at UT with the given m/s components |
| `clearnodes` | none | `{"ok":true,"nodes":[]}` | remove every maneuver node |
| `readnodes` | none | `{"ok":true,"nodes":[{...}]}` | list nodes, inner to outer |

A node object is `{"index":i,"ut":t,"prograde":p,"normal":n,"radial":r}`.
`addnode` uses `vessel.patchedConicSolver.AddManeuverNode(ut)`, sets
`node.DeltaV = new Vector3d(prograde, normal, radial)` in the node's own
pro/normal/radial frame, `node.UT = ut`, then `patchedConicSolver.Update()`.
`clearnodes` walks `patchedConicSolver.maneuverNodes` and calls
`RemoveManeuverNode`, then `Update()`. `readnodes` reads `node.UT` and
`node.DeltaV` back. All three require the vessel on rails (as `burn` does).
Executing a node is not a new plugin command: the coordinator waits for the
node's UT and issues the existing `burn <prograde> <normal> <radial>`.

Additions to `constellation/ksp_link.py`:

```python
def add_node_cmd(node: ManeuverNode) -> str:
    """The exact addnode line: "addnode <ut> <prograde> <normal> <radial>"."""

class KspLink:
    def add_node(self, node: ManeuverNode, timeout: float = 2.0) -> dict | None: ...
    def clear_nodes(self, timeout: float = 2.0) -> dict | None: ...
    def read_nodes(self, timeout: float = 2.0) -> list[dict] | None: ...
    def execute_node(self, node: ManeuverNode, timeout: float = 2.0) -> dict | None:
        """Wait until game time reaches node.ut (or schedule the burn from
        tick()), then issue the existing burn with node's components."""
```

`KspLink.REPLY_KEY` gains `"addnode": "node"`, `"clearnodes": "nodes"`,
`"readnodes": "nodes"`. `add_node_cmd` is a pure function so tests can assert
the wire format without KSP.

---

## 5. NMS adapter: render the ship and write the pose

Constraint: `cGcSpaceshipComponent.GetVelocity` access-violates on build 180383
(`spikes/nms/logs/pymhf.log:27`, `OSError: access violation reading
0xFFFFFFFFFFFFFFFF`), so the adapter must never call it. The proven paths are
`Engine.GetNodeAbsoluteTransMatrix` / `Engine.ShiftAllTransformsForNode` on the
ship scene node (`spikes/nms/mods/ctl_pose3.py`) and `cGcPlayer.SetToPosition`
(`spikes/nms/mods/ctl_player.py:137`).

Changes to `adapters/nms/constellation_nms.py`:

* `nms_targets` gains `"mode": "orbit" | "flight"` and the `ship` field gains
  `"pose": {"forward": [x, y, z], "up": [x, y, z]}` (both unit vectors in NMS
  axes) alongside the existing `body`, `pos`, `vel_per_real_s`, `alt_m`.
* New helpers on `ConstellationNMS4`:
  `_ship_node()` (owned, valid ship node nearest the player, from
  `gameData.game_state.mPlayerShipOwnership.mShips`), `_apply_ship(ship, mode)`,
  `_set_pose(pos, forward, up)`.
* `mode == "orbit"` (on rails, KSP/patched): compute `delta = ship["pos"] -
  GetNodeAbsoluteTransMatrix(node).pos` and call
  `ShiftAllTransformsForNode(node, delta)`. No ship physics, no velocity hook.
* `mode == "flight"` (powered, coordinator-owned): move the player with
  `player.SetToPosition(byref(cTkBigPos(pos, 0)), byref(direction), byref(vel))`,
  where `direction` is `pose.forward` and `vel` is the NMS-space velocity. This
  is the pose write; the adapter reports the resulting player position next
  state frame as it does today.
* Update `protocol.py`'s docstring for the two new `ship` sub-fields and `mode`.
  No other adapter discovery is needed: the coordinator already sends an
  optional `ship` object.

Safety is unchanged: the existing `GUARD_STEP_M` / `GUARD_NEAR_M` step limiting
wraps the ship shift as it wraps planet moves.

---

## 6. Coordinator wiring

New control-port messages (UDP 47813, one JSON datagram, `"t"` names exact):

| Message | Fields | Reply |
|---|---|---|
| `plan_transfer` | `from`: body id, `to`: body id, `t0` (s, optional), `span` (s, optional), `search` (bool, optional) | `{"t":"plan_transfer","transfer":{depart_ut,arrive_ut,node,dv_arrive,c3}}` |
| `add_node` | `ut`, `prograde`, `normal`, `radial` (s / m/s) | `{"t":"add_node","node":{index,ut,prograde,normal,radial}}` |
| `execute_node` | `index` (int, optional; default 0) | `{"t":"execute_node","ok":true,"burn_ut":t,"dv":[p,n,r]}` |
| `land` | `body`: body id, `terrain` (bool, optional), `touchdown_speed` (m/s, optional) | `{"t":"land","ok":true,"mode":"flight"}` |
| `launch` | `body`: body id, `alt_m` (m, optional) | `{"t":"launch","ok":true,"mode":"flight"}` |

`plan_transfer` calls `maneuver.plan_transfer` on the current universe;
`add_node` calls `KspLink.add_node`; `execute_node` arms a scheduled burn that
`tick()` fires through `KspLink.execute_node`; `land` / `launch` set
`self.flight_goal` and force `mode = "flight"` with the appropriate guidance.

Mode switching between on-rails orbit and powered flight:

* `self.mode: str` is `"orbit"` or `"flight"`.
* While `"orbit"`, `tick()` keeps reading KSP's vessel (`KspLink.vessel`) and
  predicting with `patched.py`. If the vessel's altitude above the anchor body
  falls below `FLIGHT_ENTER_ALT_M` (default 40 000 m, or the atmosphere top when
  larger), build a `FlightState` from the KSP state and a default `Vehicle`
  and switch to `"flight"`.
* While `"flight"`, the coordinator does **not** set KSP's vessel; it owns the
  state, integrates `flight.step` (with `suicide_burn_guidance` for `land`,
  `gravity_turn_guidance` for `launch`) every tick, and sends the ship in
  `nms_targets` with `"mode": "flight"`, including `pose` from the guidance
  attitude. KSP stays on rails at its last state, as the map/orbit record.
* On ascent, when `flight` guidance reaches `target_alt_m` and
  `circular_orbit_state` matches, the coordinator hands back: it writes the
  state into KSP with the existing `vesselstate setc` command, then sets
  `mode = "orbit"` (hysteresis: only above `FLIGHT_EXIT_ALT_M >=
  FLIGHT_ENTER_ALT_M`). Landing leaves `mode = "flight"` in a landed state until
  `launch` arrives.

### Landing decision (commit fd235b7)

fd235b7 found that KSP's stock PQS terrain does not rescale with `setbody`, so a
hidden-KSP vessel cannot be flown to the surface of a coordinator-reshaped
planet: the collider/terrain would not match the body the coordinator drew.
Decision: **the coordinator owns powered flight near the surface.** Below
`FLIGHT_ENTER_ALT_M`, `flight.py` integrates the descent in the coordinator's
own frame, against `body.radius` plus an optional `terrain_fn`; the NMS adapter
poses the player/ship there directly. The KSP vessel is never taken below the
threshold and is re-seeded only when ascent crosses back above it. Landing is
`landing_detected` in `flight.py`; NMS is authoritative for the surface, KSP for
orbit and the map. The terrain callback is optional and defaults to flat
(`terrain=None` -> ground at `body.radius`), because NMS has no terrain-height
query (`research nms-control.md`: approximate with distance from centre minus
sea level).

### Tests to add (not part of this doc's edits)

`tests/test_maneuver.py` (Hohmann dv against vis-viva, phase angle, Lambert
round-trip, porkchop minimum), `tests/test_patched.py` (SOI exit/entry on a
straight Hohmann, re-parent continuity, encounter miss distance),
`tests/test_flight.py` (free fall, drag terminal velocity, fuel mass flow,
suicide-burn touchdown, gravity-turn reaches `circular_orbit_state`). The exact
command strings in §4 are asserted without KSP.
