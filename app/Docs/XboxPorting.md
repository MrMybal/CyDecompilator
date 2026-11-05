# Xbox native porting in CyDecompilator

## Black Anniversary rendering: 2026-10-21.1 correction

For XEX SHA-256 `1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19`,
the custom GPU profile uses `native_querybatch_range=256`, `readback_resolve=full`,
`gamma_render_target_as_unorm16=false`, `gpu_allow_invalid_fetch_constants=true`,
`occlusion_query_enable=true` and `query_occlusion_fake_sample_count=0`.
Normal RTV rendering works; selecting ROV alone did not fix the black screen.
Full CPU-visible resolve readbacks fix HDR/exposure but can substantially reduce performance.
Do not assume a warmed-up scene proves that fast readbacks work from startup.

Z-pass events are cumulative snapshots, including nonadjacent Saber QueryBatch surveys.
The hardware handler accumulates query segments across submissions and excludes RT capture
passes. Positive range 256 selects a **bounded synthetic compatibility fallback**, not accurate
geometric lens-flare occlusion. Range 0 selects hardware snapshots. Flares remain unresolved.
Visual validation covers the a10 wake-up room and b30 beach, both rendering modes, RT off;
it does not establish whole-campaign, RT or coop readiness. Local evidence is recorded in
`data/reports/halo-anniversary-fix.json`.

The standalone launcher supports `Play-Halo.cmd --map b30` (`Play-Halo-Carte.cmd`). It follows
the normal campaign frontend with temporary A-button pulses, then overrides both LoadLevelSolo
and Saber LoadLevel. Calling `map_name` alone leaves the old UI/Saber scene; overriding only
LoadLevelSolo can load different maps in Blam and Saber. Preserve guest string ownership,
reference counts and PPC context. Hooks are exact-XEX-specific. Direct startup is solo;
coop still uses normal mission selection. Local extracted game.cfg disables the startup video;
its original is retained in `work/gpu-occlusion/anniversary-original-game.cfg`.

Reference: [official Xenia Canary Halo Anniversary tracking](https://github.com/xenia-canary/game-compatibility/issues/552),
particularly QueryBatch and readback/gamma reports. The workaround is adapted to the native
recompile runtime; no Xenia process is launched.


## Workflow in the application

Open **Xbox porting** in the sidebar. Prepare an extracted game folder, XDVDFS ISO,
or ZIP containing one ISO. A bare XBE/XEX imports only that executable. Originals
are preserved; complete folder/disc resources are saved in the analysis project.
Select an entry when there are several executable candidates.

For Xbox 360, install/configure ReXGlue in **Xbox native tools**, create a native
project and compile it. Windows x64 builds need Visual Studio C++ tools, Clang,
CMake, Ninja and the Windows SDK. The official optional SDK is separate under
`runtime/engines/rexglue/0.10.0`, verified against the pinned archive SHA-256.
Generated C++ and CMake projects live under `data/projects/<id>/xbox/builds/`.
**Edit native sources** attaches the generated folder to Project IDE.

**Existing Xbox native project** registers a previous ReXGlue project without
copying its assets or changing its build. This supports the Halo project developed
before integration. Such a project remains dependent on its original folder.

Launch explicitly with **Launch native Xbox game**. The game is owned by a Runtime
job; cancellation stops its process tree. Logs belong to the job. Saves/cache remain
under the native project's `data/`. The launcher verifies the guest and compiled
executable identities. Saved in-game display settings can override initial fullscreen.

## Method used for Halo Anniversary

The working Halo input is **Xbox 360**, not original Xbox. Its exact executable is:

`1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19`

ReXGlue translates PowerPC instructions into C++ ahead of time. A native compiler
builds that code with a console compatibility runtime and a graphics backend derived
from Xenia. xemu was a research reference for original Xbox; it is not the engine
used to run this Xbox 360 port. No separate emulator process is launched. Generated
C++ preserves machine-level behavior; it does not recover the original developer's
source project, names, types or build system.

The shipped Halo profile supplies reviewed function boundaries, callback/vtable
targets and exception-handler analysis hints. Local generated-source overlays add
PC input, frame pacing, interpolation, selected physics substeps and offline profiles.
Those hooks are restricted to the exact executable SHA-256. Other games receive a
generic ReXGlue project and require their own investigation and compatibility work.

The integrated profile overlay vendors only the SDK's needed BSD-licensed profile
sources, with original notices and hashes, under `xbox_support/third_party/rexglue`.
It generates modified copies inside each native project's `native-overlay/` folder.
The installed SDK and its original checkout are not edited.

## Evidence and status

Preparation, CPU translation, compilation, linking, process execution and gameplay
validation are different stages. An exit code of zero is **executed-unverified**;
it does not demonstrate correct graphics, input, sound, missions or multiplayer.
`nativeGameReady` remains false. User-observed Halo gameplay is useful evidence for
that title/build, not a compatibility statement for the whole Xbox catalogue.

Original Xbox XBE metadata/sections can be inspected and its assets prepared.
A complete native original-Xbox runtime/recompiler is not implemented here.
The integrated installer/build/launch profile currently targets Windows x64.
PS5 porting is a separate page/backend and does not share Xbox title addresses.

## Pitfalls encountered and rules to preserve

### Code analysis and imports

Identify register save/restore helpers, indirect callbacks, vtables, jump tables and
exception handlers for each executable. Missing destinations must be investigated;
never turn an unresolved branch into a silent successful return. For this Halo image,
two conditional targets reach the illegal zero instruction at `0x8317EE64`; the local
guard retains a fatal trap if reached. Do not generalize that rule to another game.

Use the PowerPC ABI, including stack arguments beyond r3-r10 and big-endian wire
structures. In particular, a NetDll caller argument shifts socket argument indices;
confusing r8/r9 corrupts sendto destinations. Native Windows socket port byte order
must be converted explicitly. Route both direct generated import calls and runtime
ordinal/registry resolution to the same adapter. Test meaningful behavior, not just
stub success codes.

### FPS, animation and physics

Unlock presentation pacing separately from the original simulation clock. Increasing
FPS alone does not update AI, collision or animation at the new render frequency.
Interpolation needs previous/current simulation snapshots and a render fraction;
never interpolate an already interpolated pose. Keep object identities/generations,
reset on teleport, map load, replacement, pause and discontinuous time, and restore
temporarily modified guest data after exporting the render pose.

Check player arms, enemy poses and world positions independently. Cinematic ships
can use a different transform path from bipeds. Vehicles and their follow cameras
also need separate treatment. Split-screen histories and camera state must be per
view/player. Physics substeps must preserve the original tick's total elapsed time;
they do not automatically increase AI/script frequency. Sprint modifies the local
on-foot desired velocity; weapon bob must stop while airborne and avoid vehicles.

### Mouse, menus and local players

Direct relative mouse look avoids an analog stick's dead zone and acceleration curve.
Consume each motion once; clear stale deltas on focus loss, pause and capture changes.
Deliver menu clicks through the game's existing GFx interface on its guest UI thread,
preserving guest registers and the correct press/release event semantics. Competing
virtual/Kinect cursors can overwrite the PC cursor. Convert physical window coordinates
through the current viewport, including letterbox/stretch behavior.

Escape needs an actual pause/Start input path. Two local players require two signed-in
offline profiles and separate device assignment: keyboard/mouse J1, first physical pad
J2, or two pads when keyboard reservation is disabled. The original SDK exposed only
one profile. Separate profile settings, preserve the primary save path, and do not
claim that a second independently saved campaign has been added.

### Lens flares and graphics

Halo's visibility snapshots can use adjacent 32-byte begin/end records. Incorrect
query pairing, orphaned ends or command-list splits can break host occlusion queries.
Do not replace missing query results with a fixed positive sample count such as 1000:
that makes flares visible through occluders. Validate query lifetime, accumulated
segments, depth attachments and actual masked/unmasked light sources in the game.
The prior GPU fixes have not established that every reported flare defect is solved.

The optional native GPU plugin includes SMAA and experimental DXR work. It is a separate
runtime DLL, not embedded game data. The current RT capture is not a complete Remix-like
material/light renderer. Correct RT needs geometry/transforms, texture UVs, alpha cutouts,
transparency, independent emissive data, lighting and valid primary depth. Reusing a
shaded HDR color is not equivalent to extracting an emissive channel. Two spatial
bilateral denoise passes are not temporal accumulation/reprojection with motion and
disocclusion handling. Do not claim a complete denoiser or fully reconstructed lights.
RT is suspended with two local profiles because its current capture assumes one view.

To reproduce that optional plugin from the pinned SDK checkout, run the shipped
`xbox_support/scripts/rex_gpu_diagnostics.py --source <checkout> --sdk <sdk-root>
--fix-occlusion --work <runtime-build-folder>`. It checks SDK source commit
`f5337cdc947ff6d4c4196737e2c807a48f2a1fc2` and builds an overlay without editing the
checkout. The folder receives `plugin.json` and `build/rexgpu-xenos-occlusion.dll`.
Configure that DLL in **Xbox native tools**, then rebuild the game project to stage
it. No compiled plugin or copyrighted game content is distributed with the app.

### Multiplayer and delivery

The requested scope is campaign coop, including local split screen and eventual direct
IP. Competitive Reach multiplayer is excluded. The disc's `ReachTU1.xex` is a different
executable; its presence does not mean its code is part of the campaign port.

UDP transport/address conversion is only part of network play. Session creation,
discovery, player membership and synchronized campaign state still need real host/client
implementations. The current direct-IP adapter does not establish a campaign session;
unimplemented XGI/XNet functions must not report a fabricated connected state.
Local two-profile routing is implemented; a complete split-screen session remains
subject to game testing. No Xbox Live service is supplied.

After an update, verify the actual EXE/plugin hashes and launch that recorded build.
Editing sources without rebuilding was a previous source of misleading test results.
Do not disable antivirus automatically or evade a quarantine; preserve reproducible
build logs, hashes and the original executable for investigation. Keep compiler outputs,
SDKs, assets and caches outside the shipped app source. Packaging only the UI while
depending on a private research checkout is not a complete integration.

## Shared operations

`xbox_open`, `xbox_info`, `xbox_tools`, `xbox_install`, `xbox_attach`, `xbox_create`,
`xbox_build`, `xbox_run` and `xbox_guide` are exposed through the same authenticated
Runtime to ImGui, CLI and MCP. Discover each schema before calling it. Files are staged
by the Runtime; directory snapshots are bounded and reject links/reparse points.
Cancellation must finish before temporary job artifacts are cleaned up.

Official reference: https://github.com/rexglue/rexglue-sdk
