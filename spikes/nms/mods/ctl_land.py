"""Live probe for the NMS landing/mode work (carry-over gate test).

No hooks into ship physics: it uses the two paths proven to be safe on build
180383 - the ship scene node (Engine.ShiftAllTransformsForNode) for the
on-rails "orbit" mode, and cGcPlayer.SetToPosition for the powered "flight"
mode. It never calls cGcSpaceshipComponent.GetVelocity.

Load it after ctl_player.py, then drive it through ctl_player's UDP channel:
    python spikes/nms/ctl.py loadmod ctl_land.py
    python spikes/nms/ctl.py land status
    python spikes/nms/ctl.py land node
    python spikes/nms/ctl.py land shift 100 0 0        # orbit: shift the ship node once
    python spikes/nms/ctl.py land pose 0 5000 0 0 0 1  # flight: pose the player once
    python spikes/nms/ctl.py land target 0 5000 0 0 0 1
    python spikes/nms/ctl.py land mode flight          # follow the target every frame
    python spikes/nms/ctl.py land mode orbit           # shift the ship node to target every frame
    python spikes/nms/ctl.py land mode off

Expected live results (to be confirmed by a human with NMS open):
* `land shift` / `land mode orbit`: the player's ship visibly moves and stays
  (Run ctl_pose.py's `pose scan` afterwards to check whether physics keeps it).
* `land mode flight`: the player is teleported to the target each frame and the
  reply's player position tracks it; the resulting camera/attitude is judged by
  eye. This mirrors what the adapter does with nms_targets["mode"]="flight".
"""

import builtins
import ctypes
import logging

from pymhf import Mod

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix, ShiftAllTransformsForNode

logger = logging.getLogger("ctl_land")


def _vec3(x, y, z):
    return basic.Vector3f(float(x), float(y), float(z))


def _pos_of(node):
    m = GetNodeAbsoluteTransMatrix(node)
    return (m.pos.x, m.pos.y, m.pos.z)


class CtlLand(Mod):
    __author__ = "Constellation"
    __description__ = "Live probe: ship scene-node shift and player SetToPosition"

    def __init__(self):
        super().__init__()
        builtins._constellation_land = self
        builtins._constellation_land_gen = id(self)
        self.mode = "off"  # off | orbit | flight
        self.target = None  # (x, y, z)
        self.forward = (0.0, 0.0, 1.0)
        self.follow_frames = 0
        self.last_error = None
        logger.info("land probe loaded")

    def _ship_node(self):
        gs = gameData.game_state
        if gs is None:
            return None
        player = gameData.player
        player_pos = None
        if player is not None:
            try:
                player_pos = _pos_of(player.mRootNode)
            except Exception:  # noqa: BLE001
                player_pos = None
        best = None
        best_d = None
        for sd in gs.mPlayerShipOwnership.mShips:
            try:
                if not sd.mbUnknown0x28:
                    continue
                node = sd.mPlayerShipNode
                q = _pos_of(node)
            except Exception:  # noqa: BLE001 - empty slots hold junk handles
                continue
            if player_pos is None:
                return node
            d = (q[0] - player_pos[0]) ** 2 + (q[1] - player_pos[1]) ** 2 + (q[2] - player_pos[2]) ** 2
            if best_d is None or d < best_d:
                best, best_d = node, d
        return best

    def _set_pose(self, pos, forward, vel=(0.0, 0.0, 0.0)):
        player = gameData.player
        if player is None:
            return False
        p = basic.cTkBigPos(_vec3(*pos), basic.cTkVector3(0.0, 0.0, 0.0))
        player.SetToPosition(ctypes.byref(p), ctypes.byref(_vec3(*forward)), ctypes.byref(_vec3(*vel)))
        return True

    def _status(self):
        node = self._ship_node()
        out = {"mode": self.mode, "target": self.target, "follow_frames": self.follow_frames,
               "ship_node": None if node is None else repr(node), "last_error": self.last_error}
        if node is not None:
            out["ship_pos"] = [round(c, 2) for c in _pos_of(node)]
        player = gameData.player
        if player is not None:
            out["player_pos"] = [round(c, 2) for c in _pos_of(player.mRootNode)]
        return out

    def _follow(self):
        if self.target is None:
            return
        try:
            if self.mode == "orbit":
                node = self._ship_node()
                if node is None:
                    return
                cur = _pos_of(node)
                ShiftAllTransformsForNode(node, _vec3(self.target[0] - cur[0], self.target[1] - cur[1],
                                                     self.target[2] - cur[2]))
            elif self.mode == "flight":
                self._set_pose(self.target, self.forward)
            self.follow_frames += 1
        except Exception as e:  # noqa: BLE001 - report, never kill the frame
            self.last_error = repr(e)

    def handle(self, words):
        sub = words[0] if words else "status"
        if sub == "status":
            return self._status()
        if sub == "node":
            return self._status()
        if sub == "shift" and len(words) >= 4:
            node = self._ship_node()
            if node is None:
                return {"error": "no ship node"}
            delta = _vec3(words[1], words[2], words[3])
            ShiftAllTransformsForNode(node, delta)
            return {"ok": True, "delta": [delta.x, delta.y, delta.z], "status": self._status()}
        if sub == "pose" and len(words) >= 4:
            pos = tuple(float(w) for w in words[1:4])
            if len(words) >= 7:
                self.forward = tuple(float(w) for w in words[4:7])
            ok = self._set_pose(pos, self.forward)
            return {"ok": ok, "pos": list(pos), "forward": list(self.forward)}
        if sub == "target" and len(words) >= 4:
            self.target = tuple(float(w) for w in words[1:4])
            if len(words) >= 7:
                self.forward = tuple(float(w) for w in words[4:7])
            return {"ok": True, "target": list(self.target), "forward": list(self.forward)}
        if sub == "mode" and len(words) >= 2:
            self.mode = words[1]
            if self.mode not in ("off", "orbit", "flight"):
                self.mode = "off"
                return {"error": f"mode must be off, orbit or flight, got {words[1]!r}"}
            return {"ok": True, "mode": self.mode, "target": None if self.target is None else list(self.target)}
        return {"error": f"unknown land command {sub!r}"}

    @nms.cGcApplication.Update.after
    def on_frame(self, this):
        if getattr(builtins, "_constellation_land_gen", None) != id(self):
            return  # a newer copy of this mod is loaded
        try:
            self._follow()
        except Exception as e:  # noqa: BLE001
            self.last_error = repr(e)
