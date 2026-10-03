"""Short commands for the coordinator's control port (UDP 47813). Run with no arguments for help."""
import json
import socket
import sys
from pathlib import Path

HELP = """usage: python tools/cctl.py <command> [args]

  status                      coordinator status (mode, anchor, warp, vessel)
  warp <rate>                 game-time multiplier, e.g. warp 30, warp 100
  pause | resume
  map on|off                  KSP map view
  mirror on|off               copy the NMS ship into KSP (on by default with --ksp)
  burn <prograde> [normal] [radial]     instant burn now, m/s
  plan <from> <to>            find the next transfer window, e.g. plan p1 p2
  node <ut> <prograde> [normal] [radial]  add a maneuver node (shows in KSP map)
  plannode <from> <to>        plan, then add the window's node in one step
  exec [index]                execute a node (arms itself if its time is ahead)
  land <body>                 powered descent to the surface, e.g. land p2
  launch <body> [alt_m]       gravity turn back to a circular orbit
  raw '<json>'                send any message as-is
"""


def send(msg):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(5)
    s.sendto(json.dumps(msg).encode(), ("127.0.0.1", 47813))
    try:
        return json.loads(s.recv(65535))
    except socket.timeout:
        return {"error": "no reply - is the coordinator running?"}


def floats(words, n):
    vals = [float(w) for w in words] + [0.0] * n
    return vals[:n]


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return
    cmd, args = argv[0], argv[1:]
    if cmd == "status":
        path = Path(__file__).resolve().parent.parent / "state" / "status.json"
        print(path.read_text() if path.exists() else '{"error": "no state/status.json yet"}')
        return
    if cmd == "warp":
        msg = {"t": "warp", "warp": float(args[0])}
    elif cmd in ("pause", "resume"):
        msg = {"t": cmd}
    elif cmd == "map":
        msg = {"t": "map", "on": (args[0] if args else "on") != "off"}
    elif cmd == "mirror":
        msg = {"t": "mirror", "on": (args[0] if args else "on") != "off"}
    elif cmd == "burn":
        p, n, r = floats(args, 3)
        msg = {"t": "burn", "prograde": p, "normal": n, "radial": r}
    elif cmd == "plan":
        msg = {"t": "plan_transfer", "from": args[0], "to": args[1]}
    elif cmd == "node":
        ut, p, n, r = floats(args, 4)
        msg = {"t": "add_node", "ut": ut, "prograde": p, "normal": n, "radial": r}
    elif cmd == "plannode":
        plan = send({"t": "plan_transfer", "from": args[0], "to": args[1]})
        print(json.dumps(plan, indent=1))
        node = (plan.get("transfer") or {}).get("node")
        if not node:
            return
        msg = {"t": "add_node", **{k: node[k] for k in ("ut", "prograde", "normal", "radial")}}
    elif cmd == "exec":
        msg = {"t": "execute_node", "index": int(args[0]) if args else 0}
    elif cmd == "land":
        msg = {"t": "land", "body": args[0]}
    elif cmd == "launch":
        msg = {"t": "launch", "body": args[0]}
        if len(args) > 1:
            msg["alt_m"] = float(args[1])
    elif cmd == "raw":
        msg = json.loads(args[0])
    else:
        print(HELP)
        return
    print(json.dumps(send(msg), indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
