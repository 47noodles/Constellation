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

## Tests

`python -m unittest discover -s tests -t .` (19 tests).

## Rebuild the KSP plugin

`dotnet "C:\Program Files\dotnet\sdk\8.0.419\Roslyn\bincore\csc.dll" @ksp/build.rsp`
from `ksp/` (compiles against KSP's own Managed DLLs; no NuGet), then copy
`ksp/build/ConstellationKSP.dll` to KSP's `GameData/Constellation/Plugins/` and restart KSP.
