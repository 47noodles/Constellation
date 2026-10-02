# Passthrough game-blending mods — survey

A "passthrough" mod is one where **two games run at the same time, one is hidden and drives
mechanics, and the other renders the picture**. This document surveys the ones that exist, with
links, bridge techniques, licences and what is reusable for our project.

Our project (for reference in the "reusable" column):

- **Renderer:** No Man's Sky (PC), driven from Python via `pyMHF` / `NMS.py` hooks.
- **Hidden simulators:** Space Engineers 1 (C# plugin) and Kerbal Space Program 1.12.5
  (C# plugin or kRPC).
- **Coordinator:** a central process that links the hidden sims to the renderer.
- **Goal:** co-op.

> **Terminology note / correction to the brief.** The brief describes SkyCraft as "one game runs
> hidden and drives mechanics while another renders (like SkyCraft: Skyrim plus Minecraft through
> shared memory)". In SkyCraft it is **Minecraft that is hidden and drives the player mechanics,
> and Skyrim that renders**. The general passthrough pattern is usually: the *expensive AAA game
> renders*, the *cheaper/older game is hidden and supplies one system* (physics, combat, blocks).
> Our project **inverts** this: the AAA game (NMS) renders, but the hidden games (SE, KSP) are
> themselves large simulations. That inversion is why the most relevant references below are the
> ones that bridge two *heavy* games (GTA V, Elden Ring, Monster Hunter, Skyrim), not the
> decomp-as-library ones.

---

## 1. Project table

| # | Project | Author | Renderer / Hidden | Bridge technique | Code + licence | Date | Video | Verification |
|---|---------|--------|-------------------|------------------|----------------|------|-------|--------------|
| 1 | **SkyCraft** | chasmlol | Skyrim renders / Minecraft hidden | Shared memory; SKSE C++ plugin (CommonLibSSE-NG) + Minecraft Fabric Java mod; shared `protocol/skycraft_protocol.h` layout | [github.com/chasmlol/SkyCraft](https://github.com/chasmlol/SkyCraft) — MIT | 2026 | [youtube.com/watch?v=XS3jhTHDpEY](https://www.youtube.com/watch?v=XS3jhTHDpEY) | Verified (repo + README read) |
| 2 | **Minecraft × GTA V passthrough** (`universal-modder` example) | rehan-remade (built by Claude Code) | GTA V renders / Minecraft hidden | WebSocket `127.0.0.1:25599` for camera/ground/events + **named shared memory** for RGBA+depth frames + ReShade add-on depth-compositing + ScriptHookV `.asi` | [github.com/rehan-remade/universal-modder/tree/main/examples/minecraft-gta5-passthrough](https://github.com/rehan-remade/universal-modder/tree/main/examples/minecraft-gta5-passthrough) — MIT | 2026-09-30 | Demo cut from repo (see README/video) | Verified (README + field note index read) |
| 3 | **minecraft-crossover-bridge** (Minecraft in Monster Hunter: World / Elden Ring) | justbustin | Windows game renders / native macOS Minecraft hidden | Shared memory files in `/tmp` mapped through Wine `Z:`; game-side DLL loaded as `dinput8.dll` proxy + MinHook; camera handoff; terrain raycast sampling | [github.com/justbustin/minecraft-crossover-bridge](https://github.com/justbustin/minecraft-crossover-bridge) — MIT (MinHook BSD-2) | 2026 (4 commits) | README demo; see repo | Verified (README read) |
| 4 | **Minecraft inside Elden Ring** | Tobyn Jacobs (@tobynjacobs) | Elden Ring renders / Minecraft hidden (Mac) | Passthrough; details not public | No public repo or download (demo only) | 2026-09-29 | [youtube.com/watch?v=k9CqyfauPMY](https://www.youtube.com/watch?v=k9CqyfauPMY); X trending | Video verified; **technique UNVERIFIED** |
| 5 | **latte-doom** | BradleyGatlin (fork/branch of latte-doom) | Minecraft renders / Doom hidden | Vendored **Mocha Doom** engine runs *inside Minecraft's JVM* and owns all simulation; level drawn as walkable 3D geometry (no shared memory / no separate process) | [github.com/BradleyGatlin/latte-doom-Brad-Branch-V2](https://github.com/BradleyGatlin/latte-doom-Brad-Branch-V2) — GPL-3.0 | 2026-07 | repo | Verified (GitHub metadata) |
| 6 | **libsm64** + consumers: `mario64-in-minecraft` (Zckyy), `g64` (Garry's Mod, ckosmic), `smc64` (Halo CE, KodyJKing) | libsm64 org / various | Host game renders / SM64 decomp hidden | **Decomp-as-library**: Super Mario 64 decompiled to a C library; host links it (FFI), feeds host collision in, reads character state out. No shared memory | [github.com/libsm64/libsm64](https://github.com/libsm64/libsm64) — CC0; [Zckyy/mario64-in-minecraft](https://github.com/Zckyy/mario64-in-minecraft) — other/NOASSERTION; [ckosmic/g64](https://github.com/ckosmic/g64) — no licence; [KodyJKing/smc64](https://github.com/KodyJKing/smc64) — no licence | libsm64 2020–; consumers 2022–2026 | repo/demos | Verified (GitHub API) |
| 7 | **Universal Modder** | rehan-remade | n/a — meta tooling | AI-agent skills/tools; `mashup-mods` skill documents passthrough workflow with the GTA V × Minecraft worked example; knowledge base of field notes | [github.com/rehan-remade/universal-modder](https://github.com/rehan-remade/universal-modder) — MIT | 2026-09/10 | repo | Verified (README read) |
| 8 | **kRPC** | krpc/krpc | KSP is the hidden/controllable sim (no renderer blending) | Remote Procedure Calls over TCP (protobuf); clients for Python, C#, Java, Lua, Node, Rust | [github.com/krpc/krpc](https://github.com/krpc/krpc) — other/NOASSERTION (open source) | 2014–ongoing | [krpc.github.io](https://krpc.github.io/krpc) | Verified (GitHub API) |
| 9 | **iv4xr-se-plugin** | iv4xr-project | Space Engineers as an observable/controllable sim | Plugin integrated with the iv4XR framework; observe + actuate SE programmatically (Kotlin/C#) | [github.com/iv4xr-project/iv4xr-se-plugin](https://github.com/iv4xr-project/iv4xr-se-plugin) — LGPL-3.0 | 2020–2024 | repo/docs | Verified (GitHub API) |
| 10 | **Torch** | TorchAPI | Space Engineers server/plugin framework | Extensible C# modding framework + improved client/dedicated server for SE | [github.com/TorchAPI/Torch](https://github.com/TorchAPI/Torch) — Apache-2.0 | 2016–2026 | repo | Verified (GitHub API) |
| 11 | **Archipelago** | ArchipelagoMW | n/a — multi-game co-op coordinator | Central multiworld server; per-game clients exchange items/checks; Python | [github.com/ArchipelagoMW/Archipelago](https://github.com/ArchipelagoMW/Archipelago) — other/NOASSERTION | 2021–ongoing | [archipelago.gg](https://archipelago.gg) | Verified (GitHub API) |
| 12 | **Nucleus Co-Op** | SplitScreen-Me (orig. ZeroFox5866) | n/a — local co-op multi-instance | Launches multiple instances of one game, manages windows + input for split-screen | [github.com/SplitScreen-Me/splitscreenme-nucleus](https://github.com/SplitScreen-Me/splitscreenme-nucleus) — GPL-3.0 | 2015–ongoing | [splitscreen.me](https://www.splitscreen.me/) | Verified (GitHub API) |
| 13 | **Escape from Skyrim** | Cydonyx (@cydonix) | Skyrim renders / Tarkov mechanics imported | Reported game-merging; no code/details public | No public repo | 2026-09-30 | X post | **UNVERIFIED** |
| 14 | **Halo Big Team Battle on MW2 Rust** | petey (@peteyburn) | Modern Warfare 2 renders / Halo maps+BTB rules | Reported; no code public | No public repo | 2026-09-29 | X post | **UNVERIFIED** |
| 15 | **Mario Kart × CoD: World at War Zombies** | 360noscope420blazeit (@360NoScope) | CoD WaW Zombies / Mario Kart assets | Reported; no code public | No public repo | 2026-09-29 | X post | **UNVERIFIED** |
| 16 | **"Minecraft in Skyrim"** (old) | Various (Nexus 18141) | Skyrim renders / Minecraft *models* only | Model/asset import, **not** passthrough | Nexus page | 2012-ish | [nexusmods.com/skyrim/mods/18141](https://www.nexusmods.com/skyrim/mods/18141) | Verified it is not passthrough |

### Space Engineers ↔ KSP bridge search result

A direct **Space Engineers 1 ↔ Kerbal Space Program bridge (passthrough or co-sim) was not found**
during this survey — **UNVERIFIED / apparently does not exist**. What exists are the separate
per-game ecosystems: kRPC for KSP (#8), and Torch / iv4xr-se-plugin for Space Engineers (#9, #10).
This is a gap, and therefore an opportunity: there is no prior art to copy for the SE↔KSP half of
our project, only prior art for controlling each game individually.

---

## 2. Technique notes

### 2.1 Shared memory (SkyCraft, crossover-bridge, GTA V example)
The dominant technique for two **separate heavy processes** on one machine. Both sides map the
same named page/file and exchange fixed-layout structs at frame rate.

- **SkyCraft:** a C++ header (`protocol/skycraft_protocol.h`) is the single source of truth for the
  layout, included by both the SKSE plugin and the Fabric mod. Good practice to copy.
- **crossover-bridge:** uses `/tmp` files that Wine exposes as `Z:` — a native macOS process and a
  Windows process under Wine share pages directly. Addresses this repo's cross-OS/cross-ABI case.
- **GTA V example:** shared memory is used **only for the pixel/depth frames**; a WebSocket carries
  structured state/events. Splitting "bulk pixels" from "small messages" is a useful design rule.

### 2.2 Sockets / WebSocket (GTA V example)
`127.0.0.1:25599` WebSocket carries camera pose, ground probes, input, director commands and
events. Easier to debug than shared memory, works across WSL/Windows. Note its documented safety
weakness: the link has **no token**, so any local process can send commands. For our coordinator we
should add an auth token.

### 2.3 DLL proxy + function hooking (crossover-bridge, GTA V ScriptHookV)
- Load a DLL in place of a game's own `dinput8.dll` / `dxgi.dll` so the game loads it automatically.
- **MinHook** (BSD-2) for trampolines; ScriptHookV/`.asi` on GTA V.
- **Address safety:** crossover-bridge verifies every game address against expected byte patterns at
  startup and **disables a feature rather than guessing** when the game version differs. This is the
  single most important safety pattern for hooking closed-source games; copy it for NMS/pyMHF and SE.

### 2.4 Decompilation as a library (libsm64)
Where a matching decomp exists, the game's own logic becomes a C library you link into the host.
The host supplies collision geometry and receives character state. Powerful but only applies to
games with a decompilation (SM64, OoT, etc.). **Not directly applicable to NMS, SE or KSP** (all
closed-source), but conceptually similar to using a game's own functions via hooks, as
crossover-bridge does for damage.

### 2.5 In-process vendored engine (latte-doom)
The hidden engine (Mocha Doom) is compiled into the host's JVM rather than run as a separate
process. No IPC at all, but it requires a source-available engine and a JVM host. Relevant to us
only as a contrast: our hidden sims are separate closed-source processes, so IPC is unavoidable.

### 2.6 Renderer-side compositing (crossover-bridge, GTA V example)
Both heavy-game references composite the hidden game's frame into the renderer's frame:
- GTA V: ReShade add-on + `.fx` shader; per-pixel depth test against GTA's depth buffer;
  re-projects Minecraft's frame from its render pose to the renderer's current camera to hide IPC
  latency; relights from the renderer's image.
- crossover-bridge: bridge overwrites the game camera with Minecraft's pose, then composites
  Minecraft colour+depth with a depth test, relit by the game's own brightness.
Our project's direction is different: **NMS renders its own world** and pyMHF hooks inject/observe.
We are more likely to *feed* NMS state from the hidden sims than to composite another game's frame
into NMS. The depth-compositing material is therefore a fallback, not the primary path.

### 2.7 World/collision bridging
- **Ground as collision:** GTA V example probes the renderer's ground in columns around the player
  (40 blocks, 160 probes/frame) and fills them with Minecraft **barrier** blocks; blocks placed in
  Minecraft become GTA props (with a hard cap ~400 before GTA crashes).
- **Terrain rays:** crossover-bridge casts batches of rays against the game's own collision on the
  game thread and turns hits into invisible blocks.
- **Entity/hitbox bridging:** nearby enemies are published with position, hitbox and HP and become
  invisible entities; hits go back through the game's own damage functions; a hidden stand-in
  character takes the renderer's hits and forwards them.
For us: SE/KSP have authoritative physics; the analogous work is mapping their entities/vessels
into NMS-visible objects and forwarding interactions, not the reverse.

### 2.8 Co-op
- **SkyCraft:** only the *hidden* side's world (Minecraft) is shared over the network (bundled
  `e4mc`, up to 100 players); each player keeps their **own** renderer world (Skyrim) and NPCs.
  This is a strong precedent for our co-op goal: **share the hidden simulation, keep the renderer
  per-player**, and accept that renderer-side entities are not shared yet.
- **Archipelago:** a proven central coordinator + per-game client protocol for multi-game sessions.
- **Nucleus Co-Op:** process/window/input orchestration for multiple instances on one machine.

### 2.9 Safety rules worth adopting (from Universal Modder / crossover-bridge)
- Offline / single-player only; never inject into anti-cheat-protected online games.
- Back up saves before touching them; kill processes by PID, not name.
- Verify game addresses before use; fail closed.
- Never ship game files or decompiled code; ship code + your own assets/patches.
- Add an auth token to local IPC links.

---

## 3. Top three to study

### 1. `minecraft-gta5-passthrough` (universal-modder example) — read the whole thing
**Why:** it is the closest match to our architecture and the only one that is **fully open source
with tests and a written field note**. It bridges two heavy, closed-source games on Windows; uses
a local WebSocket for state/events and shared memory for frames; forwards input while the renderer
keeps focus; maps coordinates between two engines; feeds the renderer's ground in as collision;
and sends gameplay events both ways. It also ships `fakehost.py` and `fakegta.cpp` stand-ins so
the bridge can be tested without the real games — directly applicable to testing NMS↔SE↔KSP before
everything is wired. Study: `knowledge/games/gta-v/minecraft-passthrough.md`, the `mashup-mods`
skill, and `techniques/oracles-how-agents-know-a-mod-works.md`.

### 2. `minecraft-crossover-bridge` (Monster Hunter: World / Elden Ring) — study the game-side DLL
**Why:** it is the best reference for **safely hooking a closed-source game from a small injected
DLL**, which is exactly what we must do for NMS (pyMHF) and Space Engineers (C# plugin). Its
address byte-pattern verification, `dinput8.dll` proxy loading, MinHook usage, hot-reloadable
bridge core, camera-pose handoff, terrain ray sampling, and entity/HP/damage bridging are all
directly transferable. It also documents the version-matching constraint (one game build per
feature) that we will face with NMS and SE updates.

### 3. `SkyCraft` — study the protocol and the co-op model
**Why:** it is the cleanest example of the *exact* passthrough topology (hidden game drives
mechanics, other game renders, shared memory between a C++ plugin and a managed mod) and its
shared header is a model for our coordinator's wire format. Most importantly, its **co-op design**
answers our co-op question: share the hidden simulation, keep the renderer per-player, and be
explicit about what is not shared. Its split of responsibilities (renderer owns world/NPCs/saves;
hidden game owns physics/inventory/combat) is a template for dividing NMS vs SE/KSP.

**Honourable mentions:** **kRPC** (ready-made external control for KSP 1.12.5, Python client
matches our coordinator language) and **iv4xr-se-plugin** / **Torch** (prior art for observing and
controlling Space Engineers from outside the game).

---

## 4. Gaps and risks for our project

- **No prior art for SE↔KSP co-simulation.** The two hidden sims have never been linked to each
  other or to a third renderer. Our coordinator is genuinely novel work.
- **NMS is closed-source and hook-based** (pyMHF/NMS.py). The crossover-bridge address-verification
  pattern is the mitigation; expect per-patch breakage.
- **Heavy-game bridging assumes the renderer can composite an external frame** (ReShade/ScriptHookV
  depth compositing). Whether NMS can do the equivalent is **UNVERIFIED** — this is the biggest
  technical unknown. If not, our design must instead *drive NMS from the hidden sims* rather than
  *draw them into NMS*.
- **Co-op across two hidden sims** is harder than SkyCraft's "share Minecraft, everyone has their
  own Skyrim": we would need to share the state of *both* SE and KSP, not just one.
- **Licence hygiene:** latte-doom is GPL-3.0 (copyleft); libsm64 consumers are mostly unlicensed.
  Prefer MIT/Apache references (SkyCraft, crossover-bridge, GTA V example, Universal Modder, kRPC)
  and write our own code.