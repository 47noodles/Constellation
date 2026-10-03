"""Maneuver nodes, Hohmann transfers, Lambert arcs and transfer windows.

Units are metres, seconds and m^3/s^2 throughout, as in ``orbits.py``. A
maneuver node is stored as scalar components in the vessel's local orbital frame
(prograde, orbit normal, in-plane radial) because that is the frame KSP's map
shows and the frame ``apply_node`` works in.

One interface concession: ``ManeuverNode.dv`` cannot return a vector in
"coordinator axes" from the four stored scalars alone -- the local frame is only
known once a state ``(r, v)`` is supplied. It therefore returns the components
in the node's own (prograde, normal, radial) frame; ``apply_node`` is the
function that maps them onto a state. ``lambert`` supports ``revolutions == 0``;
higher revolution counts raise ``ValueError`` rather than return a wrong arc.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .orbits import (
    TWO_PI,
    Orbit,
    Vec,
    add,
    cross,
    dot,
    norm,
    scale,
    sub,
    unit,
)
from .universe import Universe

__all__ = [
    "ManeuverNode",
    "HohmannTransfer",
    "Transfer",
    "LambertSolution",
    "orbital_directions",
    "apply_node",
    "hohmann",
    "phase_angle",
    "window_after",
    "transfer_windows",
    "lambert",
    "dv_for_lambert",
    "porkchop",
    "best_porkchop",
    "plan_transfer",
]


@dataclass(frozen=True)
class ManeuverNode:
    ut: float
    prograde: float
    normal: float
    radial: float

    def dv(self) -> Vec:
        """Node delta-v components in the node's (prograde, normal, radial) frame."""
        return (self.prograde, self.normal, self.radial)

    def magnitude(self) -> float:
        return math.sqrt(self.prograde ** 2 + self.normal ** 2 + self.radial ** 2)


@dataclass(frozen=True)
class HohmannTransfer:
    r1: float
    r2: float
    dv_depart: float
    dv_arrive: float
    transfer_time: float
    transfer_orbit: Orbit


@dataclass(frozen=True)
class Transfer:
    depart_ut: float
    arrive_ut: float
    node: ManeuverNode
    dv_arrive: float
    c3: float

    def total_dv(self) -> float:
        return self.node.magnitude() + abs(self.dv_arrive)


@dataclass(frozen=True)
class LambertSolution:
    v0: Vec
    v1: Vec
    tof: float
    revolutions: int


# --------------------------------------------------------------------------- #
# Local orbital frame
# --------------------------------------------------------------------------- #

def orbital_directions(r: Vec, v: Vec) -> tuple[Vec, Vec, Vec]:
    """(prograde, normal, radial) unit vectors at a state.

    normal = unit(r x v), prograde = unit(v), radial = unit(normal x prograde).
    Raises ValueError on a degenerate (radial or zero) state.
    """
    vn = norm(v)
    h = cross(r, v)
    hn = norm(h)
    if vn == 0.0 or hn == 0.0:
        raise ValueError("degenerate state: no orbital frame")
    prograde = scale(v, 1.0 / vn)
    normal = scale(h, 1.0 / hn)
    radial = unit(cross(normal, prograde))
    return prograde, normal, radial


def apply_node(mu: float, r: Vec, v: Vec, node: ManeuverNode) -> tuple[Vec, Vec]:
    """Position, velocity after an instantaneous burn at ``(r, v)``."""
    prograde, normal, radial = orbital_directions(r, v)
    dv = add(add(scale(prograde, node.prograde), scale(normal, node.normal)),
             scale(radial, node.radial))
    return r, add(v, dv)


# --------------------------------------------------------------------------- #
# Hohmann transfer and phase-angle windows
# --------------------------------------------------------------------------- #

def hohmann(mu: float, r1: float, r2: float, epoch: float = 0.0) -> HohmannTransfer:
    """Two-impulse transfer between circular radii ``r1`` and ``r2``."""
    if r1 <= 0.0 or r2 <= 0.0:
        raise ValueError("radii must be positive")
    if r1 == r2:
        raise ValueError("r1 == r2: no Hohmann transfer")
    a_t = 0.5 * (r1 + r2)
    v_circ1 = math.sqrt(mu / r1)
    v_circ2 = math.sqrt(mu / r2)
    v_peri = math.sqrt(mu * (2.0 / r1 - 1.0 / a_t))
    v_apo = math.sqrt(mu * (2.0 / r2 - 1.0 / a_t))
    dv_depart = v_peri - v_circ1
    dv_arrive = v_circ2 - v_apo
    transfer_time = math.pi * math.sqrt(a_t ** 3 / mu)
    e = abs(r2 - r1) / (r1 + r2)
    p_hat: Vec = (1.0, 0.0, 0.0)
    q_hat: Vec = (0.0, 0.0, -1.0)  # prograde about +y
    transfer_orbit = Orbit(mu=mu, a=a_t, e=e, p_hat=p_hat, q_hat=q_hat,
                           m0=0.0, epoch=epoch)
    return HohmannTransfer(r1, r2, dv_depart, dv_arrive, transfer_time, transfer_orbit)


def phase_angle(mu: float, r_target: float, transfer_time: float) -> float:
    """Required lead angle (rad, wrapped to [0, 2*pi)) of the target at departure."""
    n_target = math.sqrt(mu / r_target ** 3)
    return (math.pi - n_target * transfer_time) % TWO_PI


def _plane_basis(orbit: Orbit) -> tuple[Vec, Vec]:
    """Two orthonormal in-plane axes (periapsis, 90 degrees ahead)."""
    w = unit(cross(orbit.p_hat, orbit.q_hat))
    return orbit.p_hat, unit(cross(w, orbit.p_hat))


def _phase_error(from_orbit: Orbit, to_orbit: Orbit, phi: float, t: float) -> float:
    e1, e2 = _plane_basis(from_orbit)
    rs = from_orbit.position_at(t)
    rt = to_orbit.position_at(t)
    a_ship = math.atan2(dot(rs, e2), dot(rs, e1))
    a_target = math.atan2(dot(rt, e2), dot(rt, e1))
    return _wrap_pi(a_target - a_ship - phi)


def _wrap_pi(x: float) -> float:
    return (x + math.pi) % TWO_PI - math.pi


def _build_hohmann_transfer(mu: float, r1: float, r2: float, ut: float) -> Transfer:
    h = hohmann(mu, r1, r2, epoch=ut)
    node = ManeuverNode(ut=ut, prograde=h.dv_depart, normal=0.0, radial=0.0)
    return Transfer(depart_ut=ut, arrive_ut=ut + h.transfer_time, node=node,
                    dv_arrive=h.dv_arrive, c3=h.dv_depart ** 2)


def _bisect_window(from_orbit: Orbit, to_orbit: Orbit, phi: float,
                   lo: float, hi: float) -> float:
    flo = _phase_error(from_orbit, to_orbit, phi, lo)
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        fmid = _phase_error(from_orbit, to_orbit, phi, mid)
        if fmid == 0.0:
            return mid
        if (flo <= 0.0) == (fmid <= 0.0):
            lo, flo = mid, fmid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return 0.5 * (lo + hi)


def _scan_windows(mu: float, from_orbit: Orbit, to_orbit: Orbit, t0: float,
                  span: float, step: float) -> list[float]:
    h = hohmann(mu, from_orbit.a, to_orbit.a)
    phi = phase_angle(mu, to_orbit.a, h.transfer_time)
    n = max(1, int(math.ceil(span / step)))
    crossings: list[float] = []
    prev_t = t0
    prev = _phase_error(from_orbit, to_orbit, phi, t0)
    if prev == 0.0:
        crossings.append(t0)
    for i in range(1, n + 1):
        t = t0 + i * step
        cur = _phase_error(from_orbit, to_orbit, phi, t)
        if (prev <= 0.0 < cur or prev >= 0.0 > cur) and abs(cur - prev) < math.pi:
            crossings.append(_bisect_window(from_orbit, to_orbit, phi, prev_t, t))
        prev_t, prev = t, cur
    return crossings


def window_after(mu: float, from_orbit: Orbit, to_orbit: Orbit, t0: float,
                 span: float, step: float = 60.0) -> Transfer | None:
    """First Hohmann window with depart_ut >= t0 within t0 + span, or None."""
    if span < 0.0:
        raise ValueError("span must be non-negative")
    crossings = _scan_windows(mu, from_orbit, to_orbit, t0, span, step)
    if not crossings:
        return None
    return _build_hohmann_transfer(mu, from_orbit.a, to_orbit.a, crossings[0])


def transfer_windows(mu: float, from_orbit: Orbit, to_orbit: Orbit, t0: float,
                     span: float, step: float = 60.0) -> list[Transfer]:
    """Every Hohmann window in [t0, t0 + span], in time order."""
    if span < 0.0:
        raise ValueError("span must be non-negative")
    crossings = _scan_windows(mu, from_orbit, to_orbit, t0, span, step)
    return [_build_hohmann_transfer(mu, from_orbit.a, to_orbit.a, t) for t in crossings]


# --------------------------------------------------------------------------- #
# Lambert solver (universal variables)
# --------------------------------------------------------------------------- #

def _c2(psi: float) -> float:
    if psi > 1e-6:
        s = math.sqrt(psi)
        return (1.0 - math.cos(s)) / psi
    if psi < -1e-6:
        s = math.sqrt(-psi)
        return (math.cosh(s) - 1.0) / (-psi)
    return 0.5


def _c3(psi: float) -> float:
    if psi > 1e-6:
        s = math.sqrt(psi)
        return (s - math.sin(s)) / (s ** 3)
    if psi < -1e-6:
        s = math.sqrt(-psi)
        return (math.sinh(s) - s) / (s ** 3)
    return 1.0 / 6.0


def lambert(mu: float, r0: Vec, r1: Vec, tof: float, prograde: bool = True,
            revolutions: int = 0, long_way: bool = False) -> LambertSolution:
    """Universal-variable Lambert solver: the transfer from r0 to r1 in time tof.

    ``prograde`` picks the short-way transfer relative to the r0 x r1 normal.
    Raises ValueError when no conic connects the two in that time, or when
    ``revolutions != 0`` (multi-revolution arcs are not implemented).
    """
    if tof <= 0.0:
        raise ValueError("tof must be positive")
    if revolutions != 0:
        raise ValueError("multi-revolution Lambert is not implemented")
    r0 = tuple(float(c) for c in r0)
    r1 = tuple(float(c) for c in r1)
    r0n, r1n = norm(r0), norm(r1)
    if r0n == 0.0 or r1n == 0.0:
        raise ValueError("zero radius")
    cos_dnu = max(-1.0, min(1.0, dot(r0, r1) / (r0n * r1n)))
    if cos_dnu >= 1.0:
        raise ValueError("collinear endpoints: transfer plane undefined")
    short_way = prograde and not long_way
    A = math.sqrt(r0n * r1n * (1.0 + cos_dnu))
    if not short_way:
        A = -A
    if A == 0.0:
        raise ValueError("collinear endpoints: transfer plane undefined")

    psi_low, psi_up = -4.0 * math.pi, 4.0 * math.pi ** 2
    psi = 0.0
    last_dt = None
    for _ in range(200):
        c2, c3 = _c2(psi), _c3(psi)
        y = r0n + r1n + A * (psi * c3 - 1.0) / math.sqrt(c2)
        if A > 0.0 and y < 0.0:
            while y < 0.0:
                psi_low = psi
                psi = 0.5 * (psi_up + psi_low)
                c2, c3 = _c2(psi), _c3(psi)
                y = r0n + r1n + A * (psi * c3 - 1.0) / math.sqrt(c2)
        chi = math.sqrt(y / c2)
        dt = (chi ** 3 * c3 + A * math.sqrt(y)) / math.sqrt(mu)
        last_dt = dt
        if dt <= tof:
            psi_low = psi
        else:
            psi_up = psi
        if abs(dt - tof) <= 1e-9 * max(1.0, tof):
            break
        psi = 0.5 * (psi_up + psi_low)
    else:
        raise ValueError("Lambert did not converge")

    c2, c3 = _c2(psi), _c3(psi)
    y = r0n + r1n + A * (psi * c3 - 1.0) / math.sqrt(c2)
    f = 1.0 - y / r0n
    g = A * math.sqrt(y / mu)
    gdot = 1.0 - y / r1n
    if g == 0.0:
        raise ValueError("degenerate Lambert solution")
    v0 = scale(sub(r1, scale(r0, f)), 1.0 / g)
    v1 = scale(sub(scale(r1, gdot), r0), 1.0 / g)
    return LambertSolution(v0=v0, v1=v1, tof=tof, revolutions=revolutions)


def _node_from_dv(r0: Vec, v_ref: Vec, dv: Vec, ut: float) -> ManeuverNode:
    prograde, normal, radial = orbital_directions(r0, v_ref)
    return ManeuverNode(ut=ut, prograde=dot(dv, prograde), normal=dot(dv, normal),
                        radial=dot(dv, radial))


def dv_for_lambert(mu: float, r0: Vec, v0_current: Vec, r1: Vec, v1_target: Vec,
                   tof: float, prograde: bool = True,
                   revolutions: int = 0) -> Transfer:
    """Wrap lambert into the departure node and arrival capture delta-v."""
    sol = lambert(mu, r0, r1, tof, prograde=prograde, revolutions=revolutions)
    dv_depart = sub(sol.v0, v0_current)
    dv_capture = sub(v1_target, sol.v1)
    node = _node_from_dv(r0, v0_current, dv_depart, 0.0)
    return Transfer(depart_ut=0.0, arrive_ut=tof, node=node,
                    dv_arrive=norm(dv_capture), c3=dot(dv_depart, dv_depart))


# --------------------------------------------------------------------------- #
# Porkchop search over a Universe
# --------------------------------------------------------------------------- #

def _lambert_transfer(mu: float, from_orbit: Orbit, to_orbit: Orbit,
                      depart_ut: float, arrive_ut: float) -> Transfer | None:
    tof = arrive_ut - depart_ut
    if tof <= 0.0:
        return None
    r0 = from_orbit.position_at(depart_ut)
    v_from = from_orbit.state_at(depart_ut)[1]
    r1 = to_orbit.position_at(arrive_ut)
    v_to = to_orbit.state_at(arrive_ut)[1]
    try:
        sol = lambert(mu, r0, r1, tof, prograde=True)
    except ValueError:
        return None
    dv_depart = sub(sol.v0, v_from)
    dv_arrive = sub(v_to, sol.v1)
    node = _node_from_dv(r0, v_from, dv_depart, depart_ut)
    return Transfer(depart_ut=depart_ut, arrive_ut=arrive_ut, node=node,
                    dv_arrive=norm(dv_arrive), c3=dot(dv_depart, dv_depart))


def _time_grid(start: float, stop: float, step: float) -> list[float]:
    if step <= 0.0:
        raise ValueError("step must be positive")
    out: list[float] = []
    t = start
    while t <= stop + 1e-9 * max(1.0, abs(stop)):
        out.append(t)
        t += step
    if not out:
        out.append(start)
    return out


def porkchop(mu: float, from_orbit: Orbit, to_orbit: Orbit,
             depart_from: float, depart_to: float,
             arrive_from: float, arrive_to: float,
             coarse: float = 3600.0, refine: float | None = 600.0) -> list[Transfer]:
    """Grid-search departure/arrival times with the Lambert solver."""
    departures = _time_grid(depart_from, depart_to, coarse)
    arrivals = _time_grid(arrive_from, arrive_to, coarse)
    coarse_transfers: list[Transfer] = []
    for dt in departures:
        for at in arrivals:
            tr = _lambert_transfer(mu, from_orbit, to_orbit, dt, at)
            if tr is not None:
                coarse_transfers.append(tr)
    if not coarse_transfers:
        return []
    best = min(coarse_transfers, key=lambda tr: tr.total_dv())
    if not refine or refine <= 0.0:
        return sorted(coarse_transfers, key=lambda tr: tr.total_dv())

    departures = _time_grid(best.depart_ut - coarse, best.depart_ut + coarse, refine)
    arrivals = _time_grid(best.arrive_ut - coarse, best.arrive_ut + coarse, refine)
    refined: list[Transfer] = []
    for dt in departures:
        for at in arrivals:
            tr = _lambert_transfer(mu, from_orbit, to_orbit, dt, at)
            if tr is not None:
                refined.append(tr)
    if not refined:
        return sorted(coarse_transfers, key=lambda tr: tr.total_dv())
    return sorted(refined, key=lambda tr: tr.total_dv())


def best_porkchop(mu: float, from_orbit: Orbit, to_orbit: Orbit,
                  depart_from: float, depart_to: float,
                  arrive_from: float, arrive_to: float,
                  coarse: float = 3600.0, refine: float | None = 600.0) -> Transfer | None:
    """The lowest total_dv entry of ``porkchop``, or None if the grid is empty."""
    entries = porkchop(mu, from_orbit, to_orbit, depart_from, depart_to,
                       arrive_from, arrive_to, coarse=coarse, refine=refine)
    if not entries:
        return None
    return entries[0]


def plan_transfer(u: Universe, from_id: str, to_id: str, t0: float,
                  span: float, use_lambert: bool = False) -> Transfer | None:
    """Convenience over a Universe: transfer between two bodies' orbits."""
    from_orbit = u.bodies[from_id].orbit
    to_orbit = u.bodies[to_id].orbit
    if use_lambert:
        return best_porkchop(u.star_mu, from_orbit, to_orbit,
                             t0, t0 + span, t0, t0 + 2.0 * span)
    return window_after(u.star_mu, from_orbit, to_orbit, t0, span)
