"""Gate test 2b: move the player ship by its scene node instead of its physics body.

No hooks: commands run on the game thread through ctl_player's UDP channel.
Load:  python spikes/nms/ctl.py loadmod ctl_pose.py
  pose info            ship node handle, ship and player positions
  pose up <m>          Engine.ShiftAllTransformsForNode(ship node, up * m)
  pose shift <x y z>   shift by a world vector
Reading the position again on later frames (pose info) shows whether physics
keeps the move or snaps the ship back.
"""

import builtins
import ctypes
import logging
import struct

from pymhf import Mod

import nmspy.data.basic_types as basic
from nmspy.common import gameData
from nmspy.engine import GetNodeAbsoluteTransMatrix, ShiftAllTransformsForNode

logger = logging.getLogger("ctl_pose")


def _pos(m):
    return [round(m.pos.x, 2), round(m.pos.y, 2), round(m.pos.z, 2)]


class CtlPose3(Mod):
    __author__ = "Constellation"
    __description__ = "Gate test 2b: move the ship's scene node"

    def __init__(self):
        super().__init__()
        builtins._constellation_pose = self
        logger.info("pose mod loaded")

    def _ships(self):
        gs = gameData.game_state
        if gs is None:
            return []
        out = []
        for i, sd in enumerate(gs.mPlayerShipOwnership.mShips):
            try:
                m = GetNodeAbsoluteTransMatrix(sd.mPlayerShipNode)
            except Exception:  # noqa: BLE001 - empty slots may hold junk handles
                continue
            out.append((i, sd.mPlayerShipNode, m, bool(sd.mbUnknown0x28)))
        return out

    def _ship_node(self):
        """The owned ship nearest the player: the one being flown."""
        player = gameData.player
        ships = [s for s in self._ships() if s[3]]
        if not ships:
            return None
        if player is None:
            return ships[0][1]
        p = GetNodeAbsoluteTransMatrix(player.mRootNode).pos

        def d(s):
            q = s[2].pos
            return (q.x - p.x) ** 2 + (q.y - p.y) ** 2 + (q.z - p.z) ** 2

        return min(ships, key=d)[1]

    def _info(self):
        node = self._ship_node()
        out = {"ship_node": None if node is None else repr(node),
               "owned_ships": [[i, _pos(m), valid] for i, _, m, valid in self._ships()]}
        if node is not None:
            m = GetNodeAbsoluteTransMatrix(node)
            out["ship_pos"] = _pos(m)
            out["ship_up"] = [round(m.up.x, 3), round(m.up.y, 3), round(m.up.z, 3)]
        player = gameData.player
        if player is not None:
            out["player_pos"] = _pos(GetNodeAbsoluteTransMatrix(player.mRootNode))
        return out


    def _scan(self, words):
        """Find the ship's position inside its spaceship and physics components.

        Looks for float32 and float64 triples within 3 m of the ship node's
        current absolute position. Addresses come from ctl_diag's capture.
        """
        diag = getattr(builtins, "_constellation_diag", None)
        if diag is None or not diag.ship_bodies:
            return {"error": "run: diag 2   (while flying) first"}
        node = self._ship_node()
        if node is None:
            return {"error": "no ship node"}
        p = GetNodeAbsoluteTransMatrix(node).pos
        target = (p.x, p.y, p.z)
        hits = []
        for ship_addr, (phys_addr, _rb) in diag.ship_bodies.items():
            for label, base, size in (("ship", ship_addr, 0x7400), ("phys", phys_addr, 0x2000)):
                if not base:
                    continue
                buf = ctypes.string_at(base, size)
                for off in range(0, size - 12, 4):
                    x, y, z = struct.unpack_from("<fff", buf, off)
                    if abs(x - target[0]) < 3 and abs(y - target[1]) < 3 and abs(z - target[2]) < 3:
                        hits.append([label, hex(off), "f32", [round(x, 2), round(y, 2), round(z, 2)]])
                for off in range(0, size - 24, 8):
                    x, y, z = struct.unpack_from("<ddd", buf, off)
                    if abs(x - target[0]) < 3 and abs(y - target[1]) < 3 and abs(z - target[2]) < 3:
                        hits.append([label, hex(off), "f64", [round(x, 2), round(y, 2), round(z, 2)]])
        return {"ship_pos": [round(c, 2) for c in target], "hits": hits[:40], "n_hits": len(hits)}

    def handle(self, words):
        sub = words[0] if words else "info"
        if sub == "info":
            return self._info()
        if sub == "scan":
            return self._scan(words[1:])
        node = self._ship_node()
        if node is None:
            return {"error": "no game state / ship node"}
        if sub == "up":
            metres = float(words[1]) if len(words) > 1 else 5.0
            m = GetNodeAbsoluteTransMatrix(node)
            shift = basic.Vector3f(m.up.x * metres, m.up.y * metres, m.up.z * metres)
        elif sub == "shift" and len(words) >= 4:
            shift = basic.Vector3f(float(words[1]), float(words[2]), float(words[3]))
        else:
            return {"error": f"unknown pose command {sub!r}"}
        before = self._info()
        ShiftAllTransformsForNode(node, shift)
        after = self._info()
        logger.info(f"shift {shift.x:.2f},{shift.y:.2f},{shift.z:.2f}: before={before} after={after}")
        return {"ok": True, "before": before, "after_same_frame": after}
