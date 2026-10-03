"""Live probe: does the engine write the flying player ship's node through
cEgSceneNodeData.SetRelativeTransform, and does overriding that matrix move it?

No physics calls: never GetVelocity or SetLinearVelocity. The whole point is to
find out whether the per-frame scene-node write is the path the engine uses for
the ship, and whether rewriting its relative translation (before the engine
applies it) moves a flying ship.

Load it after ctl_player.py, then drive it through ctl_player's UDP channel:
    python spikes/nms/ctl.py loadmod ctl_srt.py
    python spikes/nms/ctl.py srt status
    python spikes/nms/ctl.py srt census on          # start counting calls
    python spikes/nms/ctl.py srt census off
    python spikes/nms/ctl.py srt target 0 5000 0    # absolute position to hold
    python spikes/nms/ctl.py srt mode override      # rewrite the ship node each write
    python spikes/nms/ctl.py srt mode off

`status` reports calls_total / calls_ship over the census window, the frame
count, the last relative translation the game wrote for the ship handle
(last_written_ship_pos), the ship's absolute node position (ship_abs_pos), the
mode, the target and last_error. Compare relative vs absolute: if calls_ship is
nonzero the engine does write the ship node this way.
"""

import builtins
import ctypes
import logging

from pymhf import Mod

import nmspy.data.basic_types as basic
import nmspy.data.types as nms
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix

try:  # the in-game mod dir may not have the repo on sys.path
    from adapters.nms.transforms import override_relative_pos as _override_relative_pos
except Exception:  # noqa: BLE001

    def _override_relative_pos(target, written_rel, current_abs):
        return (
            target[0] - (current_abs[0] - written_rel[0]),
            target[1] - (current_abs[1] - written_rel[1]),
            target[2] - (current_abs[2] - written_rel[2]),
        )


logger = logging.getLogger("ctl_srt")


def _pos_of(node):
    m = GetNodeAbsoluteTransMatrix(node)
    return (m.pos.x, m.pos.y, m.pos.z)


class CtlSrt(Mod):
    __author__ = "Constellation"
    __description__ = "Probe: cEgSceneNodeData.SetRelativeTransform call census and ship override"

    def __init__(self):
        super().__init__()
        builtins._constellation_srt = self
        builtins._constellation_srt_gen = id(self)
        self.mode = "off"  # off | override
        self.census = False
        self.target = None  # (x, y, z) absolute
        self.calls_total = 0
        self.calls_ship = 0
        self.frame_calls = 0
        self.frame_calls_ship = 0
        self.frames_seen = 0
        self._ship_lookup = None
        self.last_written_ship_pos = None
        self.ship_abs_pos = None
        self.last_error = None
        logger.info("srt probe loaded")

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

    def _read_ship_abs(self):
        node = self._ship_node()
        if node is None:
            return None
        try:
            return _pos_of(node)
        except Exception as e:  # noqa: BLE001
            self.last_error = repr(e)
            return None

    def _status(self):
        return {
            "mode": self.mode,
            "census": self.census,
            "target": None if self.target is None else list(self.target),
            "calls_total": self.calls_total,
            "calls_ship": self.calls_ship,
            "frames_seen": self.frames_seen,
            "frame_calls": self.frame_calls,
            "frame_calls_ship": self.frame_calls_ship,
            "ship_lookup": self._ship_lookup,
            "last_written_ship_pos": self.last_written_ship_pos,
            "ship_abs_pos": self.ship_abs_pos,
            "last_error": self.last_error,
        }

    def handle(self, words):
        sub = words[0] if words else "status"
        if sub in ("status", "st"):
            return self._status()
        if sub == "census":
            on = len(words) < 2 or words[1] == "on"
            self.census = on
            if on:
                self.calls_total = 0
                self.calls_ship = 0
                self.frame_calls = 0
                self.frame_calls_ship = 0
                self.frames_seen = 0
                self.last_written_ship_pos = None
            return {"ok": True, "status": self._status()}
        if sub == "target" and len(words) >= 4:
            try:
                self.target = tuple(float(w) for w in words[1:4])
            except ValueError:
                return {"error": "target x y z must be numbers"}
            return {"ok": True, "target": list(self.target)}
        if sub == "mode" and len(words) >= 2:
            mode = words[1]
            if mode not in ("off", "override"):
                return {"error": f"mode must be off or override, got {mode!r}"}
            self.mode = mode
            return {"ok": True, "mode": mode,
                    "target": None if self.target is None else list(self.target)}
        return {"error": f"unknown srt command {sub!r}"}

    @nms.cEgSceneNodeData.SetRelativeTransform.before
    def on_set_relative_transform(self, this, lHandle, lValue):
        try:
            if getattr(builtins, "_constellation_srt_gen", None) != id(self):
                return  # a newer copy of this mod is loaded
            try:
                lookup = lHandle.lookupInt
            except Exception:  # noqa: BLE001 - junk handle
                lookup = None
            is_ship = (lookup is not None and self._ship_lookup is not None
                       and lookup == self._ship_lookup)
            want_override = self.mode == "override" and self.target is not None and is_ship
            if not (self.census or want_override) or not lValue:
                return
            m = lValue.contents
            if self.census:
                self.calls_total += 1
                self.frame_calls += 1
                if is_ship:
                    self.calls_ship += 1
                    self.frame_calls_ship += 1
                    self.last_written_ship_pos = [m.pos.x, m.pos.y, m.pos.z]
            if want_override:
                written = (m.pos.x, m.pos.y, m.pos.z)
                absp = self.ship_abs_pos
                if absp is None:
                    absp = self._read_ship_abs()
                if absp is not None:
                    new = _override_relative_pos(self.target, written, absp)
                    m.pos.x, m.pos.y, m.pos.z = new[0], new[1], new[2]
        except Exception as e:  # noqa: BLE001 - report, never raise inside a hook
            self.last_error = repr(e)

    @nms.cGcApplication.Update.after
    def on_frame(self, this):
        if getattr(builtins, "_constellation_srt_gen", None) != id(self):
            return
        self.frames_seen += 1
        self.frame_calls = 0
        self.frame_calls_ship = 0
        try:
            node = self._ship_node()
            if node is None:
                self._ship_lookup = None
                self.ship_abs_pos = None
            else:
                self._ship_lookup = int(node.lookupInt)
                self.ship_abs_pos = list(_pos_of(node))
        except Exception as e:  # noqa: BLE001
            self.last_error = repr(e)
