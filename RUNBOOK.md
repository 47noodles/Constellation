# Constellation runbook

How to run what exists so far. Everything lives in `C:\Projects\Constellation`; the
Python venv is `.venv` (Python 3.12, pyMHF 0.2.4, NMS.py 180383).

## Pieces

| Piece | Where | Talks on |
|---|---|---|
| Coordinator (clock, orbits, anchor frames, KSP link) | `constellation/` | UDP 47812 in (NMS state), 47811 out (NMS targets), 47813 control, 47821 to KSP |
| NMS adapter (pyMHF mod) | `adapters/nms/constellation_nms.py` (copied into `spikes/nms/mods/` to load) | 47811 / 47812 |
| NMS test channel + probes | `spikes/nms/mods/ctl_*.py`, client `spikes/nms/ctl.py` | UDP 47801 |
| KSP plugin | `ksp/ConstellationKSP/Bridge.cs`, installed to KSP `GameData/Constellation/Plugins/` | UDP 47821, client `spikes/ksp/kctl.py` |
| Stand-in NMS (no game needed) | `constellation/fake_nms.py` | 47811 / 47812 |

## Run the coordinator with KSP and the stand-in NMS (no NMS needed)

1. KSP auto-loads the test save only while `GameData/Constellation/autoload.txt` exists
   (first line: `constellation_spike`). Copy `saves/scenarios/Mun Orbit.sfs` to
   `saves/constellation_spike/persistent.sfs` for a fresh start. Start KSP small:
   `KSP_x64.exe -popupwindow -screen-width 1024 -screen-height 640`.
2. When the plugin answers (`python spikes/ksp/kctl.py info`):
   `kctl.py ui hide whatsNew`, then `kctl.py warp 2` (vessels must be on rails).
3. `python -m constellation.fake_nms state/systems/00013a000355e47f.json`
4. `python -m constellation.coordinator --warp 30 --ksp` (syncs KSP on start).
5. `kctl.py setvessel Kerbin 200000` puts the vessel in orbit around the Kerbin slot
   (= NMS planet 1) after the sync.
6. Status: `state/status.json`. Control (UDP 47813, JSON): `{"t":"warp","warp":100}`,
   `{"t":"pause"}`, `{"t":"resume"}`, `{"t":"map","on":true}`,
   `{"t":"burn","prograde":50}`.

## Drive the transfer / land / launch scenario from the control port

The coordinator owns the whole scenario in `docs/transfer-land-design.md` §6.
Send one JSON datagram per message to UDP `127.0.0.1:47813` and read the reply.
A one-off client:

```python
import json, socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(3)
def ctl(msg):
    s.sendto(json.dumps(msg).encode(), ("127.0.0.1", 47813))
    return json.loads(s.recv(65535))
print(ctl({"t": "plan_transfer", "from": "p1", "to": "p2"}))
```

| Message | Fields | Reply |
|---|---|---|
| `plan_transfer` | `from`, `to` (body ids), `t0` (s, opt), `span` (s, opt), `search` (bool, opt) | `transfer` = `{depart_ut, arrive_ut, node:{index,ut,prograde,normal,radial}, dv_arrive, c3}` |
| `add_node` | `ut`, `prograde`, `normal`, `radial` | `node` = `{index,ut,prograde,normal,radial}` (also appears in KSP's map) |
| `execute_node` | `index` (opt, default 0) | `{ok, burn_ut, dv:[p,n,r]}`; `scheduled:true` when it arms for a later tick |
| `land` | `body`, `touchdown_speed` (m/s, opt) | `{ok, mode:"flight"}`; suicide burn until touchdown |
| `launch` | `body`, `alt_m` (m, opt) | `{ok, mode:"flight"}`; gravity turn to a circular orbit |

Typical live run (step 4 above with `--ksp`):

1. `plan_transfer` from the body you are orbiting to the target. `node.ut` is the
   window's departure UT; `dv_arrive` is the capture burn at the far end.
2. `add_node` with the four `node` fields; confirm the node appears in KSP's map.
3. When game time reaches `node.ut`, `execute_node` fires the existing `burn`
   with the node's components. (`execute_node` schedules for you if the UT is
   still ahead.) `state/status.json` then shows `mode` and `anchor`.
4. Watch the vessel cross into the target's SOI. `mode` stays `"orbit"` while
   KSP is on rails. Send `land` to hand the vessel to the coordinator's powered
   flight (`mode:"flight"`); it descends under `flight.suicide_burn_guidance`
   and stops in a landed state.
5. Send `launch` to run `flight.gravity_turn_guidance` up to `alt_m`; on
   reaching it the coordinator writes the circular state back to KSP with
   `vesselstate setc` and returns to `mode:"orbit"`.

## Not yet verified without a live KSP and NMS

The offline suite (`tests/test_scenario.py`) exercises the whole flow through
fake endpoints and the real orbit/patched/flight modules. These still need a
live run:

* KSP plugin `addnode`/`clearnodes`/`readnodes` and the map view rendering the
  node (the C# is written, not yet flown).
* `vesselstate setc` handback on ascent actually matching the coordinator's
  circular state (the node/capture path round-trip is committed, the ascent one
  is not).
* NMS adapter `mode:"flight"`: `cGcPlayer.SetToPosition` posing the player and
  the `pose.forward` facing; the proven `GetVelocity` ban still holds.
* Surface height: the terrain callback defaults to flat (`body.radius`); the
  NMS-authoritative surface approximation from `research nms-control.md` is not
  wired in.
* Lambert `revolutions != 0` and non-coplanar transfers (the Hohmann/Lambert
  path assumes coplanar circular orbits).
* Real vehicle numbers: `DEFAULT_VEHICLE` is a test stage, not a tuned craft.

## Tests

`python -m unittest discover -s tests -t .` (80 tests, including the fake-KSP /
fake-NMS `tests/test_scenario.py`).

## Run with the real No Man's Sky

1. Launch NMS through pyMHF only (never from Steam, or the hooks are missing):
   `python spikes/nms/run_pymhf.py` (hidden, logs to `spikes/nms/logs/`). If NMS is
   already running it attaches instead, but player reads stay empty.
2. Load your save. Keep NMS focused: it pauses when it loses focus.
3. `python spikes/nms/ctl.py loadmod constellation_nms.py` (copy the adapter into
   `spikes/nms/mods/` first; give a changed copy a new file and class name, because
   pyMHF's reload leaves the old copy's hooks running).
4. Start the coordinator (step 4 above, with or without `--ksp`).

16 GB is not enough for NMS and KSP together; tonight's KSP work ran with NMS closed.

## Rebuild the KSP plugin

`dotnet "C:\Program Files\dotnet\sdk\8.0.419\Roslyn\bincore\csc.dll" @ksp/build.rsp`
from `ksp/` (compiles against KSP's own Managed DLLs; no NuGet), then copy
`ksp/build/ConstellationKSP.dll` to KSP's `GameData/Constellation/Plugins/` and restart KSP.
