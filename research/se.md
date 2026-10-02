# Space Engineers 1 modding research (as of 2026-10-02)

Method: web search plus page fetches. Several hosts (steamcommunity, steamdb, store.steampowered, keensoftwarehouse.github.io) failed DNS from the research box, and the Keen ModAPI reference could not be read. So code-level API names below that are not backed by a fetched page are marked UNVERIFIED and come from memory of SE1 internals. Confirm each against decompiled game code before building on it. The CometWorks "se-dev-game-code" skill (below) automates the decompile.

Current game build: SE1 1.210 "Prosperity" released 27 Jul 2026 (https://low.ms/knowledgebase/space-engineers-prosperity-1-210-update-your-server, https://cogconnected.com/2026/07/space-engineers-launches-free-prosperity-update-with-new-endgame-challenges/). Pulsar v2.3.1 is "Recompile for SE1 v1.210.011" (https://github.com/SpaceGT/Pulsar/releases/tag/v2.3.1).

---

## 1. Code plugins: Plugin Loader, Pulsar, Magnetar, Torch

- Plugin Loader (sepluginloader/Avaness) was shut down in 2025 and gets no updates. Source: https://spaceengineers.wiki.gg/wiki/Plugins
- Pulsar (SpaceGT/Pulsar) is the maintained hard fork. It supports SE1 and SE2, is portable (extract to an empty folder), and installs via a Windows installer or by setting the Steam launch option `[PulsarPath] %command%`. Source: https://github.com/SpaceGT/Pulsar (README, fetched via raw.githubusercontent.com).
  - Three executables: Legacy (SE1 on .NET Framework), Interim (SE1 on .NET 10 via a compat layer) and Modern (SE2 on .NET 10). It also runs SE1 natively on Linux.
  - For SE1 build 1.210 choose Legacy: it is the least exotic path.
- Client plugin install: client plugins are compiled on the player's machine from GitHub source registered in the PluginHub, so they must be open source (https://raw.githubusercontent.com/CometWorks/skills/main/skills/se-dev-plugin/SKILL.md). Local/dev plugins can also be loaded from disk (UNVERIFIED, standard Plugin Loader behaviour).
- Server plugins, two loaders:
  - Magnetar (CometWorks/magnetar) is a Pulsar-derived loader for the Dedicated Server: headless launch, daemon mode, no WinForms/Telerik, no graphics needed, Windows (.NET Framework 4.8 or .NET 10) and Linux (.NET 10). Plugins are registered via MagnetarHub PRs. Source: https://github.com/CometWorks/magnetar
  - Torch (torchapi.com) is the long-standing DS wrapper with a plugin ecosystem. It is actively maintained: PR #645 for 1.210 merged within about 83 minutes of release (https://low.ms/blog/space-engineers-mods-and-torch-without-breaking-your-world, https://low.ms/knowledgebase/space-engineers-prosperity-1-210-update-your-server). CometWorks notes Torch plugins are a "legacy server host", Torch-only and not Magnetar-compatible.
- Capability beyond the ModAPI whitelist: plugins are ordinary managed code with full system access, unsandboxed (wiki: they can "access your PC, files, or network"). https://spaceengineers.wiki.gg/wiki/Plugins
  - Harmony is documented as first-class in the CometWorks plugin skill: prefix/postfix, AccessTools reflection, transpilers, finalizers, reverse patches, and Mono.Cecil pre-JIT patching (client only). https://raw.githubusercontent.com/CometWorks/skills/main/skills/se-dev-plugin/SKILL.md
  - Sockets are proven in-process: DirectTransport (CometWorks/direct-transport) swaps the engine's networking layer for raw UDP using LiteNetLib, as a Pulsar plugin plus a Magnetar plugin. https://raw.githubusercontent.com/CometWorks/direct-transport/main/README.md
  - Full .NET, memory-mapped files and named pipes: nothing in the .NET Framework 4.8 or .NET 10 runtimes blocks them. They are not blocked by the plugin loader. Not explicitly demonstrated in a fetched source, but implied by "full system access". UNVERIFIED as a tested example.
- Mods (ModAPI scripts) by contrast run in a whitelisted sandbox. CometWorks' toolkit also carries "Mod templates and ScriptMerge tools" and exported API whitelists from game 1.208.015. Not needed here: plugins sidestep the whitelist entirely.
- Dev aid: https://github.com/CometWorks/skills (se-dev-plugin, se-dev-game-code, se-dev-server-code). It decompiles the game or DS (about 1.5 GB, 5-15 min) into a searchable tree. This is the practical way to verify every UNVERIFIED symbol below.

Verdict: FEASIBLE. Pulsar (client) and Magnetar or Torch (server) give unrestricted .NET plus Harmony, and are current for 1.210.

---

## 2. IPC at 30-60 Hz

Recommendation (design judgement, not a sourced fact): loopback UDP (or one persistent TCP connection with NODELAY) carrying fixed-size packed binary structs, for example `struct.pack('<...')` on the Python side and a `BinaryWriter` or unsafe struct on the C# side.
- Plugin side: hook the per-tick point (see section 3). Write state into a preallocated buffer, hand it to a dedicated sender thread, and receive commands on a second thread into a lock-free latest-value slot that the sim thread reads. Never block the game thread on I/O.
- 60 Hz with about 1-4 KB per packet is far below any limit. UDP is lossy but latest-value-wins semantics suit state streams. Add a sequence number and a timestamp.
- Memory-mapped file or named pipes are also available (full .NET), and a MMF with a seqlock gives lowest latency. They are not needed at this rate, and UDP crosses easily into WSL or a different process space. Python can use `socket` plus `numpy.frombuffer`.
- Proof that UDP in a plugin works in this game: DirectTransport (source in section 1).

Verdict: FEASIBLE.

---

## 3. Runtime grid control and inputs

I could not fetch the Keen ModAPI reference, so everything here is from memory of SE1 internals. UNVERIFIED unless stated. Verify with the decompile skill.

Tick hook:
- Pulsar/Plugin Loader plugins implement `IPlugin` with `Init`, `Update` (called each frame) and `Dispose` (UNVERIFIED from memory of the PluginLoader API). Alternatively Harmony-postfix `MySession.UpdateAfterSimulation` or a `MySessionComponentBase` (`UpdateAfterSimulation`/`UpdateBeforeSimulation`), which runs at the fixed 60 Hz simulation step and is the right place for authoritative writes.

Spawn a grid from a blueprint:
- Load the blueprint `bp.sbc` into a `MyObjectBuilder_ShipBlueprintDefinition` (`MyObjectBuilderSerializer.DeserializeXML`). Then `MyAPIGateway.PrefabManager.SpawnPrefab(...)` (ModAPI, takes position/forward/up/velocities) or lower level `MyEntities.CreateFromObjectBuilderAndAdd` with a `MyObjectBuilder_CubeGrid` whose `PositionAndOrientation` you set. As a plugin you can call the internal `MyEntities`/`MyCubeGrid` directly.

Pose and velocity every tick:
- Pose: `entity.PositionComp.SetWorldMatrix(ref MatrixD)` or `entity.Teleport(...)`.
- Velocity: `entity.Physics.LinearVelocity` and `AngularVelocity` are settable.
- Forces: `Physics.AddForce(MyPhysicsForceType.APPLY_WORLD_FORCE, ...)` and `ApplyImpulse`.
- Kinematic / externally driven options, in order of preference:
  1. Dynamic body, set LinearVelocity, AngularVelocity and the world matrix every tick from the outside simulator (gives a driven body that still collides and carries the pilot).
  2. Static grid (`IsStatic`/`ConvertToStatic`) teleported each tick. Characters standing on a moving static grid do not inherit motion, so this is poor for EVA.
  3. A true Havok keyframed/kinematic rigid body via `MyPhysicsBody.RigidBody` motion-type change. UNVERIFIED that the game exposes a clean path; needs a Harmony or reflection patch.
- Precision: keep SE near its own origin and treat the orbital frame as the coordinator's. Havok and rendering lose precision far from the origin (UNVERIFIED), and orbital-scale coordinates will break it.

Seated player's control inputs:
- `IMyShipController.MoveIndicator`, `RotationIndicator`, `RollIndicator` (ModAPI, also in the internal `MyShipController`). Nonzero for the controlling seat only; multiple seats are not all reported (confirmed by a Keen suggestion post: https://support.keenswh.com/spaceengineers/pc/topic/in-game-scripts-make-imyshipcontrollers-moveindicators-available-per-seat-instead-of-per-ship).
- Also `ControllerInfo`, `Pilot` and cockpit thruster-override fields (UNVERIFIED).

Character jetpack movement and position:
- `MySession.Static.LocalCharacter` (client) or the player's `Character`. `PositionComp.WorldMatrixRef` gives position; `Physics.LinearVelocity` gives velocity. `MyCharacter.JetpackComp` exposes `TurnOnJetpack`, `Running`, and the thrust vector (UNVERIFIED symbol names). Raw intent is `MyCharacter.MoveIndicator` and `RotationIndicator`.

Verdict: FEASIBLE (all primitives exist in memory of the engine; kinematic body specifically is RISKY until verified).

---

## 4. Headless operation and input injection

- The official Dedicated Server needs no graphics card. "Does not require a graphics card (headless software)"; install about 8 GB; default UDP port 27016; Windows-only for the vanilla DS; install through SteamCMD app 298740. https://spaceengineers.wiki.gg/wiki/Dedicated_Server
- Magnetar adds a headless daemon mode with a plugin API on top (and runs on Linux with .NET 10). https://github.com/CometWorks/magnetar
- The server simulates grids and characters of connected players, so a server plugin can stream state out.
- A character exists only as a player's avatar. So a server with no client has no jetpack character unless the plugin creates an NPC/bot identity and character itself (UNVERIFIED; the engine does this for its own AI "bots" and economy NPCs, and `MyCharacter.MoveAndRotate(move, rotation, roll)` and `MyShipController.MoveAndRotate(...)` exist as the injection points, UNVERIFIED).
- Input injection from outside: no ready-made injector was found. Realistic options: (a) a plugin that receives commands over the socket and calls `MoveAndRotate` or sets the move indicators on the controlled entity; (b) a headless real client. CometWorks mentions a "Remote plugin" with `--headless` and `--no-steam` flags for "players-free load testing" (https://raw.githubusercontent.com/CometWorks/direct-transport/main/README.md). I could not find that plugin's repo or docs, so what it can inject is UNVERIFIED.
- Simplest fallback: single-player world on a hidden (minimized) Pulsar client. This avoids multiplayer and NPC creation altogether, but still renders (see section 8).

Verdict: RISKY (server headless is proven; headless character plus input injection is plausible but unproven; the hidden-client path is safe).

---

## 5. Exporting SE models (.mwm) for personal use

- MWM is a closed container. There is no official mwm-to-FBX tool, and SEUT is FBX-in, MWM-out. SEUT imports SE FBX files (not MWM) and exports MWM; needs Blender 4.0+ (dev version 5.1+). https://spaceengineers.wiki.gg/wiki/Modding/Tools/SEUT
- The practical route is to skip MWM and use the sources. The free Mod SDK ships `OriginalContent`, "source .fbx/.hkt/.xml files for the models, including DLC ones", plus `MwmBuilder.exe` (FBX to MWM) and `ModelViewer.bat` (MWM viewer). https://spaceengineers.wiki.gg/wiki/Modding/OfficialTools
  - Some SDK FBX are the ASCII-FBX variant that Blender's importer rejects. Convert with the free Autodesk FBX Converter to binary FBX 2013 first. https://spaceengineers.wiki.gg/wiki/Modding/Tutorials/Setting_Up_a_Modding_Environment
- Pipeline: Mod SDK OriginalContent FBX, then Blender (SEUT importer, which also maps materials), then export glTF, OBJ or FBX for NMS. Also read the block definition XML in the game's `Content/Data/CubeBlocks` for model paths, grid size, orientation and construction-stage models (UNVERIFIED path details).
- Other tools found: "SE Block Tools for Blender" (harag-on-steam; older, export direction) http://harag-on-steam.github.io/se-blender/ ; Mr-Mors Modding wiki https://github.com/Mr-Mors/Modding-Space-Engineers/wiki/SE-Blender-Setup ; a Steam guide to importing SE FBX into Blender https://steamcommunity.com/sharedfiles/filedetails/?id=1168501958. A site "convert.guru/mwm-converter" appears in search results but is unverified and I would not trust it. No open community mwm-to-glTF extractor was found.
- Fallback if some model has no SDK source (for example a new DLC block): dump the loaded model's vertex and index buffers from inside the game with a plugin (`MyModels`/`MyModel` data) and write glTF. UNVERIFIED, but reasonable with the decompile.
- Personal-use licence terms for derived assets: not checked. UNVERIFIED.

Verdict: FEASIBLE (via SDK FBX, not via MWM reversing).

---

## 6. Multiplayer, Torch and plugin sync

- Dedicated server plus Torch (server plugins) or Magnetar (server plugins, headless, Linux/.NET 10) is the supported path. Client-only plugins work on any server for that player alone; server-side plugins must be installed by the server admin, and often a matching client plugin too. https://spaceengineers.wiki.gg/wiki/Plugins
- CometWorks template for dual plugins: a server template with ClientPlugin, ServerPlugin and Shared projects (https://raw.githubusercontent.com/CometWorks/skills/main/skills/se-dev-plugin/SKILL.md). Sync between server and client plugins would use the engine's multiplayer messaging (UNVERIFIED which API; ModAPI `Multiplayer.SendMessageTo` is the usual one for mods).
- Torch is open source (TorchAPI/Torch, https://github.com/apeira/Torch mirror), has a WPF UI by default, and is the successor to SE Server Extender. A no-GUI mode was not confirmed in what I could read.
- DirectTransport lets a client join a server with no Steam on either side. https://github.com/CometWorks/direct-transport
- Official Keen servers prohibit plugins. Irrelevant here.
- For this project multiplayer is optional: our coordinator is local, so one SE process with one plugin is the least moving parts.

Verdict: FEASIBLE (but not needed for a first build).

---

## 7. Gravity and forces owned by an external simulator

Not sourced from docs (the ModAPI reference was unreachable). Design options, all UNVERIFIED:
- Easiest and recommended: use a world with no planets (empty space, zero natural gravity), no artificial gravity generators, and keep gravity out of SE. The coordinator owns the trajectory and writes grid pose/velocity every tick (section 3). The EVA character experiences microgravity natively.
- If you want SE's physics to integrate motion: apply forces with `Physics.AddForce(APPLY_WORLD_FORCE, ...)` each tick from the coordinator's computed acceleration, and disable engine gravity for the grid with the world setting plus a patch.
- To make gravity externally controlled, Harmony-patch the gravity provider system (`MyGravityProviderSystem.CalculateTotalGravityInPoint` and the natural/artificial variants) so it returns the vector the coordinator sends. The engine has natural versus artificial gravity (https://spaceengineers.wiki.gg/wiki/Gravity), and PB/ModAPI expose `CalculateNaturalGravityInPoint`-style calls. As a plugin, patching is allowed.
- Caveat: planet gravity falloff and the "artificial gravity weakens near natural gravity" rule are engine behaviours you do not want, so avoid planets altogether.

Verdict: FEASIBLE (empty-world plus velocity writes is trivial; gravity patching is RISKY but optional).

---

## 8. Install size and performance

- Dedicated server: about 8 GB; minimum 3.2 GHz CPU with 3 logical cores and 6 GB RAM, recommended 4.5 GHz and 10 GB; Windows .NET Framework 4.8 and VC++ 2017+. https://spaceengineers.wiki.gg/wiki/Dedicated_Server
- Client: the Steam listing quotes 35 GB storage in search snippets (from an aggregator, not the Steam page, which I could not fetch). UNVERIFIED exact figure. Prosperity pack DLC adds more blocks.
- DS is headless and needs no GPU; no benchmark figures at lowest settings were found. UNVERIFIED how much a minimized client costs at the lowest settings; treat as a normal game process using one heavy thread plus a render thread.
- Pulsar `Interim` (.NET 10) is available for faster runtime, but riskier. Stick to Legacy first.
- No tick-rate numbers found. The sim runs at 60 Hz; a lone small grid plus one character is trivial load. UNVERIFIED benchmark.

Verdict: FEASIBLE (hardware cost is small; client disk is about 35 GB).

---

## Recommended toolchain

1. Stage A, lowest risk: Space Engineers 1 client (Steam, build 1.210.x), Pulsar (Legacy), single-player empty-space world, one custom C# plugin built from the Pulsar plugin template. The plugin does the 60 Hz loop: read `LocalCharacter` pose/velocity, the controlled cockpit's move/rotation indicators and grid poses; send over loopback UDP; apply incoming pose/velocity writes. The coordinator is Python with `socket` plus `struct`.
2. Stage B, optional headless: the same logic as a Magnetar server plugin (headless DS, no GPU), with the plugin spawning a bot character and driving it through `MoveAndRotate`. Only after verifying section 4 against the decompile.
3. Models: Steam "Space Engineers - Mod SDK" `OriginalContent` FBX, then Blender with SEUT to import and fix materials, then glTF or OBJ for NMS. Convert ASCII-FBX with Autodesk FBX Converter if needed. Parse `CubeBlocks` XML for block-to-model mapping.
4. Dev support: CometWorks/skills `se-dev-game-code` (decompile 1.210) so every UNVERIFIED symbol above is checked before use.
5. Avoid: Plugin Loader (dead), mwm reverse-engineering, any reliance on planets or SE gravity.

## Source list
- https://spaceengineers.wiki.gg/wiki/Plugins
- https://github.com/SpaceGT/Pulsar
- https://github.com/SpaceGT/Pulsar/releases/tag/v2.3.1
- https://github.com/CometWorks/magnetar
- https://github.com/CometWorks/direct-transport
- https://raw.githubusercontent.com/CometWorks/skills/main/README.md
- https://raw.githubusercontent.com/CometWorks/skills/main/skills/se-dev-plugin/SKILL.md
- https://raw.githubusercontent.com/CometWorks/skills/main/skills/se-dev-server-code/SKILL.md
- https://spaceengineers.wiki.gg/wiki/Dedicated_Server
- https://spaceengineers.wiki.gg/wiki/Modding/OfficialTools
- https://spaceengineers.wiki.gg/wiki/Modding/Tools/SEUT
- https://spaceengineers.wiki.gg/wiki/Modding/Tutorials/Setting_Up_a_Modding_Environment
- https://spaceengineers.wiki.gg/wiki/Gravity
- https://low.ms/knowledgebase/space-engineers-prosperity-1-210-update-your-server
- https://raw.githubusercontent.com/TorchAPI/Torch/master/README.md
