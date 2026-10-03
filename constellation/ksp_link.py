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
from typing import TYPE_CHECKING

from .orbits import Orbit, Vec, cross, dot, norm, unit
from .universe import STAR, Universe

if TYPE_CHECKING:
    from .maneuver import ManeuverNode

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


def add_node_cmd(node: ManeuverNode) -> str:
    """The exact addnode line: "addnode <ut> <prograde> <normal> <radial>"."""
    return "addnode {!r} {!r} {!r} {!r}".format(node.ut, node.prograde, node.normal, node.radial)


def setc_cmd(name: str, r: Vec, v: Vec, body_r: Vec, body_v: Vec, ut: float) -> str:
    """The exact vesselstate setc line.

    ``r``/``v`` are the vessel relative to the reference body ``name``;
    ``body_r``/``body_v`` are that body relative to its parent; all four are in
    coordinator axes and are converted to KSP's z-up frame here. The plugin
    removes its own report-frame rotation from this same set at ``ut``.
    """
    return "vesselstate setc {} {}".format(
        name, " ".join(repr(c) for c in (*zup(r), *zup(v), *zup(body_r), *zup(body_v), ut)))


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
    # Not "norotframe": zeroing inverseRotThresholdAltitude did not stop the reporting
    # frame turning (3 Oct 2026) and appeared to drop the vessel off rails.
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


def check_inertial(universe: Universe) -> dict:
    """Full-vector check in KSP's inertial orbit frame (z-up): positions, not just distances."""
    pos = send("orbitpos")
    t = pos["ut"]
    worst, rows = 0.0, {}
    for bid, name in assignment(universe).items():
        want = zup(universe.orbit_pos(bid, t))
        got = pos["bodies"][name]
        err = norm(tuple(a - b for a, b in zip(want, got)))
        worst = max(worst, err)
        rows[bid] = {"ksp": name, "err_m": round(err, 3)}
    return {"ut": t, "worst_m": round(worst, 3), "bodies": rows}


def frame_offset(universe: Universe, orbitpos: dict) -> tuple[float, float]:
    """Rotation about z (radians) from coordinator z-up axes to KSP's reporting frame.

    KSP reports orbit positions in a frame that turns over time (its inverse
    rotation near planets), so the offset is measured from the planets, whose
    true positions the coordinator knows, at the moment of every query.
    Returns (offset, spread): spread is the largest disagreement between
    planets, which should be ~0 when the sync is right.
    """
    t = orbitpos["ut"]
    angles = []
    for bid, name in assignment(universe).items():
        c = zup(universe.orbit_pos(bid, t))
        k = orbitpos["bodies"][name]
        angles.append(math.atan2(k[1], k[0]) - math.atan2(c[1], c[0]))
    ref = angles[0]
    wrapped = [ref + math.remainder(a - ref, 2 * math.pi) for a in angles]
    mean = sum(wrapped) / len(wrapped)
    return mean, max(abs(a - mean) for a in wrapped)


def rot_z(v: Vec, angle: float) -> Vec:
    c, s = math.cos(angle), math.sin(angle)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1], v[2])


def vessel_roundtrip(universe: Universe, body_id: str, r_coord: Vec, v_coord: Vec, wait_s: float) -> dict:
    """Put KSP's vessel on a coordinator state, let KSP fly it, and compare.

    The coordinator propagates the same state with its own Kepler code; the
    difference after ``wait_s`` real seconds is the pipeline error.
    """
    import time

    from .orbits import from_state

    name = assignment(universe)[body_id]
    tc = send("orbitpos")["ut"]
    off, spread = 0.0, 0.0
    # the plugin removes KSP's frame rotation itself, at the moment it applies the state
    body_r, body_v = (zup(x) for x in universe.bodies[body_id].orbit.state_at(tc))
    set_reply = send("vesselstate setc {} {}".format(
        name, " ".join(repr(c) for c in (*zup(r_coord), *zup(v_coord), *body_r, *body_v, tc))))
    t0 = set_reply.get("ut") or send("orbitpos")["ut"]  # exact UT the state was applied at
    orbit = from_state(universe.bodies[body_id].mu, zup(r_coord), zup(v_coord), t0)
    time.sleep(wait_s)
    vs = send("vesselstate")
    off2, spread2 = frame_offset(universe, vs["orbitpos"])  # planets read in the same frame as the vessel
    # vesselstate and orbitpos are read a frame apart; use the vessel's own UT
    r_back = rot_z(tuple(vs["r"]), -off2)
    want = orbit.position_at(vs["ut"])
    return {
        "body": name, "set": set_reply.get("vessel", set_reply), "flown_game_s": round(vs["ut"] - t0, 2),
        "frame_offset_deg": [round(math.degrees(off), 3), round(math.degrees(off2), 3)],
        "frame_spread_m_equiv_deg": [round(math.degrees(spread), 6), round(math.degrees(spread2), 6)],
        "error_m": round(norm(tuple(a - b for a, b in zip(r_back, want))), 3),
        "radius_km": round(norm(want) / 1000, 3),
    }


def bring_up(universe: Universe, game_t: float, wait_s: float = 600.0) -> None:
    """After KSP auto-loads the spike save: clear the popup, go on rails, sync."""
    import time

    deadline = time.monotonic() + wait_s
    while True:
        try:
            send("info", timeout=2.0)
            break
        except (OSError, ValueError):
            if time.monotonic() > deadline:
                raise TimeoutError("KSP bridge never answered")
            time.sleep(3.0)
    print("ui", send("ui hide whatsNew"))
    print("warp", send("warp 2"))
    time.sleep(3.0)
    for cmd in sync_commands(universe, game_t):
        reply = send(cmd)
        print(cmd.split()[0], cmd.split()[1] if len(cmd.split()) > 1 else "", "->", "ok" if reply.get("ok") else reply)


class KspLink:
    """The coordinator's live link to the hidden KSP.

    ``fire`` sends without waiting (used every tick to slave KSP's clock);
    ``request`` waits for the reply (system sync, checks). Replies to fired
    commands are drained and dropped so the socket buffer never fills.
    """

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))  # Windows refuses recvfrom on a never-bound UDP socket
        self.sock.setblocking(False)
        self.last_error: str | None = None

    def _drain(self) -> None:
        while True:
            try:
                self.sock.recvfrom(65535)
            except (BlockingIOError, ConnectionResetError):
                return

    def fire(self, cmd: str) -> None:
        self._drain()
        try:
            self.sock.sendto(cmd.encode(), KSP_ADDR)
        except OSError as e:
            self.last_error = repr(e)

    # Replies carry no request id, and replies to fired "setut"s can still be in
    # flight, so each request only accepts a reply with the key its command returns.
    REPLY_KEY = {"orbitpos": "bodies", "positions": "bodies", "setbody": "body", "setgm": "body",
                 "parkmoons": "parked", "map": "map", "info": "bodies", "vesselstate": "r", "setut": "ut", "burn": "vessel",
                 "addnode": "node", "clearnodes": "nodes", "readnodes": "nodes"}

    def request(self, cmd: str, timeout: float = 2.0) -> dict | None:
        import time

        want = self.REPLY_KEY.get(cmd.split()[0])
        self._drain()
        self.sock.sendto(cmd.encode(), KSP_ADDR)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                reply = json.loads(self.sock.recvfrom(65535)[0].decode())
            except (BlockingIOError, ConnectionResetError):
                time.sleep(0.005)
                continue
            if "error" in reply or want is None or want in reply:
                return reply
        self.last_error = f"timeout: {cmd.split()[0]}"
        return None

    def sync(self, universe: Universe, game_t: float) -> bool:
        for cmd in sync_commands(universe, game_t):
            reply = self.request(cmd)
            if not reply or not reply.get("ok"):
                self.last_error = f"{cmd.split()[0]} {cmd.split()[1] if len(cmd.split()) > 1 else ''}: {reply}"
                return False
        return True

    def vessel(self, universe: Universe, timeout: float = 0.2) -> dict | None:
        """KSP's active vessel in coordinator axes, relative to its body.

        The vessel and the planets come back in one reply, in the same KSP
        frame, so removing KSP's frame rotation is exact on this read path.
        Returns {"body": coordinator body id, "r", "v", "ut"} or None.
        """
        vs = self.request("vesselstate", timeout=timeout)
        if not vs or "r" not in vs:
            return None
        names = {name: bid for bid, name in assignment(universe).items()}
        names["Sun"] = STAR  # KSP's Sun is the coordinator's star
        bid = names.get(vs["body"])
        if bid is None:
            return {"body": None, "ksp_body": vs["body"], "ut": vs["ut"]}
        off, _ = frame_offset(universe, vs["orbitpos"])
        r = zup(rot_z(tuple(vs["r"]), -off))  # zup() swaps y and z, so it is its own inverse
        v = zup(rot_z(tuple(vs["v"]), -off))
        return {"body": bid, "r": r, "v": v, "ut": vs["ut"]}

    def add_node(self, node: ManeuverNode, timeout: float = 2.0) -> dict | None:
        """Add a maneuver node to the active vessel; returns the node object or None."""
        reply = self.request(add_node_cmd(node), timeout=timeout)
        return reply.get("node") if reply else None

    def clear_nodes(self, timeout: float = 2.0) -> dict | None:
        """Remove every maneuver node."""
        return self.request("clearnodes", timeout=timeout)

    def read_nodes(self, timeout: float = 2.0) -> list[dict] | None:
        """List the active vessel's maneuver nodes, inner to outer."""
        reply = self.request("readnodes", timeout=timeout)
        return reply.get("nodes") if reply else None

    def execute_node(self, node: ManeuverNode, timeout: float = 2.0) -> dict | None:
        """Wait until game time reaches node.ut, then issue the existing burn with its components."""
        import time

        while True:
            info = self.request("info", timeout=timeout)
            if info is None:
                return None
            ut = info.get("ut")
            if ut is None or ut >= node.ut:
                break
            time.sleep(min(0.05, max(0.0, node.ut - ut)))
        return self.request(
            "burn {!r} {!r} {!r}".format(node.prograde, node.normal, node.radial), timeout=timeout)

    def worst_error(self, universe: Universe) -> float | None:
        """Largest planet position error in KSP's frame after removing its rotation (m)."""
        pos = self.request("orbitpos")
        if not pos:
            return None
        t = pos["ut"]
        off, _ = frame_offset(universe, pos)
        worst = 0.0
        for bid, name in assignment(universe).items():
            want = rot_z(zup(universe.orbit_pos(bid, t)), off)
            worst = max(worst, norm(tuple(a - b for a, b in zip(want, pos["bodies"][name]))))
        return worst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["sync", "check", "check-inertial", "commands", "bringup"])
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
    elif args.action == "bringup":
        bring_up(universe, args.game_t)
    elif args.action == "check-inertial":
        print(json.dumps(check_inertial(universe), indent=1))
    else:
        print(json.dumps(check(universe), indent=1))


if __name__ == "__main__":
    main()
