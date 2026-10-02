# KSP 1.12.5 modding for Constellation (research, 2026-10-02)

Scope: complements ksp-bodies.md (body pool, Kopernicus, runtime CelestialBody mutation, Principia). Not repeated here except where new evidence changes it.

Method and limits. I read GitHub raw sources/API (krpc/krpc, KSP-CKAN/CKAN-meta, Ezriilc/HyperEdit, LunaMultiplayer) and the kRPC v0.6.0 docs, and I inspected the KSP 1.12.5 install on this machine by reflection and compiled a test addon against it. The network then dropped (DNS failure) and the KSP forum, KSP wiki, KSP API pages and SpaceDock were never reachable from this sandbox, only via search snippets. Tag meaning: VERIFIED = read or run myself; SNIPPET = from a web-search result summary only; UNVERIFIED = memory/inference.

## 1. Building a plugin with the .NET SDK

- Runtime. VERIFIED locally: `KSP_x64_Data/Managed/mscorlib.dll` is 4.0.0.0 and `Assembly-CSharp.dll` has image runtime v4.0.30319; Unity is 2019.4.18f1 (read from `globalgamemanagers`); Mono, not .NET Core. There is no `netstandard.dll` in Managed. So target **net472** (the .NET Framework 4.x API surface Unity's "4.x" profile exposes). net48 also compiles but adds nothing; net472 is the usual choice (SNIPPET: KSPBuildTools docs https://kspbuildtools.readthedocs.io/en/latest/msbuild/configuration.html). Avoid netstandard2.x and net8.
- Assemblies to reference from `KSP_x64_Data/Managed` (SNIPPET + VERIFIED to compile): `Assembly-CSharp.dll` (KSPAddon, MapView, Orbit, Vessel, FlightGlobals, TimeWarp), `Assembly-CSharp-firstpass.dll`, `UnityEngine.dll`, `UnityEngine.CoreModule.dll` (MonoBehaviour, Application, Debug), `UnityEngine.InputLegacyModule.dll` (Input), `UnityEngine.PhysicsModule.dll`, `UnityEngine.UI.dll` only if you use UI. Set `Private=false`/`CopyLocal=false` so they are not copied to GameData. Forum how-to: https://forum.kerbalspaceprogram.com/topic/153765-getting-started-the-basics-of-writing-a-plug-in (SNIPPET).
- Gotcha, VERIFIED: this machine has only SDK 8.0.419 and no `Reference Assemblies\...\v4.7.2` and no `microsoft.netframework.referenceassemblies*` in the NuGet cache. A `net472` csproj needs the NuGet package `Microsoft.NETFramework.ReferenceAssemblies` (one online restore), or use the fallback below.
- Offline fallback, VERIFIED working: Roslyn from the SDK against KSP's own mscorlib:
  `dotnet "C:\Program Files\dotnet\sdk\8.0.419\Roslyn\bincore\csc.dll" -nologo -nostdlib+ -target:library -out:Constellation.dll -r:<Managed>\mscorlib.dll -r:<Managed>\System.dll -r:<Managed>\System.Core.dll -r:<Managed>\Assembly-CSharp.dll -r:<Managed>\Assembly-CSharp-firstpass.dll -r:<Managed>\UnityEngine.dll -r:<Managed>\UnityEngine.CoreModule.dll -r:<Managed>\UnityEngine.InputLegacyModule.dll A.cs` produced a DLL with exit 0 (test file in scratchpad, not in the project). Stick to C# features that do not need new runtime types (no records/init, no Span, no System.Text.Json).
- Minimal addon (this exact source compiled, VERIFIED compile only, never run in the game):
  ```csharp
  using UnityEngine;
  namespace Constellation {
    [KSPAddon(KSPAddon.Startup.Flight, false)]   // false = recreated every flight-scene load
    public class ConstellationFlight : MonoBehaviour {
      void Start() { Application.runInBackground = true;
                     Debug.Log("[Constellation] bodies=" + FlightGlobals.Bodies.Count); }
      void Update() { if (Input.GetKeyDown(KeyCode.M) && !MapView.MapIsEnabled) MapView.EnterMapView(); }
    }
  }
  ```
  Use `KSPAddon.Startup.MainMenu` with `once=true` for a loader that lives the whole session (same pattern Sigma Dimensions uses, per ksp-bodies.md).
- Install: `<KSP>\GameData\Constellation\Constellation.dll` (any subfolder of GameData is scanned; plugin DLLs go in `GameData/<ModName>/` or `GameData/<ModName>/Plugins/`). SNIPPET (forum 153765 above). Logs go to `KSP.log`/`Player.log` via `Debug.Log`.
- Target-version note: add a `.version` file or CKAN metadata only if you ever distribute; not needed for a private install.

Verdict: FEASIBLE (compile path verified end to end on this machine; only the NuGet ref-assembly restore or the csc fallback is needed).

## 2. kRPC

- Version. kRPC **v0.6.0**, released 2026-07-22, CKAN `ksp_version_min 1.12.3`, `ksp_version_max 1.12.5`, depends on ModuleManager (VERIFIED: https://raw.githubusercontent.com/KSP-CKAN/CKAN-meta/master/kRPC/kRPC-v0.6.0.ckan). Previous release 0.5.4 (2024-06-10). Repo is active (pushed 2026-09-27; https://github.com/krpc/krpc). Release notes (https://api.github.com/repos/krpc/krpc/releases/tags/v0.6.0, VERIFIED): TCP_NODELAY on client sockets (lower RPC round trip), settable `KRPC.GameScene`, Python client needs 3.10+.
- Protocol, VERIFIED (https://krpc.github.io/krpc/latest/communication-protocols/tcpip.html): protobuf messages prefixed with a varint length over TCP. RPC port 50000, optional separate stream port 50001 (client first connects to RPC to get a 16-byte client id). Also websockets and serialio exist. Python 3 client is `pip install krpc`.
- Streams: server pushes a value when it changes; each stream has a settable `rate` in Hz, 0 = unlimited (VERIFIED, python client docs https://krpc.github.io/krpc/latest/python/client.html). So 30-60 Hz position streams are a supported use. **Measured throughput or latency: none found. UNVERIFIED.** My expectation (UNVERIFIED): calls are executed on the Unity main thread, so effective rate is bounded by KSP's frame/FixedUpdate rate (about 50 Hz fixed, whatever the render FPS is for Update), and a hidden low-FPS KSP would cap streams accordingly. Measure it on your machine early.
- Read orbits and body positions: yes, VERIFIED from the v0.6.0 API listing (https://krpc.github.io/krpc/latest/python/api/space-center/orbit.html, .../celestial-body.html, .../vessel.html): `Orbit` has semi_major_axis, eccentricity, inclination, longitude_of_ascending_node, argument_of_periapsis, mean_anomaly_at_epoch, epoch, period, time_to_soi_change, next_orbit, position_at(ut, frame), true_anomaly_at_ut, closest approaches. `CelestialBody` has position(frame), velocity, radius (`equatorial_radius`), gravitational_parameter, sphere_of_influence, orbit, rotation. `Vessel` has orbit, position, velocity, packed, situation. I did not see a setter for any of those in the listing.
- Write orbits or body state: **no** in stock kRPC (no `set_orbit`, no body mutation in the listed members). There is `Extending kRPC` (write your own service in C# that kRPC exposes), but then you are writing the KSP-side plugin anyway.
- Comparison with a custom plugin over UDP or memory-mapped file (UNVERIFIED design reasoning; Mono in KSP has `System.Net.Sockets` and `System.IO.MemoryMappedFiles` in net472 surface, not tried):
  - kRPC: zero KSP-side code to read state, typed API with polling and streams, Python client ready; costs: protobuf stack, main-thread execution, cannot mutate bodies/orbits, extra mod install (ModuleManager).
  - Custom UDP on 127.0.0.1: tiny latency, one small packet per tick (the body pool is about 10 bodies, so a few hundred bytes), full write access from the plugin; read the socket on a background thread, enqueue, and apply in FixedUpdate. Memory-mapped file gives a lock-free latest-state block with no packets but needs a sequence-counter protocol and polling on the Python side; UDP is simpler and enough here.
  - Practical split: use a custom plugin for everything that writes (bodies, vessels, warp, scene) and for outbound state at the rate you choose; keep kRPC only as an optional debug/inspection channel.

Verdict: kRPC for reading is FEASIBLE; kRPC for setting orbits/bodies is BLOCKED (custom plugin required); the combined design is FEASIBLE with a custom plugin as the primary link.

## 3. Running KSP cheaply

- Window flags, SNIPPET (KSP wiki Startup parameters https://wiki.kerbalspaceprogram.com/wiki/Startup_parameters via search summary, page not fetchable): `-popupwindow` (borderless; needs Full Screen off in settings), `-screen-width N -screen-height N`, `-single-instance`, `-force-d3d11`, `-screen-quality Fastest`, standard Unity player flags (Unity manual https://docs.unity3d.com/2020.3/Documentation/Manual/PlayerCommandLineArguments.html). `-batchmode`/`-nographics` break the map view (see ksp-bodies.md; UNVERIFIED either way). Settings are also in `GameSettings.SCREEN_RESOLUTION_WIDTH/HEIGHT, FULLSCREEN, FRAMERATE_LIMIT, PHYSICS_FRAME_DT_LIMIT` (all VERIFIED present in this 1.12.5 Assembly-CSharp; `settings.cfg` does not exist yet in this install, so KSP has not been run here to generate it).
- Background running: Unity `Application.runInBackground` (https://docs.unity.cn/2023.2/Documentation/ScriptReference/Application-runInBackground.html, SNIPPET: default false). KSP also has its own in-game option `GameSettings.SIMULATE_IN_BACKGROUND` (VERIFIED present). Set both from your plugin at startup (`Application.runInBackground = true; GameSettings.SIMULATE_IN_BACKGROUND = true;`). Whether KSP itself already forces runInBackground: UNVERIFIED.
- Skip the main menu, SNIPPET: forum threads "Auto load on startup code" (https://forum.kerbalspaceprogram.com/topic/70665-0235-updated-auto-load-on-startup-code) and "command line to auto-load quicksave" (.../topic/103007-command-line-to-auto-load-quicksave); no maintained 1.12 mod found (UNVERIFIED). Easiest is your own `[KSPAddon(KSPAddon.Startup.MainMenu, true)]` that calls the real APIs, which all VERIFIED exist in 1.12.5: `GamePersistence.LoadGame(string,string,bool,bool)`, `HighLogic.LoadScene(GameScenes)`, `FlightDriver.StartAndFocusVessel`, `HighLogic.CurrentGame`. Exact call sequence not run: UNVERIFIED. There is no stock command-line save loader.
- Warp and timestep. Field names VERIFIED on `TimeWarp`: `warpRates`, `physicsWarpRates`, `altitudeLimits`, `maxPhysicsRate_index`, `SetRate(int, bool instant, bool)`, `GetAltitudeLimit`. Stock values (UNVERIFIED, from memory): rails rates 1,5,10,50,100,1000,10000,100000x, physics warp 1-4x, altitude-limited near bodies. On rails, warp cost is analytic (Kepler propagation), so 100000x is cheap; the cap is per-body altitude limits, not the physics timestep. Physics runs at fixed 0.02 s (UNVERIFIED), physics warp 4x just runs more steps per frame. For your design, planets are on rails, so only UT matters; set UT via warp or by setting `Planetarium` time (API not checked: UNVERIFIED).
- Load time is mostly the one-off game start (see ksp-bodies.md section 4); not measured.

Verdict: RISKY (everything needed exists, but hidden/background rendering and startup auto-load are unproven here).

## 4. Putting a vessel (or body) into a given orbit

HyperEdit is the reference: https://github.com/Ezriilc/HyperEdit (pushed 2026-04-12, master; VERIFIED by reading `Source/Model/OrbitEditor.cs` via raw.githubusercontent.com). What it does to teleport a vessel (`Vessel.SetOrbit`):
1. Reject if the target radius is above the reference body SOI or below its surface.
2. `vessel.PrepVesselTeleport()` (HyperEdit helper), then `OrbitPhysicsManager.HoldVesselUnpack(60)` to stop it unpacking for 60 frames.
3. `GoOnRails()` on every vessel in `FlightGlobals.fetch.vessels`.
4. "HardsetOrbit": copy inclination, eccentricity, semiMajorAxis, LAN, argumentOfPeriapsis, meanAnomalyAtEpoch, epoch, referenceBody into the existing `orbitDriver.orbit`, then `orbit.Init()` and `orbit.UpdateFromUT(Planetarium.GetUniversalTime())`; if the reference body changed invoke `orbitDriver.OnReferenceBodyChange`.
5. `vessel.orbitDriver.pos = vessel.orbit.pos.xzy; vessel.orbitDriver.vel = vessel.orbit.vel;` and fire `GameEvents.onVesselSOIChanged` if the body changed, then `FloatingOrigin.ResetTerrainShaderOffset()`.
Notes: inclination and LAN of exactly 0 are nudged to 0.0001 to avoid degenerate math; sign of `sma` is forced negative for hyperbolic orbits.

Signatures VERIFIED by reflection on the local 1.12.5 `Assembly-CSharp.dll`: `Orbit.SetOrbit(double inc, e, sma, lan, argPe, mEp, t, CelestialBody)`, `Orbit.UpdateFromStateVectors(Vector3d pos, Vector3d vel, CelestialBody, double UT)`, `Orbit.UpdateFromFixedVectors`, `Orbit.UpdateFromOrbitAtUT`, `Orbit.Init()`, `Orbit.UpdateFromUT`, `Orbit.getRelativePositionAtUT`; `Vessel.SetPosition(Vector3d[, bool usePristineCoords])`, `SetWorldVelocity`, `SetRotation`, `GoOnRails()`, `GoOffRails()`, `IgnoreGForces(int)`; `OrbitDriver.SetOrbitMode(UpdateMode)`, `UpdateOrbit(bool)`, `updateFromParameters()`, `RecalculateOrbit(CelestialBody)`, `TrackRigidbody`; `OrbitDriver.UpdateMode` = {TRACK_Phys, UPDATE, IDLE}; `OrbitPhysicsManager.HoldVesselUnpack(int)`; `PatchedConicSolver.Update()/UpdateFlightPlan()`; `GameSettings.DEBUG_MAX_SETPOSITION_ALTITUDE`.

On-rails rules (HyperEdit code + API names; the semantics are partly UNVERIFIED): a packed/on-rails vessel is driven by its `OrbitDriver` in `UPDATE` mode, so writing the Keplerian elements and re-`Init()` moves it. A physics-loaded (unpacked) vessel is `TRACK_Phys`: the orbit is recomputed from the rigidbody each physics frame and your write is overwritten, which is why HyperEdit packs everything first and holds unpack. Moving a loaded vessel in space uses `SetPosition` plus `SetWorldVelocity` instead. Spawning a brand-new vessel at a given orbit (ProtoVessel ConfigNode with an ORBIT block, then `HighLogic.CurrentGame.AddVessel`) is the standard approach (UNVERIFIED, I did not check that API); the alternative is to keep one persistent vessel and re-orbit it with the recipe above.

New and important for ksp-bodies.md: HyperEdit also mutates **CelestialBody orbits at runtime**: `body.SetOrbit(newOrbit)` writes the same Keplerian fields into `body.orbitDriver.orbit`, `Init()`, `UpdateFromUT`, moves the body between `orbitingBodies` lists if the parent changes, and calls `body.RealCbUpdate()` (HyperEdit extension, UNVERIFIED what it contains; `CelestialBody.CBUpdate()` and `SetupConstants()` exist, VERIFIED). HyperEdit's `PlanetEditor.cs` changes GeeASL, atmosphere, rotation period, initial rotation, tidal lock and orbit live, but not radius or GM, so the runtime radius/GM/scaledBody path in ksp-bodies.md remains the unproven part. It also wraps Principia gravity hacks (Principia incompatibility stays).
Vessel Mover (https://github.com/BahamutoD/VesselMover, last push 2016-04-25, abandoned) only moves landed/loaded vessels; useless here.

Verdict: FEASIBLE for vessel and body orbit rewrites (shipping precedent in HyperEdit's source); RISKY for runtime radius/GM changes (still unproven).

## 5. Map view on demand

- `MapView.EnterMapView()` and `MapView.ExitMapView()` are static; `MapView.MapIsEnabled` is a static property; `MapView.MapCamera` exists (VERIFIED by reflection in 1.12.5). My test addon calls `EnterMapView()` on a keypress and compiled; not run. Flight scene (with an active vessel) and the Tracking Station have their own map handling; entering map in the wrong scene is UNVERIFIED. The stock map key is `GameSettings.MAP_VIEW_TOGGLE` (not checked).
- Rendering while unfocused: UNVERIFIED. Unity keeps running and rendering when `runInBackground` is true (https://docs.unity.cn/2023.2/Documentation/ScriptReference/Application-runInBackground.html, SNIPPET), and a topmost/offscreen window continues to present; a minimized window typically stops presenting on Windows (UNVERIFIED). Keep the window "shown but off-screen or behind" rather than minimized, and show/raise it with Win32 `ShowWindow`/`SetWindowPos` from the coordinator when the player hits the map key. Input will not reach a background window without focus, so forward the map key from the coordinator (or activate the window on demand).

Verdict: RISKY (API verified, background/hidden-window rendering and input handoff unverified).

## 6. Co-op with LunaMultiplayer

- Status. LMP 0.29.2 "for KSP 1.12", released 2026-05-17; 0.29.1 on 2026-04-24; a 0.30.0 nightly draft on 2026-06-02 (VERIFIED: https://api.github.com/repos/LunaMultiplayer/LunaMultiplayer/releases). CKAN `ksp_version "1.12"`, dependency Harmony2 (VERIFIED https://raw.githubusercontent.com/KSP-CKAN/CKAN-meta/master/LunaMultiplayer/LunaMultiplayer-0.29.2.ckan). Actively maintained; recent notes are crash/robustness fixes.
- Stack, VERIFIED (README https://raw.githubusercontent.com/LunaMultiplayer/LunaMultiplayer/master/README.md): UDP via Lidgren, NTP time sync, entity interpolation, NAT punchthrough, UPnP, IPv6; science/funds shared in career. Server is a separate .NET app; the 0.29.1 notes say it checks for the **.NET 6 runtime** at startup (so install .NET 6 runtime next to the 8 SDK).
- Subspace and warp model: **UNVERIFIED** (LMP wiki unreachable). Search surfaced only the DarkMultiPlayer-era design (SUBSPACE: each player warps freely and can sync to another player's time; master-warp mode: one player holds the warp lock and everyone follows; NONE: no warp) from https://forum.kerbalspaceprogram.com/topic/75753-multiplayer-time-warp-theory (SNIPPET). LMP descends from DMP and keeps subspaces, but I could not confirm its server `WarpMode` settings. Your install already has `saves/LunaMultiplayer` and `saves/DarkMultiPlayer` folders, so check the LMP server's `Config/` settings files directly.
- Fit with this design (reasoning, UNVERIFIED): LMP syncs vessels, crew and scenario state of a shared universe whose bodies are fixed; it does not know about runtime-rewritten bodies, and its subspace UT model would fight a coordinator that dictates UT per NMS system. Two hidden KSPs fed the same body/orbit data by the Python coordinator over UDP are simpler and deterministic (orbits are pure functions of UT and elements). LMP is only worth it if you need KSP-native shared vessels or player-to-player flight in KSP itself, which this project does not.

Verdict: RISKY (exists and maintained for 1.12.5, but warp model unverified and it conflicts with coordinator-owned time/bodies); not recommended for the core loop.

## Recommended toolchain

1. One custom KSPAddon plugin ("Constellation.dll", net472 via the NuGet reference-assembly package, or the csc offline recipe above) in `GameData/Constellation/`; it owns startup auto-load, `runInBackground`, scene control, body-pool rewrites, vessel orbit writes (HyperEdit's HardsetOrbit recipe), UT/warp, and map-view toggle.
2. Link to the Python coordinator: localhost UDP (or a named pipe) with small JSON/binary packets; plugin receives on a background thread and applies on FixedUpdate, sends state at the rate you choose. Skip memory-mapped files.
3. Kopernicus with a fixed body pool (per ksp-bodies.md), no Principia.
4. kRPC 0.6.0 + ModuleManager only as an optional read/debug channel, not in the critical path.
5. No LunaMultiplayer in the core loop; revisit only for KSP-native co-op.
6. First spike (half a day): launch KSP with `-popupwindow -screen-width 640 -screen-height 360`, auto-load a save, rewrite Mun's orbit with HardsetOrbit, call `MapView.EnterMapView()` with the window behind another one, screenshot it; this one run settles Q3, Q4 and Q5 at once, plus measure the UDP round trip.
