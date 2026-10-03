"""Coordinator mirror mode: the live NMS ship copied back into KSP.

A fake KSP peer on an ephemeral UDP port records the `vesselstate setc` lines
the coordinator pushes; the NMS ship report is fed straight into the
coordinator's state (the handler path), so no live port is ever touched.
Checks, per docs/transfer-land-design.md:

* a ship hovering 200 km above the anchor planet's NMS position lands 200 km
  from the anchor body centre (to under 1 m);
* 100 m/s per real second at warp 1 pushes 100 m/s, at warp 10 pushes 10 m/s;
* a report older than 0.5 s pushes nothing;
* pushes never exceed 5 Hz;
* plan_transfer turns mirror off.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
import unittest.mock as mock

import constellation.ksp_link as ksp_link
from constellation import coordinator as coordinator_mod
from constellation import flight, protocol
from constellation.coordinator import Coordinator
from constellation.orbits import norm
from constellation.universe import Universe

HOST = "127.0.0.1"
PLANETS = [
    {"slot": 0, "home": [1_000_000.0, 0.0, 200_000.0], "radius": 130_000.0},
    {"slot": 1, "home": [2_500_000.0, 0.0, -400_000.0], "radius": 130_000.0},
]
# 200 km above planet 0's generated position: inside its sphere of influence.
PLAYER = (1_000_000.0, 200_000.0, 200_000.0)


class FakeKsp(threading.Thread):
    """A UDP peer on an ephemeral port that records the plugin's command set."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((HOST, 0))
        self.addr = self.sock.getsockname()
        self.sock.settimeout(0.1)
        self.received: list[str] = []
        self._halt = False

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
                self.sock.sendto(json.dumps(self.reply(line)).encode(), addr)
            except OSError:
                return

    def reply(self, line: str) -> dict:
        w = line.split()
        cmd = w[0] if w else "info"
        if cmd == "vesselstate":
            return {"ok": True, "ut": 0.0, "r": [0.0, 0.0, 0.0]}
        if cmd == "setut":
            return {"ok": True, "ut": 0.0}
        return {"ok": True}

    def stop(self) -> None:
        self._halt = True
        self.join(timeout=1.0)
        self.sock.close()


class MirrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.peer = FakeKsp()
        self.peer.start()
        self.sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sink.bind((HOST, 0))
        self._patches = [
            mock.patch.object(ksp_link, "KSP_ADDR", self.peer.addr),
            mock.patch.object(protocol, "NMS_STATE_PORT", 0),
            mock.patch.object(protocol, "NMS_CMD_PORT", self.sink.getsockname()[1]),
            mock.patch.object(coordinator_mod, "CTL_PORT", 0),
        ]
        for p in self._patches:
            p.start()
        self.state_path = os.path.join(tempfile.gettempdir(),
                                       f"constellation-mirror-{os.getpid()}.json")
        self.coord = Coordinator(self.state_path, warp=1.0, ksp=True)
        u = Universe.from_nms_planets(PLANETS)
        current = {p["slot"]: tuple(p["home"]) for p in PLANETS}
        self.assertEqual(u.anchor_to_current(PLAYER, current, 0.0), "p0")
        self.coord.universe = u
        self.coord.ksp_synced = True
        self.coord.mode = "orbit"
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for p in self._patches:
            try:
                p.stop()
            except RuntimeError:
                pass
        self.peer.stop()
        self.sink.close()
        for s in (self.coord.sock_state, self.coord.sock_cmd, self.coord.sock_ctl):
            s.close()
        if self.coord.ksp is not None:
            self.coord.ksp.sock.close()

    # ---- helpers ----
    def feed(self, pos, vel, real_t, frame: int = 1) -> None:
        self.coord.last_state = {
            "t": "nms_state", "player": list(PLAYER),
            "ship": {"pos": list(pos), "vel": list(vel), "frame": frame, "real_t": real_t},
        }

    def setc_lines(self) -> list[str]:
        return [line for line in list(self.peer.received) if line.startswith("vesselstate setc")]

    def wait_setc(self, before: int, timeout: float = 1.0) -> list[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines = self.setc_lines()
            if len(lines) > before:
                return lines
            time.sleep(0.005)
        return self.setc_lines()

    @staticmethod
    def parse_setc(line: str):
        w = line.split()
        nums = [float(x) for x in w[3:16]]
        return w[2], tuple(nums[0:3]), tuple(nums[3:6])

    def reset_pushes(self) -> None:
        self.peer.received.clear()
        self.coord.mirror_last_push_at = None
        self.coord.mirror_pushes = 0

    # ---- tests ----
    def test_mirror_on_by_default_with_ksp(self) -> None:
        self.assertTrue(self.coord.mirror_on)

    def test_hovering_ship_lands_200_km_from_anchor(self) -> None:
        anchor_nms = self.coord.universe.anchor_nms
        pos = (anchor_nms[0], anchor_nms[1] + 200_000.0, anchor_nms[2])
        before = len(self.setc_lines())
        self.feed(pos, (0.0, 0.0, 0.0), real_t=time.monotonic())
        self.coord._mirror_step(time.monotonic())
        lines = self.wait_setc(before)
        self.assertGreater(len(lines), before, "no setc push")
        name, r_ksp, v_ksp = self.parse_setc(lines[-1])
        self.assertEqual(name, "Moho")
        self.assertLess(abs(norm(r_ksp) - 200_000.0), 1.0)
        self.assertLess(norm(v_ksp), 1e-6)

    def test_velocity_scales_with_warp(self) -> None:
        anchor_nms = self.coord.universe.anchor_nms
        pos = (anchor_nms[0], anchor_nms[1] + 200_000.0, anchor_nms[2])

        self.reset_pushes()
        self.feed(pos, (100.0, 0.0, 0.0), real_t=1000.0)
        self.coord._mirror_step(1000.0)
        lines = self.wait_setc(0)
        self.assertTrue(lines)
        _, _, v1 = self.parse_setc(lines[-1])
        self.assertAlmostEqual(norm(v1), 100.0, places=6)

        self.reset_pushes()
        self.coord.clock.set_warp(10.0)
        self.feed(pos, (100.0, 0.0, 0.0), real_t=2000.0)
        self.coord._mirror_step(2000.0)
        lines = self.wait_setc(0)
        self.assertTrue(lines)
        _, _, v10 = self.parse_setc(lines[-1])
        self.assertAlmostEqual(norm(v10), 10.0, places=6)

    def test_stale_report_pushes_nothing(self) -> None:
        anchor_nms = self.coord.universe.anchor_nms
        pos = (anchor_nms[0], anchor_nms[1] + 200_000.0, anchor_nms[2])
        self.reset_pushes()
        now = 5000.0
        self.feed(pos, (0.0, 0.0, 0.0), real_t=now - 1.0)
        self.coord._mirror_step(now)
        time.sleep(0.1)
        self.assertEqual(self.setc_lines(), [])
        # a fresh report in the same place does push, so the silence was staleness
        self.feed(pos, (0.0, 0.0, 0.0), real_t=now + 1.0)
        self.coord._mirror_step(now + 1.0)
        self.assertTrue(self.wait_setc(0))

    def test_pushes_never_exceed_5_hz(self) -> None:
        anchor_nms = self.coord.universe.anchor_nms
        pos = (anchor_nms[0], anchor_nms[1] + 200_000.0, anchor_nms[2])
        self.reset_pushes()
        for i in range(20):  # 20 reports over 1 real second, every 0.05 s
            now = 1_000.0 + i * 0.05
            self.feed(pos, (0.0, 0.0, 0.0), real_t=now)
            self.coord._mirror_step(now)
        time.sleep(0.1)
        pushes = len(self.setc_lines())
        self.assertGreaterEqual(pushes, 1)
        self.assertLessEqual(pushes, 5)

    def test_plan_transfer_turns_mirror_off(self) -> None:
        self.assertTrue(self.coord.mirror_on)
        reply = self.coord.dispatch({"t": "plan_transfer", "from": "p0", "to": "p1"})
        self.assertEqual(reply.get("t"), "plan_transfer")
        self.assertFalse(self.coord.mirror_on)

    def test_land_and_launch_turn_mirror_off(self) -> None:
        self.coord.mirror_on = True
        self.coord.dispatch({"t": "land", "body": "p0"})
        self.assertFalse(self.coord.mirror_on)
        self.coord.mirror_on = True
        self.coord.dispatch({"t": "launch", "body": "p0"})
        self.assertFalse(self.coord.mirror_on)

    def test_mirror_control_message_and_status(self) -> None:
        self.coord.dispatch({"t": "mirror", "on": False})
        self.assertFalse(self.coord.mirror_on)
        self.coord.dispatch({"t": "mirror", "on": True})
        self.assertTrue(self.coord.mirror_on)
        status = self.coord.status()
        self.assertIn("mirror", status)
        block = status["mirror"]
        self.assertEqual(set(block), {"on", "last_push_age_s", "ship_alt_m", "pushes"})
        self.assertTrue(block["on"])

    def test_handback_restores_mirror(self) -> None:
        self.coord.mirror_on = True
        self.coord.target_alt_m = 20_000.0
        self.coord.flight_state = flight.FlightState("p0", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                                                     1000.0, 0.0)
        self.coord._mirror_pause()
        self.assertFalse(self.coord.mirror_on)
        self.coord._handback_to_orbit("p0")
        self.assertTrue(self.coord.mirror_on)


if __name__ == "__main__":
    unittest.main()
