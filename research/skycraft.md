# SkyCraft v0.1.0 study (Skyrim SE visible renderer + hidden Minecraft Java mechanics)

Source: https://github.com/chasmlol/SkyCraft, tag v0.1.0 (shallow clone in a temp folder). Citations are repo-relative `path:line`.
Layout: `skse/` (C++ SKSE plugin on CommonLibSSE-NG), `fabric/` (Java Fabric mod), `protocol/` (shared header), `tools/` (README.md:181-186).
Caveat: `docs/DESIGN.md` is a draft (v0.1, 2026-09-29) and the shipped code diverged from it. Trust the code over the design doc (see section 7).

## 1. License and what we can reuse
- MIT, copyright 2026 chasmlol (LICENSE:1-3). Use, copy, modify, merge, publish, distribute, sublicense and sell are all allowed (LICENSE:5-8). The only condition is to keep the copyright and permission notice (LICENSE:12-13). No warranty (LICENSE:15-20).
- THIRD-PARTY-NOTICES.md:5-13 lists the plugin's dependencies: CommonLibSSE-NG, spdlog, fmt, SimpleIni (MIT) and xbyak (BSD-3).
- THIRD-PARTY-NOTICES.md:17-21 lists the bundled Minecraft pieces: Prism Launcher is GPL-3.0, Fabric API Apache-2.0, e4mc MIT. Prism is shipped unmodified as a separate program, so the GPL does not touch the mod code. If we ever bundle a launcher we need the same separation.
- Reusable verbatim (MIT) and engine-agnostic:
  - The seqlock, SPSC ring and triple-buffer patterns (`protocol/skycraft_protocol.h`, `skse/src/Link.cpp`, `fabric/src/main/java/dev/skycraft/link/SkyLink.java`).
  - The heartbeat, PID and named-mutex handshake.
  - The hidden-window and focus-spoof tricks, and the frame pacing.
  - Tick-timestamp interpolation.
  - The Havok-to-voxel collision exporter ideas.
- Not reusable for us: everything that touches Skyrim or Minecraft internals (REL::IDs, mixins, CommonLib types). Copy patterns, not code.

## 2. Shared memory, sync and rates

### Mapping
- One named file mapping, `Local\SkyCraft_v1` (protocol/skycraft_protocol.h:17), created by Skyrim with `CreateFileMappingW` on `INVALID_HANDLE_VALUE`, i.e. a pagefile-backed section (skse/src/Link.cpp:28-29). Minecraft opens it with `OpenFileMappingW` and `MapViewOfFile` through Java 25 FFM downcalls (fabric/src/main/java/dev/skycraft/link/SkyLink.java:41-46, 122-133).
- Retry is at most once a second (SkyLink.java:117-121).
- Total size is `kOffRenderRing + 64 MB` (protocol/skycraft_protocol.h:42): 32 MB collision ring + 3 x 33 MB overlay slots + 64 MB render ring, roughly 200 MB. All little-endian (header:7). Magic 0x43594B53 and version 10 are checked on open (header:15-16; SkyLink.java:134-139).
- On creation Skyrim zeroes every region it owns, because a stale mapping can survive (Link.cpp:43-53). Because Skyrim is the creator, Skyrim restart resets state; Minecraft detects it by the changed `skyrimPid` (SkyLink.java:107-114). A new Minecraft PID is detected by Skyrim (skse/src/Game.cpp:510-524).

### Fields and regions (protocol/skycraft_protocol.h)
| Offset | Region | Direction | Fields / sync |
|---|---|---|---|
| 0x0 | Header (0x20, :45-54) | both | u32 magic, version, skyrimPid, mcPid; u64 skyrimHeartbeatMs, mcHeartbeatMs (GetTickCount64) |
| 0x100 | SkyState (0x40, :78-90) | Sky->MC | seqlock `seq`; flags (InGame, MenuOpen, Loading, :57-62); worldId (worldspace or cell FormID); collisionEpoch; f64 posX/Y/Z; f32 yaw, pitch; teleportSeq; viewportW/H; gameHour |
| 0x200 | McState (0xC8, :105-139) | MC->Sky | seqlock `seq`; flags (InWorld, ScreenOpen, OnGround, Sneaking, Sprinting, Dead, Swimming, Flying, :93-103); f64 x,y,z (interpolated feet); yaw, pitch, eyeHeight, sensitivity; teleportAck; guiScale; frameCounter; fovDeg; bobPhase/bobAmount; f64 eyeX/Y/Z; raw 20 Hz tick block (tickQpc, prev/cur feet, tickEyeO/tickEye, walkDistO/walkDist, bobO/bob, tickMs); cameraMode (F5) and cameraDistance |
| 0x300 | OverlayCtl + 3 slot headers at 0x340 (:149-165) | MC->Sky | triple buffer. `state` bits 0-1 = middle slot index, bit 2 = dirty. Slot header: w, h, flags, frameId |
| 0x400 | WaterGrid (:69-76) | Sky->MC | seqlock; origin X/Z; worldId; 16x16 floats of water surface MC-y, or -1e30 for none |
| 0x1000 | Input ring (:168-171) | Sky->MC | SPSC, 4096 x 16-byte InputEvent {u16 type, u16 code, i32 a,b,c} (:457-465); head u64 at +0x00, tail u64 at +0x40, data at +0x80 |
| 0x12000 | ActorTable (:199-233) | Sky->MC | seqlock; count; up to 256 x 64-byte ActorRecord {formId, flags, xyz, yaw, width, height, healthFrac, level, name[24]} |
| 0x17000 | Event ring (:236-279) | MC->Sky | SPSC, 512 x 32-byte McEvent {type, formId, a,b,c,d, flags, weapon}: HitActor, PlayerDied, Explosion, ArrowStuck, SkillUse |
| 0x1C000 | WorldEntities (:284-319) | MC->Sky | seqlock; up to 160 x 96-byte entities (arrows, items, cracks, shadows) + block selection box |
| 0x20000 | Collision ring (:467-520) | Sky->MC | 32 MB byte ring, 8-aligned messages {u32 type, u32 bytes}; Clear/Region/Tris/Pad. A ColBlock is an 8x8x8 occupancy mask (64-bit rows) of one MC block, i.e. 1/8-block voxels. ColTri is exact triangles + flags |
| after overlay | Render ring (:321-350) | MC->Sky | 64 MB byte ring; messages Atlas, Section (vertex mesh per 16^3 section), Avatar, Scene, Texture, AtlasRegion, Lights, Solids, Ragdoll, ClearAll |

### Synchronisation (no locks, no kernel events in the hot path)
- Seqlocks for latest-value slots. The writer bumps `seq` to odd, fences, copies the payload and stores `seq+2` with release (skse/src/Link.cpp:85-97 SkyState, 99-111 water, 187-203 actors; Java writer SkyLink.java:315-323). Readers loop on acquire-load, bail if odd, copy, then re-check the seq (Link.cpp:113-133, 64 attempts; SkyLink.java:245-281, up to 1000 attempts, spinning then `Thread.yield`).
- SPSC rings with monotonically increasing u64 head and tail and release/acquire. Input is written in Link.cpp:135-151 and drained by Java (SkyLink.java:367). Events are read in Link.cpp:205-224. A slow consumer is not blocked: on overflow the reader skips to the newest 512 (Link.cpp:218-220). The byte rings add padding messages to wrap (Link.cpp:153-185, 250-276).
- Overlay triple buffer: lock-free `xchg` of the middle index plus a dirty bit (header:142-147; Link.cpp:278-290).
- Heartbeats: both sides write GetTickCount64 into the header (Link.cpp:78-83; SkyLink.java:106). Skyrim's timeout for MC is 3 s (Link.cpp:13, 63-71). MC's timeout for Skyrim is 8 s because loading screens stall Skyrim (SkyLink.java:22-23, 85).
- Clocks: both sides use QueryPerformanceCounter, so tick timestamps line up across processes (SkyLink.java:151-169).
- Named mutex `Local\SkyCraft_v1_minecraft`, held by Minecraft so Skyrim knows not to launch another (SkyLink.java:54-68; skse/src/Launcher.cpp:41-50).

### Update rates
- SkyState is written once per Skyrim frame, from the player-update hook (Game.cpp:954-971). Its seq advances by 2 per Skyrim frame.
- Minecraft is slaved to Skyrim: `paceFrame()` busy-waits up to 25 ms for the SkyState seq to change, then renders. It skips the wait if Skyrim is stalled, such as in a menu or after Alt-Tab (fabric/src/client/java/dev/skycraft/client/SkyClient.java:390-410). Minecraft's own limiter and vsync are overridden (SkyClient.java:412-418; client/mixin/FramerateLimitTrackerMixin.java:13-17).
- McState is written twice: once per MC render frame, for the interpolated camera (SkyClient.java:317-376); and once per 20 Hz physics tick, with raw prev/cur positions and a QPC timestamp (SkyClient.java:208-242).
- Skyrim interpolates between ticks on its own frame clock with an adaptive render delay of 4 to 30 ms, which removes judder from the two games' unsynchronised frame phases (Game.cpp:715-745; header:122-124).
- ActorTable: every Skyrim frame while puppeting (skse/src/Combat.cpp:872), range 80 blocks (Combat.cpp:7). The Minecraft server tick (20 Hz) reads it (SkyCombat.java:73-84, in fabric/src/main/java/dev/skycraft/combat/), and a client-side `ProxySync` re-positions the stand-ins every render frame (client/ProxySync.java:24-46).
- WaterGrid: every 3rd frame (Game.cpp:978-980). Collision regions next to the player are re-sent every 1 s (skse/src/Collision.cpp:13) with a 2.5 ms per-frame budget (Collision.cpp:14). The Minecraft consumer thread sleeps 2 ms when idle (fabric/src/main/java/dev/skycraft/world/SkyCollision.java:158-165).
- Overlay: the MC GUI layer is read back asynchronously with 3 staging buffers, so it is about one frame late. It is copied into shared memory as RGBA8 and published to the triple buffer (client/FrameExporter.java:14-20, 42-112). Skyrim draws it from a hook on D3D11 Present (skse/src/Overlay.cpp:370-407).

## 3. How Minecraft is launched and kept hidden
- The SKSE plugin launches it (skse/src/Launcher.cpp:225-273). Options in `SkyCraft.ini`: `bStartWithSkyrim`, `sLauncher`, `sArguments` (Launcher.cpp:230, 239-241; README.md:81-96).
- Default: a bundled portable Prism Launcher is unpacked with `tar.exe` to `%LOCALAPPDATA%\SkyCraft` (Launcher.cpp:116-173) and started with `--launch SkyCraft` (Launcher.cpp:240). A stamp file keeps Prism's accounts and the world while replacing the mod jars (Launcher.cpp:120-123, 140-145). Auth uses the user's own Microsoft account in Prism, because the official launcher cannot be launched into a profile from outside (Launcher.cpp:17-18).
- It starts the process through Explorer's COM `IShellDispatch2::ShellExecute` on the desktop view, so the child is not Skyrim's child. This keeps it out of Mod Organizer's virtual file system and out of MO2's wait list. It falls back to CreateProcess (Launcher.cpp:52-97, 177-202).
- It starts at most one: it checks the named mutex first (Launcher.cpp:41-50, 234-237).
- Hidden, in three layers:
  - JVM flag `-Dskycraft.startHidden=true`. On the first frame it hides the window with `SDL_HideWindow`, sets music volume to 0 and stops the title music (SkyClient.java:20-25, 73-79, 432-439).
  - Window mixins force `isFocused` to return true while linked and `isIconified` to return false (client/mixin/WindowMixin.java:32-46). Minecraft therefore never pauses or grabs the real mouse. `pauseOnLostFocus` is off (SkyClient.java:415). When unlinked it reports unfocused so it never grabs the hidden mouse (WindowMixin.java:34-37).
  - A mixin skips the "Loading terrain" wait, because Minecraft never renders its level (client/mixin/WaitingForPlayerChunkMixin.java:9-15).
- The Minecraft window is resized to Skyrim's viewport so the overlay matches (SkyClient.java:441-450). Render and simulation distance are set to 8 (SkyClient.java:419-423).
- Lifecycle: it auto-opens or creates the world "SkyCraft" from the title screen once linked (client/MirrorWorld.java:105-166). It quits itself 5 s after Skyrim's PID disappears (SkyClient.java:147-171). Dev flags `-Dskycraft.quitWithSkyrim=false` and `-Dskycraft.showWindow=true` (SkyClient.java:20, 150).
- The world is a void "mirror" world: custom dimension -1024..+1024 high, with mob spawning, time and weather gamerules off (fabric/src/main/resources/data/skycraft/dimension_type/mirror.json:19-22; fabric/src/main/java/dev/skycraft/SkyCraft.java:35-50).

## 4. Mapping positions, rotations, entities
- Scale: 1 block = 70 Skyrim units (protocol/skycraft_protocol.h:19-20). Chosen because the MC player is 1.8 blocks and the Skyrim player about 128 units (header:19; docs/DESIGN.md:55).
- Axes (skse/src/Link.h:68-80). `SkyToMc = (x/70, z/70, -y/70)` and `McToSky = (x*70, -z*70, y*70)`. Skyrim is Z-up with +Y north, Minecraft is Y-up with -Z north. Headings: `mcYaw = heading_deg + 180`, `heading = (yaw - 180)` in radians (Link.h:79-80). All protocol coordinates are Minecraft space (header:8).
- Havok: converted via `GetWorldScaleInverse() / 70`, noting that a Havok unit is 69.99125 game units (skse/src/Collision.cpp:21-25).
- Look direction: Skyrim integrates raw mouse deltas with Minecraft's sensitivity formula and owns yaw and pitch. That gives a zero-latency camera; Minecraft just copies them to the player each frame (Game.cpp:578-591; SkyClient.java:138-144). The Skyrim camera is set to Minecraft's eye position, FOV (vertical to Skyrim's horizontal, Game.cpp:229-244), bob and F5 mode (Game.cpp:795-850).
- Player: Minecraft is authoritative. Skyrim's player is a puppet moved with `SetPosition(McToSky(feet))` every frame, with velocity zeroed and the character controller flagged on-ground or in-air from Minecraft's state (Game.cpp:771-791). Skyrim's PlayerControls handler is hooked to swallow all native input (skse/src/Input.cpp:241-251). Skyrim's controls are deliberately left enabled, because NPC combat AI is skipped if they are off (skse/src/Game.cpp:267-294, `EnsureControlsEnabled`).
- Teleports and world change use `teleportSeq`/`teleportAck`. If Skyrim moves the player more than 300 units, or on load, door or fast travel, Skyrim bumps `teleportSeq` and MC teleports its player. MC then holds the player still until Skyrim's collision has arrived (Game.cpp:17, 559-576; SkyClient.java:127-136, 244-287).
- World identity: `worldId` is a worldspace FormID for exteriors or the cell FormID for interiors. A change bumps `epoch`, which drops all MC-side collision (Game.cpp:545-557; header:81-83). All interiors share one Minecraft world, so blocks appear across interiors (README.md:143-144).
- Terrain: Skyrim collision reaches Minecraft as data, not blocks. A worker thread reads the Havok `bhkWorld` shapes under a read lock (Collision.cpp:243-244, 264-292), voxelises them into 1/8-block occupancy plus exact triangles, and streams them in regions (radius 5 regions, Collision.cpp:9-12; header:479-520). Minecraft injects the shapes into its own collision queries (docs/DESIGN.md:78-85; mixins `BlockCollisionsMixin`, `EntityCollideMixin`). Steep slopes (> about 50 degrees) are coarsened into walls (Collision.cpp:17-18).
- Entities, Skyrim to Minecraft: each Skyrim actor within 80 blocks becomes an invisible server-side `SkyrimActorEntity` "proxy" (a real LivingEntity) with a Skyrim-sized hitbox (width = 2 x BoundRadius/70, height = GetHeight/70), name and health fraction (Combat.cpp:171-215; SkyCombat.java:98-130; ProxySync.java:35-45). Vanilla Minecraft combat code runs on the proxy. Hits are collected per tick and sent as `kEvHitActor` (SkyCombat.java:87-95).
- Entities, Minecraft to Skyrim: Minecraft builds the meshes (block sections, avatar, other entities and particles, atlas) and Skyrim draws them in its own render pass, so they are depth-tested and shadowed by Skyrim (header:321-350; skse/src/WorldRender.cpp:1100-1108 for message dispatch; hooks at WorldRender.cpp:3263-3286). Arrows, drops and cracks go through a separate small table (header:281-307).
- Damage scaling (constants): MC to Skyrim is `mcDamage * (5 + 0.25 * npcLevel)` (Combat.cpp:331-332). Skyrim to MC is `skyrimDamage / 5` (SkyCombat.java:55-56, 204).
- Hits go through Skyrim's own hit pipeline (`HitData` plus a hooked function, Combat.cpp:346-373, with a `DoDamage` fallback at 374-384).
- Block collision for NPCs: Minecraft publishes solid-block bitsets (`kRenSolids`, header:344-345), and the plugin hooks the pathing code (skse/src/PathAvoid.cpp:5 and 165-180, `REL::ID(41642)` plus 7 callers).
- Skyrim skills level up from Minecraft actions through `kEvSkillUse` (header:248-249).

## 5. Input flow
- Skyrim owns the physical window and focus. A `BSInputDeviceManager` event sink captures every key, mouse button, scroll, mouse move and char event. It converts (DirectInput scancode table to SDL scancode, Input.cpp:8-34; mouse button remap :173) and pushes onto the input ring (Input.cpp:96-190; Link.cpp:135-151). Minecraft drains it at the start of each frame and replays it into its own `KeyboardHandler`/`MouseHandler` with synthetic `KeyEvent`s, keeping a virtual key state for `isKeyDown` (client/InputBridge.java:31-75, 99-120).
- Routing is by state, not by a mode toggle.
  - Skyrim menu or loading: routing is off and held keys are released (Input.cpp:104-111; SkyClient.java:110-112).
  - A small allow-list stays with Skyrim: G (activate), H (wait), Esc, `~`, J, M, F9 go to Skyrim; O opens Minecraft's pause screen (Input.cpp:36-49, 145-161, 212-216).
  - A Minecraft screen open: all keys, mouse and text go to Minecraft, with a virtual cursor kept in overlay pixels (Input.cpp:121-127, 181-185).
  - Skyrim's `MenuControls` and `PlayerControls` are vfunc-hooked to swallow the rest (Input.cpp:197-251, 261-264).
- Skyrim-to-Minecraft hurt events travel back on the same ring as `kInHurt` (header:181; InputBridge.java:77-97).
- Activation: pressing G triggers Skyrim's crosshair target (`ActivateRef`), skipping furniture because Minecraft owns the player position (Input.cpp:54-74). The design called for nearest-target arbitration (docs/DESIGN.md:123-127); the shipped version uses a dedicated key instead.
- Mouse look bypasses the ring: Skyrim integrates deltas locally and sends the resulting yaw and pitch in SkyState (Game.cpp:578-591, 963-964).

## 6. Multiplayer
- It is vanilla Minecraft multiplayer, Minecraft side only. README.md:98-113: the host presses O, "Open to LAN", and the bundled e4mc mod gives an `abc-def.e4mc.link` address. Friends type `/join <link>`. Up to 100 players. Each player keeps their own Skyrim world, NPCs and quests (README.md:100-101).
- Implementation:
  - `MirrorWorld.joinFriend` disconnects and reconnects the Minecraft client to the address through the normal `ConnectScreen` (client/MirrorWorld.java:59-68, 135-144). `/leave` and an automatic fall-back return to the local world (MirrorWorld.java:79-89, 105-116).
  - Host and guests all run their own Skyrim and SkyCraft. The host's Skyrim talks to the host's integrated server by shared memory; a guest's Skyrim talks to the host's server through custom Fabric payloads `Hurt` (guest to server) and `Died` (server to guest) (fabric/src/main/java/dev/skycraft/net/SkyNet.java:14-49, 51-60).
  - A mixin raises the LAN player cap to 100 (client/mixin/IntegratedServerMixin.java:9-15). Another disables anti-fly kicking because guests stand on Skyrim ground the host server cannot see (fabric/src/main/java/dev/skycraft/mixin/MinecraftServerFlightMixin.java:10-16). `maybeBackOffFromEdge` is also overridden (mixin/PlayerEdgeMixin.java:12-19).
  - Remote players are drawn by Minecraft's own entity renderer into the scene mesh stream (`kRenScene`, header:339-340).
  - The server trusts guests only up to a clamp: damage is capped at 10000 per hit (SkyNet.java:56-58).
- Discord rich presence provides a Join button (README.md:111-113; client/DiscordPresence.java).
- Test aids: `tools/fake_skyrim.py` and `tools/fake_guest.py` simulate the other end of the link (README.md:186).

## 7. Limitations and hacks to avoid
Limitations (README.md:132-148):
- Skyrim inventory, magic, shouts and perks are unavailable while Minecraft drives the player.
- Minecraft hits do not reach Skyrim objects, only NPCs. There is no in-game way back to plain Skyrim.
- Signs are not drawn. Interiors share one Minecraft world.
- Guests cannot hit their own Skyrim NPCs; in multiplayer only the Minecraft world is synced.
- Camera mods (Improved Camera SE, SmoothCam, True Directional Movement) conflict.
- Skyrim SE 1.6/1.7 only (README.md:49), not 1.5.97 and not VR.

Hacks and fragilities:
- Binary-address dependence. Hooks use `REL::ID` numbers plus hard-coded offsets, so they break on each game build: WorldRender.cpp:3275-3286, Combat.cpp:234-244 and 675-679, Game.cpp:490 and 1211, PathAvoid.cpp:165-179.
- Reverse-engineered Havok shape layouts are read at raw offsets and wrapped in fault guards (Collision.cpp:214, 370, 467-501).
- Hook on the D3D11 Present vtable (Overlay.cpp:370-407).
- About 30 mixins into Minecraft internals (client/mixin/*, main/mixin/*), pinned to Minecraft 26.3 and Java 25 (docs/DESIGN.md:24-28, 248).
- Behaviour-defeating tricks: focus and iconify spoofing (WindowMixin.java), skipping the chunk wait (WaitingForPlayerChunkMixin.java), forcing the player `essential` so Skyrim cannot kill it (Combat.cpp:869-871), freezing the player until collision arrives and lifting it out of geometry (SkyClient.java:244-293).
- CPU path for the overlay: MC main render target readback to RGBA8 in shared memory, about one frame late, sized for up to 3840 x 2160 x 4 x 3 slots (header:33-36; FrameExporter.java:14-20).
- Geometry streaming is a very large custom protocol: the render ring is 64 MB and carries every mesh. It works, but it is the biggest source of coupling.
- Bundled launcher: depends on Microsoft sign-in via Prism, extracts to `%LOCALAPPDATA%`, uses the Explorer-COM launch trick (Launcher.cpp:52-97).
- Polling and busy-waits: `paceFrame` spins up to 25 ms, 2 ms sleep loops, seqlock spins of up to 1000 attempts (SkyClient.java:399-406; SkyCollision.java:158-165; SkyLink.java:251).
- Design doc vs reality: DESIGN.md planned GPU texture sharing (OpenGL/Vulkan to D3D11 interop) with frame-lockstep fences (docs/DESIGN.md:168-176) and `PlayerState` view matrices plus named events (docs/DESIGN.md:182-187). The shipped code does none of that: CPU readback, mesh streaming, spinning on seq, no named events. Dimension range also differs (DESIGN.md:65 says -2032/4064; JSON says -1024/2048, mirror.json:19-22).

## 8. Lessons for our design (NMS visible; Space Engineers 1 and KSP 1.12.5 hidden)

What transfers directly:
1. Split authority per quantity. SkyCraft is exact about this. Minecraft is authoritative for the body: position, physics, health, inventory (docs/DESIGN.md:100-102). Skyrim is authoritative for the world: terrain, NPCs, look direction, time (SkyState). For us: NMS owns the camera and world rendering; SE owns character and ship physics; KSP owns orbits. Each field in the protocol gets one writer.
2. Make the visible game the pacing clock and the hidden game a follower (SkyClient.java:390-410). Keep raw fixed-rate ticks with a QPC timestamp and let the visible renderer interpolate (Game.cpp:715-745). That matters for KSP and SE, which tick at fixed physics rates while NMS renders at an uncorrelated frame rate.
3. Use seqlocks for latest-value state, SPSC rings for events and bulk, and a header with heartbeats and PIDs. No kernel calls in the hot path; add a protocol version and magic. Both ends must re-sync on peer restart (generation counters, epoch bumps, teleportSeq/teleportAck; Link.cpp:43-53; SkyLink.java:88-91).
4. Hidden-game recipe: spoof focus and iconify, mute audio, shrink render distance and skip level rendering (WindowMixin.java, SkyClient.java:412-439). For SE, a dedicated server avoids all of it (no window). Our hidden processes should be launched and supervised by the coordinator, via a detached shell launch if a mod manager or sandbox must stay unlocked (Launcher.cpp:52-97).
5. Heartbeats and graceful degradation. When the peer dies, freeze and hold state rather than fall to defaults (SkyClient.java:187-201; Game.cpp:934-945).
6. Keep both games' logic unmodified; translate, never reimplement (docs/DESIGN.md:18). Feed the hidden game only the data it needs from the visible one (SkyCraft's Havok exporter), or avoid that coupling.

What does not transfer:
- SkyCraft's heavy parts (collision voxelisation, mesh streaming, depth-composited draw hook) exist because the hidden game's output must be drawn inside the visible one. With NMS as renderer we do not need Minecraft-style block meshes. We need a small set of poses: ship, character, planet, orbit objects. SE and KSP supply kinematics, not geometry, so the render protocol can be a few hundred bytes of poses. Treat SkyCraft's overlay and render-ring work as "later, maybe", not as a model.
- Coordinates are the real risk for us. SkyCraft has one fixed scale (70 units/block, header:19-20) and one flat world, so doubles in the protocol are enough (header:84, 109, 120). NMS (planetary, with its own origin and rebasing), SE (large worlds, planet gravity) and KSP (orbital frames, 1e10 m scales, floating origin) need an explicit frame graph. Put a frame ID plus a double-precision origin in every pose, as `RenScene` does with `originX/Y/Z` (header:404-409) and `worldId`/`collisionEpoch` (header:81-83). Keep SkyCraft's rule of one conversion function per end (Link.h:68-80), written once and unit tested.

Coordinator versus pairwise shared memory:
- SkyCraft is pairwise (one mapping, Skyrim creates, Minecraft joins) and gets away with it because there are two processes and one link. Its multiplayer is a separate network layer (SkyNet payloads plus vanilla Minecraft networking), with the guest's Skyrim pushing events through a Minecraft client to the host server (SkyNet.java:14-49). Already awkward: two parallel paths for the same events (shared-memory ring for the host, InputBridge.java:83-97; packet for guests).
- With three games and co-op, N pairwise links is O(N^2), each needing its own handshake, version and restart logic. Recommendation: a central coordinator that owns routing and authority.
  - Each game talks only to the coordinator. Per-game shared memory is still fine (the same SkyCraft patterns; the coordinator is the side that creates the mappings). Python pyMHF hooks in NMS and C# plugins in SE and KSP each implement one small client of one protocol.
  - The coordinator holds the world model: canonical frame graph, entity table, authority map, tick scheduler, heartbeats, restarts. It does the unit and frame conversions once.
  - Real networking (TCP/UDP) lives only at the coordinator, for co-op, reusing the same message types between coordinators, so there is one event path instead of two.
  - It also supervises hidden processes, applies a global pacing clock, and can record and replay. SkyCraft's `fake_skyrim.py`/`fake_guest.py` stand-ins show the value of testing against a fake peer (README.md:186).
- Cost: one more hop and one more process. For the hot path (pose to NMS camera) use the coordinator as a shared-memory switchboard, not a socket relay. It can expose seqlock slots to peers directly and copy only when it must transform.
- For KSP via kRPC: kRPC is already a coordinator-style RPC server over TCP. Put a thin bridge in the coordinator, subscribe to streams at tick rate and republish into shared memory. Do not have NMS talk to kRPC directly.

Co-op shape:
- Mirror SkyCraft's principle: each player has their own visible NMS, and only the hidden-game world is shared (README.md:98-101, 145-146). The hidden simulations are the shared world (one SE dedicated server and one KSP instance for the group, or per-player KSP with synced orbits), and each player's NMS is a view onto it.
- Prefer one authoritative host for the shared hidden sim (an SE dedicated server fits natively). Clients send input events and receive state, like SkyCraft's guests (SkyNet.Hurt, Died). Guests then need no copy of the hidden game. SkyCraft needs every guest to run Minecraft only because it uses the integrated server; we can avoid that cost.
- Trust model: clamp and validate client claims on the host (SkyNet.java:56-58); assume friends only unless we build more.
- Be explicit about what is shared. SkyCraft chose "Minecraft world shared, Skyrim worlds separate" and hit real limits: guests cannot hit their own Skyrim NPCs (README.md:145-146). For us the equivalent question is whether NMS planets and discoveries are shared; in a visible-renderer-only role, NMS state stays local, which is simplest.
- Other players must be rendered in the visible game. SkyCraft has Minecraft draw them into the mesh stream. For us a pose-only protocol plus NMS-side remote avatars or ships is much cheaper.

Concrete recommendations:
1. Adopt SkyCraft's primitives as written: header and heartbeat, seqlock, SPSC ring, triple buffer, QPC-stamped ticks, generation counters. Use `protocol/skycraft_protocol.h` as the template for a versioned single-source-of-truth header with a mirrored class per language and `static_assert` layout checks (header:4-6, 54, 90, 139).
2. Do not copy the render-ring/mesh and collision-voxel designs unless NMS needs actual geometry from SE or KSP. Start with poses and events.
3. Build the coordinator early, with a fake peer per game (like `tools/fake_*.py`), so each plugin is testable alone.
4. Define the frame graph and unit conversions first. Scale and axis conversion is the first thing SkyCraft pins down (Link.h:68-80, yaw offset of 180 degrees).
5. Avoid reverse-engineered address IDs where an official API exists (SE: plugin API, KSP: KSPAddon/kRPC). NMS.py/pyMHF is the analogue of SkyCraft's `REL::ID` hooks and will break across NMS updates; isolate those hooks in one module with a version table and fail soft (SkyCraft logs and skips a missing hook site, WorldRender.cpp:3263-3286).
6. Pace hidden sims to the visible renderer only where that is safe. An SE dedicated server and KSP should run on their own fixed ticks, with NMS interpolating between ticks as Skyrim does (Game.cpp:715-745). Spin-waiting on the visible game's frame counter (SkyClient.java:390-410) is a hack to use only for latency-critical, locally hosted pairs.
