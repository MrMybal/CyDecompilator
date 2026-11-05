# Xbox native porting

Discover the server's current `xbox_*` schemas. Read `xbox_guide language=en|fr`
for the full shipped method and known problems before changing a native profile.

`xbox_open` accepts exactly one absolute `file` or `directory`. ISO means XDVDFS;
ZIP must contain one ISO. Use a folder/disc to include game resources. A bare
XBE/XEX deliberately imports only the executable. Inputs are preserved in the
persistent analysis project; directory links and reparse points are refused.
Use `entry` for a relative executable when defaults are ambiguous.

`xbox_info` separates prepared input from a native project/build. Xbox first
generation has XBE inspection/preparation only: do not claim native recompilation.
Xbox 360 uses a separate ReXGlue SDK; inspect/configure `xbox_tools`, or use the
authorized `xbox_install` operation for the official pinned Windows SDK. Compiling
needs Windows x64, Clang/Visual Studio C++, Ninja/CMake and the Windows SDK.

`xbox_create` emits a persistent editable CMake/ReXGlue project. The verified Halo
profile is restricted to its original executable SHA-256, not its title/name.
Generic games need their own function/helper/callback/exception analysis and runtime
compatibility. Never reuse Halo's addresses in another executable. SDK source stays
unchanged; overlays operate on generated copies. Never hide unresolved branches,
missing graphics or unimplemented services behind successful stub return codes.

`xbox_attach` registers an existing native project after checking its original XEX,
manifest and existing build receipt. This does not copy its resources or execute it.
Retain the original directory. `xbox_build` performs actual generation/compilation
through the job-owned process tree. A failed/cancelled build cannot be launched
as though it had updated the prior playable executable.

Use `workspace_open` on the native project's returned `directory` to edit sources
in Project IDE. Recompile before testing changes. `xbox_run` verifies the original
and compiled executable, the manifest and recorded optional GPU plugin, then owns
the running game until exit or cancellation. Its `coop` option is for the exact Halo
profile: keyboard/mouse player one, first physical controller player two. Saved
in-game display preferences may override initial `fullscreen`.

Unlocking presentation FPS is separate from simulation frequency. Interpolate
previous/current simulation state, with object and per-view identity, reset on
discontinuities and restore temporarily modified guest data. Handle cinematic
ships, vehicle transforms and follow cameras separately from biped animation.
Physics substeps must preserve elapsed time; sprint weapon bob stops airborne.
GFx menu clicks run on the guest UI thread and preserve registers. Input devices
and offline profiles must be distinct for local coop. Network/wire hooks must
respect the PowerPC argument ABI and big-endian ports/addresses.

The optional DXR work is experimental, with incomplete material/light extraction
and spatial rather than temporal denoising; lens-flare fixes remain subject to
visual validation. RT is suspended with two local profiles. Direct IP UDP routing
does not provide a complete campaign session. Competitive Reach multiplayer is
explicitly excluded. Do not implement or announce Xbox Live service support.

Report actual build hashes and observed scenarios. `nativeGameReady=false` and
`executed-unverified` are deliberate: compilation, a clean exit and finite tests
do not prove a complete game or full Xbox catalogue compatibility.
