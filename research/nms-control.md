# Can an external process drive No Man's Sky build 180383 as a pure renderer?

Research date: 2026-10-02. Method: shallow clones of NMS.py (HEAD 52e2e55, "Update for 180383", 2026-10-01) and pyMHF (HEAD 24e9c25, 2026-09-30) in a temp folder, source read directly. Nothing was run in-game. Every claim is cited as `file:line` (paths relative to `nmspy/data/` in NMS.py unless stated) or a URL. UNVERIFIED means: not confirmed by source or by a running game.

Prior research: `nms.md` (same folder). This note answers the control questions only.

## Bottom line

NMS.py gives us a Python-in-process hook layer with a per-frame callback, a game-thread-safe way to call native functions, and typed pointers to the player, solar system, planets and scene graph. It does NOT give a documented "set ship transform", "set camera" or "raycast terrain" call. The cheapest viable design is probably: drive the player or ship pose, and let NMS's own camera follow it. Every write path is untested on 180383.

No existing mod found (GitHub, Nexus, Reddit search) teleports the player, overrides ship flight, overrides the camera, or spawns/moves scene nodes at runtime. Searches were shallow: Reddit was blocked to our fetcher and Nexus returned 403. So "none found" means "none found by us", not "none exist".

## 1. Player position and orientation, every frame

- Read: YES. `cGcPlayer.mRootNode` (types.py:1530) plus `Engine.GetNodeAbsoluteTransMatrix` (types.py:2859-2867, wrapper `nmspy/engine.py:16-27`) returns a full 3x4 matrix. `example_mods/playerLocation.py:93-97` does exactly this. `cGcPlayer.mPosition` (types.py:1534, offset 0x360) and `cGcPlayerEnvironment.mPlayerTM` (types.py:1925) are alternatives.
- Write: probably YES, via the game's own teleport. `cGcPlayer.SetToPosition(this, cTkBigPos*, dir*, vel*)` is declared with a byte signature (types.py:1583-1590). The example only hooks it to log (`playerLocation.py:103-114`); no repo code calls it. Calling a declared function works in principle: `FunctionHook._call` builds a ctypes prototype and calls the resolved address (pyMHF `pymhf/core/hooking.py:960-1015`), and pattern lookups are cached (`pymhf/core/memutils.py:275-299`). Position is `cTkBigPos = cTkPhysRelVec3` (local + offset, basic_types.py:777, 225-231), i.e. NMS uses a floating-origin split position, not one double.
- Physics fight: UNVERIFIED. The player has a Havok character controller (`mPhysicsController`, types.py:1531; `mTargetVelocity`, types.py:1508-1509). `SetToPosition` also carries a velocity argument, so calling it each frame with velocity zero is the natural "pin" approach. `cGcPlayer.CheckFallenThroughFloor` (types.py:1553) and `cGcPlayer.Update` (types.py:1574) are hookable and could be NOOPed (see Q2) to stop the game re-snapping the player. Whether the engine tolerates 30-60 teleports/second without footstep, audio, chunk-streaming or camera-smoothing glitches is unknown.
- Direct field writes to `mPosition` would be overwritten by physics each frame; use the function call.

## 2. Ship position, orientation, velocity; suppressing NMS flight

- Handles: `cGcSpaceshipComponent` (types.py:3549) has `mpPhysics` (0x6248) -> `cTkPhysicsComponent.mRigidBody` (types.py:3503-3505), `mbControllerActive`, `mfHeight`, `meLandState`, and hookable `Update`, `UpdateControlled` and `GetVelocity` (types.py:3579-3600). `cTkRigidBody.SetLinearVelocity` and `SetAngularVelocity` are declared (types.py:3478-3500).
- Suppression: YES in mechanism. pyMHF's `@NOOP` decorator on a `.before` hook stops the original function running and substitutes the hook's return value (pymhf `core/hooking.py:478-495` and the compound detour at 272-327). So `@NOOP @nms.cGcSpaceshipComponent.UpdateControlled.before` should disable NMS flight input handling while we drive the rigid body. Caution: the NOOP docstring warns the hooked function must return a type-correct value or the game crashes. UNVERIFIED that skipping `UpdateControlled` alone is enough (landing, boost, weapons, `Update` itself also touch the body).
- Velocity write: declared, UNVERIFIED in 180383. `broken_patterns.txt:6` lists `cTkRigidBody::SetAngularVelocity` as "Could not rename" in the 180383 update run, so that signature may not resolve. `SetLinearVelocity` is not listed.
- Position/orientation write for the ship: NOT PRESENT. No `SetTransform`/`SetPosition` for the ship body is declared. Options: (a) integrate velocity so position follows (velocity-driven, lossy), (b) write the ship scene node with `cEgSceneNodeData.SetRelativeTransform` (types.py:4922-4930) using `cGcPlayerShipOwnership.mShips[i].mPlayerShipNode` (types.py:1003-1013, 1046-1048 area), but the rigid body will overwrite the node each physics step, (c) respawn at a pose with `cGcPlayerShipOwnership.SpawnNewShip(matrix, gear, index, override)` (types.py:1041-1049), too heavy per frame.
- Finding the ship component: `GetShipComponent(index)` (types.py:1058-1064) returns a raw `cTkComponent*`. The address of the live `cGcPlayerShipOwnership` object is not in `cGcSimulation` or `cGcPlayerState` as exposed; UNVERIFIED how to obtain it except by capturing `this` in a hook such as `cGcPlayerShipOwnership.Update` (types.py:1034-1039), which is what `singletons.py:33-40` does for `cGcApplication`.
- Alternative that avoids ship physics: keep the player on foot, fly nothing, and use Q1 to move the player-as-camera. The ship is then rendered as a scene-node group (Q4).

## 3. Camera override

- NOT PRESENT as a runtime object. A search of `types.py` finds no camera manager, camera node or view-matrix struct. `exported_types.py:28266-28306` (`cGcCameraGlobals`) is static tuning data (offsets, free-camera settings for base building: `BaseBuildingFreeCameraSettings`, `ShipConstructionFreeCameraSettings`, `StationExteriorFreeCameraSettings`), not the live camera. `exported_types.py:588` has a `TeleportCamera` bool in some action-data struct (parent struct not identified; UNVERIFIED relevance).
- Data-file route: `GcCameraGlobals` is a mutable global (`nmspy/globals.py:144, 193`) and `PlayerGlobals` walk speed is already written live (`playerLocation.py:99-101`), so tuning values (first-person offsets, FOV-type values) can likely be changed at runtime. This does not give per-frame pose control.
- Third-party: Nexus "Improved Camera"/third-person mods are MBIN data edits (search result summaries; mod pages returned 403, not opened). GitHub `Mrsuss60/NoMansSky_MODs` ("customizable third person camera, no FOV limit") README gives no technical method (https://github.com/Mrsuss60/NoMansSky_MODs, UNVERIFIED whether runtime or MBIN).
- Practical consequence: treat the camera as "attached to player/ship" and move that (Q1/Q2). A free camera needs reverse-engineering a new signature. NMS has a photo mode (`cGcPhotoModeUI`, types.py:4969, `mPhotoModeSettings`, types.py:903) that could be exploited, UNVERIFIED.

## 4. Spawn, move and remove objects at runtime; a ship as many parts at 30 Hz

- Spawn: PARTIAL. `Engine.AddResource` (types.py:2900), `Engine.AddGroupNode(parent, name)` (types.py:2920), and `Engine.AddNodes(parent, sceneGraphResHandle)` (types.py:2942) are declared as static function hooks. These are the engine primitives for "load a .SCENE.MBIN and instantiate it under a parent node". Parent candidates: `cGcSimulation.mSimulationRootNode` and `maGroupNodes` (types.py:2210-2211, with `group_node(name)` helper). No example calls them. UNVERIFIED that the argument conventions (`TkHandle` by value, result pointers) behave as typed.
- Move: YES in mechanism. `cEgSceneNodeData.SetRelativeTransform(handle, cTkMatrix34*)` (types.py:4922-4930) is declared; global access via `cEgModules.mgpSceneManager` pattern (types.py:5012-5017) -> `cEgSceneManager.mData` (types.py:4934-4936). Also readable: `GetNodeAbsoluteTransMatrix`, `ShiftAllTransformsForNode` (types.py:2859-2862; helper in engine.py:25-27, used for floating-origin shifts). Caveat: `cEgSceneNodeData` declares `mpRelativeTransformBuffer` and `mpPrevRelativeTransformBuffer` both at 0x48 (types.py:4911-4912); one offset is probably wrong, so raw buffer writes are unsafe. Use the function.
- Remove: NOT PRESENT. No `RemoveNode`/`DeleteNode`/`SetNodeActive` is declared in `Engine` (types.py:2857-3002). Scene node flags carry `mbRemoved`/`mbActive` bits but the source marks that layout "the 4.13 representation and is no longer valid" (types.py:4893-4900). Workaround: never delete, pool nodes and hide by scaling or moving far away.
- Base-building objects: structs and markers exist (commit 03763bb; `cGcBaseBuildingManager`, types.py:2596-2650, `GetBaseRootNode`, `AddObjectMarker`) but no "place part" function. The manager is a global found by a pattern and the file itself says "TODO: Need to add the offset of this struct to the globals" (types.py:2594). Not a spawning API.
- 30 Hz ship-as-parts: FEASIBLE ON PAPER if built as one group node with child part nodes. Moving the ship is then a single `SetRelativeTransform` on the group per tick, not one per part, because child transforms are relative. Cost is a handful of ctypes calls per frame. If every part must move independently it is N calls/frame; a few hundred is probably fine for ctypes, UNVERIFIED. Visibility culling, LOD, and whether custom part scenes exist (stock scene paths only, otherwise needs MBINCompiler per `nms.md` section 6) are open.

## 5. Reading the current system

- Solar system: `gameData.simulation.mpSolarSystem` (`common.py:30-33`, types.py:2204) -> `cGcSolarSystem` (types.py:1865-1878). `maPlanets` is an array of 6 `cGcPlanet`; `miPrimaryPlanet`; `mSolarSystemData`; `mSpaceStationNode` (0x521890, types.py:1877) and `GetName` (types.py:1912; used in `playerLocation.py:58-64`).
- Planet position: `cGcPlanet.mPosition` (types.py:1654, offset 0xD74D0) and `mSolarSystemData.PlanetPositions` (exported_types.py:33235) and `SunPosition` (33237). `cGcPlayerEnvironment` gives nearest planet index, distance, sea level and position (types.py:1929-1934).
- Biome: `cGcPlanet.mPlanetGenerationInputData.Biome` (types.py:1644; enum field exported_types.py:22745); `gravityManipulator.py:186-192` logs the biome and position per planet, so this is the best-proven read in the repo.
- Gravity: write path exists (`cGcPlanet.UpdateGravity(mult)`, types.py:1685-1690, used in `gravityManipulator.py:195-201`). Read is via `cTkDynamicGravityControl.GetGravity(result, pos*, a4)` (types.py:2770-2780) or the gravity-point table (types.py:2731-2757), UNVERIFIED how to get the instance.
- Radius: no clean field. Only `mRegionMap.mfCachedRadius` (types.py:1614, offset 0x30 inside the region map) and the `PlanetSize` enum (exported_types.py:22749). Radius must be inferred or measured. UNVERIFIED.
- Creatures: `cGcPlanetData.CreatureIDs` (exported_types.py:38573), `CreatureLife`, `Life`, and `PlanetInfo.Fauna/Flora` strings (exported_types.py:8711-8712); `cGcPlanetGenerator.GenerateCreatureSpawnData` etc. are hookable (types.py:3712-3760). This lists creature types per planet, not live individual creature positions. The live creature set is `cGcCreatureComponent` (types.py:3855) and ecosystem (types.py:2020); positions UNVERIFIED.
- Space station location: node handle readable via `mSpaceStationNode`, absolute pose via `GetNodeAbsoluteTransMatrix`. Spawn parameters in `mSolarSystemData.SpaceStationSpawn.SpawnPosition/SpawnFacing` (exported_types.py:12193-12197, 33233).
- Wire-up: capture `cGcApplication` once (`_internal_mods/singletons.py:33-40`), then `gameData.*` properties work.

## 6. Trigger or detect a warp

- Trigger: `cGcSimulation.WarpToSystem(this, cGcGalacticSolarSystemAddress*)` is declared (types.py:2237-2243). Not demonstrated; UNVERIFIED whether it does the full warp tunnel, loads, and save-state update or only a partial step. `cGcGameState.ComputeWarpCapability` (types.py:1469-1479), `cGcSpaceshipWarp` pulse-drive state/timers (types.py:2168-2191) are readable.
- Fallback trigger: edit the save (`libNOM.io`, `nms.md` section 3) and reload, slow and not frame-rate.
- Detect: YES by hooks. `cGcSolarSystem.Generate/Construct` (types.py:1883, 1895), `OnEnterPlanetOrbit/OnLeavePlanetOrbit` (types.py:1885-1891), `cGcPlayerState.mLocation` (types.py:870) and `gameData.simulation.mCurrentUA` (types.py:2213). The app state-change hook already exists (`singletons.py:42-65`).

## 7. Terrain raycast or height query

- NOT FOUND. No `RayCast`, `GetHeight` or terrain-sample function is declared. Closest items: `cGcBinoculars.UpdateRayCasts` (types.py:3409, takes a `cTkContactPoint*`, UNVERIFIED usable), `cGcSpaceshipComponent.mfHeight` (types.py:3568, height above ground for a ship), `cGcPlayerEnvironment.mfDistanceFromPlanet` and `mfNearestPlanetSealevel` (types.py:1930-1932), the terrain editor beam (types.py:3508-3540), and `cGcTerrainRegionMap` (types.py:1613-1635). Distance-from-centre minus sea level is the cheap approximation. A proper height query would require reverse-engineering a new signature.

## 8. Tick rate, hook latency, IPC

- Tick source: the "main loop" is a hook on `cGcApplication.Update` (types.py:2562-2563), exposed as `@main_loop.before/after` (`nmspy/decorators.py:6-15`, wired in `_internal_mods/singletons.py:67-75`). It therefore runs once per rendered frame on the game thread; the rate equals NMS's frame rate (unmeasured). `cGcPlayer.Update`, `cGcSimulation.Update` and `cGcSpaceshipComponent.Update` all take `lfTimeStep` and are also hookable.
- Latency: no measurements in the repos. pyMHF docs say detour overhead is "fairly low" but warn heavy work in the main loop "could easily cause performance issues" (pyMHF `docs/docs/libraries/custom_callbacks.rst:124`). Each detour runs Python in the game thread under the GIL (`hooking.py:272-327`). A handful of ctypes calls per frame is expected to cost tens of microseconds; UNVERIFIED, measure.
- Failure behaviour: a detour that raises is removed permanently ("It has been disabled", `hooking.py:285-291`). Wrap bodies in try/except to avoid a silent stop.
- IPC to an external C# process: PRACTICAL. The mod is ordinary CPython, so `socket`, named pipes, `mmap` shared memory and UDP all work from inside a `@main_loop` callback. pyMHF itself ships a FastAPI/uvicorn server (`pymhf/injected.py:335-336`, binds `0.0.0.0:5000`, so firewall it or change the bind) with GET/PUT and a read-only websocket (`pymhf/core/http_api.py:80-93, 100-134`, polled with `asyncio.sleep(0.001)`; docs `http_api.rst` say websockets are read-only and should be cheap). HTTP/WS is fine for control commands but is the wrong choice for 30 Hz poses: endpoint handlers run on the server thread, not the game thread, so native calls from them are thread-unsafe (UNVERIFIED but standard). Recommended: shared memory or a localhost UDP socket polled with a non-blocking read inside `@main_loop.before`; apply the latest pose in the game thread.
- Example integration: `floh-bhaptics/NoMansSky_bhaptics_NMSpy` forwards NMS.py game events to an external haptics player; README does not disclose the IPC mechanism (https://github.com/floh-bhaptics/NoMansSky_bhaptics_NMSpy).
- Focus/pause: NMS pauses when the window loses focus. `cGcApplication.mbPaused`, `mbWindowFocused`, `mbHasFocus` are at 0xB8D5-0xB8DA (types.py:2578-2581) and `kBlankii/NMS_PauseBeGone` (https://github.com/kBlankii/NMS_PauseBeGone, updated 2026-09-26) exists to bypass the auto-pause. A visible NMS window beside hidden SE/KSP windows must stay focused or have the pause defeated.
- Platform risks: NMS.py "can very easily break" on game updates (README); every build needs its commit (`nms.md` section 1). Python must be the official CPython 3.9-3.13, not 3.14 (`nms.md`).

## Other relevant repos and mods found

- `gurrenm3/NoMansSky.Api` (C#, Reloaded-II): per-frame game-loop hook, player stats, 20 global MBINs; no teleport/spawn/ship/camera; game version support not stated; last commit date not seen (https://github.com/gurrenm3/NoMansSky.Api). It would let the C# bridge live in-process, but is stale relative to build 180383, UNVERIFIED.
- `ArDev-ACG/NoMansSky-Mods` (creature mods, updated 2026-10-02): data-file mods only as far as seen (https://github.com/ArDev-ACG/NoMansSky-Mods).
- NMS.py open issues: only #45 (PyMemoryEditor swap) (https://github.com/monkeyman192/NMS.py/issues). Recent commit titles contain no camera/teleport/ship-control work (https://github.com/monkeyman192/NMS.py/commits/master/).
- Not accessed: r/NMSModding (blocked), Nexus mod pages (403). No Nexus mod using NMS.py to teleport or control the ship was surfaced; the coordinate teleport mods that exist are save-file editors (reload required).

## Go / no-go for NMS as renderer

| Capability | Verdict | Why |
|---|---|---|
| Per-frame tick on game thread | GO | `cGcApplication.Update` hook (types.py:2562, singletons.py:67) |
| Read player pose | GO | `GetNodeAbsoluteTransMatrix` (playerLocation.py:93) |
| Write player pose each frame | CONDITIONAL | `SetToPosition` declared, never called in repo; physics interaction untested |
| Write ship velocity | CONDITIONAL | `SetLinearVelocity` declared; `SetAngularVelocity` pattern flagged broken (broken_patterns.txt:6) |
| Write ship pose directly | NO-GO (as is) | No setter; needs new signature or node-write workaround |
| Suppress NMS flight | CONDITIONAL | `@NOOP` + `UpdateControlled.before` (hooking.py:478), crash risk |
| Free camera | NO-GO (as is) | No runtime camera object; use follow-camera via player/ship |
| Spawn scene nodes | CONDITIONAL | `AddGroupNode/AddNodes/AddResource` declared, uncalled |
| Move scene nodes at 30 Hz | CONDITIONAL-GO | `SetRelativeTransform` declared; one call per group |
| Remove nodes | NO-GO (as is) | No removal API; pool and hide |
| Read planets, biome, station | GO | `gravityManipulator.py:186`, `cGcSolarSystem` fields |
| Planet radius | CONDITIONAL | No clean field |
| Trigger warp | CONDITIONAL | `WarpToSystem` declared, untested |
| Detect warp | GO | Hooks on `Generate`, orbit enter/leave, `mLocation` |
| Terrain height query | NO-GO (as is) | Approximate with distance-from-centre minus sea level |
| IPC to external C# | GO | In-process CPython; shared memory or UDP; avoid HTTP for 30 Hz |
| Overall | CONDITIONAL-GO | Viable if player/ship pose control survives the tests below; otherwise save-edit fallback |

## Three cheapest in-game tests, in order

1. Frame-rate and player teleport. Run NMS.py at 180383, add a mod with `@main_loop.before` that logs `time.perf_counter()` deltas for 60 s (gives real tick rate and callback cost), then each frame calls `nms.cGcPlayer.SetToPosition` with a position moving along a slow circle and zero velocity (start from `playerLocation.py`). Pass if the player tracks smoothly on foot with no rubber-banding and the third-person camera follows. Fail tells us the Q1 pin approach is dead and the ship/scene-node route is needed.
2. Ship velocity override. While flying in space, add `@NOOP @nms.cGcSpaceshipComponent.UpdateControlled.before` (return a safe value) and call `mpPhysics.mRigidBody.SetLinearVelocity` each frame from a scripted path; log `GetVelocity`. Also check at startup whether the `SetAngularVelocity` pattern resolves (pyMHF logs unresolved patterns) because `broken_patterns.txt:6` flags it. Pass if the ship follows the scripted velocity and orientation can be steered. This decides the ship-as-camera design.
3. Scene-node ship. Capture `cEgModules.mgpSceneManager`, call `Engine.AddGroupNode` under a `cGcSimulation` group node, `Engine.AddNodes` with a stock ship scene resource as a child (load it via `Engine.AddResource`), then move the group each frame with `SetRelativeTransform` (and read back via `GetNodeAbsoluteTransMatrix`). Pass if the model renders and moves with no flicker or culling. Then add 50-200 children and measure frame-time cost. This decides whether the "ship from many parts" renderer idea is workable without touching ship physics.
