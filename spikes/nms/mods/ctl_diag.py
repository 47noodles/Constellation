"""Diagnostic: who calls cTkRigidBody.SetLinearVelocity, and is the ship's body one of them?

Load:  python spikes/nms/ctl.py loadmod ctl_diag.py
Then:  python spikes/nms/ctl.py diag      (starts a 5 s capture, returns the last result)
The ship mod (ctl_ship2) records the rigid-body address it writes to; this mod
counts every SetLinearVelocity call by target address so we can see whether the
game itself writes that body each frame (overwriting us) or never touches it.
"""

import builtins
import ctypes
import logging
import time

from pymhf import Mod

import nmspy.data.types as nms

logger = logging.getLogger("ctl_diag")


class CtlDiag(Mod):
    __author__ = "Constellation"
    __description__ = "SetLinearVelocity call census"

    def __init__(self):
        super().__init__()
        self.until = 0.0
        self.calls = {}
        self.ship_bodies = {}
        self.result = None
        builtins._constellation_diag = self

    def handle(self, words):
        if words and words[0] == "result":
            return {"capturing": bool(self.until), "result": self.result}
        if words and words[0] == "override":
            # override freeze|cruise|off [secs] [lo hi]: rewrite the velocity argument of the
            # game's own SetLinearVelocity calls for bodies in [lo, hi) (hex), default: the
            # 64 KB after the ship's physics component.
            mode = words[1] if len(words) > 1 else "freeze"
            secs = float(words[2]) if len(words) > 2 else 6.0
            if mode == "off":
                self.ov_until = 0.0
                return {"ok": True, "override": "off", "hits": getattr(self, "ov_hits", {})}
            phys = [v[0] for v in self.ship_bodies.values() if v[0]]
            if len(words) > 4:
                lo, hi = int(words[3], 16), int(words[4], 16)
            elif phys:
                lo, hi = phys[0], phys[0] + 0x10000
            else:
                return {"error": "run 'diag 2' while in the ship first to find its physics component"}
            self.ov_mode, self.ov_lo, self.ov_hi = mode, lo, hi
            self.ov_hits = {}
            self.ov_until = time.perf_counter() + secs
            return {"ok": True, "override": mode, "range": [hex(lo), hex(hi)], "secs": secs}
        return self.start(float(words[0]) if words else 5.0)

    def start(self, secs=5.0):
        self.calls = {}
        self.ship_bodies = {}
        self.until = time.perf_counter() + secs
        return {"ok": True, "capturing_s": secs, "previous": self.result}

    @nms.cTkRigidBody.SetLinearVelocity.before
    def on_set_vel(self, this, lVelocity, a3):
        ov_until = getattr(self, "ov_until", 0.0)
        if ov_until:
            if time.perf_counter() > ov_until:
                self.ov_until = 0.0
                logger.info(f"override done, hits={self.ov_hits}")
            else:
                addr = ctypes.cast(this, ctypes.c_void_p).value
                if self.ov_lo <= addr < self.ov_hi:
                    v = lVelocity.contents
                    if self.ov_mode == "freeze":
                        v.x, v.y, v.z = 0.0, 0.0, 0.0
                    elif self.ov_mode == "cruise":
                        v.x, v.y, v.z = 0.0, 0.0, 60.0
                    self.ov_hits[hex(addr)] = self.ov_hits.get(hex(addr), 0) + 1
        if not self.until:
            return
        if time.perf_counter() > self.until:
            self._finish()
            return
        addr = ctypes.cast(this, ctypes.c_void_p).value
        self.calls[addr] = self.calls.get(addr, 0) + 1

    @nms.cGcSpaceshipComponent.UpdateControlled.after
    def on_ship(self, this, lfTimeStep):
        if not self.until:
            return
        ship_addr = ctypes.cast(this, ctypes.c_void_p).value
        try:
            rb = this.contents.mpPhysics.contents.mRigidBody
            rb_addr = ctypes.addressof(rb)
            phys_addr = ctypes.cast(this.contents.mpPhysics, ctypes.c_void_p).value
        except ValueError:
            rb_addr = phys_addr = None
        self.ship_bodies[ship_addr] = (phys_addr, rb_addr)

    def _finish(self):
        self.until = 0.0
        top = sorted(self.calls.items(), key=lambda kv: -kv[1])[:8]
        ships = {hex(k): [hex(v[0]) if v[0] else None, hex(v[1]) if v[1] else None]
                 for k, v in self.ship_bodies.items()}
        ship_rbs = {v[1] for v in self.ship_bodies.values() if v[1]}
        self.result = {
            "distinct_bodies": len(self.calls),
            "total_calls": sum(self.calls.values()),
            "top_targets": [[hex(a), n, a in ship_rbs] for a, n in top],
            "ship_component -> [physics, rigid_body]": ships,
            "game_writes_ship_body": any(a in ship_rbs for a in self.calls),
        }
        logger.info(f"diag: {self.result}")
