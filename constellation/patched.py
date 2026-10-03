"""Patched-conic vessel propagation across coordinator-owned spheres of influence.

A vessel is propagated as a Kepler conic in the frame of the body whose SOI it
is currently inside. When it reaches that body's sphere-of-influence radius the
state is re-expressed in the parent body's frame (subtracting the child's own
position and velocity), so the state is continuous across the boundary. This
mirrors KSP's patched conics and is what the coordinator uses to predict SOI
crossings and planetary encounters.

Units are metres, seconds, m/s and m^3/s^2 throughout, matching ``orbits.py``.
Vectors are coordinator (orbit-space) axes; a state's ``r``/``v`` are relative
to the centre of ``state.body``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .orbits import Vec, add, from_state, norm, sub
from .universe import STAR, Universe


@dataclass(frozen=True)
class VesselState:
    body: str  # "star" or "p<slot>": the body the state is relative to
    r: Vec  # position relative to body centre, coordinator axes (m)
    v: Vec  # velocity relative to body centre (m/s)
    ut: float  # s


@dataclass(frozen=True)
class SoiCrossing:
    ut: float  # s
    body_from: str  # SOI left
    body_to: str  # SOI entered
    r: Vec  # position relative to body_from at the crossing (m)
    v: Vec  # velocity relative to body_from at the crossing (m/s)


@dataclass(frozen=True)
class Encounter:
    body: str  # body encountered
    ut: float  # s of closest approach
    miss_m: float  # distance from body centre at closest approach (m)
    rel_speed_mps: float
    impact: bool  # miss_m < body.radius


def body_mu(u: Universe, body_id: str) -> float:
    """``u.star_mu`` for STAR, else ``u.bodies[body_id].mu``."""
    if body_id == STAR:
        return u.star_mu
    return u.bodies[body_id].mu


def body_soi(u: Universe, body_id: str) -> float:
    """``math.inf`` for STAR, else ``u.bodies[body_id].soi``."""
    if body_id == STAR:
        return math.inf
    return u.bodies[body_id].soi


def body_parent(u: Universe, body_id: str) -> str:
    """STAR for a planet (single-level hierarchy today)."""
    return STAR


def soi_chain(u: Universe, body_id: str) -> list[str]:
    """The parent chain from STAR down to ``body_id``: ``["star", "p1"]``."""
    if body_id == STAR:
        return [STAR]
    chain = [body_id]
    b = body_id
    while b != STAR:
        b = body_parent(u, b)
        chain.append(b)
    chain.reverse()
    return chain


def state_at(u: Universe, state: VesselState, t: float) -> VesselState:
    """Kepler-propagate within the current SOI to time ``t``."""
    mu = body_mu(u, state.body)
    orbit = from_state(mu, state.r, state.v, epoch=state.ut)
    r, v = orbit.state_at(t)
    return VesselState(state.body, r, v, t)


def position_nms(u: Universe, state: VesselState, t: float) -> Vec:
    """NMS-space position of the vessel at ``t``."""
    return add(u.nms_pos(state.body, t), state_at(u, state, t).r)


def velocity_nms(u: Universe, state: VesselState, t: float) -> Vec:
    """NMS-space velocity of the vessel at ``t`` (body nms_vel plus relative v)."""
    return add(u.nms_vel(state.body, t), state_at(u, state, t).v)


def find_soi_exit(u: Universe, state: VesselState, t_max: float,
                  step: float = 30.0) -> SoiCrossing | None:
    """First time in ``(state.ut, t_max]`` at which ``|r(t)|`` reaches the current
    body's SOI radius, by sign change and bisection. None if it stays inside."""
    soi = body_soi(u, state.body)
    if math.isinf(soi):
        return None

    def f(t: float) -> float:
        return norm(state_at(u, state, t).r) - soi

    f_prev = f(state.ut)
    if f_prev >= 0.0:
        return None
    t_prev = state.ut
    t = state.ut + step
    while t <= t_max:
        f_t = f(t)
        if f_t >= 0.0:
            root = _bisect_root(f, t_prev, t, f_prev)
            s = state_at(u, state, root)
            return SoiCrossing(root, state.body, body_parent(u, state.body), s.r, s.v)
        t_prev, f_prev = t, f_t
        t += step
    return None


def find_soi_entry(u: Universe, state: VesselState, target_body: str,
                   t_max: float, step: float = 30.0) -> SoiCrossing | None:
    """First time in ``(state.ut, t_max]`` at which the vessel comes within
    ``body_soi(u, target_body)`` of ``target_body``'s centre."""
    soi = body_soi(u, target_body)
    if math.isinf(soi):
        return None

    def f(t: float) -> float:
        s = state_at(u, state, t)
        rel = sub(u.orbit_pos(target_body, t), u.orbit_pos(state.body, t))
        return norm(sub(s.r, rel)) - soi

    f_prev = f(state.ut)
    if f_prev <= 0.0:
        return None
    t_prev = state.ut
    t = state.ut + step
    while t <= t_max:
        f_t = f(t)
        if f_t <= 0.0:
            root = _bisect_root(f, t_prev, t, f_prev)
            s = state_at(u, state, root)
            return SoiCrossing(root, state.body, target_body, s.r, s.v)
        t_prev, f_prev = t, f_t
        t += step
    return None


def reparent(u: Universe, state: VesselState, crossing: SoiCrossing) -> VesselState:
    """Re-express ``state`` in ``body_to``'s frame at the crossing UT.

    ``state`` is relative to ``crossing.body_from``; the body_from's own position
    and velocity in a common (orbit) frame are added, and body_to's subtracted,
    so the resulting state is continuous across the patch.
    """
    offset_r = sub(u.orbit_pos(crossing.body_from, crossing.ut),
                   u.orbit_pos(crossing.body_to, crossing.ut))
    offset_v = sub(u.orbit_vel(crossing.body_from, crossing.ut),
                   u.orbit_vel(crossing.body_to, crossing.ut))
    return VesselState(crossing.body_to,
                       add(state.r, offset_r),
                       add(state.v, offset_v),
                       crossing.ut)


def propagate(u: Universe, state: VesselState, t_end: float,
              max_crossings: int = 8) -> list[VesselState]:
    """Propagate to ``t_end``, applying SOI exits and reparenting at each crossing.

    Returns the segment states: each entry is the state at the end of one SOI
    segment (the last, in the final SOI, at ``t_end``).
    """
    out: list[VesselState] = []
    cur = state
    for _ in range(max_crossings):
        crossing = find_soi_exit(u, cur, t_end)
        if crossing is None:
            out.append(state_at(u, cur, t_end))
            return out
        s = state_at(u, cur, crossing.ut)
        cur = reparent(u, s, crossing)
        out.append(cur)
    out.append(state_at(u, cur, t_end))
    return out


def trajectory(u: Universe, state: VesselState, t_end: float,
               step: float = 60.0) -> list[VesselState]:
    """Sampled path over ``[state.ut, t_end]``, crossing SOIs as ``propagate``."""
    out: list[VesselState] = []
    cur = state
    t = state.ut
    for _ in range(8):
        crossing = find_soi_exit(u, cur, t_end, step)
        seg_end = crossing.ut if crossing is not None else t_end
        tt = t
        while tt < seg_end:
            out.append(state_at(u, cur, tt))
            tt += step
        if crossing is None:
            break
        s = state_at(u, cur, crossing.ut)
        cur = reparent(u, s, crossing)
        t = crossing.ut
    out.append(state_at(u, cur, t_end))
    return out


def predict_encounter(u: Universe, state: VesselState, target_body: str,
                      t_max: float, step: float = 30.0) -> Encounter | None:
    """Closest approach to ``target_body`` over the propagated path, or None if
    the path never enters its SOI."""
    if target_body == STAR or target_body == state.body:
        return None
    entry = find_soi_entry(u, state, target_body, t_max, step)
    if entry is None:
        return None
    rep = reparent(u, state_at(u, state, entry.ut), entry)
    exit_crossing = find_soi_exit(u, rep, t_max, step)
    t_hi = exit_crossing.ut if exit_crossing is not None else t_max

    best_t = entry.ut
    best_d = norm(state_at(u, rep, best_t).r)
    tt = entry.ut + step
    while tt <= t_hi:
        d = norm(state_at(u, rep, tt).r)
        if d < best_d:
            best_d, best_t = d, tt
        tt += step

    lo = max(entry.ut, best_t - step)
    hi = min(t_hi, best_t + step)
    if hi > lo:
        best_t = _min_distance_time(u, rep, lo, hi)
    s = state_at(u, rep, best_t)
    miss = norm(s.r)
    return Encounter(target_body, best_t, miss, norm(s.v),
                     miss < u.bodies[target_body].radius)


def predict_all_encounters(u: Universe, state: VesselState, t_max: float,
                           step: float = 30.0) -> list[Encounter]:
    """One Encounter per non-star body whose SOI the path enters, time-ordered."""
    found: list[Encounter] = []
    for body_id in u.bodies:
        if body_id == state.body:
            continue
        enc = predict_encounter(u, state, body_id, t_max, step)
        if enc is not None:
            found.append(enc)
    found.sort(key=lambda e: e.ut)
    return found


def _bisect_root(f, lo: float, hi: float, f_lo: float) -> float:
    """Bisect for a root of ``f`` bracketed by ``[lo, hi]`` (opposite signs)."""
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if (f(mid) < 0.0) == (f_lo < 0.0):
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-6:
            break
    return 0.5 * (lo + hi)


def _min_distance_time(u: Universe, state: VesselState, lo: float, hi: float,
                       iters: int = 80) -> float:
    """Ternary search for the time of closest approach to the state's body."""
    for _ in range(iters):
        m1 = lo + (hi - lo) / 3.0
        m2 = hi - (hi - lo) / 3.0
        if norm(state_at(u, state, m1).r) < norm(state_at(u, state, m2).r):
            hi = m2
        else:
            lo = m1
    return 0.5 * (lo + hi)
