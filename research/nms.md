# No Man's Sky PC modding research for an NMS ↔ Space Engineers ↔ KSP bridge

Research date: 2026-10-02 (all "seen" dates are 2026-10-02 unless stated).
Context: personal bridge project that needs to read/write live NMS state, pin a game
version, edit saves programmatically, and possibly add a data-driven interactable.

Legend: every factual claim carries a URL, or is explicitly marked **UNVERIFIED**.
SteamDB and DuckDuckGo blocked automated access during this research (CAPTCHA/403), so
depot/manifest IDs and hardware benchmarks are marked UNVERIFIED.

---

## 1. Runtime code hooking (pyMHF / NMS.py)

**What it is.** `NMS.py` (by monkeyman192) is a Python library that exposes internal NMS
game functions, built on top of `pyMHF` ("Python Modding and Hooking Framework"), which
itself wraps `pymem` + `cyminhook` (MinHook). Source: <https://github.com/monkeyman192/NMS.py>,
<https://github.com/monkeyman192/pyMHF> (seen 2026-10-02). pyMHF is generic (any
game/app); NMS.py supplies the NMS-specific offsets, types and callbacks.

**Supported game versions / build IDs (this is the key finding).** NMS.py is *actively
maintained per Steam build*, not frozen. Its commit history shows named updates for
builds `170671`, `178854`, `178994`, `179105`, `180132`, and `180383`; the latest commit
is "Update for NMS 180383", dated 2026-10-01. Source:
<https://github.com/monkeyman192/NMS.py/commits/master/> (seen 2026-10-02). So as of this
research the current supported build is **180383** (the COSMOS / 7.0 era). The repo's
GitHub *tags* stop at `0.7.1` (Dec 2024) and there are no GitHub *Releases*, but the
`master` branch is the live, version-tracked artifact. Source:
<https://github.com/monkeyman192/NMS.py/tags>,
<https://github.com/monkeyman192/NMS.py/releases> (seen 2026-10-02).

**What can be read/written at runtime.** pyMHF supports hooking a function by offset or
byte signature and running detours before/after the original; arbitrary structs can be
mapped and read/written; live mod reload; per-tick and level-change callbacks; keyboard
callbacks; and an auto-generated DearPyGUI + optional FastAPI HTTP API. Sources:
<https://monkeyman192.github.io/pyMHF/>,
<https://github.com/monkeyman192/pyMHF> (seen 2026-10-02). NMS.py's shipped example mods
demonstrate player location, inventory, visited systems, gravity manipulation, instant
scanning and audio:
<https://github.com/monkeyman192/NMS.py/tree/master/example_mods> (seen 2026-10-02).
Commit history adds structs/hooks for: base-building manager and galaxy map
(<https://github.com/monkeyman192/NMS.py/commit/0a27703>), markers and base-building
objects (<https://github.com/monkeyman192/NMS.py/commit/03763bb>), interaction/UI structs
and `DoInteractionEvent` (<https://github.com/monkeyman192/NMS.py/commit/fe8b616>), solar
system + model types (<https://github.com/monkeyman192/NMS.py/commit/27ec0ac>), and
fishing (<https://github.com/monkeyman192/NMS.py/commit/102b7c2>) (seen 2026-10-02).

Mapping that to the questions asked:
- **Player position** — yes (example `playerLocation.py`).
- **Current system / planet** — yes (solar-system and `visited_systems` types).
- **Inventory** — yes (example `inventory_test.py`).
- **Units / currencies** — UNVERIFIED for a dedicated helper, but the save JSON
  currencies are readable/writable and inventories are hooked, so likely reachable.
- **Ship** — UNVERIFIED directly; model/space types exist and save-side ship data is fully
  editable, but no example confirms live ship-object writes.
- **Spawning objects** — partial: base-building object and marker structs exist; no
  example confirms arbitrary world-object spawning.
- **Triggering warp** — UNVERIFIED; galaxy-map structs exist, but no explicit warp call.
- **Creature/planet data** — UNVERIFIED; system/model types exist but no confirmed
  creature-data reader.

**Explicit online restriction.** The NMS.py README states it "will never contain functions
relating to online functionality to avoid any abuse", and that game updates "can very
easily break mods utilising NMS.py", with broken-save responsibility on the user. Source:
<https://github.com/monkeyman192/NMS.py> (seen 2026-10-02).

**Runtime requirements.** Recommended install is `python -m pip install nmspy`; Python must
be the official CPython build (not the Windows Store or uv-managed build, which crash the
injected process); **Python 3.14 is not yet supported**; pyMHF `0.2.4` is referenced in a
recent NMS.py commit. Sources: <https://github.com/monkeyman192/NMS.py>,
<https://github.com/monkeyman192/NMS.py/commit/cc6207f>,
<https://monkeyman192.github.io/pyMHF/> (seen 2026-10-02).

**Fragility across updates.** High by design: every game build shifts offsets/signatures,
and NMS.py must be re-updated per build (which its author does, often within days). Pinning
a build without pinning the matching NMS.py commit will break. A minor build change can
silently invalidate function patterns (`broken_patterns.txt` exists in the repo). Source:
<https://github.com/monkeyman192/NMS.py>,
<https://github.com/monkeyman192/NMS.py/commits/master/> (seen 2026-10-02).

**Verdict: feasible for read + some writes, but risky** — NMS.py is current (build 180383)
and covers position/system/inventory/interaction, but ship/spawn/warp/creature writes are
unconfirmed, you must match NMS.py commit ↔ game build, and online functions are
deliberately absent.

---

## 2. Version locking on Steam

**Tool.** `DepotDownloader` (SteamRE) downloads a specific app/depot/manifest to a folder
of your choice, optionally on a named branch, with `-username`/`-qr` auth. Usage:
`./DepotDownloader -app <id> [-depot <id> [-manifest <id>]] [-branch <name>] [-dir <path>]`.
Source: <https://github.com/SteamRE/DepotDownloader> (seen 2026-10-02).

**App ID.** No Man's Sky Steam AppID is **275850**. Sources:
<https://store.steampowered.com/app/275850/No_Mans_Sky/>,
<https://github.com/zencq/libNOM.io> (seen 2026-10-02). The specific content depot IDs and
historical manifest IDs must be read from SteamDB's NMS depot page (login-gated); **exact
depot/manifest numbers are UNVERIFIED** because SteamDB blocked automated access.

**Steam Console alternative.** The classic method is
`download_depot <appid> <depotid> <manifestid>` typed into the Steam client console
(`steam://open/console`), which downloads that exact manifest into
`steamapps/content/app_<id>/depot_<id>/`. This is widely documented community procedure;
**UNVERIFIED by a primary source in this session** (SteamDB was blocked).

**Official beta branches.** NMS historically exposes an **`experimental`** Steam branch used
to test patches ahead of release; **UNVERIFIED for 2026** because the SteamDB branch listing
and search engines were blocked. Do not rely on a public branch existing for the build you
want.

**Preventing auto-updates.** Standard Steam measures: Library → NMS → Properties → Updates →
set "Only update this game when I launch it"; additionally run the pinned build from a
DepotDownloader folder *outside* the Steam library, and/or use Steam Offline Mode. This is
well-known client behaviour; **UNVERIFIED against an official Valve doc in this session**.

**Important caveat on old manifests.** DepotDownloader's own FAQ notes "Steam allows
developers to block downloading old manifests, in which case no manifest code is returned"
and that old-build downloads may be slow/401 unless logged in. Source:
<https://github.com/SteamRE/DepotDownloader> (seen 2026-10-02).

**Recommendation.** Lock the NMS install to the build NMS.py currently supports,
**build 180383 (COSMOS / 7.0 era, Oct 2026)**, download it once with DepotDownloader into a
non-Steam folder, keep Steam's copy separate from the bridge workflow, and disable
auto-update. If old manifest download is blocked, capture the current build while it is
still the live build (then never update). Because NMS.py re-tracks builds, pin NMS.py to
the commit matching 180383 (`52e2e55` / `f43f611`) as well.

**Verdict: feasible but risky** — downgrading works in principle, but Steam can block old
manifests and there is no guaranteed official branch; capture the build while current and
freeze.

---

## 3. Save files

**Format.** NMS saves (`.hg`) are LZ4-compressed JSON, with the JSON keys obfuscated by a
mapping the tooling de-obfuscates. Save format generations: `2001` (Foundation 1.10–Prisms
3.53), `2002` incl. Waypoint 4.00 (Frontiers 3.60–Adrift 4.72), `2003` (Worlds Part I 5.00–
The Cursed 5.29), and `2004` incl. 5.53 (Worlds Part II 5.50 and up). Source:
<https://github.com/zencq/libNOM.io> (seen 2026-10-02). The original `2000` vanilla format
is not supported by libNOM.io. Compression is **K4os.Compression.LZ4**; de-obfuscation is
**libNOM.map**; MBINCompiler ships `mapping.json` "to de-obfuscate the save file .json".
Sources: <https://github.com/zencq/libNOM.io>,
<https://github.com/monkeyman192/MBINCompiler> (seen 2026-10-02).

**Libraries / tools.**
- **libNOM.io** (zencq, .NET; used by NomNom): reads/writes saves for all supported
  platforms, with a JSON-path get/set API
  (`save.GetJsonValue<int>("PlayerStateData.UniverseAddress...")`,
  `save.SetJsonValue(...)`, `platform.Write(container)`), plus a CLI. Source:
  <https://github.com/zencq/libNOM.io> (seen 2026-10-02). NuGet `libNOM.io`, latest seen
  `0.14.2`. Source: <https://www.nuget.org/packages/libNOM.io/> (seen 2026-10-02).
- **NomNom** (zencq, Windows/.NET; GUI on libNOM.io): currencies, exosuit/multitool/ship/
  freighter stats, inventories, add items/technology, **fast travel to any system and
  trigger space battles**, edit raw JSON, automatic backup. Versioning mirrors the game
  (e.g. 7.0.x), backwards compatible to Beyond 2.11. Sources:
  <https://github.com/zencq/NomNom>,
  <https://www.nexusmods.com/nomanssky/mods/1566> (updated 2026-06-05) (seen 2026-10-02).
- **goatfungus NMSSaveEditor** (Java; "for WORLDS"): currencies, base stats, inventories
  (add/clone/repair items), raw JSON editor, base/freighter structure backup, delete/export/
  import ships and frigates. Requirements: .NET-style Java 8 runtime; supports Steam/GOG/
  PS4/MS Store. Source: <https://github.com/goatfungus/NMSSaveEditor> (seen 2026-10-02).
- **MetaIdea nms-savetool** (C#): decrypt/encrypt Steam saves, recreate/validate edited
  saves; explicitly "exploits backward compatibility so it should be future proof". Source:
  <https://github.com/MetaIdea/nms-savetool> (seen 2026-10-02).

**Programmatic editing between sessions.** Yes. libNOM.io's documented API loads a container,
edits JSON values, and writes it back; NomNom's "fast travel to any system" and
"ships/frigates delete/export/import" confirm location and ship changes; NMSSaveEditor
confirms add/remove items, units, and ship import. Sources above (seen 2026-10-02). On PC
the game reads saves on load, so edits made while the game is closed take effect next load.
Caveats: Microsoft Store saves cannot be reloaded while the game is running, and gen-2000
vanilla saves are out of scope for libNOM.io. Source: <https://github.com/zencq/libNOM.io>
(seen 2026-10-02).

**How the game reacts.** Editors target the game's own JSON schema so edits are generally
accepted; the main risk is invalid values/over-limit inventories (NMSSaveEditor warns that
exceeding vanilla inventory limits "might BREAK" the game) and version mismatches between
tool and game. Sources: <https://github.com/goatfungus/NMSSaveEditor>,
<https://github.com/zencq/NomNom> (seen 2026-10-02). A backup is automatic in NomNom and
recommended everywhere.

**Verdict: feasible** — save editing is mature, actively maintained, and can add/remove
items, units, ships and change location between sessions.

---

## 4. Multiplayer

**Cross-version play is not allowed.** NMS enforces matching builds: a "Version Mismatch"
error occurs when two players are on different versions, and the standard fix is to update
both to the same version. Sources:
<https://deltiasgaming.com/no-mans-sky-version-mismatch-error-how-to-fix/> (2026-09-30),
<https://dotesports.com/no-mans-sky/news/no-mans-sky-version-mismatched-what-it-means-and-how-to-fix-it>
(2025-09-02),
<https://www.reddit.com/r/NoMansSkyTheGame/comments/12mr6ir/version_mismatch/> (seen
2026-10-02). Cross-Platform Multiplayer, Online Co-op and Online PvP are listed features,
so same-build cross-play works, but a pinned older build can only co-op with other players
on that same pinned build (and only for platforms whose stores also allow that build).
Source: <https://store.steampowered.com/app/275850/No_Mans_Sky/> (seen 2026-10-02).

**Do mods / pyMHF break online?** Data/Pak mods are generally client-side and many are
multiplayer-safe if all players share the same build and the mod does not change shared
state; pyMHF/NMS.py is a local runtime hook and the library explicitly refuses to ship
online functions. Sources: <https://github.com/monkeyman192/NMS.py> (seen 2026-10-02).
Whether an injected process or modified Pak triggers anti-cheat/desync is not documented in
the sources reviewed; **UNVERIFIED**.

**Verdict: risky** — same-build friends can play together, but pinning an old build segments
your group to that build, and online behaviour with runtime hooking is undocumented.

---

## 5. Install size and laptop performance

**Install size.** Steam's store page lists **15 GB available space** as the minimum.
Source: <https://store.steampowered.com/app/275850/No_Mans_Sky/> (seen 2026-10-02). Real
installs commonly exceed this after updates/caches; treat 15 GB as a floor (delta
**UNVERIFIED**).

**Minimum GPU spec.** The store minimum lists "Nvidia GTX 1060 3GB, AMD RX 470 4GB, **Intel
UHD graphics 630**", 8 GB RAM, Intel Core i3, Windows 10/11 64-bit. Source:
<https://store.steampowered.com/app/275850/No_Mans_Sky/> (seen 2026-10-02).

**Target laptop.** Intel Core Ultra 5 135U has 16 GB RAM and, in place of a discrete GPU, an
integrated **Intel Arc** (Meteor Lake) iGPU. The Arc-based iGPU is a different and generally
faster class than the UHD 630 the game lists as minimum; on a 16 GB machine the game meets
the RAM minimum. Therefore lowest-settings 1080p play is expected to be *possible*, but no
specific FPS figure was obtainable (search engines were CAPTCHA-blocked); **exact
framerate and thermal/throttling behaviour on the 135U are UNVERIFIED**. Note the 135U is a
low-power ultrabook part (15 W class), so sustained performance will be well below desktop
Arc/discrete benchmarks. **UNVERIFIED**.

**Verdict: risky** — meets/beats the stated minimum on paper, but integrated low-power
graphics mean quality/performance is a real constraint, especially once a bridge process is
also running.

---

## 6. Data-file modding (MBIN/EXML/MXML via MBINCompiler/AMUMSS)

**Toolchain.** `MBINCompiler` (monkeyman192/libMBIN) converts the game's binary `.MBIN` data
files to text and back; since the Worlds Part 2 update it emits **MXML** (renamed to `.EXML`
when packaging a mod). Each MBIN format is tied to a game version, so the matching
MBINCompiler build must be used. `mapping.json` also de-obfuscates saves. Requires .NET 8.
Source: <https://github.com/monkeyman192/MBINCompiler> (seen 2026-10-02).

**AMUMSS** ("Auto Mod-builder Updater with Mod Script System") builds mods from Lua scripts
that name file/variable/value changes and re-applies them to the current game files,
producing `.pak` mods; it depends on MBINCompiler and lags a few days after each game
update. It can detect/merge mod conflicts. Sources:
<https://stepmodifications.org/wiki/NoMansSky:AMUMSS_Guide>,
<https://www.nexusmods.com/nomanssky/mods/957>,
<https://github.com/HolterPhylo/AMUMSS> (seen 2026-10-02).

**Can it add new items/recipes?** In principle yes — data tables (products, technologies,
recipes, string tables) are MBIN files and can be edited/regenerated, and the NMS modding
community distributes Lua scripts that alter tables. Sources above, plus:
<https://github.com/MetaIdea/nms-amumss-lua-mod-script-collection> (seen 2026-10-02).
However, adding a *brand-new* item safely requires unique IDs (often hash-derived), matching
string/localisation entries, icons, and recipe wiring; there is no primary source reviewed
that documents a fully new item end-to-end, so **"new item creation is possible" is
UNVERIFIED in detail** and would be fragile/conflict-prone.

**Custom interactable building as a portal.** NMS interactions are driven by entity/
interaction tables; base "Teleporter" behaviour is tied to a specific entity type rather
than a generic data flag. Data files can re-skin or repurpose an existing teleporter-like
part, but defining a *new* interaction type is not something the data-file toolchain alone
is documented to do. A custom interactable portal is therefore best implemented as a hybrid:
data mod for the visible/placed object + an NMS.py hook on interaction events
(`DoInteractionEvent` / interaction/UI structs exist) to drive bridge behaviour. Sources:
<https://github.com/monkeyman192/NMS.py/commit/fe8b616>,
<https://github.com/monkeyman192/NMS.py/commit/03763bb>,
<https://stepmodifications.org/wiki/NoMansSky:AMUMSS_Guide> (seen 2026-10-02). Pure-data
"new interaction" support is **UNVERIFIED / likely not achievable**.

**Verdict: risky** — adding recipes/items and re-skinning a portal part via
MBINCompiler/AMUMSS is plausible but update-fragile; a genuinely new interactable
interaction is best done by hooking, i.e. blocked for data-files alone.

---

## Final recommendation: version lock + toolchain

**Recommended game lock: NMS Steam build `180383` (COSMOS / 7.0 era, 2026-10-01).**
Rationale: it is the build the actively-maintained NMS.py currently targets (commit
`52e2e55` / `f43f611`), and the newest save format (`2004`) that libNOM.io/NomNom/MBINCompiler
all support.

Toolchain:
- **Game:** Steam AppID 275850, installed/mirrored via **DepotDownloader** (`-app 275850
  -manifest <180383 manifest>`), Steam auto-update disabled. Get the exact depot/manifest
  from SteamDB while logged in (**specific IDs UNVERIFIED**).
- **Runtime hooking:** CPython (official installer, **3.9–3.13, not 3.14**), `pip install
  nmspy`, **pyMHF 0.2.4+**, NMS.py pinned to the 180383 commit. Keep a second NMS.py commit
  per build if you ever re-pin.
- **Saves:** **NomNom 7.0.x** (GUI) + **libNOM.io** (headless .NET/CLI) for programmatic
  edits; **NMSSaveEditor** as a fallback GUI; **nms-savetool** for Steam save encrypt/decrypt.
- **Data files:** **MBINCompiler** release matching 7.0 + **AMUMSS** with Lua scripts for
  update-resilient table mods.
- **Guardrails:** automatic save backups before every programmatic write; freeze updates
  before touching data files; co-op only with players on build 180383.