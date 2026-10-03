# Constellation

Constellation is a live bridge that blends **Kerbal Space Program 1.12.5** and
**No Man's Sky build 180383** into one pretend solar system. NMS is the game you
look at. KSP runs hidden behind it and supplies the orbital mechanics and the
map. A Python process in the middle owns the universe, the clock and the flight
between orbit and ground.

It is inspired by **chasm's SkyCraft** ([github.com/chasmlol/SkyCraft](https://github.com/chasmlol/SkyCraft)),
which blends Skyrim (as the visible renderer) and Minecraft (hidden, driving
player mechanics) over shared memory. Constellation applies the same idea to two
space games.

This is an unofficial fan project, not affiliated with Squad, Private Division,
Take-Two Interactive or Hello Games.

## The goal experience

You start in orbit of a planet. You open KSP's map, plan a transfer to another
planet and burn in a transfer window. The vessel crosses into the target's sphere
of influence (SOI), you descend and land, and later launch back to orbit. All of
it plays out in the visible No Man's Sky universe, with NMS's planets, stations
and fauna around you, while KSP owns the orbit maths underneath.

## Architecture

Three processes and a Python coordinator:

- **No Man's Sky** is the visible renderer. It draws space, planets, stations and
  fauna, and it is where the player and the ship are shown. A pyMHF/NMS.py mod
  (`adapters/nms/constellation_nms.py`) moves NMS's planets and poses the player
  or ship every rendered frame.
- **Kerbal Space Program** is hidden. A C# KSPAddon plugin
  (`ksp/ConstellationKSP/Bridge.cs`) reshapes KSP's stock bodies to match the
  coordinator's universe, owns the vessel on rails, and shows maneuver nodes in
  KSP's real map view. KSP reads back out the vessel state the coordinator asks
  for.
- **The Python coordinator** (`constellation/`) owns the universe layout, the
  game clock, SOI handovers, transfer planning and powered flight near a surface.
  It converts between KSP's orbital frame, NMS's coordinates and its own orbit
  space, and it is the single source of truth for time.
- **Space Engineers 1** support is planned but deferred. It is not wired up.

Two coordinate spaces are joined by an **anchor**: the body the player is inside
stays fixed in NMS space, and every other body is placed relative to it. When the
player crosses into another SOI the anchor moves to the new body's current NMS
position, so nothing jumps.

```
                     coordinator (Python)
        config/state |  clock | universe | maneuvers | flight
                     |
     +---------------+----------------+
     |               |                |
  UDP 47811       UDP 47813        UDP 47821
  (targets)      (control)        (commands)
     v               |                v
 NMS adapter     (external      KSP plugin
 (pyMHF mod)      clients)      (C# KSPAddon,
     |                            hidden)
     v                               v
 No Man's Sky                   Kerbal Space Program
 (visible renderer)             (orbits + map view)

  NMS adapter -> coordinator: UDP 47812 (player/planet state)
```

UDP ports:

| Port | Direction | Purpose |
|---|---|---|
| 47811 | coordinator -> NMS | planet targets, ship/player pose |
| 47812 | NMS -> coordinator | player and planet state |
| 47813 | external -> coordinator | control (warp, plan_transfer, land, launch, ...) |
| 47821 | coordinator -> KSP | body reshape, warp, map, burn, maneuver nodes |
| 47801 | external -> NMS | NMS test channel used by `spikes/nms/ctl.py` |

## Status

Constellation is an early research project. Be sceptical of anything described
below as "built": most of the flight logic has only been exercised against fake
game endpoints. **Nothing in the transfer / land / launch scenario has been
played live on both real games yet.**

### Live-tested against the real games

- NMS's planets are moved to the coordinator's KSP-style orbits each rendered
  frame (commits `7ab154b`, `554ff7f`).
- Per-frame player position override over the NMS test channel passes
  (commit `611bfad`); the UDP command channel and runtime mod load/unload work
  (commit `0cde8c1`).
- The KSP plugin reshapes a body live (radius, GM, SOI, orbit), with patched
  conics and the map view rendering in a background window (commit `a53580e`).
- The coordinator pushes its system into KSP's body pool and the sync was
  verified to the millimetre (commit `fd235b7`); it slaves KSP's clock every tick
  and forwards the map (commit `37abf8f`).
- The vessel round-trips between coordinator and KSP; a coordinator burn changes
  KSP's vessel velocity in orbital directions; the vessel path runs
  KSP -> coordinator -> NMS position (commits `4472c3a`, `d487ab2`, `ed7cebe`,
  `19dadad`).

### Built, but tested offline only

The whole scenario is exercised in `tests/test_scenario.py` through fake KSP and
fake NMS endpoints, using the real orbit, patched-conic and flight modules. It
has never been flown live. Specifics:

- The scenario snaps to a **20 km circular capture orbit** after SOI entry, and
  to a circular orbit at the end of the ascent, rather than modelling the burns
  continuously.
- KSP's maneuver-node commands (`addnode`, `clearnodes`, `readnodes`) and the map
  drawing the node are written in C# but not yet flown.
- Writing the ascent result back to KSP with `vesselstate setc` is not verified;
  the node/capture path round-trips, the ascent handback does not.
- The NMS adapter's `"flight"` mode (posing the player with
  `cGcPlayer.SetToPosition`) and its NMS ship rendering are unverified.
- Transfers are **Hohmann and coplanar only**. A Lambert solver exists, but
  `revolutions != 0` and non-coplanar transfers are untested.
- Surface height defaults to flat (`body.radius`); the NMS-authoritative surface
  is not wired in.
- `DEFAULT_VEHICLE` is a test stage, not a tuned craft.

### Not started

- A live end-to-end run of the transfer / land / launch scenario on real KSP and
  NMS.
- Space Engineers 1 support (planned, deferred).
- Co-op and networking.

## Requirements

- An owned copy of **Kerbal Space Program 1.12.5** (Windows/Steam).
- An owned copy of **No Man's Sky build 180383**.
- **Windows**.
- **Python** (the runbook uses 3.12 in a `.venv`; NMS.py needs official CPython
  3.9-3.13, not 3.14).
- **pyMHF 0.2.4** and **NMS.py** pinned to the 180383 commit.
- The **.NET SDK** (8.0.x is what the runbook uses) to build the KSP plugin.
- Enough RAM to run both games. The runbook notes 16 GB is not enough for NMS
  and KSP at once, so the KSP work has been done with NMS closed.

## Quick start

See **[RUNBOOK.md](RUNBOOK.md)** for how to run each piece: the coordinator with
KSP and the stand-in NMS, the full transfer / land / launch control messages, the
real NMS path through pyMHF, and how to rebuild the KSP plugin.

## Tests

```
python -m unittest discover -s tests -t .
```

80 tests. They include pure unit tests for orbits, maneuver planning, patched
conics and powered flight, plus `tests/test_scenario.py`, which runs the whole
scenario against fake KSP and fake NMS endpoints.

## Repo layout

| Path | What it is |
|---|---|
| `constellation/` | Python coordinator: clock, orbits, universe/anchor, patched conics, maneuver/Lambert, powered flight, protocol, KSP link, fake NMS |
| `adapters/nms/` | pyMHF/NMS.py mod that drives NMS, plus the pure transform maths it uses |
| `ksp/ConstellationKSP/` | C# KSPAddon plugin for KSP 1.12.5, and `build.rsp` for the offline build |
| `docs/transfer-land-design.md` | The fixed interfaces for the transfer, landing and launch modules |
| `research/` | Background notes on NMS, KSP, Space Engineers, SkyCraft and feature gaps |
| `spikes/` | Early test rigs: probe mods, control clients and logs |
| `tests/` | The unittest suite |
| `evidence/` | KSP map screenshots captured during the spikes |
| `RUNBOOK.md` | How to run everything |

## Notes

There is no licence file in this repository yet.

NMS.py and pyMHF are fragile by design: they hook a specific game build and break
on updates. Constellation pins NMS to build 180383 and the matching NMS.py
commit. The NMS ship path deliberately avoids `cGcSpaceshipComponent.GetVelocity`,
which access-violates on that build.
