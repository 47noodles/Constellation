"""The Constellation coordinator: owns the clock and the orbits, drives NMS.

    python -m constellation.coordinator [--warp 60] [--hz 30] [--state state/coordinator.json]

Each tick it reads the NMS adapter's newest state (player position, planets),
re-anchors to the body the player is in, and sends every planet's target NMS
position. Game time is saved to the state file so a restart (or a later
session) resumes the same orbits: nothing about planet positions is stored
in NMS.

Control (UDP, port CTL_PORT), one JSON message per datagram:
    {"t": "warp", "warp": 100}   {"t": "pause"}   {"t": "resume"}   {"t": "status"}
"status" is answered with the current status object.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time

from . import protocol
from .clock import Clock
from .universe import Universe

CTL_PORT = 47813
log = logging.getLogger("coordinator")


class Coordinator:
    def __init__(self, state_path: str, warp: float = 1.0):
        self.state_path = state_path
        self.clock = Clock(warp=warp)
        self.universe: Universe | None = None
        self.sys_key: str | None = None
        self.seq = 0
        self.last_state: dict | None = None
        self.last_state_at = 0.0
        self.saved = self._load()
        self.anchor_changes = 0
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
        t = self.clock.now()
        if self.universe.update_anchor(tuple(self.last_state["player"]), t):
            self.anchor_changes += 1
            log.info("anchor -> %s at game_t=%.1f", self.universe.anchor, t)
        self.seq += 1
        rate = 0.0 if self.clock.paused else self.clock.warp
        targets, vels = {}, {}
        for b in self.universe.bodies.values():
            targets[str(b.slot)] = [round(c, 3) for c in self.universe.nms_pos(b.id, t)]
            vels[str(b.slot)] = [round(c * rate, 3) for c in self.universe.nms_vel(b.id, t)]
        msg = {"t": "nms_targets", "seq": self.seq, "sys": self.sys_key, "game_t": t, "warp": rate,
               "targets": targets, "vel_per_real_s": vels}
        self.sock_cmd.sendto(protocol.encode(msg), (protocol.HOST, protocol.NMS_CMD_PORT))

    def status(self) -> dict:
        out = {"sys": self.sys_key, "game_t": round(self.clock.now(), 2), "warp": self.clock.warp,
               "paused": self.clock.paused, "seq": self.seq, "anchor_changes": self.anchor_changes,
               "state_age_s": round(time.monotonic() - self.last_state_at, 2) if self.last_state else None}
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
        return out

    def _handle_control(self) -> None:
        while True:
            try:
                data, addr = self.sock_ctl.recvfrom(protocol.MAX_DATAGRAM)
            except (BlockingIOError, ConnectionResetError):
                return
            try:
                msg = protocol.decode(data)
                kind = msg.get("t")
                if kind == "warp":
                    self.clock.set_warp(float(msg["warp"]))
                elif kind == "pause":
                    self.clock.pause()
                elif kind == "resume":
                    self.clock.resume()
                reply = self.status()
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
                with open(status_path, "w", encoding="utf-8") as f:
                    json.dump(self.status(), f, indent=1)
                next_save = started + 5.0
            time.sleep(max(0.0, period - (time.monotonic() - started)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warp", type=float, default=1.0)
    ap.add_argument("--hz", type=float, default=30.0)
    ap.add_argument("--state", default=os.path.join("state", "coordinator.json"))
    ap.add_argument("--status", default=os.path.join("state", "status.json"))
    args = ap.parse_args()
    os.makedirs("state", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(os.path.join("state", "coordinator.log")), logging.StreamHandler()])
    Coordinator(args.state, warp=args.warp).run(args.hz, args.status)


if __name__ == "__main__":
    main()
