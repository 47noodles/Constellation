"""A stand-in for the NMS adapter (SkyCraft's lesson: build a fake peer per game).

Speaks the real protocol: reports a player and planets at ~30 Hz on
NMS_STATE_PORT, and applies the coordinator's targets to its own planet list,
exactly as the pyMHF adapter does. Lets the coordinator, and KSP behind it,
run end to end without No Man's Sky running.

    python -m constellation.fake_nms state/systems/<sys>.json [--sys KEY] [--player-slot 1]
"""

from __future__ import annotations

import argparse
import json
import math
import time

from . import protocol


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("planets")
    ap.add_argument("--sys", default="00013a000355e47f")
    ap.add_argument("--player-slot", type=int, default=1, help="stand 130 km from this planet's centre")
    ap.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = forever)")
    args = ap.parse_args()
    with open(args.planets, encoding="utf-8") as f:
        planets = {p["slot"]: {"home": list(p["home"]), "pos": list(p["home"])} for p in json.load(f)}
    home = planets[args.player_slot]["home"]
    player = [home[0], home[1] + 130_000.0, home[2]]
    out = protocol.udp_socket()
    cmd = protocol.udp_socket(protocol.NMS_CMD_PORT)
    seq, started, applied = 0, time.monotonic(), 0
    while not args.seconds or time.monotonic() - started < args.seconds:
        msg = protocol.drain_latest(cmd, "nms_targets")
        if msg is not None and msg.get("sys") == args.sys:
            for slot, target in msg["targets"].items():
                if int(slot) in planets:
                    planets[int(slot)]["pos"] = list(target)
                    applied += 1
            # the player stands on the anchor: keep them on whatever planet they were on
            here = planets[args.player_slot]["pos"]
            player = [here[0], here[1] + 130_000.0, here[2]]
        seq += 1
        state = {"t": "nms_state", "seq": seq, "sys": args.sys, "frame_ms": 33.3, "player": player,
                 "applied_game_t": msg.get("game_t") if msg else None,
                 "planets": [{"slot": s, "pos": p["pos"], "home": p["home"]} for s, p in planets.items()]}
        out.sendto(protocol.encode(state), (protocol.HOST, protocol.NMS_STATE_PORT))
        if seq % 300 == 0:
            moved = {s: round(math.dist(p["pos"], p["home"]) / 1000) for s, p in planets.items()}
            ship = msg.get("ship") if msg else None
            ship_txt = ""
            if ship:
                centre = planets[int(ship["body"][1:])]["pos"]
                ship_txt = f" ship around {ship['body']} at {math.dist(ship['pos'], centre) / 1000:.1f} km from its centre (alt {ship['alt_m'] / 1000:.1f} km)"
            print(f"seq {seq} applied {applied} km from home {moved}{ship_txt}", flush=True)
        time.sleep(1 / 30)


if __name__ == "__main__":
    main()
