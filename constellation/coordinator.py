"""The Constellation coordinator: owns the clock and the orbits, drives NMS.

    python -m constellation.coordinator [--warp 60] [--hz 30] [--state state/coordinator.json]

Each tick it reads the NMS adapter's newest state (player position, planets),
re-anchors to the body the player is in, and sends every planet's target NMS
position. Game time is saved to the state file so a restart (or a later
session) resumes the same orbits: nothing about planet positions is stored
in NMS.

With --ksp, the coordinator also drives the hidden KSP: on entering a system
it pushes the universe into KSP's body pool, every tick it sets KSP's clock to
game time, and every few seconds it measures KSP's planet error.

Two modes (docs/transfer-land-design.md section 6):
    "orbit"  KSP owns the vessel on rails; the coordinator reads it and predicts
             with patched.py, and KSP's map shows the maneuvers.
    "flight" powered flight near a body; the coordinator owns the state and
             integrates flight.py, while NMS poses the player/ship.

Mirror mode copies the live NMS ship back into KSP: while it is on and the NMS
adapter reports a fresh ship pose (real age < 0.5 s), the coordinator inverts
the anchor transform and pushes the vessel to KSP with `vesselstate setc` at no
more than 5 Hz. It starts on with `--ksp`; plan_transfer/add_node/execute_node/
land/launch take it off for the duration of coordinator-owned control, and
handback to orbit restores it.

Control (UDP, port CTL_PORT), one JSON message per datagram:
    {"t": "warp", "warp": 100}   {"t": "pause"}   {"t": "resume"}   {"t": "status"}
    {"t": "mirror", "on": true}  (copy the NMS ship into KSP; default on with --ksp)
    {"t": "map", "on": true}     (KSP's real map view, with --ksp)
    {"t": "burn", "prograde": 50, "normal": 0, "radial": 0}   (m/s on KSP's vessel, with --ksp)
    {"t": "plan_transfer", "from": "p1", "to": "p2", "t0": 0, "span": 1e7, "search": false}
    {"t": "add_node", "ut": 1234, "prograde": 50, "normal": 0, "radial": 0}
    {"t": "execute_node", "index": 0}
    {"t": "land", "body": "p2", "touchdown_speed": 1.0}
    {"t": "launch", "body": "p2", "alt_m": 30000}
"status" is answered with the current status object.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import math
import os
import time

from . import flight, maneuver, patched, protocol
from .clock import Clock
from .ksp_link import KspLink, assignment, setc_cmd, zup
from .maneuver import ManeuverNode
from .orbits import norm, sub
from .patched import VesselState
from .universe import STAR, Universe

CTL_PORT = 47813
log = logging.getLogger("coordinator")

# Below this altitude above the anchor body the coordinator takes over powered
# flight; ascent hands back only above FLIGHT_EXIT_ALT_M (hysteresis).
FLIGHT_ENTER_ALT_M = 40_000.0
FLIGHT_EXIT_ALT_M = 45_000.0
# Game seconds integrated per coordinator tick while in powered flight.
FLIGHT_DT = 0.25

# Mirror mode: copy the NMS ship's pose into KSP while the coordinator is not
# flying it. A ship report older than this many real seconds is ignored, and
# pushes are capped at this rate.
MIRROR_MAX_AGE_S = 0.5
MIRROR_PUSH_HZ = 5.0

# A general-purpose lander/ascent stage. Bodies are small (tens of km to a few
# hundred km) with roughly Earth surface gravity, so this has a comfortable
# thrust-to-weight while still lofting into orbit.
DEFAULT_VEHICLE = flight.Vehicle(dry_mass_kg=2000.0, fuel_kg=120_000.0,
                                 thrust_n=1_500_000.0, isp_s=300.0)


class Coordinator:
    def __init__(self, state_path: str, warp: float = 1.0, ksp: bool = False,
                 vehicle: flight.Vehicle | None = None,
                 flight_dt: float = FLIGHT_DT):
        self.state_path = state_path
        self.clock = Clock(warp=warp)
        self.universe: Universe | None = None
        self.sys_key: str | None = None
        self.seq = 0
        self.last_state: dict | None = None
        self.last_state_at = 0.0
        self.saved = self._load()
        self.anchor_changes = 0
        self.ksp = KspLink() if ksp else None
        self.ksp_synced = False
        self.ksp_worst_m = None
        self.ship: dict | None = None  # KSP vessel in coordinator axes, relative to its body
        self.ship_read_at = 0.0
        # ---- orbit <-> flight (docs/transfer-land-design.md section 6) --------
        self.mode = "orbit"
        self.flight_goal: str | None = None  # "land" | "launch" | "landed" | None
        self.flight_state: flight.FlightState | None = None
        self.vehicle = vehicle or DEFAULT_VEHICLE
        self.flight_dt = flight_dt
        self.guidance = None
        self.atm: flight.Atmosphere | None = None
        self.terrain: flight.TerrainFn | None = None
        self.touchdown_speed = 1.0
        self.target_alt_m = 0.0
        self.flight_pose: tuple | None = None
        self.last_landing_speed: float | None = None
        # ---- mirror mode: NMS ship -> KSP (see docs/transfer-land-design.md) --
        self.mirror_on = bool(ksp)  # on by default when started with --ksp
        self.mirror_pushes = 0
        self.mirror_last_push_at: float | None = None
        self.mirror_ship_alt_m: float | None = None
        self._mirror_before_pause: bool | None = None
        # ---- maneuver nodes ---------------------------------------------------
        self.nodes: list[ManeuverNode] = []
        self.pending_exec: int | None = None
        self.transfer: maneuver.Transfer | None = None
        self.last_dv: tuple | None = None
        self.next_encounter: patched.Encounter | None = None
        self._skip_vessel_read = 0
        self.sock_state = protocol.udp_socket(protocol.NMS_STATE_PORT)
        self.sock_cmd = protocol.udp_socket()
        self.sock_ctl = protocol.udp_socket(CTL_PORT)

    # ---- persistence -------------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {"systems": {}}

    def _save(self) -> None:
        if self.sys_key is not None:
            self.saved["systems"][self.sys_key] = {"game_t": self.clock.now(), "warp": self.clock.warp}
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.saved, f, indent=1)
        os.replace(tmp, self.state_path)

    # ---- system changes ------------------------------------------------------
    def _enter_system(self, state: dict) -> None:
        self.sys_key = state["sys"]
        prior = self.saved["systems"].get(self.sys_key, {})
        self.clock.set_time(prior.get("game_t", 0.0))
        planets = [{"slot": p["slot"], "home": p["home"], "radius": p.get("radius")} for p in state["planets"]]
        self.universe = Universe.from_nms_planets(planets, epoch=0.0)
        t = self.clock.now()
        current = {p["slot"]: tuple(p["pos"]) for p in state["planets"]}
        anchor = self.universe.anchor_to_current(tuple(state["player"]), current, t)
        log.info("entered system %s at game_t=%.1f, %d bodies, anchor=%s",
                 self.sys_key, t, len(self.universe.bodies), anchor)
        if self.ksp is not None:
            self.ksp_synced = self.ksp.sync(self.universe, t)
            log.info("KSP sync %s %s", "ok" if self.ksp_synced else "FAILED", self.ksp.last_error or "")

    # ---- one tick ----------------------------------------------------------------
    def tick(self) -> None:
        state = protocol.drain_latest(self.sock_state, "nms_state")
        if state is not None:
            self.last_state, self.last_state_at = state, time.monotonic()
            if state.get("sys") != self.sys_key and state.get("planets"):
                if self.sys_key is not None:
                    self._save()
                self._enter_system(state)
        self._handle_control()
        if self.universe is None or self.last_state is None:
            return
        self._fire_due_node()
        t = self.clock.now()
        if self.universe.update_anchor(tuple(self.last_state["player"]), t):
            self.anchor_changes += 1
            log.info("anchor -> %s at game_t=%.1f", self.universe.anchor, t)
        self.seq += 1
        rate = 0.0 if self.clock.paused else self.clock.warp
        if self.mode == "flight":
            self._step_flight()
        else:
            self._read_vessel(t)
            self._maybe_enter_flight()
        targets, vels = {}, {}
        for b in self.universe.bodies.values():
            targets[str(b.slot)] = [round(c, 3) for c in self.universe.nms_pos(b.id, t)]
            vels[str(b.slot)] = [round(c * rate, 3) for c in self.universe.nms_vel(b.id, t)]
        msg = {"t": "nms_targets", "seq": self.seq, "sys": self.sys_key, "game_t": t, "warp": rate,
               "mode": self.mode, "targets": targets, "vel_per_real_s": vels}
        ship_nms = self._ship_nms(t)
        if ship_nms is not None:
            msg["ship"] = ship_nms
        self.sock_cmd.sendto(protocol.encode(msg), (protocol.HOST, protocol.NMS_CMD_PORT))
        if self.ksp is not None and self.ksp_synced:
            self.ksp.fire(f"setut {t!r}")  # KSP's clock is a slave of game time
        self._mirror_step(time.monotonic())

    def _read_vessel(self, t: float) -> None:
        if self.ksp is None or not self.ksp_synced or self.seq % 6 != 0:
            return
        if self._skip_vessel_read > 0:
            self._skip_vessel_read -= 1
            return
        try:
            ship = self.ksp.vessel(self.universe)
            if ship is not None:
                self.ship, self.ship_read_at = ship, t
                if self.seq % 30 == 0:
                    self._update_prediction(t)
        except Exception as e:  # noqa: BLE001
            self.ksp.last_error = repr(e)

    def _update_prediction(self, t: float) -> None:
        """Coordinator-owned patched-conic prediction of the next encounter.

        The KSP vessel is propagated in the coordinator's own frame rather than
        trusting KSP's patched conics; the next SOI entry/impact is cached for
        ``status``. Best-effort: any failure just clears the prediction.
        """
        if self.universe is None or self.ship is None or self.ship.get("body") is None:
            self.next_encounter = None
            return
        state = VesselState(self.ship["body"], tuple(self.ship["r"]),
                            tuple(self.ship["v"]), self.ship["ut"])
        try:
            found = patched.predict_all_encounters(self.universe, state, t + 3600.0, step=60.0)
        except Exception:  # noqa: BLE001
            self.next_encounter = None
            return
        self.next_encounter = found[0] if found else None

    # ---- powered flight ------------------------------------------------------
    def _body_mu(self, body_id: str) -> float:
        return self.universe.star_mu if body_id == STAR else self.universe.bodies[body_id].mu

    def _flight_ship_nms(self, t: float) -> dict | None:
        """The powered-flight state as an NMS ship target (mode "flight")."""
        s = self.flight_state
        if s is None:
            return None
        u = self.universe
        body_nms = u.nms_pos(s.body, t)
        body_vel = u.nms_vel(s.body, t)
        rate = 0.0 if self.clock.paused else self.clock.warp
        body = u.bodies.get(s.body)
        forward, up = self.flight_pose if self.flight_pose is not None else (
            _unit(s.r), _unit(s.r))
        return {"body": s.body, "pos": [round(body_nms[k] + s.r[k], 3) for k in range(3)],
                "vel_per_real_s": [round((body_vel[k] + s.v[k]) * rate, 3) for k in range(3)],
                "alt_m": round(norm(s.r) - (body.radius if body else 0.0), 1),
                "pose": {"forward": list(forward), "up": list(up)}}

    def _step_flight(self) -> None:
        s = self.flight_state
        if s is None:
            return
        u = self.universe
        mu = self._body_mu(s.body)
        body = u.bodies.get(s.body)
        sr = body.radius if body is not None else 0.0
        if self.guidance is not None:
            cmd = self.guidance.command(s)
        else:
            cmd = flight.Command(0.0, _unit(s.r))
        nxt = flight.step(s, self.vehicle, mu, self.flight_dt, cmd.throttle,
                          cmd.attitude, self.atm, self.terrain, sr)
        self.flight_state = nxt
        self.flight_pose = (cmd.attitude, _unit(nxt.r))
        if self.flight_goal == "land":
            if flight.landing_detected(u, nxt, self.terrain, self.touchdown_speed):
                self.last_landing_speed = norm(nxt.v)
                self.flight_state = flight.hold_landed(nxt)
                self.flight_goal = "landed"
                self.guidance = None
        elif self.flight_goal == "launch":
            alt = norm(nxt.r) - sr
            if alt >= self.target_alt_m and nxt.fuel_kg > 0.0:
                self._handback_to_orbit(s.body)

    def _handback_to_orbit(self, body: str) -> None:
        """Ascent done: seed the circular orbit state and give the vessel back to KSP."""
        st = flight.circular_orbit_state(self.universe, body, self.target_alt_m,
                                         epoch=self.clock.now())
        st = dataclasses.replace(st, fuel_kg=self.flight_state.fuel_kg)
        self.ship = {"body": body, "r": st.r, "v": st.v, "ut": self.clock.now()}
        if self.ksp is not None:
            self._write_vessel_to_ksp(body, st.r, st.v, self.clock.now())
        self.mode = "orbit"
        self.flight_goal = None
        self.guidance = None
        self.flight_state = None
        self.flight_pose = None
        if self._mirror_before_pause:
            self.mirror_on = True
            self._mirror_before_pause = None

    def _write_vessel_to_ksp(self, body: str, r, v, ut: float) -> None:
        name = assignment(self.universe)[body]
        body_r, body_v = self.universe.bodies[body].orbit.state_at(ut)
        self.ksp.request(setc_cmd(name, r, v, body_r, body_v, ut))

    def _maybe_enter_flight(self) -> None:
        """Below the threshold, switch from rails to powered flight (section 6)."""
        if self.flight_goal != "land" or self.ship is None or self.universe is None:
            return
        body = self.ship.get("body")
        if body is None or body != self.universe.anchor:
            return
        b = self.universe.bodies.get(body)
        if b is None:
            return
        alt = norm(tuple(self.ship["r"])) - b.radius
        threshold = max(FLIGHT_ENTER_ALT_M, self.atm.top_m if self.atm else 0.0)
        if alt >= threshold:
            return
        self.flight_state = flight.FlightState(body, tuple(self.ship["r"]), tuple(self.ship["v"]),
                                               self.vehicle.fuel_kg, self.clock.now())
        self.guidance = flight.suicide_burn_guidance(
            self.vehicle, self._body_mu(body), b.radius, self.atm, self.terrain,
            self.touchdown_speed)
        self.mode = "flight"

    # ---- maneuver nodes ------------------------------------------------------
    def _default_span(self, from_id: str, to_id: str) -> float:
        t1 = self.universe.bodies[from_id].orbit.period
        t2 = self.universe.bodies[to_id].orbit.period
        if not math.isfinite(t1) or not math.isfinite(t2):
            return 1e7
        inv = abs(1.0 / t1 - 1.0 / t2)
        if inv < 1e-12:
            return 2.0 * t1
        return 2.0 / inv  # two synodic periods

    @staticmethod
    def _transfer_dict(tr: maneuver.Transfer) -> dict:
        n = tr.node
        return {"depart_ut": n.ut, "arrive_ut": tr.arrive_ut,
                "node": {"index": 0, "ut": n.ut, "prograde": n.prograde,
                         "normal": n.normal, "radial": n.radial},
                "dv_arrive": tr.dv_arrive, "c3": tr.c3}

    def _ctl_plan_transfer(self, msg: dict) -> dict:
        self._mirror_pause()
        if self.universe is None:
            return {"t": "plan_transfer", "error": "no universe"}
        from_id, to_id = msg["from"], msg["to"]
        t0 = float(msg.get("t0", self.clock.now()))
        span = msg.get("span")
        span = self._default_span(from_id, to_id) if span is None else float(span)
        tr = maneuver.plan_transfer(self.universe, from_id, to_id, t0, span,
                                    use_lambert=bool(msg.get("search", False)))
        if tr is None:
            return {"t": "plan_transfer", "transfer": None, "error": "no transfer window"}
        self.transfer = tr
        return {"t": "plan_transfer", "transfer": self._transfer_dict(tr)}

    def _ctl_add_node(self, msg: dict) -> dict:
        self._mirror_pause()
        node = ManeuverNode(ut=float(msg["ut"]), prograde=float(msg.get("prograde", 0.0)),
                            normal=float(msg.get("normal", 0.0)),
                            radial=float(msg.get("radial", 0.0)))
        self.nodes.append(node)
        reply = self.ksp.add_node(node) if self.ksp is not None else None
        if reply is None:
            reply = {"index": len(self.nodes) - 1, "ut": node.ut, "prograde": node.prograde,
                     "normal": node.normal, "radial": node.radial}
        return {"t": "add_node", "node": reply}

    def _ctl_execute_node(self, msg: dict) -> dict:
        self._mirror_pause()
        index = int(msg.get("index", 0))
        if index < 0 or index >= len(self.nodes):
            return {"t": "execute_node", "ok": False, "error": "no such node"}
        node = self.nodes[index]
        now = self.clock.now()
        if now + 1e-9 >= node.ut:
            self._fire_node(index)
            return {"t": "execute_node", "ok": True, "burn_ut": now, "dv": list(node.dv())}
        self.pending_exec = index
        return {"t": "execute_node", "ok": True, "burn_ut": node.ut, "dv": list(node.dv()),
                "scheduled": True}

    def _fire_due_node(self) -> None:
        if self.pending_exec is None:
            return
        node = self.nodes[self.pending_exec]
        if self.clock.now() + 1e-9 >= node.ut:
            self._fire_node(self.pending_exec)

    def _fire_node(self, index: int) -> None:
        """Burn the node: update the coordinator's own state and tell KSP."""
        node = self.nodes[index]
        if self.ship is not None and self.ship.get("body") is not None:
            mu = self._body_mu(self.ship["body"])
            _, v2 = maneuver.apply_node(mu, tuple(self.ship["r"]), tuple(self.ship["v"]), node)
            self.ship = dict(self.ship)
            self.ship["v"] = v2
        if self.ksp is not None:
            self.ksp.execute_node(node)
        self.last_dv = node.dv()
        self.pending_exec = None
        self._skip_vessel_read = 2  # do not let a stale KSP read undo the burn

    def _ctl_land(self, msg: dict) -> dict:
        self._mirror_pause()
        if self.universe is None:
            return {"t": "land", "ok": False, "error": "no universe"}
        body = msg["body"]
        if body not in self.universe.bodies:
            return {"t": "land", "ok": False, "error": f"unknown body {body}"}
        self.touchdown_speed = float(msg.get("touchdown_speed", 1.0))
        terrain = msg.get("terrain")
        self.terrain = terrain if callable(terrain) else None
        alt0 = float(msg.get("alt_m", 20_000.0))
        b = self.universe.bodies[body]
        if self.ship is not None and self.ship.get("body") == body:
            st = flight.FlightState(body, tuple(self.ship["r"]), tuple(self.ship["v"]),
                                    self.vehicle.fuel_kg, self.clock.now())
        else:
            st = dataclasses.replace(flight.circular_orbit_state(self.universe, body, alt0),
                                     fuel_kg=self.vehicle.fuel_kg)
        self.flight_state = st
        self.flight_goal = "land"
        self.guidance = flight.suicide_burn_guidance(
            self.vehicle, self._body_mu(body), b.radius, self.atm, self.terrain,
            self.touchdown_speed)
        self.mode = "flight"
        self.flight_pose = None
        return {"t": "land", "ok": True, "mode": "flight"}

    def _ctl_launch(self, msg: dict) -> dict:
        self._mirror_pause()
        if self.universe is None:
            return {"t": "launch", "ok": False, "error": "no universe"}
        body = msg["body"]
        if body not in self.universe.bodies:
            return {"t": "launch", "ok": False, "error": f"unknown body {body}"}
        alt = float(msg.get("alt_m", 30_000.0))
        self.target_alt_m = alt
        b = self.universe.bodies[body]
        if self.flight_state is not None and self.flight_state.body == body:
            st = dataclasses.replace(self.flight_state, v=(0.0, 0.0, 0.0),
                                     fuel_kg=max(self.flight_state.fuel_kg, self.vehicle.fuel_kg))
        else:
            r = (0.0, b.radius, 0.0)
            st = flight.FlightState(body, r, (0.0, 0.0, 0.0), self.vehicle.fuel_kg,
                                    self.clock.now())
        self.flight_state = st
        self.flight_goal = "launch"
        self.guidance = flight.gravity_turn_guidance(
            self.vehicle, self._body_mu(body), alt, self.atm, turn_start_alt_m=1000.0)
        self.mode = "flight"
        self.flight_pose = None
        return {"t": "launch", "ok": True, "mode": "flight"}

    # ---- ship in NMS space ---------------------------------------------------
    def _ship_nms(self, t: float) -> dict | None:
        """The vessel's position for NMS: its body's NMS position plus its offset.

        Orbit: the KSP vessel, advanced linearly with its velocity between reads.
        Flight: the coordinator-owned powered-flight state (mode "flight").
        """
        if self.mode == "flight":
            return self._flight_ship_nms(t)
        s = self.ship
        if not s or s.get("body") is None or self.universe is None:
            return None
        dt = t - s["ut"]
        rel = tuple(s["r"][k] + s["v"][k] * dt for k in range(3))
        body_nms = self.universe.nms_pos(s["body"], t)
        body_vel = self.universe.nms_vel(s["body"], t)
        rate = 0.0 if self.clock.paused else self.clock.warp
        body = self.universe.bodies.get(s["body"])  # None for the star
        return {"body": s["body"], "pos": [round(body_nms[k] + rel[k], 3) for k in range(3)],
                "vel_per_real_s": [round((body_vel[k] + s["v"][k]) * rate, 3) for k in range(3)],
                "alt_m": round(sum(c * c for c in rel) ** 0.5 - (body.radius if body else 0.0), 1)}

    # ---- mirror: copy the NMS ship's pose into KSP ---------------------------
    def _ship_report(self) -> dict | None:
        """The optional "ship" key from the adapter's newest state report.

        {"pos": [x,y,z] NMS absolute metres, "vel": [vx,vy,vz] metres per REAL
        second, "frame": adapter frame, "real_t": time.monotonic() at sample}.
        """
        if self.last_state is None:
            return None
        ship = self.last_state.get("ship")
        if not isinstance(ship, dict) or "pos" not in ship:
            return None
        return ship

    def _mirror_relative(self, report: dict, now_real: float) -> tuple:
        """Ship report -> (anchor-relative r, v, age in real seconds).

        This is the exact inverse of ``Universe.nms_pos``: the anchor body is
        pinned at ``universe.anchor_nms`` and the two spaces share the
        coordinator's axes, so a ship at NMS ``pos`` is at ``pos - anchor_nms``
        relative to the anchor body centre. The adapter's velocity is per real
        second, so game velocity is that divided by the warp (1 real s = warp
        game s). The anchor's own orbital velocity is not added here: ``setc``
        carries it separately as the body's state relative to its parent.
        """
        warp = self.clock.warp if self.clock.warp > 0.0 else 1.0
        r = sub(tuple(float(c) for c in report["pos"]), self.universe.anchor_nms)
        v = tuple(float(c) / warp for c in report.get("vel", (0.0, 0.0, 0.0)))
        age = now_real - float(report.get("real_t", 0.0))
        return r, v, age

    def _mirror_push(self, r, v) -> None:
        """Send one setc state putting KSP's active vessel at the mirrored pose."""
        u = self.universe
        ut = self.clock.now()
        if u.anchor == STAR:
            name, body_r, body_v = "Sun", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        else:
            name = assignment(u)[u.anchor]
            body_r, body_v = u.bodies[u.anchor].orbit.state_at(ut)
        self.ksp.fire(setc_cmd(name, r, v, body_r, body_v, ut))
        self.mirror_pushes += 1
        self.mirror_ship_alt_m = norm(r) - (u.bodies[u.anchor].radius if u.anchor in u.bodies else 0.0)

    def _mirror_step(self, now_real: float) -> None:
        """Push a fresh ship report to KSP at no more than MIRROR_PUSH_HZ."""
        if not self.mirror_on or self.ksp is None or not self.ksp_synced:
            return
        if self.mode != "orbit" or self.universe is None:
            return
        report = self._ship_report()
        if report is None:
            return
        r, v, age = self._mirror_relative(report, now_real)
        if age < 0.0 or age >= MIRROR_MAX_AGE_S:
            return
        if (self.mirror_last_push_at is not None
                and now_real - self.mirror_last_push_at < 1.0 / MIRROR_PUSH_HZ):
            return
        self._mirror_push(r, v)
        self.mirror_last_push_at = now_real

    def _mirror_pause(self) -> None:
        """A coordinator-owned command takes the ship off the mirror; handback
        to orbit puts it back if it was on."""
        if self.mirror_on:
            self._mirror_before_pause = True
            self.mirror_on = False

    def status(self) -> dict:
        out = {"sys": self.sys_key, "game_t": round(self.clock.now(), 2), "warp": self.clock.warp,
               "paused": self.clock.paused, "seq": self.seq, "anchor_changes": self.anchor_changes,
               "mode": self.mode,
               "state_age_s": round(time.monotonic() - self.last_state_at, 2) if self.last_state else None}
        if self.flight_state is not None:
            out["flight"] = {"goal": self.flight_goal, "body": self.flight_state.body,
                             "alt_m": round(norm(self.flight_state.r) - self.universe.bodies[self.flight_state.body].radius, 1)
                             if self.flight_state.body in self.universe.bodies else None,
                             "fuel_kg": round(self.flight_state.fuel_kg, 1),
                             "speed_mps": round(norm(self.flight_state.v), 3),
                             "last_landing_speed_mps": self.last_landing_speed}
        if self.ksp is not None:
            out["ksp"] = {"synced": self.ksp_synced, "worst_planet_error_m": self.ksp_worst_m,
                          "last_error": self.ksp.last_error}
            ship = self._ship_nms(self.clock.now())
            if ship is not None:
                out["ship"] = ship
        if self.next_encounter is not None:
            e = self.next_encounter
            out["next_encounter"] = {"body": e.body, "ut": round(e.ut, 1),
                                     "miss_m": round(e.miss_m, 1),
                                     "rel_speed_mps": round(e.rel_speed_mps, 1),
                                     "impact": e.impact}
        if self.universe is not None:
            out["anchor"] = self.universe.anchor
            t = self.clock.now()
            out["bodies"] = {
                b.id: {"slot": b.slot, "orbit_km": round(b.orbit.a / 1000), "period_h": round(b.orbit.period / 3600, 2),
                       "soi_km": round(b.soi / 1000)} for b in self.universe.bodies.values()}
            if self.last_state:
                reported = {p["slot"]: p["pos"] for p in self.last_state["planets"]}
                errs = {}
                # compare against where the planets should be at the moment the
                # adapter placed them, not now
                t_applied = self.last_state.get("applied_game_t") or t
                for slot, target in self.universe.nms_targets(t_applied).items():
                    if slot in reported:
                        errs[slot] = round(sum((a - b) ** 2 for a, b in zip(target, reported[slot])) ** 0.5)
                out["target_minus_reported_m"] = errs
                out["player"] = self.last_state["player"]
                out["nms_frame_ms"] = self.last_state.get("frame_ms")
        out["mirror"] = {
            "on": self.mirror_on,
            "last_push_age_s": round(time.monotonic() - self.mirror_last_push_at, 2)
            if self.mirror_last_push_at is not None else None,
            "ship_alt_m": round(self.mirror_ship_alt_m, 1) if self.mirror_ship_alt_m is not None else None,
            "pushes": self.mirror_pushes,
        }
        return out

    # ---- control port --------------------------------------------------------
    def dispatch(self, msg: dict) -> dict:
        """Handle one control message and return the reply (the control port's body)."""
        kind = msg.get("t")
        if kind == "warp":
            self.clock.set_warp(float(msg["warp"]))
        elif kind == "pause":
            self.clock.pause()
        elif kind == "resume":
            self.clock.resume()
        elif kind == "mirror":
            self.mirror_on = bool(msg.get("on", True))
            if self.mirror_on:
                self._mirror_before_pause = None
            return self.status()
        elif kind == "plan_transfer":
            return self._ctl_plan_transfer(msg)
        elif kind == "add_node":
            return self._ctl_add_node(msg)
        elif kind == "execute_node":
            return self._ctl_execute_node(msg)
        elif kind == "land":
            return self._ctl_land(msg)
        elif kind == "launch":
            return self._ctl_launch(msg)
        elif kind == "burn" and self.ksp is not None:
            reply = self.ksp.request("burn {!r} {!r} {!r}".format(
                float(msg.get("prograde", 0)), float(msg.get("normal", 0)), float(msg.get("radial", 0))))
            self.ship = None  # re-read the vessel next tick
            return reply or {"error": "no reply from KSP"}
        elif kind == "map" and self.ksp is not None:
            self.ksp.request("map on" if msg.get("on", True) else "map off")
        return self.status()

    def _handle_control(self) -> None:
        while True:
            try:
                data, addr = self.sock_ctl.recvfrom(protocol.MAX_DATAGRAM)
            except (BlockingIOError, ConnectionResetError):
                return
            try:
                reply = self.dispatch(protocol.decode(data))
            except Exception as e:  # noqa: BLE001 - report to the sender
                reply = {"error": repr(e)}
            self.sock_ctl.sendto(protocol.encode(reply), addr)

    def run(self, hz: float, status_path: str) -> None:
        period = 1.0 / hz
        next_save = time.monotonic() + 5.0
        while True:
            started = time.monotonic()
            self.tick()
            if started >= next_save:
                self._save()
                if self.ksp is not None and self.ksp_synced and self.universe is not None:
                    try:
                        err = self.ksp.worst_error(self.universe)
                        self.ksp_worst_m = None if err is None else round(err, 1)
                    except Exception as e:  # noqa: BLE001 - KSP trouble must never stop the coordinator
                        self.ksp.last_error = repr(e)
                        log.warning("KSP check failed: %r", e)
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(self.status(), f, indent=1)
                next_save = started + 5.0
            time.sleep(max(0.0, period - (time.monotonic() - started)))


def _unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (0.0, 1.0, 0.0) if n == 0.0 else (v[0] / n, v[1] / n, v[2] / n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warp", type=float, default=1.0)
    ap.add_argument("--hz", type=float, default=30.0)
    ap.add_argument("--state", default=os.path.join("state", "coordinator.json"))
    ap.add_argument("--status", default=os.path.join("state", "status.json"))
    ap.add_argument("--ksp", action="store_true", help="drive the hidden KSP (plugin on UDP 47821)")
    args = ap.parse_args()
    os.makedirs("state", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(os.path.join("state", "coordinator.log")), logging.StreamHandler()])
    Coordinator(args.state, warp=args.warp, ksp=args.ksp).run(args.hz, args.status)


if __name__ == "__main__":
    main()
