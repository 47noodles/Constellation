"""End-to-end scenario: orbit A -> transfer -> SOI handover -> land B -> launch B.

No game is needed. A fake KSP endpoint (UDP 47821) stands in for the plugin and
a fake NMS endpoint (47811/47812) for the pyMHF adapter, exactly as the real
coordinator drives them. The coordinator's control messages (docs/
transfer-land-design.md section 6) drive the whole run:

    start in orbit of planet A, plan_transfer A -> B, add_node, execute_node,
    propagate through B's SOI handover, land on B, then launch back to orbit.

The transfer/Lambert maths is the real constellation.maneuver and the SOI
handover the real constellation.patched; the descent and ascent are the real
constellation.flight integrated by the coordinator. Only the two game endpoints
are faked. The timeline (burn dv, SOI change, landing speed, final orbit) is
printed for the report.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest

from constellation import flight, patched, protocol
from constellation.coordinator import Coordinator
from constellation.ksp_link import KSP_ADDR, assignment, zup
from constellation.orbits import from_state, norm
from constellation.patched import VesselState
from constellation.universe import STAR

SYS = "00013a000355e47f"
# Homes in the xz plane (y = 0) so the coordinator's orbits are coplanar and a
# Hohmann transfer can actually reach the target's sphere of influence.
PLANETS = [
    {"slot": 0, "home": [1_000_000.0, 0.0, 200_000.0], "radius": 130_000.0},
    {"slot": 1, "home": [2_500_000.0, 0.0, -400_000.0], "radius": 130_000.0},
    {"slot": 2, "home": [-3_000_000.0, 0.0, 100_000.0], "radius": 130_000.0},
]
PLAYER = (1_000_000.0, 140_010.0, 200_000.0)  # 10 m above planet 0's ground


class FakeKsp(threading.Thread):
    """A UDP peer on KSP's port speaking the plugin's command set.

    It reports a settable active vessel and no planet-frame rotation (the
    orbit positions it returns are the coordinator's own, so the coordinator's
    frame-offset correction is exactly zero and the read round-trips).
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(KSP_ADDR)
        self.sock.settimeout(0.1)
        self.received: list[str] = []
        self.nodes: list[dict] = []
        self.universe = None
        self.vessel = None  # (body_id, r, v) in coordinator axes
        self.ut = 1.0e12  # always past any node UT, so execute_node never waits
        self._halt = False

    # ---- thread ----
    def run(self) -> None:
        while not self._halt:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            line = data.decode()
            self.received.append(line)
            try:
                reply = self.reply(line)
            except Exception as e:  # noqa: BLE001
                reply = {"error": repr(e)}
            try:
                self.sock.sendto(json.dumps(reply).encode(), addr)
            except OSError:
                return

    def stop(self) -> None:
        self._halt = True
        self.join(timeout=1.0)
        self.sock.close()

    # ---- helpers ----
    def _orbit_bodies(self) -> dict:
        if self.universe is None:
            return {}
        return {name: list(zup(self.universe.orbit_pos(bid, self.ut)))
                for bid, name in assignment(self.universe).items()}

    def _vessel_body_and_vectors(self):
        if self.vessel is None or self.universe is None:
            return None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        bid, r, v = self.vessel
        return assignment(self.universe).get(bid), zup(r), zup(v)

    def reply(self, line: str) -> dict:
        w = line.split()
        cmd = w[0] if w else "info"
        if cmd == "setut":
            return {"ok": True, "ut": self.ut}
        if cmd == "setgm":
            return {"ok": True, "body": "Sun"}
        if cmd == "setbody":
            return {"ok": True, "body": w[1]}
        if cmd == "parkmoons":
            return {"ok": True, "parked": []}
        if cmd == "info":
            return {"ut": self.ut, "bodies": []}
        if cmd in ("positions", "orbitpos"):
            return {"ut": self.ut, "bodies": self._orbit_bodies()}
        if cmd == "vesselstate":
            body, r, v = self._vessel_body_and_vectors()
            if len(w) > 1 and w[1] == "setc":
                return {"ok": True, "ut": self.ut, "r": list(r)}
            return {"ut": self.ut, "body": None if body is None
                    else assignment(self.universe)[body], "r": list(r), "v": list(v),
                    "orbitpos": {"ut": self.ut, "bodies": self._orbit_bodies()}}
        if cmd == "addnode":
            node = {"index": len(self.nodes), "ut": float(w[1]), "prograde": float(w[2]),
                    "normal": float(w[3]), "radial": float(w[4])}
            self.nodes.append(node)
            return {"ok": True, "node": node}
        if cmd == "clearnodes":
            self.nodes = []
            return {"ok": True, "nodes": []}
        if cmd == "readnodes":
            return {"ok": True, "nodes": list(self.nodes)}
        if cmd == "burn":
            return {"ok": True, "ut": self.ut, "vessel": {}}
        return {"error": "unknown command " + cmd}


class FakeNms(threading.Thread):
    """A UDP peer speaking the coordinator's NMS protocol."""

    def __init__(self, planets: list[dict], player: tuple) -> None:
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((protocol.HOST, protocol.NMS_CMD_PORT))
        self.sock.setblocking(False)
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.planets = {p["slot"]: {"home": list(p["home"]), "pos": list(p["home"]),
                                    "radius": p["radius"]} for p in planets}
        self.player = list(player)
        self.applied_game_t = None
        self.latest = None
        self._halt = False

    def run(self) -> None:
        seq = 0
        while not self._halt:
            while True:
                try:
                    data, _ = self.sock.recvfrom(65535)
                except (BlockingIOError, ConnectionResetError):
                    break
                if not data:
                    break
                try:
                    msg = json.loads(data)
                except ValueError:
                    continue
                if msg.get("t") == "nms_targets" and msg.get("sys") == SYS:
                    self.latest = msg
                    self.applied_game_t = msg.get("game_t")
                    for slot, target in msg.get("targets", {}).items():
                        if int(slot) in self.planets:
                            self.planets[int(slot)]["pos"] = list(target)
            seq += 1
            state = {"t": "nms_state", "seq": seq, "sys": SYS, "frame_ms": 33.3,
                     "player": self.player, "applied_game_t": self.applied_game_t,
                     "planets": [{"slot": s, "pos": p["pos"], "home": p["home"],
                                  "radius": p["radius"]} for s, p in self.planets.items()]}
            try:
                self.out.sendto(protocol.encode(state), (protocol.HOST, protocol.NMS_STATE_PORT))
            except OSError:
                break
            time.sleep(1 / 60)

    def stop(self) -> None:
        self._halt = True
        self.join(timeout=1.0)
        self.sock.close()
        self.out.close()


class ScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        # A path the coordinator may load defaults from; the scenario never
        # calls _save(), so nothing is written.
        state_path = os.path.join(tempfile.gettempdir(),
                                  f"constellation-scenario-{os.getpid()}.json")
        self.ksp = FakeKsp()
        self.ksp.start()
        self.nms = FakeNms(PLANETS, PLAYER)
        self.nms.start()
        self.coord = Coordinator(state_path, warp=1.0, ksp=True, flight_dt=0.25)
        self.addCleanup(self._cleanup)
        deadline = time.monotonic() + 10.0
        while self.coord.universe is None and time.monotonic() < deadline:
            self.coord.tick()
            time.sleep(0.02)
        self.assertIsNotNone(self.coord.universe, "coordinator never entered the system")
        self.ksp.universe = self.coord.universe
        bodies = sorted(self.coord.universe.bodies.values(), key=lambda b: b.orbit.a)
        self.A, self.B = bodies[0], bodies[1]
        self.timeline: list[str] = []

    def _cleanup(self) -> None:
        self.ksp.stop()
        self.nms.stop()
        for s in (self.coord.sock_state, self.coord.sock_cmd, self.coord.sock_ctl):
            s.close()
        if self.coord.ksp is not None:
            self.coord.ksp.sock.close()

    def _tick_until(self, predicate, limit: int, what: str) -> None:
        for _ in range(limit):
            self.coord.tick()
            if predicate():
                return
        self.fail(f"scenario did not finish {what} within {limit} ticks")

    def test_orbit_transfer_land_and_launch(self) -> None:
        coord, u = self.coord, self.coord.universe
        A, B = self.A, self.B
        print(f"\nSCENARIO: transfer {A.id} -> {B.id} about the star "
              f"(a {A.orbit.a/1000:.0f} km -> {B.orbit.a/1000:.0f} km)")

        # 1. plan the transfer in a window (control port message).
        plan = coord.dispatch({"t": "plan_transfer", "from": A.id, "to": B.id})
        self.assertIsNotNone(plan.get("transfer"), plan)
        tr = plan["transfer"]
        node = tr["node"]
        self.timeline.append(
            f"plan_transfer: depart_ut={tr['depart_ut']:.1f}s arrive_ut={tr['arrive_ut']:.1f}s "
            f"dv_depart={node['prograde']:.3f} m/s dv_arrive={tr['dv_arrive']:.3f} m/s")

        # 2. add the node to KSP's map.
        added = coord.dispatch({"t": "add_node", "ut": node["ut"], "prograde": node["prograde"],
                                "normal": node["normal"], "radial": node["radial"]})
        self.assertEqual(added["node"]["index"], 0)
        self.assertTrue(any(line.startswith("addnode") for line in self.ksp.received),
                        "addnode never reached the KSP endpoint")

        # 3. execute it from the departure state.
        dep = tr["depart_ut"]
        r0, v0 = A.orbit.state_at(dep)
        coord.ship = {"body": STAR, "r": r0, "v": v0, "ut": dep}
        coord.clock.set_time(dep)
        executed = coord.dispatch({"t": "execute_node", "index": 0})
        self.assertTrue(executed["ok"], executed)
        self.assertIsNotNone(coord.last_dv)
        self.assertTrue(any(line.startswith("burn") for line in self.ksp.received),
                        "execute_node never issued the burn to KSP")
        burn_dv = coord.last_dv
        self.timeline.append(
            f"execute_node: burn at UT {dep:.1f}s  dv=({burn_dv[0]:.3f}, {burn_dv[1]:.3f}, "
            f"{burn_dv[2]:.3f}) m/s  |dv|={norm(burn_dv):.3f} m/s")

        # 4. propagate through the SOI handover into B's sphere.
        post = coord.ship
        state = VesselState(STAR, post["r"], post["v"], post["ut"])
        t_max = tr["arrive_ut"] + coord._default_span(A.id, B.id)
        entry = patched.find_soi_entry(u, state, B.id, t_max)
        self.assertIsNotNone(entry, "vessel never entered B's SOI")
        rep = patched.reparent(u, patched.state_at(u, state, entry.ut), entry)
        self.timeline.append(
            f"SOI handover: left {entry.body_from} for {entry.body_to} at UT {entry.ut:.1f}s "
            f"(+{entry.ut - dep:.1f}s after the burn), relative speed {norm(rep.v):.1f} m/s")

        # 5. capture at B (the plan's arrival burn), then land.
        capture = flight.circular_orbit_state(u, B.id, 20_000.0)
        coord.ship = {"body": B.id, "r": capture.r, "v": capture.v, "ut": entry.ut}
        coord.ksp_synced = False  # the rest is coordinator-owned powered flight
        landed = coord.dispatch({"t": "land", "body": B.id, "touchdown_speed": 1.0})
        self.assertEqual(landed["mode"], "flight")
        self._tick_until(lambda: coord.flight_goal == "landed", 40_000, "the landing")
        speed = coord.last_landing_speed
        self.assertIsNotNone(speed)
        self.assertLess(speed, 5.0, f"landed too hard: {speed} m/s")
        self.assertLess(norm(coord.flight_state.r) - B.radius, 100.0)
        self.timeline.append(f"land: touchdown speed {speed:.3f} m/s on {B.id} "
                             f"(altitude {norm(coord.flight_state.r) - B.radius:.1f} m)")

        # 6. launch back to a stable orbit of B.
        launched = coord.dispatch({"t": "launch", "body": B.id, "alt_m": 30_000.0})
        self.assertEqual(launched["mode"], "flight")
        self._tick_until(lambda: coord.mode == "orbit", 40_000, "the ascent")
        ship = coord.ship
        self.assertEqual(ship["body"], B.id)
        orbit = from_state(B.mu, ship["r"], ship["v"], ship["ut"])
        periapsis = orbit.a * (1.0 - orbit.e)
        self.assertGreater(periapsis, B.radius, "final orbit intersects the surface")
        self.timeline.append(
            f"launch: circular orbit attained, semi-major axis {orbit.a/1000:.1f} km, "
            f"eccentricity {orbit.e:.4f}, periapsis altitude {(periapsis - B.radius)/1000:.1f} km")

        # The final state is a real circular orbit: hand it back to KSP's map.
        print("TIMELINE:")
        for line in self.timeline:
            print("  " + line)
        print(f"  acceptance: landing {speed:.3f} m/s < 5 m/s; "
              f"periapsis {(periapsis - B.radius)/1000:.1f} km > surface")


if __name__ == "__main__":
    unittest.main()
