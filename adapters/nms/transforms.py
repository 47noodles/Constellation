"""Pure transform maths for the NMS adapter.

This module has no pymhf/nmspy imports on purpose: it is importable offline so a
unit test can check that the adapter computes the right ship shift and player
pose from coordinator state without a running game. ``ConstellationNMS4``
translates the returned ``ShipAction`` into engine and player calls.

Coordinator state (see constellation/protocol.py and docs/transfer-land-design.md):
    nms_targets["mode"]                  "orbit" | "flight"
    nms_targets["ship"]["pos"]           absolute NMS position at send time
    nms_targets["ship"]["vel_per_real_s"] velocity per real second
    nms_targets["ship"]["pose"]["forward"]/[up]  unit vectors in NMS axes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

Vec = tuple[float, float, float]

GUARD_NEAR_M = 160_000.0
GUARD_STEP_M = 50.0


def _sub(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _len(v: Sequence[float]) -> float:
    return (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5


def _unit(v: Sequence[float], fallback: Vec = (0.0, 1.0, 0.0)) -> Vec:
    n = _len(v)
    if n == 0.0:
        return fallback
    return (v[0] / n, v[1] / n, v[2] / n)


def extrapolate(pos: Sequence[float], vel_per_real_s: Sequence[float] | None, age: float) -> Vec:
    """Advance a send-time position by ``age`` real seconds of velocity."""
    if vel_per_real_s is None or age == 0.0:
        return (pos[0], pos[1], pos[2])
    return _add(pos, (vel_per_real_s[0] * age, vel_per_real_s[1] * age, vel_per_real_s[2] * age))


def ship_shift(ship: dict, node_pos: Sequence[float], age: float = 0.0) -> Vec:
    """The delta to shift the ship scene node from ``node_pos`` to where the
    coordinator wants the ship drawn, extrapolated to now."""
    target = extrapolate(ship["pos"], ship.get("vel_per_real_s"), age)
    return _sub(target, node_pos)


def pose_vectors(ship: dict) -> tuple[Vec, Vec]:
    """(forward, up) unit vectors in NMS axes; forward defaults to +Z, up to +Y."""
    pose = ship.get("pose") or {}
    forward = _unit(pose.get("forward", (0.0, 0.0, 1.0)), (0.0, 0.0, 1.0))
    up = _unit(pose.get("up", (0.0, 1.0, 0.0)), (0.0, 1.0, 0.0))
    return forward, up


def guard_allows(delta: Sequence[float], current_pos: Sequence[float], player_pos: Sequence[float] | None,
                 step_m: float = GUARD_STEP_M, near_m: float = GUARD_NEAR_M) -> bool:
    """The planet-move guard, applied to a ship shift: a move larger than
    ``step_m`` in one frame is refused if the ship is, or would end up, within
    ``near_m`` of the player."""
    if player_pos is None:
        return True
    if _len(delta) <= step_m:
        return True
    now_d = _len(_sub(current_pos, player_pos))
    new_d = _len(_sub(_add(current_pos, delta), player_pos))
    return min(now_d, new_d) >= near_m


@dataclass(frozen=True)
class ShipAction:
    """What the adapter should do with the ship this frame."""

    mode: str = "none"          # "orbit" | "flight" | "none"
    delta: Vec = (0.0, 0.0, 0.0)  # orbit: Vector3f passed to ShiftAllTransformsForNode
    pos: Vec = (0.0, 0.0, 0.0)  # flight: absolute NMS position for SetToPosition
    forward: Vec = (0.0, 0.0, 1.0)
    up: Vec = (0.0, 1.0, 0.0)
    vel: Vec = (0.0, 0.0, 0.0)  # flight: SetToPosition velocity


def plan_ship(ship: dict | None, mode: str, node_pos: Sequence[float] | None = None,
              age: float = 0.0) -> ShipAction:
    """Decide the ship transform from coordinator state.

    * ``mode == "flight"``: pose the player at the extrapolated ship position,
      facing ``pose.forward``, with the NMS-space velocity. No scene-node move.
    * otherwise (``"orbit"``): shift the ship scene node by the delta between
      the coordinator position and its current node position.
    * no ship, or orbit without a node: ``mode == "none"`` (do nothing).
    """
    if not ship:
        return ShipAction()
    if mode == "flight":
        pos = extrapolate(ship["pos"], ship.get("vel_per_real_s"), age)
        forward, up = pose_vectors(ship)
        vel = tuple(ship.get("vel_per_real_s") or (0.0, 0.0, 0.0))
        return ShipAction(mode="flight", pos=pos, forward=forward, up=up, vel=vel)
    if node_pos is None:
        return ShipAction()
    return ShipAction(mode="orbit", delta=ship_shift(ship, node_pos, age))


def override_relative_pos(target: Sequence[float], written_rel: Sequence[float],
                          current_abs: Sequence[float]) -> Vec:
    """New relative translation that puts a scene node at ``target`` absolute.

    A node's absolute position is ``parent + written_rel`` for the relative
    translation the engine is about to write, so the parent offset is
    ``current_abs - written_rel``. Returning ``target - parent`` makes the
    resulting absolute position ``target``."""
    return _sub(target, _sub(current_abs, written_rel))
