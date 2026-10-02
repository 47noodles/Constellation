"""Push the coordinator's universe into KSP's stock body pool, and check the result.

KSP is the orbit engine and map view (Lachlan, 2 Oct 2026). Its stock planets are
used as a fixed pool: the coordinator's bodies, in order of orbit radius, take
over Moho, Eve, Kerbin, Duna, Dres, Jool and Eeloo; unused pool planets are
parked far out; stock moons are shrunk inside their parents (see the plugin's
`parkmoons`). The Sun takes the star's mass. KSP's clock is set to game time.

    python -m constellation.ksp_link sync <planets.json> [--game-t T]
    python -m constellation.ksp_link check <planets.json>

`planets.json` is the NMS planet list ([{"slot", "home"}...]) the universe is
built from. `check` compares every pairwise body distance between the
coordinator and KSP at KSP's current time; distances are frame independent, so
this works before the NMS-to-KSP axes are calibrated.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import socket

from .orbits import Orbit, Vec, cross, dot, norm, unit
from .universe import Universe

KSP_ADDR = ("127.0.0.1", 47821)
POOL = ["Moho", "Eve", "Kerbin", "Duna", "Dres", "Jool", "Eeloo"]
PARK_SMA = 5e12  # far beyond any coordinator orbit


def zup(v: Vec) -> Vec:
    """Coordinator axes (+y up) to KSP's z-up orbital frame."""
    return (v[0], v[2], v[1])


def ksp_elements(o: Orbit) -> dict:
    """Elements for KSP's Orbit.SetOrbit from a circular coordinator orbit.

    Periapsis is put at the ascending node (any choice is valid for e = 0) and
    the mean anomaly at epoch is the angle from the node to the epoch position.
    """
    if o.e > 1e-9:
        raise NotImplementedError("only circular orbits are mapped so far")
    p, q = zup(o.p_hat), zup(o.q_hat)
    h = unit(cross(p, q))
    inc = math.acos(max(-1.0, min(1.0, h[2])))
    node = (-h[1], h[0], 0.0)
    node = unit(node) if norm(node) > 1e-12 else (1.0, 0.0, 0.0)
    lan = math.atan2(node[1], node[0])
    in_plane = cross(h, node)
    u0 = math.atan2(dot(p, in_plane), dot(p, node)) + o.m0
    return {
        "sma": o.a, "ecc": 0.0, "inc_deg": math.degrees(inc), "lan_deg": math.degrees(lan) % 360.0,
        "argpe_deg": 0.0, "mep_rad": u0 % (2 * math.pi), "epoch": o.epoch,
    }


def position_from_elements(el: dict, mu: float, t: float) -> Vec:
    """Inverse of ksp_elements in z-up axes (used by the tests)."""
    inc, lan = math.radians(el["inc_deg"]), math.radians(el["lan_deg"])
    n = math.sqrt(mu / el["sma"] ** 3)
    u = el["mep_rad"] + n * (t - el["epoch"])
    node = (math.cos(lan), math.sin(lan), 0.0)
    h = (math.sin(inc) * math.sin(lan), -math.sin(inc) * math.cos(lan), math.cos(inc))
    in_plane = cross(h, node)
    return tuple(el["sma"] * (math.cos(u) * node[k] + math.sin(u) * in_plane[k]) for k in range(3))


def assignment(universe: Universe) -> dict[str, str]:
    """Coordinator body id -> KSP pool body name, inner to outer."""
    ordered = sorted(universe.bodies.values(), key=lambda b: b.orbit.a)
    if len(ordered) > len(POOL):
        raise ValueError(f"{len(ordered)} bodies but only {len(POOL)} pool planets")
    return {b.id: POOL[k] for k, b in enumerate(ordered)}


def sync_commands(universe: Universe, game_t: float) -> list[str]:
    cmds = [f"setut {game_t!r}", f"setgm Sun {universe.star_mu!r}"]
    used = assignment(universe)
    for bid, name in used.items():
        b = universe.bodies[bid]
        el = ksp_elements(b.orbit)
        cmds.append("setbody {} {!r} {!r} {!r} {!r} {!r} {!r} {!r} {!r} {!r}".format(
            name, b.radius, b.mu, el["sma"], el["ecc"], el["inc_deg"], el["lan_deg"],
            el["argpe_deg"], el["mep_rad"], el["epoch"]))
    for k, name in enumerate(n for n in POOL if n not in used.values()):
        cmds.append(f"setbody {name} 1000.0 1000.0 {PARK_SMA * (1 + k)!r} 0.0 0.0 0.0 0.0 0.0 0.0")
    cmds.append("parkmoons")
    return cmds


def send(cmd: str, timeout: float = 5.0) -> dict:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(cmd.encode(), KSP_ADDR)
        return json.loads(s.recvfrom(65535)[0].decode())


def check(universe: Universe) -> dict:
    """Pairwise distances, coordinator vs KSP, at KSP's current UT."""
    pos = send("positions")
    t = pos["ut"]
    used = assignment(universe)
    worst, rows = 0.0, []
    for (a, na), (b, nb) in itertools.combinations(used.items(), 2):
        d_coord = norm(tuple(x - y for x, y in zip(universe.orbit_pos(a, t), universe.orbit_pos(b, t))))
        d_ksp = norm(tuple(x - y for x, y in zip(pos["bodies"][na], pos["bodies"][nb])))
        err = abs(d_coord - d_ksp)
        worst = max(worst, err)
        rows.append([a, b, round(d_coord / 1000, 3), round(d_ksp / 1000, 3), round(err, 3)])
    sun_d = {bid: round(norm(tuple(pos["bodies"][n])) / 1000, 3) for bid, n in used.items()}
    return {"ut": t, "worst_m": round(worst, 3), "pairs_km": rows, "ksp_dist_from_sun_km": sun_d}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["sync", "check", "commands"])
    ap.add_argument("planets")
    ap.add_argument("--game-t", type=float, default=0.0)
    args = ap.parse_args()
    with open(args.planets, encoding="utf-8") as f:
        universe = Universe.from_nms_planets(json.load(f))
    if args.action == "commands":
        print("\n".join(sync_commands(universe, args.game_t)))
    elif args.action == "sync":
        for cmd in sync_commands(universe, args.game_t):
            reply = send(cmd)
            print(cmd.split()[0], cmd.split()[1] if len(cmd.split()) > 1 else "", "->",
                  "ok" if reply.get("ok") else reply)
    else:
        print(json.dumps(check(universe), indent=1))


if __name__ == "__main__":
    main()
