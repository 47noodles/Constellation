"""Messages between the coordinator and game adapters (v0: JSON over local UDP).

One datagram per message. Every message has "t" (type) and "seq". Receivers
keep only the newest "seq" per sender, so a lost or reordered datagram is
harmless: each message carries complete state, never a delta.

NMS adapter -> coordinator (port NMS_STATE_PORT):
    {"t": "nms_state", "seq": int, "sys": str, "frame_ms": float,
     "player": [x, y, z], "applied_game_t": float | null,
     "planets": [{"slot": int, "pos": [x, y, z], "home": [x, y, z]}]}
    "sys" identifies the star system (NMS universe address as hex); it
    changes on warp. "home" is where NMS generated the planet, captured the
    first time the adapter saw the system.

coordinator -> NMS adapter (port NMS_CMD_PORT):
    {"t": "nms_targets", "seq": int, "sys": str, "game_t": float, "warp": float,
     "targets": {"<slot>": [x, y, z]}, "vel_per_real_s": {"<slot>": [vx, vy, vz]}}
    Absolute NMS positions at send time, plus velocity per real second (warp
    already applied) so the adapter can extrapolate between messages. The
    adapter ignores targets for another "sys".
    Optional "ship": {"body": id, "pos": [x, y, z], "vel_per_real_s": [...],
    "alt_m": float}: where the ship KSP is flying should be drawn in NMS.
"""

from __future__ import annotations

import json
import socket

HOST = "127.0.0.1"
NMS_CMD_PORT = 47811  # coordinator -> NMS adapter
NMS_STATE_PORT = 47812  # NMS adapter -> coordinator
MAX_DATAGRAM = 65000


def encode(msg: dict) -> bytes:
    data = json.dumps(msg, separators=(",", ":")).encode()
    if len(data) > MAX_DATAGRAM:
        raise ValueError(f"message too large for one datagram: {len(data)} bytes")
    return data


def decode(data: bytes) -> dict:
    return json.loads(data.decode("utf-8"))


def udp_socket(bind_port: int | None = None, blocking: bool = False) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if bind_port is not None:
        s.bind((HOST, bind_port))
    s.setblocking(blocking)
    return s


def drain_latest(sock: socket.socket, msg_type: str) -> dict | None:
    """Read everything waiting and return the newest message of a type."""
    latest = None
    while True:
        try:
            data, _ = sock.recvfrom(MAX_DATAGRAM)
        except (BlockingIOError, InterruptedError):
            return latest
        except ConnectionResetError:  # Windows reports ICMP port unreachable here
            continue
        try:
            msg = decode(data)
        except (ValueError, UnicodeDecodeError):
            continue
        if msg.get("t") == msg_type and (latest is None or msg.get("seq", 0) >= latest.get("seq", 0)):
            latest = msg
