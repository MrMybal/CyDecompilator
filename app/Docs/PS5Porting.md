# PS5 input preparation and desktop ports

CyDecompilator owns input inspection, snapshots, job scheduling, conversion receipts
and execution assertions. Actual console API/GPU compatibility comes from the optional,
separate [AnyPS5](https://github.com/boykopovar/AnyPS5) backend. Container extraction
uses the separate [PS5 UltraPack](https://github.com/knutwurst/ps5-ultrapack) CLI.
Both engines remain separate programs. Experimental AnyPS5 changes are provided as
a GPL source patch; no engine code is imported into the Python application.

This is a desktop porting workflow, not a complete PS5 emulator or a promise to
reconstruct the original source project. Existing Workspace/Project IDE operations
can investigate the prepared executable and reconstruct supported source separately.

## Native interface

Open **PS5 porting** in the sidebar.

1. Under **Porting tools**, install official AnyPS5 tools for Windows or Linux.
   Install UltraPack when starting with PKG/PFS/archive inputs. Its package helper
   build needs .NET SDK 9+. Existing installations can instead be configured by path.
2. Select one application file or folder. A complete extracted folder should include
   its own `eboot.bin`, runtime modules and resources. Choose a relative entry when
   the input contains several applications. **Prepare input** creates a persistent
   project; the supplied original is preserved.
3. Check prerequisites, select the target OS, then **Convert for desktop**. Optional
   AMD instruction rewriting is delegated to the selected converter. **Standalone
   homebrew** must be explicitly selected and rejects bundled executable modules.
   **Analyze conversion failures automatically** is enabled by default: a converter
   failure produces a bounded built-in C/assembly dossier without changing the input.
   Additional root executables are passed with AnyPS5's `--executable`, separately
   from shared PRX modules; all their output formats are checked before a receipt
   is accepted. `secondaryExecutables` and `additionalExecutables` report them.
   A converter without that switch or an ambiguous mix of loose root libraries and
   secondary root programs fails explicitly. Existing module folders remain intact.
4. Expand **Test scenarios**, provide expected outputs/exit codes, then run the
   converted application. Inspect diagnostics and the separate output directory.

The AI page offers **Port and test** for the selected prepared project. It uses the
same operations and existing provider credentials, with bounded steps/checkpoints.

**CyDecompilator analysis** can also inspect the prepared entry or a selected module
before conversion. It uses the native disassembler, built-in C engine or an installed
Ghidra engine, shows affected functions and opens the analyzed executable in Workspace.
The built-in native/C loader now reads ELF program load headers when sections are absent;
that fallback rejects malformed/overlapping ranges and limits loaded data to 512 MiB.

## Operations and automation

The operation contract is generated in `CyTool.json`. MCP names are prefixed `op_`;
parameters use the normal envelope, for example:

```json
{"parameters":{"file":"D:/applications/own.pkg","maxBytes":274877906944}}
```

| Operation | Purpose / notable inputs |
|---|---|
| `porting_open` | Exactly one `file` or `directory`; optional relative `entry`, `maxBytes`. Returns `projectId`, `importId`, manifests and ELF evidence. |
| `porting_info` | Read a prepared input by project and optional import id. Includes `unwrapped` and `unpreparedSelf`. |
| `porting_tools` | Read/configure absolute `relinker`, `windowsLibraries`, `linuxLibraries`, `ultrapackCli`, `ultrapackPython`, `ultrapackPkgTool` paths. |
| `porting_install` | `backend=anyps5` installs converter plus `target` libraries; `backend=ultrapack` installs source/private Python and, by default, its package helper. `buildPkgHelper=false` omits the helper. |
| `porting_plan` | Inspect input and missing target tools; readiness is not a compatibility verdict. |
| `porting_convert` | `projectId`, optional `importId`, `target`, `toIntel`, explicit `standalone`. Returns persistent conversion receipt and diagnostics. |
| `porting_diagnose` | Hash-bound guest analysis and AnyPS5 evidence links. Optional `engine=cdec/native/ghidra`, `module`, `importId`, `attemptId`, `conversionId`, `maxFunctions`. No application execution or patching. |
| `porting_conversion` | Read the latest or a selected `conversionId` and output manifest. |
| `porting_run` | Verify hashes, run a new private copy on the matching host, enforce `timeout` and up to 20 scenarios. |

An execution scenario can contain:

```json
{"arguments":["--export","sample"],"stdin":"","expectedExitCode":0,"expectedStdout":"done\n"}
```

Use expectations from the requested behavior or independent observations, not the
converted program's own output merely to make it pass. Line endings are exact.
Every asserted case must pass for `scenarios-passed`. A run without assertions is
`executed-unverified`; a conversion is always initially `converted-unverified`.
These states do not claim whole-application equivalence. The integrated
`ai_agent workflow=port` requires an asserted successful run and unchanged receipt
files before it accepts completion; a later failed run invalidates old proof.

## Connecting AnyPS5 to our analysis engines

Every completed converter invocation saves an `attemptId` and its bounded output,
including failures. A run saves a `runId`; diagnoses use only matching input and
conversion records. The default automatic analysis can be disabled with
`porting_convert analyzeOnFailure=false`. A diagnostic failure is reported separately
and cannot turn a converter failure into success.

`porting_diagnose` verifies the selected guest bytes and any conversion registry
against their manifests. It analyzes/disassembles actual functions, locates decoded
syscall instructions and reads NID/library/call-site records from AnyPS5's main registry.
It returns source hashes, evidence origin/line/index, exact instruction matches,
bounded C/assembly samples, coverage and unknowns. A module can be analyzed separately;
unattributed converter errors are not assigned to it just because addresses coincide.

AnyPS5 v0.1.2 can print a guest virtual address under the label `code offset`.
Registry/diagnostic values are therefore checked against guest virtual and file-offset
mappings. Only a unique decoded instruction can be linked to a function; ambiguous
interpretations and uncertain module attribution remain unresolved. Runtime host
pointers/return addresses are not translated by guessing a base address. A traced
NID may identify candidate source call sites, not the exact observed caller.

The native/C sectionless loader does not yet resolve the full console dynamic NID
symbol format. C samples can retain unresolved imports or explicitly unmodeled
instructions; `hasUnmodeledInstructions` flags known unsupported-instruction comments.
Such C is analysis evidence, not a drop-in implementation. Diagnosis does not implement
missing APIs, rewrite syscalls, rebuild GPU compatibility or prove game equivalence.

Windows conversion options `diagnostics=true` and `traceImports=true` request the
actual AnyPS5 `--windows-diagnostics` and `--trace-imports` switches after capability
probing. Instrumentation additionally requires `libc.prx` among the guest's selected
library dependencies; merely copying the compatibility library into the output is
insufficient. Unsupported switches or inputs fail explicitly.

For an instrumented Windows conversion, `porting_run traceLibraries=all` or a
comma-separated list such as `libkernel,libSceSaveData` controls `APS5_TRACE_CALLS`.
The variable is cleared when tracing is not requested. The adapter parses call
entries emitted in captured output; this is not a continuous tracing UI and no
trace entries are invented when the backend emits none. Ordinary finite scenario
assertions are still required for execution validation.

## Inputs and limits

- Built-in preparation handles x86-64 little-endian ELF64, mapped plaintext SELF
  (including kernel fake-SELF) and ordinary ZIP. SELF rebuilding is limited to
  512 MiB input / 1 GiB output and explicitly resolvable segment mappings. Compressed
  segments, encrypted executable payloads and ambiguous layouts are refused.
  Non-load metadata may legally have a smaller/zero memory size. Missing note,
  version or comment payloads are explicitly listed in `unwrapped[].omittedMetadata`
  and removed from the rebuilt metadata table; essential load/dynamic data cannot
  be silently omitted. Original SELF files are retained.
- Encrypted signed resources under `sce_sys`, such as `about/right.sprx`, may be
  retained unchanged and listed as opaque metadata. This does not mean they were
  decrypted. An unsupported primary executable or required runtime module stops
  preparation. No key acquisition/decryption is implemented.
- UltraPack extracts PKG, FFPFS/FFPFSC, exFAT/FFPKG, RAR and 7z into a job-owned
  directory. Supported package variants/codecs depend on that backend and helper.
  RAR may require an external unrar or 7-Zip installation. Password prompts and
  automatic multipart companion discovery are not exposed by this adapter.
- The prepared input/temporary extraction limit defaults to **256 GiB** and can
  be set up to **1 TiB**. Runtime file staging accepts up to 1 TiB. Trees are limited
  to 100,000 files and reject links/reparse points, traversal, nonportable names and
  case collisions. Extraction is monitored approximately once per second and
  validated again on completion; transient disk use can exceed a limit between polls.
  SDK staging, extraction, conversion and execution need separate working copies.
  The relinker input copy includes code/modules/metadata; the complete resource tree
  is copied once into its output. On one volume that validated job output moves
  atomically into persistent project state; another volume uses a cancellable verified
  copy. The extra private container copy is discarded after extraction, with its
  hash/size retained. SDK staging is cleaned up at task finish. Execution still uses
  a fresh complete output copy, so a large game's resources need corresponding
  free space on the job drive. Transient UltraPack scratch-file moves are tolerated
  during monitoring; the completed application receives strict final validation.
- Library names found in strings are explicitly candidates, not proven imports.
  Prerequisite checks inspect configured files, not the completeness of all console
  APIs. The converter's actual version determines supported CLI switches and modules.
- Output targets are Windows PE and Linux ELF, x86-64. Execution requires the matching
  OS/architecture. Linux conversion can be requested on Windows; local Windows tests
  do not validate Linux execution. GPU/driver requirements belong to the backend.
- The adapter does not autorun conversions, silently skip game modules, apply input
  patch configuration or disable syscall checks. All target execution is an explicit
  run/capture operation with owned child-process cleanup and bounded output.
- `porting_run` currently asserts stdout and exit codes. Existing behavior operations
  can gather richer graphical/network evidence; this workflow does not automatically
  establish audio, controller, visual, network or whole-game equivalence.

## Installation and persistence

AnyPS5 official release assets require published SHA-256 digests. The host converter,
target libraries and their archive are stored under `runtime/engines/anyps5`; reuse
checks both downloaded asset hashes and extracted library contents. CLI capabilities
are probed because released versions can lag upstream documentation.

UltraPack is downloaded from its official repository at a resolved Git commit,
with source/archival hashes recorded locally. Its Python dependencies live in a
private venv under `runtime/engines/ultrapack/<commit>`. They are not installed in
the application's Python. The optional package helper is built from that source
using .NET SDK 9+. Source archives do not publish an independent checksum; recorded
local hashes are not a publisher signature. Runtimes/dependencies retain their
upstream licenses. Profiles and extraction scratch files stay in the owning job.

Settings live in `data/settings/porting.json`. Prepared inputs, originals of unwrapped
SELF files, conversion receipts and run reports are explicit persistent project
state under `data/projects/<id>/porting`. Task cleanup removes job intermediates,
not these records. Hash verification refuses an altered prepared input/output.

## Experimental AnyPS5 source profile

`engine-patches/anyps5-depth-copy.patch` targets upstream commit
`b6583dd8687f359c2caea295cde23e4732b73433`. Its JSON manifest records the patch hash,
before/after source hashes, test selection and limits; the GPL-2.0-only license is
included beside it. It implements single-sample DB depth-to-color copies using the
title's actual drawing geometry and a driver fragment shader. Multisample, layered
and unsupported maintenance combinations are refused. A descriptor update also
retains an unchanged stage's descriptor set when only the other stage needs a
snapshot, rather than rewriting both stages' textures and buffers.

With the pinned recursive upstream checkout, the supported WinLibs toolchain and
the Khronos Vulkan validation layer available separately, build a fresh profile:

```powershell
runtime/python/Scripts/python.exe app/scripts/build_anyps5_depth_copy.py --source runtime/engines/anyps5/compat-source --build runtime/engines/anyps5/compat-build --toolchain-bin runtime/engines/winlibs/15.2.0posix-14.0.0-ucrt-r7/mingw64/bin --validation-layer-dir runtime/engines/vulkan-sdk/1.4.363.0/layers/Bin --output runtime/engines/anyps5/my-depth-copy-profile
```

The script checks the revision and source hashes, applies the patch when necessary,
builds the relinker and libraries, and runs GPU checks with validation both with and
without graphics pipeline libraries. Missing layers, skipped tests and VUID errors
fail the build. Existing output profiles are preserved. The result prints the
`relinker` and `windowsLibraries` paths accepted by `porting_tools`; it does not
change settings. Reconvert a prepared project to retain a new receipt with those
exact backend hashes. This experimental profile is separate from official release
updates and remains unverified for general gameplay.

The D32 Vulkan fixture checks 14,336 pixels across full, half, triangle, rectangle,
scissor and culling cases, including unchanged pixels outside the drawing coverage.
It passed on an RTX 3090 with no VUID errors in either pipeline mode, alongside the
six focused existing graphics/snapshot tests. D16 hardware values, multisample copies,
other GPUs and console equivalence are not established by these checks.

Windows UI Automation/PrintWindow captures can remain black for a Vulkan window
that actually renders. For this investigation the backend's own bounded GPU frame
dumps were checked as well. Capturing a cinematic at 60 FPS establishes neither
the performance of the later 3D scene nor successful gameplay. Performance reports
must name the scene, cache state and capture/profiling options.

Interactive runs must leave `APS5_NO_PAD_INPUT` unset. That diagnostic switch
discards keyboard and mouse events. `porting_run` clears an inherited value.
`APS5_PAD_INPUT_FILE` can inject controlled
buttons while keeping physical input active. Default bindings include Enter or
Space for Cross, Escape for Options, arrows for the directional pad, and WASD for
the left stick. Keyboard focus must be on the game window. At very low frame rates,
brief button presses can be missed or appear delayed.

The experimental snapshot cache also accepts aligned subranges of an already
captured, unchanged buffer. It retains the same write/collection/registry stamp
checks, byte and entry caps; requests crossing the cached range or violating
descriptor alignment use the regular path. This targets buffer-copy CPU cost;
it does not establish a gameplay speed improvement without a scene comparison.

A local before/after comparison of the first stationary 3D room on the RTX 3090
measured approximately 1.13 versus 2.06 presents per second. Both runs used the
same executable, working directory, active physical input and profiling/capture
options, with accumulated shader caches. Complete ten-second summary intervals
after 60 seconds were aggregated; the setup panels evolve during these runs.
A separate pair of ten-second windows showing the same welcome dialog measured
approximately 1.14 versus 2.55 FPS, with matching GPU captures retained. Animation
and workload timing can vary. This
compares two modified depth-copy profiles, since upstream main rejects that draw.
These rates remain insufficient for playable behavior. Shader ABI preparation
and the remaining buffer/draw work still consume substantial CPU time.

### CyDecompilator shader preparation profile

`engine-patches/cy-render-preparation.patch` includes the depth-copy and buffer
changes above and replaces repeated shader-state copies with shared immutable
states. A transaction copies a state only when editing it. Publication invalidates
the shared view; existing readers retain their original version. Registration and
source-handle insertion invalidate the view under the existing synchronization.
This changes CPU preparation inside the AnyPS5 backend; loading, system libraries
and shader translation still depend on AnyPS5. The shared view retains one extra
copy of the current state's containers per cached shader; compiled artifacts
remain shared. Retained readers can keep an older version until their transaction
ends. Memory consumption has not been benchmarked separately.

Build this profile with the same script and arguments above, adding
`--manifest app/engine-patches/cy-render-preparation.json` and choosing a new output
directory. The builder refuses source changes absent from the selected manifest.
The depth-only manifest remains available for reproducing the earlier profile.

Ten focused GPU tests pass with Vulkan validation in both pipeline modes. The
publication tests exercise retained readers, aborted edits, nested transactions,
registration races and fresh reads after publication. Three preparation tests also
pass with `APS5_NO_SHARED_PREPARED_STATE=1`, a diagnostic switch selecting the old
copying path for comparisons with the same binary. Keep that switch unset for the
shared-state path. Functional tests do not establish a gameplay performance gain.

A local same-binary comparison on the RTX 3090 measured 2.67 FPS using the legacy
copying path and 3.06 FPS using shared states on the same rendered title screen
(about 15% higher). Reported shader ABI preparation fell from 211 to 152 ms per
present; GPU work was approximately 43.6 ms in both cases. Each selected run spans
about 41 seconds with accumulated shader caches, active physical input, identical
capture/profiling settings and retained GPU images. The cinematic ended at different
times, so matching title-screen intervals were selected separately and main-menu
intervals were excluded. The report and `trace_digest.py` summaries are retained
locally as `data/reports/pkg-PPSA34502/preparation-performance-comparison.json` and
`preparation-{legacy,shared}-trace-digest.txt`. This compares two modes of our
modified backend; unmodified upstream rejects the depth-copy draw. The measured
gain is limited to this scenario and remains insufficient for playable behavior.

### Persistent read-only snapshot slices

`engine-patches/cy-render-snapshot-slices.patch` extends the preparation profile
with a C++ path that reuses an immutable portion of a previously captured storage
buffer across collection epochs. The exact-size cache remains first. On a miss,
the path checks a containing snapshot at the same base or up to sixteen recent
storage snapshots. Descriptor offsets and lengths retain the requested range.

Reuse requires matching allocation-registry identity and valid descriptor alignment.
Write tracking proves the requested bytes unchanged; dirty or uncertain blocks
are compared against the retained snapshot. Checking one slice never advances the
generation of unchecked portions of the buffer. A mismatch falls back to the
existing capture path. Prior draws retain their original bytes. The existing
1 GiB storage-cache budget and 1,024-entry cap still apply.

Build with `--manifest app/engine-patches/cy-render-snapshot-slices.json` and a fresh
output directory. The manifest adds the isolated `agc_draw_snapshot_slices` test.
`APS5_NO_PERSISTENT_DRAW_SLICES=1` selects the earlier capture policy for a comparison
using the same binary. Keep the switch unset to use persistent slices. This replaces
one buffer-preparation path inside the compatibility backend; the original game
logic and the remaining AnyPS5 loading, translation and system-library paths remain
in use.

Eleven focused tests pass on the RTX 3090 with Khronos validation, both with and
without graphics pipeline libraries. The isolated slice fixture checks CPU writes
inside and outside a requested slice, dirty blocks whose selected bytes remain
equal, registry changes, alignment, range boundaries, eviction and retained reader
immutability. A GPU transfer reads 65,536 bytes from a nonzero returned slice offset
and checks every resulting byte. The build requires both fixture completion messages.

The local same-binary title-screen comparison measured median ten-second-window
rates of 2.37 FPS with the earlier capture policy and 3.77 FPS with persistent
slices. The aggregates over the selected matching title-screen intervals were
2.26 and 3.82 FPS; the reference process exited earlier, so the selected durations
differ (61 and 81 seconds). The reference includes a long frame in its last selected
interval. GPU busy time increased from about 22 to 49 ms per present in these runs;
the change does not establish a GPU speed improvement. CPU `Graphics.Draw` time
decreased from about 256 to 77 ms per present. These phase times overlap and must
not be added to GPU time.

The last three main draw-thread counter reports averaged 0.288 versus 0.040 MiB
copied per draw (about 86% fewer copied bytes). Those approximate ten-second
counters are reported separately from the exact summary intervals. Scene matching
uses retained GPU images and the title-logo region, followed by visual inspection;
cinematics and main-menu intervals are excluded. Reports and trace digests are
retained locally under `data/reports/pkg-PPSA34502/snapshot-slices-*`. The later
functional check of the final profile runs during full-project conversion and is
excluded from performance comparisons. These rates remain far below 60 FPS and
do not validate full gameplay.

### Native graphics ABI preparation and concurrent readers

`engine-patches/cy-render-native-readers.patch` and its pinned manifest replace the
graphics ABI state preparation path with compact, sorted register words. The path
retains the original implicit context and user configuration registers, applies
header, fused-stage and caller overrides in order, and produces the same canonical
ABI keys. Scratch buffers are reused. Dense register banks are reconstructed only
when a new graphics ABI must be prepared. Header arrays are read with bounded,
unaligned-safe copies without allocating a temporary array for each header.

Prepared ABI cache hits use concurrent immutable readers under a shared lock.
Writers retain exclusive publication. A cache miss releases the read lock and
reacquires the writer lock before taking fresh preparation snapshots; a staged
transaction cannot use the read-only shortcut. Pending or failed registration,
expired stage links, a new rectangle request, or changed stage entry counts take
the preparation path. The shortcut does not skip shader execution or rendering.

Nineteen focused checks pass locally on the RTX 3090 with Khronos validation in
three configurations: regular pipelines, no graphics pipeline libraries, and
canonical-key comparison against the previous dense state resolver. The checks
include parallel readers, writer exclusion, upgrade to a fresh writer, retained
snapshot immutability, nested staged edits, and pending/failed preparation. Eight
additional ABI deferral scenarios cover stage, rectangle and registration failures.
The original upstream library passes the corresponding eleven preparation checks.

Build with `--manifest app/engine-patches/cy-render-native-readers.json` and a fresh
output directory. `APS5_NO_NATIVE_ABI_STATE=1` selects the dense state resolver;
`APS5_NO_NATIVE_ABI_READERS=1` disables the concurrent-reader shortcut.
`APS5_CHECK_NATIVE_ABI_KEYS=1` compares the compact and dense keys at runtime and
rejects a discrepancy. Keep that expensive comparison disabled for speed tests.
`APS5_PROFILE_ABI=1` exposes state, key, lock and preparation phases in trace
summaries. The CPU timers measure inclusive elapsed time, including waits, summed
across calls and threads and normalized by presentations. They do not measure the
cost of compiling one shader and must not be added together.

The earlier compact-state profile compared over 1.3 million graphics state keys
on the supplied game's bounded run without a discrepancy. CyDecompilator also
disassembled and decompiled the identified compatibility-library function from
the verified binary. Its generated C contains sixteen unmodeled instructions and
is retained as investigative evidence. The replacement is written from the
available C++ source; generated C is not used as an executable replacement.
This changes preparation inside the AnyPS5 backend. Loading, system services,
shader translation and Vulkan rendering remain in use; it is not a reconstruction
of the game's entire original graphics engine.

### Native graphics resource profile

`engine-patches/cy-render-native-graphics.patch` and its manifest combine compact
ABI state, concurrent readers for graphics/pixel preparation and immutable GPU
buffer snapshots. Known rectangle stage combinations also take the reader path;
new fragments and changed preparation counts still rebuild through an exclusive
transaction.

Large persistent read-only snapshots now have a device buffer uploaded once with
queued GPU copies. Draw descriptors use this buffer with the original slice
offset and range. A mapped host mirror remains available for write tracking and
byte comparisons. CPU writes invalidate reuse and produce a new snapshot rather
than changing a cached resident copy. Neither an upload nor a cache hit adds a
CPU wait. The existing device-buffer allocator prefers device memory and supports
host placement under memory pressure.

Resident cache accounting is limited to 256 MiB of logical snapshot data and 256
entries. In-flight draws retain their resources after eviction; allocator pools
and in-flight allocations have their existing separate accounting. Transient,
small, unaligned, unsupported and oversized sources retain the host path.
Diagnostic input captures read the same selected buffer as the descriptors.

Build this combined profile with
`--manifest app/engine-patches/cy-render-native-graphics.json` and a fresh output
directory. `APS5_NO_RESIDENT_DRAW_SNAPSHOTS=1` disables resident snapshot uploads.
The isolated GPU fixture checks slice contents, reuse, eviction, retained reader
values, source replacement and CPU write invalidation. Nineteen focused checks
pass with Vulkan validation in all three configurations. A bounded functional run
of the combined profile renders the title screen. A later capture after advancing
is black while shader preparation and resource lookups are still logged; that
subsequent phase and gameplay remain unvalidated. The combined profile has not
been assigned a performance result. It remains a partial replacement of
graphics preparation and memory management inside the compatibility backend;
it does not recover or replace the complete original game engine.

### Native graphics input reuse

`engine-patches/cy-render-native-state-cache.patch` adds a bounded per-thread
cache before register merging. Each entry identifies the immutable registration
registry, the ordered shader snapshots, live fused-header register overrides,
context and primitive registers, device serial and compilation policy. Header
validation still runs before lookup. A matching input reuses its canonical state
only after checking the published preparation and rectangle dependencies.
Otherwise the regular preparation path runs. Registry replacement clears the
cache; changed inputs select a different entry. The cache retains at most 64
entries with bounded key sizes and does not keep old registries alive.

Build it with `--manifest app/engine-patches/cy-render-native-state-cache.json`
and a fresh profile directory. `APS5_NO_NATIVE_ABI_INPUT_CACHE=1` disables this
path. `APS5_CHECK_NATIVE_ABI_KEYS=1` reconstructs states on cache hits and compares
the cached result with both native merging and dense reconstruction. The shader
fixture changes overrides in place, repeats inputs and rejects a changed header
after a previously successful lookup. No performance or gameplay claim follows
from those checks.

### Published preparation views

`engine-patches/cy-render-native-published-views.patch` lets ready-state queries
read immutable published snapshots without holding the global publication lock.
Each query samples a revision, reads the required states under their individual
mutexes and accepts the result only if the revision is unchanged. Group commits
and registry replacements invalidate the revision. Staged edits, pending states,
failed preparation and changed revisions keep the transactional path.
The original blocking `ReadOnly` API retains its lifetime and writer exclusion
contract. Concurrency fixtures check retained snapshots, publication while a view
is alive, group consistency, registry replacement and staged-write rejection.
Build with `--manifest app/engine-patches/cy-render-native-published-views.json`.
These correctness checks do not establish a frame-rate improvement.

### Shared native binding metadata

`engine-patches/cy-render-native-binding-metadata.patch` groups the sixteen
metadata vectors of a descriptor binding in shared storage. Prepared plans,
materialized shader results and draw copies retain that storage. A mutable
metadata access detaches a shared payload before changing it; descriptor words
and push constants remain specific to each result. This avoids cloning image,
sampler and buffer access metadata on every materialization. The descriptor
cache codec retains its field order. The graphics fixture checks that changing
one draw's buffer-write classification cannot change another draw's validation.
The grouped checks also include descriptor selection, artifact isolation and
cache serialization through the shader cache fixture.

Build with `--manifest app/engine-patches/cy-render-native-binding-metadata.json`
and a fresh profile directory. This changes preparation in the C++ graphics
backend; it does not reconstruct the complete original engine or establish
60 FPS.

### Registered graphics call reuse

`engine-patches/cy-render-native-calls.patch` adds a bounded per-thread shortcut
for repeated preparation, stage binding and rectangle binding calls. The key
includes the device and compilation policy, ordered header addresses and header
bytes, context overrides and primitive registers. The per-draw user-data pointer
is excluded because static ABI resolution uses the registered snapshot instead.
Only headers at their actual registration address and without a fused-type
override are eligible. Changed publication revisions, expired registries, altered
inputs and staged edits retain normal lookup and validation. Relocated and fused
headers keep the full path. The fixture also changes a cached header's code
pointer to an unregistered program and verifies that resolution fails.

This profile includes shared binding metadata, publication views and resident
buffers. Build with `--manifest app/engine-patches/cy-render-native-calls.json`.
Performance and full-game coverage must be established separately.

### Invocation source reuse

`engine-patches/cy-render-native-invocations.patch` also reuses prepared source
handles before taking the per-shader preparation mutex. A bounded per-thread
cache holds weak references, the exact static ABI key, binding layout and code
offset. Publication changes invalidate the entries, including activation of
converted sampling. Each reuse still validates the prepared invocation against
the current request; live user data is captured again. Linked callees and
converted sampling retain the full lookup path. The fixture checks changing
invocation data, descriptor layouts, removed prepared entries and shader lifetime.

Build with `--manifest app/engine-patches/cy-render-native-invocations.json`.
The profile is experimental; compilation and focused GPU checks do not establish
60 FPS or full-game compatibility. Local library iterations can update the
existing disposable working copy without duplicating the game's resources;
immutable conversion receipts remain separate from that working copy.

### Draw resource transfer and descriptor reuse

`engine-patches/cy-render-native-draw-resources.patch` groups new resident buffer
uploads for a draw between one pair of buffer-scoped barriers. Existing resident
buffers are retained, duplicate sources share one upload, and original slice
offsets are preserved. The destination access is shader read; the conservative
destination stage remains valid for graphics and compute queues. Cache limits and
CPU-write invalidation are unchanged.

After the normal snapshot and write checks, rewritten descriptor sets can be
reused independently for the main and fragment stages when their selected
buffer identities, offsets and ranges match. Each resource object keeps at most
eight weak entries per set; the cache retains neither descriptor sets nor game
buffers after their recorded users release them. Changing one stage's data
replaces its set. Images and other unchanged bindings come from the completed,
immutable resource object. `APS5_NO_DRAW_SET_REUSE=1` disables this reuse.

Build with `--manifest app/engine-patches/cy-render-native-draw-resources.json`.
Fixtures read back three distinct GPU upload slices, check duplicate suppression,
and check repeated, independently changed and restored descriptor sets and their
lifetime. These checks do not establish game performance or full-game coverage.

### Native draw submission storage and prepared lookups

`engine-patches/cy-render-native-submission.patch` adds reusable C++ scratch
leases for draw preparation. A queued direct or indirect draw retains its entire
lease until command recording finishes, so another draw cannot overwrite its
stage pointers, shader memory or snapshots. Returned leases release all resources
before pooling their vector storage. Each producer pool retains at most 64 leases;
a lease above 512 KiB is discarded. Inline, recursive and failed preparation paths
use the same ownership rules. `APS5_NO_NATIVE_DRAW_SCRATCH=1` disables pooling.

Prepared binding plans and specialized modules also have bounded thread-local
weak lookups, with exact complete keys and module-plan ownership checks. A binding
plan key includes the fragment descriptor-set policy. Misses retain canonical
shared caches and one-time initialization; only initialized successful entries
enter the local lookup. Each lookup holds at most 128 entries, each capped at
4,096 key words. `APS5_NO_NATIVE_PREPARED_LOOKUPS=1` disables these lookups.
`APS5_CHECK_NATIVE_ABI_KEYS=1` checks hits against canonical entries.

Build with `--manifest app/engine-patches/cy-render-native-submission.json`.
The focused suite additionally exercises asynchronous indirect draws, queued index
reads, changing shader data, inline draws and committer shutdown. It runs with
Vulkan validation in standard, no-pipeline-library, canonical-key-verification and
native-reuse-disabled modes. Existing depth, snapshot and publication checks are
retained. These checks establish finite rendering and ownership behavior, not
60 FPS or full-game equivalence.

`APS5_TRACE_EXIT=1` records guest main returns, requested shutdown status,
normal or handler-free shutdown and SDL quit events. This is diagnostic only;
window-close and guest-exit behavior is preserved. Local iterations replace
hash-verified libraries in one reusable working copy without copying game assets.

### Descriptor reuse after completed GPU batches

`engine-patches/cy-render-native-descriptor-lifetime.patch` extends the native
submission profile with descriptor handles that can survive completed GPU batches.
The earlier weak-handle cache loses an entry as soon as its last recorded user is
released. This profile retains at most eight immutable handles per stage and
resource object; each cached binding keeps weak CPU/device-buffer ownership proofs.
An expired source invalidates the entry before raw-pointer keys are compared.
The handles do not keep snapshot buffers alive.

Retention has a shared budget of 262,144 units across devices and resources:
64 units per handle plus its descriptor count. A full budget falls back to weak
handle reuse, and handle destruction returns its units. Resource release clears
cached handles before releasing the original layouts and descriptor allocations.
`APS5_NO_PERSISTENT_DRAW_SETS=1` selects the earlier weak-handle behavior.

Build with `--manifest app/engine-patches/cy-render-native-descriptor-lifetime.json`.
The draw fixture releases complete recorder batches, requests unchanged sets again,
changes both stages independently, exceeds the entry bound, verifies buffer release
and reintroduces evicted data. The same 27-check suite runs in four Vulkan
validation configurations, including a mode with persistence disabled. The builder
rechecks source hashes after compilation and validation before publishing a profile.
Rendering the main menu and measuring game performance remain separate checks.

### Stable parameter buffers and incremental resident updates

`engine-patches/cy-render-native-buffer-updates.patch` recycles parameter buffers
only when their pool is the sole remaining strong owner. Recorded draw bindings
retain their buffers through GPU completion; live readers prevent reuse. A matching
allocation and size can therefore receive new words without allocating another
buffer or changing its descriptor identity. The eight-slot parameter pool prefers
free slots when admitting a new value. `APS5_NO_MOVED_BUFFER_RECYCLING=1` restores
allocation on changed words.

A persistent storage snapshot can also retain its device buffer when both its CPU
buffer and device buffer have exclusive cache ownership. Changed tracked blocks
are compared against the CPU mirror; differing ranges are merged and aligned to
four bytes, then uploaded together through the existing visibility barriers.
Pending changes accumulate until upload. An outstanding reader forces immutable
replacement, and a failed upload invalidates the resident entry for a full retry.
The existing host/device cache budgets are unchanged.
`APS5_NO_RESIDENT_DRAW_UPDATES=1` selects the earlier replacement path.

Descriptor-cache lookup checks buffer lifetime only for a matching key; expired
entries are also removed on insertion. Every accepted hit still proves ownership.
The focused fixtures exercise retained readers, completed parameter-buffer reuse,
descriptor eviction, two separated dirty GPU ranges and every unchanged readback
byte. The build manifest requires actual incremental GPU readback in the three
enabled modes and checks the disabled fallback in the fourth mode.
Build with `--manifest app/engine-patches/cy-render-native-buffer-updates.json`.
These checks do not establish 60 FPS or full-game compatibility.

`engine-patches/cy-render-native-scheduling.patch` moves completed draw-resource
destruction outside the pipeline mutex. Completion remains outstanding until
destruction finishes, so a drain still waits for retained resources to be released.
Its regression case queries the queue from a captured object's destructor and
checks that a simultaneous drain cannot finish early.

The Windows host allocator adds size classes through 64 KiB with a 512 KiB cache
budget per thread. Non-class-sized foreign blocks return to the host heap; sized
and unsized deletes, transfers between threads and ending threads are exercised.
SRT evaluation retains at most 1 MiB of heap-frame storage per thread, reserves
read provenance from the immutable tape's read-node count and uses isolated
scratch for nested memory callbacks. Large and nested walks are compared with
the interpreter. `APS5_NO_SRT_FRAME_REUSE=1` disables heap-frame reuse.
`APS5_SAMPLE_COMMITTER=<file>` captures only the draw-committer thread when a
targeted diagnostic is needed; sampling is off by default.

Build with `--manifest app/engine-patches/cy-render-native-scheduling.json`.
These changes do not establish 60 FPS; stable-menu cadence must be measured
separately without detailed profiling.

`engine-patches/cy-render-native-buffer-rotation.patch` retains older storage
snapshot versions after a reader prevents an in-place update. A matching version
can return to service only when its CPU and resident GPU buffers have no readers;
dirty blocks since that version's generation are then refreshed. Current readers
keep their previous CPU/GPU contents. Retired versions are limited to 128 entries
and one quarter of the existing host snapshot budget, with current and retired
versions together held to that original budget. Their resident buffers count
against the existing device snapshot limits and are evicted before active ones.
`APS5_NO_DRAW_SNAPSHOT_ROTATION=1` restores replacement without version retention.

Large host-visible buffer allocations use size classes with at most 12.5% padding.
The mapped span, Vulkan buffer size and descriptor ranges retain the exact request;
only the underlying memory capacity is rounded, under the original pool budget.
`APS5_NO_LARGE_HOST_CLASSES=1` retains exact-size large host allocations.
Fixtures verify allocation reuse, a live reader, requested view bounds, GPU
readback of different sizes, retained version limits and dirty-only rotation while
another GPU version stays unchanged. Build with
`--manifest app/engine-patches/cy-render-native-buffer-rotation.json`.

`engine-patches/cy-render-native-device-parameters.patch` places frequently changed
draw-parameter buffers of at most 64 KiB in host-visible, coherent device-local
memory when the buffer and device support it. A 64 MiB process-wide live-capacity
budget falls back to the normal host-memory path when full; unavailable memory
types or a refused allocation also use that fallback. Charges follow the shared
buffer's lifetime, including readers still using it. Released backing allocations
may remain in the existing bounded buffer pool, so the live-capacity budget is not
a total VRAM-usage limit. Guest buffers and CPU comparison snapshots retain their
usual memory placement. `APS5_NO_DEVICE_PARAMETERS=1` disables the preference.

Fixtures check the selected memory type, budget exhaustion/release, unsupported
buffer memory-type bits, unchanged held data, GPU readback on mapped device memory
and the host-only fallback. Build with
`--manifest app/engine-patches/cy-render-native-device-parameters.json`.

## Fine buffer synchronization

`engine-patches/cy-render-native-fine-updates.patch` refines storage snapshot
updates using the existing CPU page stamps and driver store history. One 16-bit
mask describes the dirty 4 KiB pages of each 64 KiB tracking block; queries take
one tracker lock and allocate no tracking state. Missing coverage, an unknown
generation, insufficient output space or discarded driver history conservatively
invalidate the affected range. Import-window and mapping changes retain the
existing tracking semantics.

Only dirty pages are compared. Changed 256-byte tiles update an exclusively owned
CPU snapshot and its resident GPU buffer; live readers still force an immutable
replacement or rotation through a completed version. Dense updates coalesce to at
most 128 regions, and each buffer's regions use one Vulkan copy command. Alignment
expansion preserves the exact logical buffer bounds. Existing host/device budgets
remain unchanged. `APS5_NO_FINE_DRAW_UPDATES=1` restores block-level comparison and
copy granularity while retaining the grouped Vulkan submission.

The focused fixtures cover CPU and driver stores, lost history, invalid ranges,
unaligned storage boundaries, scattered and dense changes, unchanged writes,
retained versions and full GPU readback. Build with
`--manifest app/engine-patches/cy-render-native-fine-updates.json`.

This implementation is informed by shadPS4's
[buffer synchronization](https://github.com/shadps4-emu/shadPS4/blob/main/src/video_core/buffer_cache/buffer_cache.cpp)
and [memory tracking](https://github.com/shadps4-emu/shadPS4/blob/main/src/video_core/buffer_cache/memory_tracker.h).
It uses CyDecompilator's existing AnyPS5 snapshot/lifetime model; no shadPS4 source
or dependency is incorporated. It does not add a PS4 converter or a PS3 backend,
reconstruct the full game engine, or establish 60 FPS or gameplay compatibility.

## Preparing draw descriptors

Local game experiments reuse the verified working copy on the project drive.
The private runner refuses new full game copies, paths on C: and working copies
outside the workspace. Private package/graphics MCP jobs also use `runtime/build`
instead of the Windows temporary directory. Game trials have a 30-second process
deadline and do not retry automatically.

`engine-patches/cy-render-native-descriptor-plan.patch` builds an immutable draw
descriptor plan when a resource object completes. Sorted descriptor-pool sizes,
variable descriptor counts, source write indices and allocation-to-buffer offsets
are retained with that object. Draw rewrites patch the selected buffers and emit
writes for the affected shader sets without repeating layout traversal or sorting.
Resource proofs, snapshot ownership, descriptor retention budgets and live data
checks remain unchanged. `APS5_NO_NATIVE_DESCRIPTOR_PLAN=1` rebuilds the plan for
each rewrite. This profile excludes experimental SRT replay. Focused array,
split-set and retained-data checks do not establish game performance or 60 FPS.

## Reusing SRT address evaluation

`engine-patches/cy-render-native-srt-replay.patch` adds bounded reuse of successful
SRT evaluation to the driver's `ShaderMemory` reader. General SRT callbacks retain
their existing behavior unless their caller explicitly sets `stableReadReplay`.
This capability requires repeated reads to return the capture's stable word values
without additional external effects. The normal and specialization readers must
be identical. ShaderMemory satisfies this through its per-capture page/word cache;
live reads still perform its normal GPU synchronization and record memory regions.

Reuse checks tape ownership, shader base, user-data contents and tracing shape.
It then replays every previously successful memory read in order. Changed pointers,
conditions or descriptor words reject reuse before later dependent reads and rebuild
the graph. Only raw reads whose roots feed exclusively proven pure flat slots can
change without rebuilding; all corresponding flat slots are refreshed. Failed or
partially evaluated walks are not cached. Nested calls use the ordinary evaluation
path and cannot alter the outer call's cache.

Weak tape owners, at most 32 entries and 2 MiB of retained vector capacity per
thread bound the cache. `APS5_NO_SRT_REPLAY=1` disables it.
`APS5_TRACE_SRT_REPLAY=1` enables aggregate hit/rebuild/rejection counters; these
counters are not frame timings. Build with
`--manifest app/engine-patches/cy-render-native-srt-replay.json`.

`engine-patches/cy-render-native-srt-keys.patch` refines this cache after the first
menu run showed only about 3.8% aggregate hits. When the walk recorded user-data
dependencies, its key compares only registers used as values or bases; unused
registers cannot invalidate the address evaluation. Callers without that evidence
keep full register comparison. Current user-data words still reach materialization
normally. Changed used roots and all live memory words remain checked.

Lookup is indexed by tape, successful entries move to the end of an LRU list, and
rejected records are removed before rebuilding. This profile permits up to 128
entries under the same 2 MiB retained-payload budget per thread; map/list bookkeeping
adds bounded container overhead. Fixtures check unused-register hits, changed used
roots, indexed eviction and the existing interpreter comparisons. Build with
`--manifest app/engine-patches/cy-render-native-srt-keys.json`.

This replaces repeated CPU address-graph evaluation, not shader execution or the
game's complete graphics engine. Performance and gameplay require separate scene
evidence.

The replay profiles remain experimental. The observed aggregate hit rate was
approximately 4% across loading and menu, and no useful scene performance gain was
established. The active local working copy was restored to the fine-update profile.
The latest replay run contains one matching menu capture, which cannot establish
menu cadence; the user reports approximately 6 FPS. The 60 FPS target remains unmet.

## Verification

`tests/test_porting.py` covers real snapshots, malformed input boundaries, embedded
ZIP metadata in PKG, plaintext SELF subranges, opaque signed metadata, MCP provenance,
compiled native execution, exact assertions, altered files and controlled-model
agent completion. Its controlled converter is an adapter-contract test, not proof
that a game works with AnyPS5.
`tests/test_porting_analysis.py` exercises sectionless native/C discovery, malformed
load ranges, syscall/function links, registry hash binding, file/virtual ambiguity,
runtime-address non-inference, separate modules and stale evidence rejection.

To exercise installed official backends on a generated, owned ELF fixture:

```powershell
runtime/python/Scripts/python.exe app/scripts/verify_porting.py --install-anyps5 --install-ultrapack --build-pkg-helper --pfs
runtime/python/Scripts/python.exe app/scripts/verify_porting.py --syscall-check
runtime/python/Scripts/python.exe app/scripts/verify_porting.py --diagnostics
```

Omit installation flags to use configured tools. Reports are saved under
`data/reports/porting-verification`. This real Windows check has passed with AnyPS5
v0.1.2: PFS extraction, ELF conversion, copied libraries/resources and exit-code
assertion. A separately generated 1.2 MiB debug PKG was also imported, with its
plaintext main SELF prepared and its signed metadata explicitly preserved as opaque.
A supplied 22.7 GB debug PKG was also extracted in full (3,551 files), its eleven
plaintext SELF images prepared, and its main/two secondary executables converted
with AnyPS5 v0.1.2 and the complete resources. A bounded Windows run loaded the
modules and initialized Vulkan, then aborted with
`sceVoiceGetPortAttr: attribute 1001 not implemented`. The C diagnosis preserved
that runtime dependency error, its run evidence and source hashes; it did not infer
a guest call site from host stack addresses. The input and converted project remain
separate persistent snapshots. This is a successful conversion and a failed startup
scenario, not validated gameplay. GPU rendering quality and Linux execution remain
unverified.

A separate experimental Windows library profile, built from upstream commit
`b6583dd8687f359c2caea295cde23e4732b73433`, then replaced only `libSceVoice.prx`
in a new complete conversion receipt. Both upstream voice tests passed. The bounded
visual capture displayed logos and the introductory cinematic; advancing through
the intro exposed a second failure: `DB_RENDER_CONTROL = 0x84` depth copy is
unsupported. A full unmodified build of the same upstream commit reproduced that
failure and passed the four focused voice/graphics tests. PM4 capture was retained;
it does not contain the guest memory behind indirect register writes, so it alone
cannot prove the rejected draw's full state or geometry coverage. The later
depth-copy profile crossed this rejection and rendered the title screen, confirmed
by the backend's own GPU frame dumps. A further full conversion with the matching
current-source relinker and libraries also reached that screen. Before the
buffer-range optimization, its steady title scene took roughly 700–1,000 ms per
frame, although the cinematic reached 60 FPS after shader preparation. CPU buffer
snapshot preparation dominated; GPU work was roughly 30–45 ms per frame. Cold
shader compilation also caused long initial stalls. Neither the title screen nor
those finite captures establish playable behavior or full-game compatibility.
The upstream voice-activity fallback writes a neutral zero byte;
it does not implement voice chat. Custom profiles remain separate from the official
release installation and are selected through `porting_tools` library paths.
The real v0.1.2 syscall rejection check maps the reported `0x401005` guest address
to file offset `0x1005`, function `_start`, and the actual decoded syscall. The fixture
is never executed. Windows startup diagnostics conversion/execution has also passed.
Positive runtime trace bindings use controlled registry/log fixtures; the no-import
smoke-test executable cannot satisfy AnyPS5's libc dependency for import instrumentation.
