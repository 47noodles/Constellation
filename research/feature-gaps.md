# Feature-gap analysis: Space Engineers 1, KSP 1.12.5, No Man's Sky (Oct 2026)

Research date: 2026-10-02. Method: web search and fetch only; no game was run. Anything I could not confirm from a page I read is marked UNVERIFIED. "Compat" means compatibility with the current SE1 / KSP 1.12.5 / NMS build 180383.

## 0. Version baseline

- NMS: the current major update is Cosmos (7.0), released 2026-09-09; 7.04 is the latest hotfix. Sources: https://www.nomanssky.com/2026/09/no-mans-sky-cosmos/ and https://www.perfectly-nintendo.com/no-mans-sky-switch-software-updates/. One source lists it as "6.50 Cosmos, Aug 9 2026" (https://nomanssky.wiki/recent/), which conflicts. Treat the Cosmos date as settled and the version label as unsettled.
- NMS build 180383: UNVERIFIED. SteamDB returned 403 and no page I read ties 180383 to a version. Every NMS "works on 180383" entry below is therefore at best "works on 7.0x".
- NMS player-built corvettes exist. They shipped in Voyagers 6.0 (Aug 2025): modular, multi-crew, hundreds of ship modules. Source: https://hellogames.org/2025/08/27/introducing-the-voyagers-update-and-customisable-corvettes-in-no-mans-sky/. Remnant 6.2 (Feb 2026) brought them to Switch. Source: https://nintendoeverything.com/no-mans-sky-remnant-6-2-update-announced-patch-notes/.
- Cosmos adds a star map, space-station ownership, free-floating orbital bases, space hulks, alliances and a journey to the star. Source: https://www.nomanssky.com/2026/09/no-mans-sky-cosmos/.
- SE1 is still updated. Update 1.209 "Economy 2" shipped 2026-04-05 (https://www.spaceengineersgame.com/space-engineers-economy-2/). A blog post dates it May 2026 (https://blog.marekrosa.org/2026/05/space-engineers-economy-2/), so there is a date conflict. The current SE1 build number is UNVERIFIED. Space Engineers 2 is in Early Access (https://store.steampowered.com/app/1133870/Space_Engineers_2/). It is out of scope here.
- KSP 1.12.5 was released 2023-01-11 and is the final KSP1 version (https://mac.softpedia.com/progChangelog/Kerbal-Space-Program-Changelog-106651.html).

## 1. Signature strengths (short)

- SE1:
  - Block-level ship building with interiors, subgrids and physics.
  - Destructible, persistent voxel planets with gravity and atmosphere.
  - In-game C# Programmable Block plus a mod API and plugins.
  - Hydrogen jetpack, magnetic boots, walking inside ships.
  - Survival resources, a wide weapon set, 4-32 player multiplayer.
  - Economy 2 contracts and NPC-staffed trade stations.
  - Source: https://spaceengineers.wiki.gg/wiki/Features. The explicit "no orbital mechanics" statement is on the same page.
- KSP 1.12.5:
  - Patched-conic orbits, maneuver nodes, atmospheric flight with re-entry heating, and a mission-planning culture.
  - Core strength is the orbital layer. Everything else is thin unless modded.
  - The orbital and heating claims are common knowledge: UNVERIFIED by a page I read.
- NMS 7.0:
  - Procedural galaxy, planets with biomes and fauna, and fast seamless planet-to-space flight.
  - Stations with NPC traffic, plus Cosmos station ownership.
  - Corvette building, base building, multiplayer up to 32 (https://www.nomanssky.com/).
  - Interstellar warp and the new star map.

## 2. Matrix (strong / basic / missing)

| # | Area | SE1 | KSP 1.12.5 | NMS 7.0 |
|---|---|---|---|---|
| 1 | Character movement | strong: jetpack, mag boots, walks ships | basic: EVA jetpack, ladders, no real walking | strong: sprint, jetpack, spacewalk (Cosmos "spacewalking enhancements") |
| 2 | Ship building | strong: block-level, interiors | strong: part-based, no interiors | basic-to-strong: corvette modules, fixed archetypes otherwise |
| 3 | Ship flight physics | strong: full rigid-body, thrusters | strong: rigid-body, realistic thrust | basic: arcade, speed caps, soft stops |
| 4 | Orbital mechanics and gravity | missing: gravity wells only, no orbits | strong: patched conics (n-body via mod) | missing: planets static (UNVERIFIED), no orbital dynamics |
| 5 | Aero and re-entry | basic: drag-light atmosphere, heat via mod | strong: stock re-entry heating | missing: atmosphere is cosmetic (UNVERIFIED) |
| 6 | Map and mission planning | basic: GPS waypoints, contracts | strong: map view, maneuver nodes | basic-to-strong: galaxy map, new Cosmos star map |
| 7 | Planets and terrain | strong: destructible voxels (few planets) | basic: static heightmap, 1 scale | strong: procedural planets, caves, water |
| 8 | Biomes and fauna | basic: sparse, per-planet | missing: no fauna | strong: fauna, flora, weather |
| 9 | Stations and NPC traffic | basic-to-strong: Economy 2 stations, NPC cargo ships, NPCs inside | missing | strong: stations, freighter traffic, station ownership (Cosmos) |
| 10 | Economy | strong: Economy 2 contracts, store blocks, reputation | basic: career funds only | strong: markets, trade, units |
| 11 | Survival and resources | strong | basic: life support absent in stock | strong |
| 12 | Combat and damage | strong: block-level damage, many weapons | missing-to-basic: none stock | basic: ship and creature combat, no structural damage |
| 13 | Automation and scripting | strong: Programmable Block, mod API | basic: stock SAS only (kOS and kRPC are mods) | missing: no in-game scripting |
| 14 | Interstellar travel | missing (mods fake it) | missing (single system) | strong: warp and galaxy map |
| 15 | Multiplayer | strong: 4-32 players | basic: none stock (LunaMultiplayer mod) | strong: up to 32 via Space Anomaly |

Cell ratings from pages I read: SE row 1, 4, 10, 13, 15; NMS row 6, 9, 14, 15. The rest are my judgement from general knowledge. UNVERIFIED unless a page is cited above.

## 3. Gap cells (basic or missing) and existing mods

### SE1 gaps

| Gap | Mod | Link | Last updated | Compat |
|---|---|---|---|---|
| Orbital mechanics | Real Orbits (fakes orbits; players are teleported to real planet positions) | https://steamcommunity.com/sharedfiles/filedetails/comments/3351055036 | UNVERIFIED (Steam returned 429) | UNVERIFIED on current SE1; reported working with Real Solar Systems |
| Orbits and interstellar | Real Solar Systems (OLD) | https://steamcommunity.com/sharedfiles/filedetails/comments/3326723404 | 2024-10-18 | Removed from Steam and incompatible. A republished replacement exists but I did not find its link (UNVERIFIED). |
| Aero and re-entry | Aerodynamic Physics (friction heat plus re-entry shock-wave heat, wind) | https://steamcommunity.com/sharedfiles/filedetails/changelog/571920453 | UNVERIFIED | UNVERIFIED |
| Economy and NPC | Vanilla Economy 2, not a mod | https://www.spaceengineersgame.com/space-engineers-economy-2/ | 2026-04-05 | Native |
| Hosting and plugins | Plugin Loader | https://github.com/sepluginloader/PluginLoader | v1.12.8, 2025-04-28 (repo pushed 2026-09-05) | UNVERIFIED |
| Hosting and plugins | Torch | https://github.com/TorchAPI/Torch | 1.3.1, 2023-12-22 (repo pushed 2026-07-27) | UNVERIFIED |
| Interstellar | none found with a verified link | | | |

### KSP 1.12.5 gaps

| Gap | Mod | Link | Last updated | Compat 1.12.5 |
|---|---|---|---|---|
| Orbital depth (n-body) | Principia | https://github.com/mockingbirdnest/Principia | tag 2026091103-Lévy | Yes, README lists 1.12.2 to 1.12.5 |
| Real-scale planets | Real Solar System (needs Kopernicus) | https://github.com/KSP-RO/RealSolarSystem/releases/tag/v20.1.3.0 | 2024-07-13 | UNVERIFIED |
| Realism, re-entry, engines | Realism Overhaul v18.0.0.0 | https://github.com/KSP-RO/RealismOverhaul/releases/latest | 2026-06-03 | Version not stated on the page; UNVERIFIED |
| Career, economy | RP-1 v4.7.0.0 | https://github.com/KSP-RO/RP-1/releases/tag/v4.7.0.0 | 2026-09-05 | UNVERIFIED (I believe 1.12.5) |
| Survival, life support | Kerbalism 3.43 | https://github.com/Kerbalism/Kerbalism/releases/tag/3.43 | 2026-09-27 | Yes, "KSP 1.12.x" per release page |
| Automation | kOS 1.6.0.1 | https://github.com/KSP-KOS/KOS/releases/tag/1.6.0.1 | 2026-05-14 | KSP version not stated; UNVERIFIED |
| External scripting | kRPC v0.6.0 | https://github.com/krpc/krpc/releases/tag/v0.6.0 | 2026-07-22 | KSP version not stated; UNVERIFIED |
| Autopilot, planning | MechJeb2 dev build | https://github.com/MuMech/MechJeb2/releases | dev-2.16.0.0-1721, 2026-10-01 | UNVERIFIED |
| Walking and first-person | WalkAbout | https://forum.kerbalspaceprogram.com/topic/193732-112x-walkabout | UNVERIFIED | Thread title says 1.12.x |
| First-person view | Kerbal VR (also first-person EVA) | https://github.com/FirstPersonKSP/Kerbal-VR/releases/tag/0.9.4.5 | 2025-10-14 | UNVERIFIED |
| Inventory | KIS (Kerbal Inventory System) | https://github.com/ihsoft/KIS/releases | v1.27, 2020-12-23 | Forum thread says min KSP 1.12; UNVERIFIED |
| Combat | BDArmory Plus v1.9.0.0 | https://forum.kerbalspaceprogram.com/topic/209092-19x-112x-bdarmory-plus-bda-v1900-2025-01-22 | 2025-01-22 | Yes, thread title 1.9.x to 1.12.x |
| Terrain | Parallax (PBR terrain and surface objects; visual only) | https://forum.kerbalspaceprogram.com/topic/209714-112x-parallax-pbr-terrain-and-surface-objects-208 | UNVERIFIED | Thread title 1.12.x |
| Atmosphere visuals | Scatterer 0.0878 | https://github.com/LGhassen/Scatterer/releases/tag/0.0878 | 2024-07-16 | UNVERIFIED |
| New planets, bodies | Kopernicus (R-T-B fork) | https://github.com/R-T-B/Kopernicus | UBE-release-86, 2022-10-26 (repo pushed 2024-08-04) | UNVERIFIED |
| Interstellar | KSP Interstellar Extended (KSPIE) | search hit only; I found no direct page | UNVERIFIED | Search result says 1.12.5; UNVERIFIED |
| Multiplayer | LunaMultiplayer | https://github.com/LunaMultiplayer/LunaMultiplayer/releases | UNVERIFIED | UNVERIFIED |
| Stations and NPC traffic, biomes and fauna, economy beyond career | none found | | | |

### NMS gaps (all "compat" values are UNVERIFIED against build 180383)

| Gap | Mod | Link | Last updated | Compat |
|---|---|---|---|---|
| Flight physics (momentum, 0G, no safety zone) | Realistic Flight Overhaul by PodcastPrimate | https://www.nexusmods.com/nomanssky/mods/2490 | 2025-09-03 (for Voyagers) | Not confirmed on 7.0/7.04. Direct Nexus fetch returned 403; date came from search snippets. |
| Scripting and hooks | NMS.py (hooking framework; read/hook game functions) | https://github.com/monkeyman192/NMS.py | repo pushed 2026-10-01 | README warns updates break mods; 7.x support not stated |
| Mod tooling | MBINCompiler | https://github.com/monkeyman192/MBINCompiler/releases | v7.04.1-pre3, 2026-09-24 | Targets 7.04 by name |
| Save access | NomNom savegame editor | https://github.com/zencq/NomNom/releases | 7.00.2, 2026-09-28 | Targets 7.00 by name |
| Orbital mechanics, aero and re-entry, interstellar physics, automation | none found | | | |

## 4. Effort to build inside the game (gaps with no existing mod)

Ratings assume a single developer and no engine source. Basis: general knowledge and the hook-framework pages above. UNVERIFIED as estimates.

| Game | Gap | Effort | Why |
|---|---|---|---|
| SE1 | True moving orbital bodies (physical planets in motion) | infeasible | Engine has static planets; Real Orbits teleports the player instead (see search result above) |
| SE1 | Fake orbit layer fed by an external ephemeris (character plus ship pose from KSP) | medium | Mod API plus per-tick pose; teleport pattern already exists |
| SE1 | Interstellar travel | medium | Fake via world swap or teleport, same as Real Orbits pattern |
| SE1 | Biomes and fauna depth | large | Needs new content, AI and assets |
| KSP | Walkable ship interiors and full character movement | large | Kerbals are not physics-walkers; WalkAbout covers only part |
| KSP | Stations and NPC traffic | large | Needs agent AI and economy hooks; nothing stock |
| KSP | Biomes and fauna | large | No ecosystem layer |
| KSP | Destructible voxel terrain | infeasible | Terrain is a heightmap quadtree |
| KSP | Economy beyond career | medium | RP-1 and Strategia-type systems exist; a market is new |
| NMS | In-game scripting or automation | medium | NMS.py hooks exist; no official API |
| NMS | Newtonian flight on 7.0x | small | RFO exists; port to current binary if it breaks |
| NMS | Orbital mechanics (moving planets) | infeasible | Planets and star systems are baked and procedural; faking is large |
| NMS | Aero and re-entry heating | medium | Hook ship state, apply heat damage and effects |
| NMS | Block-level ship physics (SE style) | infeasible | Corvette modules are cosmetic assemblies |

## 5. Top ten recommended mods

Design: SE character, KSP orbital mechanics, NMS universe. NMS is the visible game. SE and KSP run hidden. Column "Cuts bridge work" = reduces what the live bridge has to compute, translate or stream.

| # | Game | Mod | Status | Cuts bridge work | Reason |
|---|---|---|---|---|---|
| 1 | KSP | kRPC | Existing (v0.6.0, 2026-07-22; 1.12.5 UNVERIFIED) | Yes | Ready-made RPC and streaming API for orbit state, so the bridge needs no custom KSP plugin |
| 2 | KSP | Principia | Existing (Lévy, Sep 2026, 1.12.5 yes) | Yes | Orbits, n-body and extended-body gravity are computed inside KSP; the bridge only reads positions |
| 3 | KSP | MechJeb2 dev | Existing (2026-10-01; 1.12.5 UNVERIFIED) | Yes | Maneuver planning and autopilot run inside the hidden game, so the bridge does not need its own planner |
| 4 | KSP | kOS | Existing (1.6.0.1, 2026-05-14; 1.12.5 UNVERIFIED) | Yes | On-vessel guidance scripts reduce per-frame commands over the bridge |
| 5 | KSP | Kopernicus planet pack matching the NMS system layout (generator) | To build, medium | Yes | Bodies and masses in KSP match NMS positions, so the bridge does not remap frames |
| 6 | NMS | NMS.py plus a custom pose-injector mod | Existing framework plus to build, medium to large | No | This is the bridge endpoint itself; it hooks ship position and velocity. Breaks on game updates. |
| 7 | NMS | Realistic Flight Overhaul | Existing (2025-09-03; compat on 7.0x UNVERIFIED) | Yes | Momentum is preserved and safety nets are removed, so mirrored velocities need fewer corrections |
| 8 | SE1 | Character-only stripped world plus Programmable Block or plugin exporter of character pose and input | To build, small to medium | Yes | Moves character physics to a small headless world; the bridge streams only pose |
| 9 | SE1 | Plugin Loader or Torch headless host | Existing (Plugin Loader v1.12.8, 2025-04-28; Torch 1.3.1; current SE1 compat UNVERIFIED) | Yes | Runs SE1 hidden or dedicated without a GUI |
| 10 | NMS | Re-entry heat and speed-cap effect layer (hook-driven) | To build, medium | No | Visual and damage feedback for KSP-side aero; reuses the NMS.py hook |

## 6. Caveats

- Nexus Mods, SteamDB, Fandom and some GitHub API calls returned 403 or 402 during research. Steam workshop returned 429 after a few fetches. That caused most of the UNVERIFIED dates above.
- GitHub unauthenticated API rate limit was hit midway. Release data shown comes from calls made before that and from GitHub release pages.
- The mod list is not exhaustive. KSP has hundreds of mods that I did not cover.
