"""Gate test 1: can an external driver set the NMS player's position every frame?

Buttons in the pyMHF GUI:
  * Capture       - record the player's current position as the circle centre.
  * Nudge up 2 m  - one SetToPosition call, 2 m along the player's up axis.
  * Start circle  - every frame, SetToPosition along a 3 m circle (10 s period).
  * Stop circle
Every 5 s it logs frame-time stats and, while circling, how far the player
ended up from where we put them on the previous frame (does NMS fight us?).
Results also go to spikes/nms/logs/ctl_player.csv.
"""

import csv
import ctypes
import math
import os
import time
from logging import getLogger

from pymhf import Mod
from pymhf.gui.decorators import gui_button

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix

logger = getLogger("ctl_player")

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
RADIUS_M = 3.0
PERIOD_S = 10.0


def _v(x, y, z):
    return basic.Vector3f(x, y, z)


class CtlPlayer(Mod):
    __author__ = "Constellation"
    __description__ = "Gate test 1: per-frame player position override"

    def __init__(self):
        super().__init__()
        self.center = None
        self.up = None
        self.right = None
        self.at = None
        self.circling = False
        self.t0 = 0.0
        self.last_target = None
        self.errors = []
        self.frame_dts = []
        self.last_frame = None
        self.last_report = time.perf_counter()
        os.makedirs(LOG_DIR, exist_ok=True)
        self.csv = open(os.path.join(LOG_DIR, "ctl_player.csv"), "a", newline="")
        self.out = csv.writer(self.csv)
        self.out.writerow(["t", "event", "frame_ms_mean", "frame_ms_p95", "err_m_mean", "err_m_max", "note"])

    # ---- helpers -----------------------------------------------------------
    def _matrix(self):
        player = gameData.player
        if player is None:
            return None
        return GetNodeAbsoluteTransMatrix(player.mRootNode)

    def _set(self, x, y, z):
        player = gameData.player
        if player is None or self.at is None:
            return False
        pos = basic.cTkBigPos(_v(x, y, z), _v(0, 0, 0))
        direction = _v(self.at.x, self.at.y, self.at.z)
        vel = _v(0, 0, 0)
        player.SetToPosition(ctypes.byref(pos), ctypes.byref(direction), ctypes.byref(vel))
        return True

    def _row(self, event, note="", fm=0.0, fp=0.0, em=0.0, ex=0.0):
        self.out.writerow([f"{time.time():.3f}", event, f"{fm:.2f}", f"{fp:.2f}", f"{em:.3f}", f"{ex:.3f}", note])
        self.csv.flush()

    # ---- GUI ---------------------------------------------------------------
    @gui_button("Capture position")
    def capture(self):
        m = self._matrix()
        if m is None:
            logger.warning("No player yet - load into the game first")
            return
        self.center = (m.pos.x, m.pos.y, m.pos.z)
        self.up, self.right, self.at = m.up, m.right, m.at
        msg = f"centre={self.center} up=({m.up.x:.2f},{m.up.y:.2f},{m.up.z:.2f})"
        logger.info("Captured " + msg)
        self._row("capture", msg)

    @gui_button("Nudge up 2 m (once)")
    def nudge(self):
        self.capture()
        if self.center is None:
            return
        cx, cy, cz = self.center
        target = (cx + 2 * self.up.x, cy + 2 * self.up.y, cz + 2 * self.up.z)
        try:
            self._set(*target)
        except Exception as e:  # noqa: BLE001 - report anything the call raises
            logger.exception("SetToPosition failed")
            self._row("nudge_error", repr(e))
            return
        after = self._matrix()
        note = f"target={target} after_call=({after.pos.x:.2f},{after.pos.y:.2f},{after.pos.z:.2f})"
        logger.info("Nudge " + note)
        self._row("nudge", note)

    @gui_button("Start circle")
    def start(self):
        self.capture()
        if self.center is None:
            return
        self.t0 = time.perf_counter()
        self.errors.clear()
        self.last_target = None
        self.circling = True
        self._row("start")

    @gui_button("Stop circle")
    def stop(self):
        self.circling = False
        self._row("stop")
        logger.info("Circle stopped")

    # ---- per frame ---------------------------------------------------------
    @nms.cGcApplication.Update.after
    def on_frame(self, this):
        now = time.perf_counter()
        if self.last_frame is not None:
            self.frame_dts.append((now - self.last_frame) * 1000.0)
        self.last_frame = now

        if self.circling:
            m = self._matrix()
            if m is not None and self.last_target is not None:
                tx, ty, tz = self.last_target
                self.errors.append(math.dist((m.pos.x, m.pos.y, m.pos.z), (tx, ty, tz)))
            a = 2 * math.pi * (now - self.t0) / PERIOD_S
            cx, cy, cz = self.center
            r, f = self.right, self.at
            target = (
                cx + RADIUS_M * (math.cos(a) * r.x + math.sin(a) * f.x),
                cy + RADIUS_M * (math.cos(a) * r.y + math.sin(a) * f.y),
                cz + RADIUS_M * (math.cos(a) * r.z + math.sin(a) * f.z),
            )
            try:
                self._set(*target)
                self.last_target = target
            except Exception as e:  # noqa: BLE001
                self.circling = False
                logger.exception("SetToPosition failed during circle; stopped")
                self._row("circle_error", repr(e))

        if now - self.last_report >= 5.0 and self.frame_dts:
            dts = sorted(self.frame_dts)
            fm = sum(dts) / len(dts)
            fp = dts[int(0.95 * (len(dts) - 1))]
            em = sum(self.errors) / len(self.errors) if self.errors else 0.0
            ex = max(self.errors) if self.errors else 0.0
            logger.info(
                f"frames={len(dts)} mean={fm:.1f}ms p95={fp:.1f}ms"
                + (f" | drift mean={em:.3f}m max={ex:.3f}m" if self.circling else "")
            )
            self._row("stats", "circling" if self.circling else "idle", fm, fp, em, ex)
            self.frame_dts.clear()
            self.errors.clear()
            self.last_report = now
