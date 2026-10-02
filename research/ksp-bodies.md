# Can a hidden KSP 1.12.5 mirror a per-warp NMS star system?

Research depth: low. Method: read Kopernicus (github.com/Kopernicus/Kopernicus, master) and Sigma Dimensions (github.com/Sigma88/Sigma-Dimensions, master) source directly, plus web search of KSP forum threads. The KSP API doc pages (kerbalspaceprogram.com/ksp/api) returned 404 for the class pages I tried, so KSP engine behaviour below is mostly from general KSP modding knowledge and is marked UNVERIFIED. Nothing here was run in a live KSP.

Source key (raw GitHub, master):
- Injector.cs = https://github.com/Kopernicus/Kopernicus/blob/master/src/Kopernicus/Injector.cs
- Body.cs = .../src/Kopernicus/Configuration/Body.cs
- OrbitLoader.cs = .../src/Kopernicus/Configuration/OrbitLoader.cs
- SigmaDimensions.cs = https://github.com/Sigma88/Sigma-Dimensions/blob/master/%5BSource%5D/SigmaDimensions/Dimensions/SigmaDimensions.cs

## 1. Can a plugin change CelestialBody properties at runtime?

Short answer: the numbers can be written, but nothing recomputes the derived state. You must redo it yourself. Nobody I found does this at runtime. Kopernicus and Sigma Dimensions both do it at load time.

- Fields are writable. A forum result shows a plugin setting `mun.sphereOfInfluence = 0` and editing `orbit.semiMajorAxis`, and notes the change persists only while the scene lives; remove all vessels and launch fresh and it resets (search snippet, https://forum.kerbalspaceprogram.com/topic/15922-munmover-problems; the page itself returned 403, so UNVERIFIED in detail).
- Kopernicus shows what must be recomputed after changing an orbit. `OrbitLoader.FinalizeOrbit` (OrbitLoader.cs ~lines 381-410) recomputes `hillSphere`, `sphereOfInfluence` (`a * (m/M)^0.4`), `orbit.period`, `meanMotion`, `meanAnomaly`, `orbitPercent` and `ObTAtEpoch`. Setting only `gravParameter` leaves `Mass`, `GeeASL`, `period`, `meanMotion` and SOI stale. A runtime plugin would have to copy this routine.
- Kopernicus config exposes radius, mass, geeASL, gravParameter, sphereOfInfluence and hillSphere as separate properties (https://github.com/Kopernicus/Kopernicus/wiki/Properties, deprecated wiki). That confirms they are independent stored values. SOI and hill sphere can be forced (`body.Has("sphereOfInfluence")` check in OrbitLoader.cs).
- Terrain (PQS): the PQS sphere has its own `radius` and mod offsets. Sigma Dimensions has to patch PQSCity offsets, PQSMod altitudes and the space center after any resize (SigmaDimensions.cs lines 83-134, 159-179, 265-318), and it runs once as a `[KSPAddon(KSPAddon.Startup.MainMenu, true)]` (SigmaDimensions.cs line 11), so it is a load-time operation. Changing `Radius` live with an active PQS would leave a mismatched sphere. Avoidable if pool bodies have no PQS or are never entered.
- Scaled space (map view mesh): Kopernicus builds a scaled-space mesh per body from PQS and radius, cached by a hash that includes `Radius` (Body.cs lines ~405-426, `ScaledVersion.RebuildScaledSpace(meshHash)`). The map-view size is the scaledBody mesh scale. At runtime you would set `body.scaledBody.transform.localScale` yourself. UNVERIFIED, but the mechanism is a plain transform.
- Map view: orbit lines come from `OrbitDriver` and `OrbitRenderer`. Kopernicus adds `OrbitRendererUpdater` (OrbitLoader.cs lines ~330, 357) so the line colour and data refresh. After editing `orbit`, call `orbitDriver.UpdateOrbit()`/`orbit.Init()`. UNVERIFIED which call is sufficient.
- Name: `bodyName` is the identity key used by saves and `FlightGlobals.GetBodyByName`. `displayName` is what the UI shows. Changing `displayName` is the safe route. Kopernicus ships `Components/NameChanger.cs` (file exists; contents not read, UNVERIFIED).
- Existing vessel orbits: `Orbit` objects cache values derived from the reference body's `gravParameter`. Any vessel orbit must be re-initialised after a GM change (`orbit.UpdateFromStateVectors` or `SetOrbit`). With no vessels around the changed body this is moot. UNVERIFIED.
- Time-warp altitude limits and atmosphere are per-body arrays. Pool bodies should have no atmosphere.

## 2. Can bodies be added at runtime? Is a fixed pool the realistic route?

No. Kopernicus builds the whole system once, at `KSPAddon.Startup.PSystemSpawn`, then replaces `PSystemManager.Instance.systemPrefab` (Injector.cs lines 47-48, 68, 168-172: "OVERWRITE THE SYSTEM PREFAB SO KSP ACCEPTS OUR CUSTOM SOLAR SYSTEM"). Bodies are parented to the PSystem and indexed in `FlightGlobals.Bodies` with `flightGlobalsIndex` (Loader.cs ~lines 430-517). I found no runtime add API in Kopernicus. Injecting a CelestialBody after PSystemSpawn would mean building scaled-space, orbit driver, flightGlobalsIndex and PQS by hand. Not a known-good path.

Realistic route: yes, a fixed pool. Declare N bodies in Kopernicus config (for example 1 star, 6-8 planets, a few moons, parent links fixed), keep unused ones parked far away or with scaled-space disabled (Injector.cs ~line 298 shows a `invisibleScaledSpace` property exists, UNVERIFIED how it behaves), and have a plugin write radius, GM, SOI, orbit, displayName and scaledBody scale each warp. Cost: the star system topology is limited by the pool (moons per planet are fixed). Choose a pool with enough planets and moons per planet for the largest NMS system, and unused ones hidden.

## 3. Can planets be made stationary?

Not as a built-in Kopernicus feature that I could verify. The Kopernicus wiki does not document one. Kopernicus sets every orbiting body to `OrbitDriver.UpdateMode.UPDATE` (OrbitLoader.cs line 331). Options:
- (a) Make planets effectively static by giving the star a tiny `gravParameter` (orbital period goes as 1/sqrt(GM)), and force SOI manually. Cheap, no hack of the driver. SOI and period formulas in `FinalizeOrbit` would need the forced values (SOI can be forced via the `sphereOfInfluence` property).
- (b) Each update, set `orbit.epoch`/`meanAnomalyAtEpoch` so the mean anomaly stays fixed. Simple and robust.
- (c) `OrbitDriver.UpdateMode.IDLE` exists in the API (`class_orbit_driver.html` returned 404, so UNVERIFIED semantics; I believe IDLE means the driver does not update the body).
It matters little for a vessel in a planet's SOI, because in patched conics the vessel's orbit around the planet is independent of the planet's motion. It only matters for map-view drawing, SOI exit and the camera frame.

## 4. Load time and hiding a scene reload

- Kopernicus cost is paid once, at game start. Forum reports: planet packs with Kopernicus take from tens of seconds on NVMe to 10-15 minutes on weak hardware (search result summarising forum threads, e.g. https://forum.kerbalspaceprogram.com/topic/194936-181-191-kopernicus-continued/page/13 and https://forum.kerbalspaceprogram.com/topic/172817-loading-just-loading-how-does-one-speed-it-up/page/2; I did not read these pages). Those figures come from large packs. A pool of ~10 PQS-less bodies on stock parts should be far lighter, but UNVERIFIED; no measurement on a low-end PC exists in what I found. Kopernicus has a scaled-space mesh cache keyed by hash (Body.cs ~405-426) and `OnDemandLoading` for textures, both of which reduce reloads.
- With the fixed-pool route no reload is needed per warp. The plugin rewrites body data in place. This is the main reason to prefer it over a reload.
- A flight scene reload (e.g. to reset vessel and orbit state) normally takes seconds and could be covered by a warp animation, but is UNVERIFIED on a low-end PC. Avoid it; a full game restart (Kopernicus reload) is certainly too slow to hide.
- Hiding KSP itself: running with a minimised or off-screen window, or `-batchmode`/`-nographics`, is UNVERIFIED. The map view needs a rendering camera, so `-nographics` almost certainly breaks it. If the goal is only a headless orbit solver, see section 6.

## 5. Patched conics, maneuver nodes, map view with externally overwritten vessel state

Standard KSP modding practice (UNVERIFIED here, no source cited): overwrite a vessel's orbit with `vessel.orbitDriver.orbit.UpdateFromStateVectors(pos, vel, body, UT)` (or `SetOrbit` from elements), then update the patched conic solver (`vessel.patchedConicSolver.Update()`). Requirements and risks:
- The vessel must be on rails (packed). If it is physics-loaded, KSP rewrites the orbit from the rigidbody every physics frame and your overwrite is lost.
- Patched conics work when the vessel's orbit changes SOI because `OrbitDriver`'s SOI checks and the solver run in the flight scene; the map view draws the conic patches. Maneuver nodes require the flight scene (not the tracking station) and an active vessel with the patched conic solver enabled, which also needs the Tracking Station / Mission Control building level to allow it in career mode (sandbox: no limits).
- If your own system reads KSP's predicted orbit (Pe, Ap, SOI transitions, node delta-v), then external overwrite is fine; KSP only does analytic 2-body Kepler propagation plus SOI patch detection. Because it is analytic, you only need to feed it a state per update, not integrate.
- Time: KSP's UT must be synced with your timeline. Orbits are functions of UT, so overwrite and warp rate must match, or use the same UT as the source of truth.
- Principia (https://github.com/mockingbirdnest/Principia): not compatible with this design. It does N-body integration over bodies fixed at load time; its README has nothing on runtime body modification (README only mentions pairing with RealSolarSystem). Do not install it.

## 6. Alternative: compute orbits outside KSP with a C# Kepler library, KSP for map view only

What you would lose or have to rebuild:
- SOI patching and encounter detection (conic patches, SOI transitions, closest-approach markers, Ap/Pe markers drawn by `PatchedConicSolver`). You would compute and push patches yourself, or accept no encounters.
- Maneuver node gizmos and their predicted-trajectory updates, unless you keep KSP's solver in the loop with vessel state pushed each tick, which is what section 5 does anyway.
- Time warp consistency, since your own UT would need to follow KSP's.
- KSP also gives you free analytic 2-body propagation, so a separate Kepler library mostly duplicates what KSP does. Its only benefit is non-KSP semantics (e.g. NMS's own rules) and decoupling from KSP quirks and load time.
- If KSP is only a renderer, you still need the same body pool and runtime resizing, so section 1-3 risks are unchanged. Only vessel-orbit logic moves out.
- At that point a cheaper option is to skip KSP and draw the map in your own renderer (Unity/other). You lose KSP's polished map UI, orbit line shading, camera and UI for free, but gain control and a fast start (no Kopernicus load).

## Recommendation

Feasible but unproven, and the risk is concentrated in one unverified assumption: that mutating a live `CelestialBody` (radius, GM, SOI, orbit, scaledBody scale) and re-initialising its OrbitDriver in-flight gives a clean map view. All known tools (Kopernicus, Sigma Dimensions) do the equivalent at load time only, which is a warning sign. Nothing in the source I read forbids it, though.

If you go ahead:
1. Spike first (about half a day): stock KSP 1.12.5, a plugin that rewrites the Mun's radius/GM/SOI/orbit/displayName and `scaledBody` scale at runtime in the flight scene while a packed vessel orbits it. If map lines, SOI and a maneuver node behave, proceed.
2. Then add Kopernicus with a fixed body pool (one star, about 8 planets, several moons each, PQS-less, no atmosphere), one game start, no scene reloads. Make planets static with option 3(b) or a tiny star GM.
3. Do not use Principia.
4. If the spike fails, fall back to computing orbits outside KSP and rendering the map in your own renderer, rather than forcing KSP to be a display.

Unverified summary: all KSP engine behaviour in sections 1, 3, 4, 5 (OrbitDriver update modes, scaledBody scale, patched conic solver after overwrite, hidden-window rendering, load times on a low-end PC). Confirmed from source: that Kopernicus builds bodies once at PSystemSpawn (Injector.cs), that `FinalizeOrbit` shows the set of derived values to recompute (OrbitLoader.cs), that Kopernicus sets `UpdateMode.UPDATE` (OrbitLoader.cs:331), and that Sigma Dimensions runs once at MainMenu (SigmaDimensions.cs:11).
