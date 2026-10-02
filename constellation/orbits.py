"""Two-body Kepler orbits: elements <-> state vectors, propagation by time.

Units are metres, seconds and m^3/s^2 throughout. Vectors are 3-tuples in the
system frame (the same axes NMS uses; +y is "up" out of the ecliptic).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec = tuple[float, float, float]

TWO_PI = 2.0 * math.pi


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec:
    n = norm(a)
    if n == 0.0:
        raise ValueError("zero vector has no direction")
    return scale(a, 1.0 / n)


@dataclass(frozen=True)
class Orbit:
    """A Keplerian orbit about a body with gravitational parameter ``mu``.

    The orientation is stored as the perifocal basis (``p_hat`` toward
    periapsis, ``q_hat`` 90 degrees ahead in the direction of motion) rather
    than as angles, which avoids the singularities of circular and equatorial
    orbits that every planet in a generated system tends to have.
    """

    mu: float
    a: float  # semi-major axis (m); negative for hyperbolic
    e: float  # eccentricity
    p_hat: Vec
    q_hat: Vec
    m0: float  # mean anomaly at epoch (rad)
    epoch: float  # seconds

    @property
    def mean_motion(self) -> float:
        return math.sqrt(self.mu / abs(self.a) ** 3)

    @property
    def period(self) -> float:
        if self.e >= 1.0:
            return math.inf
        return TWO_PI / self.mean_motion

    def state_at(self, t: float) -> tuple[Vec, Vec]:
        """Position and velocity relative to the central body at time ``t``."""
        n = self.mean_motion
        m = self.m0 + n * (t - self.epoch)
        if self.e < 1.0:
            m = math.fmod(m, TWO_PI)
            ecc = _solve_elliptic(m, self.e)
            cos_e, sin_e = math.cos(ecc), math.sin(ecc)
            b = self.a * math.sqrt(1.0 - self.e * self.e)
            x = self.a * (cos_e - self.e)
            y = b * sin_e
            edot = n / (1.0 - self.e * cos_e)
            vx = -self.a * sin_e * edot
            vy = b * cos_e * edot
        else:
            h = _solve_hyperbolic(m, self.e)
            ch, sh = math.cosh(h), math.sinh(h)
            a = abs(self.a)
            b = a * math.sqrt(self.e * self.e - 1.0)
            x = a * (self.e - ch)
            y = b * sh
            hdot = n / (self.e * ch - 1.0)
            vx = -a * sh * hdot
            vy = b * ch * hdot
        r = add(scale(self.p_hat, x), scale(self.q_hat, y))
        v = add(scale(self.p_hat, vx), scale(self.q_hat, vy))
        return r, v

    def position_at(self, t: float) -> Vec:
        return self.state_at(t)[0]


def circular(mu: float, r0: Vec, up: Vec = (0.0, 1.0, 0.0), epoch: float = 0.0) -> Orbit:
    """A circular orbit that passes through ``r0`` at ``epoch``.

    The orbit plane contains ``r0`` and the horizontal direction
    ``cross(up, r0)``, so a body sitting in the ecliptic orbits in it, and one
    above or below it gets the smallest inclination that still reaches it.
    Motion is prograde about ``up``.
    """
    radius = norm(r0)
    p_hat = unit(r0)
    q = cross(up, p_hat)
    if norm(q) < 1e-9:  # r0 parallel to up: pick any perpendicular
        q = cross((1.0, 0.0, 0.0), p_hat)
    q_hat = unit(q)
    return Orbit(mu=mu, a=radius, e=0.0, p_hat=p_hat, q_hat=q_hat, m0=0.0, epoch=epoch)


def from_state(mu: float, r: Vec, v: Vec, epoch: float) -> Orbit:
    """Elements from a position and velocity relative to the central body."""
    rn = norm(r)
    h = cross(r, v)
    e_vec = sub(scale(cross(v, h), 1.0 / mu), scale(r, 1.0 / rn))
    e = norm(e_vec)
    energy = dot(v, v) / 2.0 - mu / rn
    a = -mu / (2.0 * energy)
    w_hat = unit(h)  # orbit normal
    if e > 1e-10:
        p_hat = unit(e_vec)
    else:  # circular: measure from the current position
        p_hat = unit(r)
    q_hat = cross(w_hat, p_hat)
    # true anomaly of r in the perifocal frame
    nu = math.atan2(dot(r, q_hat), dot(r, p_hat))
    if e < 1.0:
        ecc = 2.0 * math.atan2(math.sqrt(1.0 - e) * math.sin(nu / 2.0), math.sqrt(1.0 + e) * math.cos(nu / 2.0))
        m0 = ecc - e * math.sin(ecc)
    else:
        hyp = 2.0 * math.atanh(math.sqrt((e - 1.0) / (e + 1.0)) * math.tan(nu / 2.0))
        m0 = e * math.sinh(hyp) - hyp
    return Orbit(mu=mu, a=a, e=e, p_hat=p_hat, q_hat=q_hat, m0=m0, epoch=epoch)


def soi_radius(a_parent_orbit: float, mu_body: float, mu_parent: float) -> float:
    """Laplace sphere of influence, as KSP uses: a * (m / M)^(2/5)."""
    return a_parent_orbit * (mu_body / mu_parent) ** 0.4


def _solve_elliptic(m: float, e: float) -> float:
    ecc = m if e < 0.8 else math.pi
    for _ in range(50):
        f = ecc - e * math.sin(ecc) - m
        step = f / (1.0 - e * math.cos(ecc))
        ecc -= step
        if abs(step) < 1e-13:
            break
    return ecc


def _solve_hyperbolic(m: float, e: float) -> float:
    h = math.asinh(m / e) if e > 0 else m
    for _ in range(80):
        f = e * math.sinh(h) - h - m
        step = f / (e * math.cosh(h) - 1.0)
        h -= step
        if abs(step) < 1e-13:
            break
    return h
