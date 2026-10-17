<p align="center"><img src="assets/logo-256.png" width="160" alt="CyDecompilator"></p>

# CyDecompilator — developer guide

AI-assisted multi-engine decompiler built on CyToolsCore 0.10 (Python 3.11, Dear ImGui).
User guide (French): `../README.md` (same text as `../LISEZ-MOI.md`, kept for the CyTools delivery layout).

## Evidence and behavior investigations

The Investigation tab shares nine Runtime operations for inert JS/TS/HTML/ASAR
snapshots, Electron IPC/preload/module candidates, local source maps, imported HAR,
Ghidra type/instruction/high-pcode dossiers, feature relationship queries and bounded
Windows process comparisons. See [Docs/Investigation.md](Docs/Investigation.md) for
limits and setup; `tests/test_investigation.py` exercises actual parsers and processes.
TypeScript 5.9.3 is private and SHA512 verified; Node.js is required on PATH. Matching
observations never imply equivalence. Replayable Windows UI Automation and Chromium/Electron
CDP scenarios retain control states, screenshots, HTTP metadata and owned-process TCP
observations. Browser recording requires Node.js 22+; Windows uses a privately compiled
.NET Framework helper. Indirect native calls and cross-function value resolution remain unresolved.

## Reconstruction workflow

`reconstruction_run` unifies workspace generation, bounded builds, optional AI source
repairs with private Git history, and recorded behavior comparisons. It handles .NET,
native executable/shared/static targets and Node/web/Electron workspaces. Reports
separate compiled artifacts from validated scenarios and retain missing evidence.
See [Docs/Reconstruction.md](Docs/Reconstruction.md), with actual runtime/build
integration coverage in `tests/test_reconstruction.py`.

## Layout

```
CyDecompilator/
  CyDecompilator.exe / .sh     launchers (exe built by app/build_launcher.ps1)
  app/
    tool.py                    Runtime + handlers (CLI / JSONL / HTTP / MCP entry point)
    desktop.py                 Dear ImGui window (same Runtime, jobs only)
    operations.py              operation contracts -> build_manifest.py -> CyTool.json
    cydec/
      detect.py                format detection from bytes
      project.py               persistent projects (sha256 dedup, analyses, code cache, annotations)
      service.py               business API shared by every interface
      workspace.py             reconstructed .sln/.csproj/.vcxproj/CMake projects, source saves and builds
      history.py               private local Git snapshots, bounded diffs and reversible source restores
      patching.py              verified C leaf-function replacement in a separate x86/x64 PE copy
      managed_patching.py      build C# donor, import selected IL method, verify and publish a copy
      csharp.py                source snapshots + SDK Roslyn editor services
      debugger.py              job-owned NetCoreDbg DAP sessions, controls and pause handles
      components.py            engine downloads: resolve official release, verify, extract, locate
      process.py               cancellable subprocesses (whole tree killed on cancel)
      updates.py               application updates from GitHub releases (stage, verify, apply, rollback)
      pe_info.py               PE facts: protections, version, Rich, exports/forwarders, TLS, entropy, packers
      pdb.py / symbols.py      PDB lookup (symbol server, local), MSF reader, publics/procs, MSVC demangler
      unpack.py                PyInstaller, .NET single-file bundle, UPX, zip overlay extraction
      engines/                 ghidra, cdec (own C decompiler), native (Capstone), ilspy, java (vineflower, jadx), python, shader
      shader/                  own engine: dxbc.py + hlsl.py, spirv.py + glsl.py, dxil.py
      ai/                      providers (from CyTools_AIChat), assistant.py, verify.py (compile checks)
    locales/                   ui.json (scaffold catalogue) + cydec-fr.json (our strings)
    tests/                     pytest suite, MCP acceptance, shader fixtures with fxc reference listings
    managed/                   pinned dnlib helper, built on demand into runtime/engines
    csharp/                    Roslyn helper, built using local SDK dotnet-format assemblies
  data/                        projects, settings, logs, reports (never replaced by updates)
  runtime/                     python venv, engines, downloads, updates, backups, build
```

## Set up a development runtime (Windows)

```powershell
py -3.11 -m venv runtime\python
runtime\python\Scripts\python.exe -m pip install -r app\requirements.txt -r app\requirements-dev.txt
# or, against a local SDK checkout:
runtime\python\Scripts\python.exe -m pip install "cytools-core[mcp] @ file:///D:/_Project/CyToolsCore"
powershell -ExecutionPolicy Bypass -File app\build_launcher.ps1   # needs Visual Studio C++ tools
```

The venv is not relocatable: create it in its final place. On Linux create `runtime/python`
the same way with python3.11 and use `CyDecompilator.sh`.

## Commands (tested)

```powershell
runtime\python\Scripts\python.exe app\build_manifest.py            # after editing operations.py
runtime\python\Scripts\cytools.exe validate app\CyTool.json
runtime\python\Scripts\python.exe -m pytest app\tests -q
runtime\python\Scripts\python.exe app\tests\acceptance_mcp.py      # real MCP stdio session
runtime\python\Scripts\python.exe app\tool.py list-operations
runtime\python\Scripts\python.exe app\tool.py invoke open_file --params-file params.json --timeout 3600
runtime\python\Scripts\python.exe app\tool.py mcp                  # MCP server on stdio
runtime\python\Scripts\python.exe app\scripts\install_component.py ghidra jadx
runtime\python\Scripts\python.exe app\scripts\merge_translations.py
runtime\python\Scripts\python.exe app\desktop.py --ui-test-open=<file> --screenshot=data\reports\ui.png
```

`params.json` example: `{"path": "C:/Windows/SysWOW64/find.exe", "engine": "ghidra"}`.
The CLI `invoke` timeout defaults to 300 s: pass `--timeout` for Ghidra on large binaries.

## Identity and permissions

Operations declare `network`, `processSpawn` and `filesystemExternal` where they really have
those effects. When `CYTOOLS_TOKEN` is not set, `tool.py` mints a local client holding exactly
the declared permissions and exports its token for the transport. To restrict an MCP client,
create one with `tool.py create-client --name ai --permission processSpawn` and set
`CYTOOLS_TOKEN` to its token: it can then analyse and decompile but not download or call AI.

## MCP usage pattern

1. `op_open_file {"parameters": {"path": "D:/samples/app.exe"}}` → poll `cy_get_job` → `projectId`.
2. `op_list_functions`, `op_decompile`, `op_xrefs`, `op_strings`, `op_search` to explore.
3. `op_rename`, `op_set_comment` to annotate (applied to every later view).
4. `op_ai_convert` / `op_ai_explain` / `op_ai_ask` to use the configured AI provider of the Tool
   (an AI client usually reasons itself and only needs steps 1–3).
5. `op_export_sources {"destination": "D:/out"}` writes all units with annotations.

Projects are the Tool's persistent store (like a database): they survive task cleanup by
design. `op_delete_project` removes one. Input copies staged by the SDK are task files and are
removed by `cy_finish_task` as usual.

## Integrated project editor and function patches

`workspace_history action=status/snapshot/compare/restore` exposes the IDE Git history tab.
Git must be on PATH. Each attached folder has a separate private bare repository below the
persistent analysis project, independent of the user's Git repository/index/config/hooks/remotes.
Exact-byte source/resource/local-dependency snapshots exclude generated/VCS/cache folders and
are bounded to 4000 files, 128 MiB total and 32 MiB per file. Git plumbing bypasses text filters,
ignore rules and signing; commands run cancellably through `process.run`. Text diffs are bounded;
binary changes are marked. Snapshot requires a description. Restore requires a comparison revision,
refuses stale files, links/reparse points, original applications and conflicting file/directory layouts,
saves the current tree first, restores with atomic per-file writes and creates a new linear commit.
On write/commit failure it attempts rollback from the captured current bytes; the backup commit
remains recoverable. The editor requires saved buffers and freezes them during restore, then reloads
open files and clears stale build/patch/semantic results. Versions are explicit, local, with no push UI.
Git stores file contents; filesystem timestamps, ACLs and executable modes are not restored.
Managed patch receipts expose `sourceCommit` when matching sources were already saved in history.

`project_ui.py` implements the Project IDE tab using the same TextEditor and Runtime jobs as
the analysis window. `workspace_create` persists a source project in `data/projects/<id>/source`
or a new explicit destination, and emits a Visual Studio solution. .NET exports use ILSpy and
select a C# language version compatible with the detected SDK. Native exports use `c_module`
and build a static library by default, or an executable/shared image with `nativeTarget`.
Missing startup adapters, TLS initializers, data exports and inferred types remain explicit.
JavaScript/Electron exports preserve sources/resources and provide build/run/ASAR paths.
`workspace_open` attaches an existing C#, VC++, CMake or multi-project solution folder.
`workspace_info` returns available projects; `workspace_execute targetProject` selects one relative
`.csproj`/`.vcxproj`. Empty selection builds/tests the whole solution; run requires a startup project.

`workspace_info`, `workspace_read` and `workspace_save` expose the editor files. Saves are atomic,
confined to the attached folder, reject changed SHA256 revisions, and preserve UTF-8 BOM and CRLF.
The editor adds file filtering, line navigation and conflict recovery by reloading from disk;
edits made while an asynchronous reload is pending are preserved. `workspace_search` searches saved
UTF-8 text with literal/case/whole-word matching, file/line/column results, and bounded scan/results.
Generated output, binary/non-UTF-8 and oversized files are skipped and reported.
`workspace_execute` builds/rebuilds, tests or runs through `cydec.process.run`; all subprocess trees
are cancellable. Diagnostics carry file/line/column for editor navigation. Building C# requires
a .NET SDK, not just the private ILSpy runtime. CTest fails on missing tests; .NET test output
without an executed test summary is reported as `no-tests`. Run/test execute application code.

`patch_prepare` compiles exactly one C function to a matching x86/x64 Windows COFF object with
clang, refuses relocations, absolute/RIP-relative data, out-of-function branches, calls, stack
frames or preserved-register writes, and checks the original executable range for overlapping
functions, loader relocations and unwind metadata. `patch_apply` revalidates the plan and input
hash, NOP-pads the function range, updates the PE checksum and writes a new EXE/DLL plus a
persistent receipt. Originals and existing outputs cannot be overwritten. Keep the ABI and
calling convention unchanged; compile success alone does not establish semantic correctness.
Existing Authenticode signatures are invalid after modification. `extended=true` uses the bounded
single-object linker in `native_linker.py`: append a PE section, link internal code/data and calls to
existing analyzed functions/exports/IAT slots, apply x86/x64 COFF relocations, merge x64 runtime
function entries and rebuild ASLR base relocations. Redirect at least five complete entry bytes
with a relative jump; existing other section contents and addresses are verified unchanged.
`bindings` optionally maps C symbol names to validated original virtual addresses. The default
leaf mode is retained. Free section-header space is required; CFG, new TLS, unresolved symbols,
unsupported relocations/metadata and original entry loader relocations are refused. Keep the
ABI unchanged. The new section is writable only when the compiler emits writable data.
Live-process injection and native debugger integration are not implemented.

`workspace_csharp` offers `complete`, `definition`, `diagnostics`, `symbols`, `references`, `rename`
and `format` using the installed
SDK's Roslyn Workspaces/Features. The IDE exposes Ctrl+Space, F12, a declaration list and automatic
diagnostics after editing pauses. Requests include open C# buffers without saving them. Completion
edits retain the editor's undo history; results are discarded when buffers or the caret changed.
Coordinates count Unicode characters, including astral characters, rather than UTF-16 units.
Rename uses Roslyn symbols across source projects, leaves homonymous symbols alone, and refuses
introduced compiler conflicts. Rename/format return reviewed before/after edits. The UI loads
closed affected files, verifies the complete saved-source revision with `workspace_refactor_check`,
then checks all buffers before any change. It applies undoable buffer edits; Save remains explicit.

The helper requires SDK 8+ with bundled dotnet-format assemblies and builds offline, with package
sources cleared, into a job workdir before caching under `runtime/engines/csharp-services`. The
project model reads local .csproj metadata, confined C# source, reference packs, HintPath metadata,
restored package compile references and ProjectReference links inside the workspace. It does not
run user MSBuild targets, analyzers or source generators. Conditional/imported properties, generated
files, unsupported build layouts and missing framework/package references can make analysis partial;
model notes explain these cases and a normal Build remains authoritative. Unsaved .csproj edits
must be saved before they affect this model. Source snapshots are bounded to 32 MiB/2000 files;
up to 200 edited buffers and 200 results are accepted. Other editor languages retain text search.
`workspace_evaluate` explicitly runs MSBuild `ResolveReferences` and reads evaluated Compile,
ReferencePath, ProjectReference and properties (SDK 8+). Custom targets can execute in this action.
The cached editor model honors imports/configuration/source selection, includes generated sources
for diagnostics, and is invalidated by configuration/source-list changes. Multi-target projects
use their first framework. Refactoring generated files is refused; change the generator input.

`debug_start` builds a selected startup .csproj in Debug with optimization disabled and portable
PDBs, then launches NetCoreDbg over stdio DAP. Install the `netcoredbg` component from the IDE
Debugger panel or Engines tab (official Samsung release, published SHA256 when available).
The local .NET SDK 8+ and the target application's .NET Core runtime are required. Multi-project
solutions require a startup project; multi-target/custom builds can select a relative built DLL.
Outputs must remain inside the source workspace and cannot be the original application. The
output requires a runtimeconfig and portable PDB; Framework/library/native debugging is not exposed.

The launch Runtime job owns the adapter and application until termination. `debug_status` provides
its ephemeral sessionId/stopId, console and state; separate `debug_control` jobs inspect the stack,
select threads/frames, read locals/expand objects, continue, pause, step in/over/out or disconnect.
The launch job has a separate exclusive group so controls can execute while it remains active.
Cancel, timeout, protocol failure and Runtime shutdown stop the entire process tree. The UI uses
F5 (start/continue), Shift+F5 (stop), F9 (toggle saved-line breakpoint), F10, F11 and Shift+F11.
The editor marks breakpoints/current instruction and navigates to the selected source frame.
`debug_breakpoints` persists up to 200 confined C# {path,line} records. Active sessions accept
replacement breakpoints through debug_control and show verified/pending bindings from the adapter.

Source saves, workspace changes and rebuilds are refused during a session; editor files are read-only.
Sources changed on disk during the build invalidate launch; changes detected at a pause suppress
automatic source navigation and tell the user to restart. Every paused command carries stopId;
old session/frame/variable handles are refused after restart or resume. Variables are paged/bounded,
console history is bounded to 200k characters and the full debugger console stays in the job log.
Sessions are in-memory and end when the owning Runtime closes; breakpoints survive restarts.
No arbitrary protocol requests, expression evaluation, existing-process attach or hot reload is offered.
`debug_start receiptId=...` debugs a verified modified copy without rebuilding. Prepare with
`symbols=true` (portable, unoptimized build), then write the copy with its original filename.
dnlib remaps imported method sequence points/local scopes and async/iterator stepping records
into a new matching portable PDB. Unmodified methods have no regenerated source correspondence.
The copy, PDB and runtime/dependency hashes plus workspace source revision must still match.
The owning job and stale-handle/cancellation rules are identical to rebuilt-project debugging.

`managed_methods` lists .NET metadata tokens and signatures. `managed_patch_prepare` builds the
attached C# workspace, finds its rebuilt assembly (or uses an explicit relative `donor`), and imports
one method body into the original assembly. Its dnlib helper maps self references to original
members and copies locals, branches, strings and exception handlers; the replacement can grow.
Reachable compiler-generated dependencies for lambdas, captured variables, local functions,
async methods and iterators are imported under fresh names, including generic and nested layouts.
Shared lambda caches import only the selected method's reachable helpers. State-machine attributes
are remapped to the isolated types. Generated helpers cannot be selected directly: edit their owning
source method. The preview and receipt list the added types and methods. All existing other method
bodies and all original method/type/field tokens are checked after writing, including successive patches.
The generated graph is bounded to 64 types, 1,000 methods and 2,000 fields; unsupported generated
metadata is refused. `allowNewMembers=true` imports reachable new user-defined types, methods
and compatible fields, with constructors/properties/events for new types; reports list all additions.
New instance/layout fields on existing types and changes to their initializers are refused, including
non-default static field initialization. P/Invoke/runtime-only new methods and unsupported metadata
still require rebuilding. Changed signatures, mixed-mode and ReadyToRun images require a complete
rebuild. `symbols=true` regenerates portable symbols for imported methods. Strong names are refused
unless `removeStrongName=true` explicitly authorizes removal; dependent assemblies can then fail.
`patch_apply` publishes the verified assembly and snapshots of runtime configuration/dependencies
to a separate output. Donor companions are copied only when keeping the original assembly filename,
and existing companion files are preserved. Source changes invalidate the prepared plan.

The helper is restored in locked mode from official NuGet (dnlib 4.5.0, published SHA512 in
`managed/packages.lock.json`) and cached under `runtime/engines/managed-patcher`. It requires a
.NET SDK; target assemblies are read as metadata without loading or running them.
Patch plans/receipts and source edits intentionally belong to persistent projects;
compiler intermediates and logs belong to job workdirs.

`patch_apply` now returns a stable `receiptId` and `launchKind`; `patch_outputs` restores copy history
and the last completed run. `patch_run` accepts a recorded receipt, arguments and a 1–900 second
timeout. It rechecks the copy and any copied companion hashes, refuses originals and DLLs without
an entry point, and runs modern managed executables through an installed .NET host. Windows .NET
Framework EXEs run directly. The working directory is the output folder. No donor rebuild or original
execution happens as part of this action. Exit zero means `passed`, not behavior equivalence.

Workspace jobs and copy runs emit bounded `ProcessOutput` events for both stdout and stderr.
Desktop jobs dispatch batched updates to the console; cancellation/error retains the streamed output.
The full streams remain in job logs. `cydec.process.run` kills descendants on cancellation/timeout;
the UI's Run action captures output without interactive stdin. Debug offers its own controls.

Tests in `tests/test_workspace.py` and `tests/test_managed_patching.py` exercise Visual Studio builds,
multi-project startup selection, CMake tests, ILSpy C# decompile/edit/rebuild/reinject/run, x86/x64
patches, generic IL, try/catch, strong-name removal, disk conflicts and refusal paths. Managed tests
also run isolated closures, shared caches, local functions, async lambdas, generic async methods,
iterators and async iterators in Debug/Release, and repeated replacements with original tokens retained.
`tests/test_patch_execution.py` covers real copy runs, spaced arguments, nonzero exit codes, live
stdout/stderr, changed files/dependencies, original protection, timeouts and Runtime cancellation.
`tests/test_desktop_roundtrip.py` builds and runs real reproducible WinForms/WPF test applications
with an embedded resource, WPF BAML, local dependency and compact identifiers, then decompiles,
rebuilds/runs and reinjects/runs them. ILSpy export now snapshots local references with relative
HintPaths so moving the temporary export to the persistent workspace does not break dependencies.
XAML files are editable; arbitrary third-party obfuscation/protection remains case-dependent.
`tests/test_csharp_services.py` covers real scoped member completion, framework metadata, Unicode
edits, cross-file/project definitions, diagnostics/declarations from unsaved buffers, Runtime calls,
undo preservation and stale results; project build targets are never executed by these operations.
`tests/test_debugger.py` exercises real .NET breakpoint binding, stack/locals/object expansion,
entry stop, step in/over/out, pause/continue, normal exit, stale handles, Runtime commands,
cancellation/restart, timeout/protocol failure and shutdown with child-process cleanup. It also
verifies ILSpy decompile → reconstruct → Debug build → source breakpoint → step into → normal exit
with regenerated portable symbols and an unchanged original assembly.
Debugger references: [NetCoreDbg](https://github.com/Samsung/netcoredbg),
[Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/).
Refactoring reference: [Roslyn Renamer](https://learn.microsoft.com/en-us/dotnet/api/microsoft.codeanalysis.rename.renamer.renamesymbolasync).
Format references: [Microsoft PE/COFF](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format),
[.NET build](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-build).

## Engines and components

`components.py` resolves the current release from the official source at install time
(GitHub API with asset `digest`, Adoptium API checksum, Microsoft release metadata SHA512,
NuGet, PyPI), downloads with `cytools_core.downloads.DownloadManager` (resume, size, hash),
extracts with traversal/link refusal into `runtime/engines/<id>/<version>` and records
`installed.json`. Previous versions stay until removed. A system install or a user-chosen
folder (`set_component_path`) is preferred when valid; Ghidra additionally requires `javac`.

| Engine | Units | Decompile | Disassembly |
|---|---|---|---|
| ghidra | functions | C (analysis-time batch, then on demand with `-process -noanalysis`) | — |
| cdec | same discovery as native (x86/x64/ARM64 PE, ELF) | C from `cydec/cdec` (lifter → data flow → structurer → C); `c_module` writes one recompilable C file | annotated asm |
| native | functions (entry, exports, symbols, x64 .pdata, call targets) | — | annotated asm |
| ilspy | types | C# (`-t`) | IL (`-il -t`), project export (`-p`) |
| vineflower | classes | Java | `javap -c -p` |
| jadx | classes + AndroidManifest.xml | Java | — |
| python | code objects | source ≤ 3.8 | xdis / dis |
| shader | entry points | HLSL (DXBC), GLSL (SPIR-V), summary (DXIL) | fxc-style / spirv-dis-style |

## Shader engine

- `dxbc.py`: container, RDEF (cbuffer variables, bindings), ISGN/OSGN/ISG1/OSG1/PCSG, SM4/5
  token decoding. The disassembly is checked instruction by instruction against fxc listings.
- `hlsl.py`: structured control flow from the tokens, signature/RDEF naming, typed literals. <!-- gitleaks:allow (prose, not a secret) -->
  The output of every fixture is recompiled with D3DCompile in the tests.
- `spirv.py` / `glsl.py`: SPIR-V parsing, structured CFG rebuilt from merge instructions,
  single-use inlining with a store barrier for mutable memory, Phi variables, swizzle merging,
  `while` recovery.
- `dxil.py`: container metadata (PSV0, signatures, root signature, debug name).
- `llvmbc.py` / `dxil_hlsl.py`: LLVM 3.7 bitstream reader (abbreviations, BLOCKINFO, types, constants,
  metadata, relative operand ids) and DXIL → HLSL: reflection from the STAT chunk (resource names, cbuffer
  and struct fields with offsets, signatures), dominator/post-dominator based structuring (if/else, while,
  switch, break/continue), phi variables, dx.op intrinsics. Every fixture recompiles with dxc in the tests.

## AI assistant

`ai/assistant.py` builds context (facts, callers, callees, imports, strings, analyst notes)
and runs explain / rename / convert / ask / batch rename. `ask` uses a JSON tool protocol
(one object per turn) so it works with any provider. `convert` compile-checks with
`ai/verify.py` (CPython, javac, D3DCompile, MSVC via vswhere, clang/gcc, dotnet SDK, rustc,
go) and feeds errors back for `verifyRounds` repairs. Results are saved under
`data/projects/<id>/ai/`. Keys never enter parameters, jobs, configurations or logs.

## Releases (application update stream)

The default repository is `MrMybal/CyDecompilator` (configurable in the Engines tab, or
cleared). `app/scripts/make_release.py` builds `dist/CyDecompilator-<version>.zip` from the
committed tree (`git archive HEAD` + `app/release.json` with `runtimeAbi` and commit) and, with
`--publish`, creates the GitHub release `v<version>` and uploads it. Bump `VERSION` in
`build_manifest.py` (and regenerate `CyTool.json`) before a release.

The updater stages the asset in `runtime/updates`, checks GitHub's SHA-256 digest, the Tool
identity, the runtime ABI and that the tree compiles, keeps the current `app/` in
`runtime/backups` and never touches `data/`. A private repository needs a GitHub token with
read access: `GITHUB_TOKEN` or the token field of the Updates section (DPAPI-sealed, never a
job parameter). Publishing needs a token with write access.

## Built-in C decompiler (`cydec/cdec`)

Engine order for native files is `ghidra`, `cdec`, `native`: Ghidra stays the default when
installed; `cdec` needs nothing and handles x86 / x86-64 (Win64, SysV, x86 cdecl/stdcall/thiscall,
MSVC helper register conventions) and ARM64 (AAPCS64 / Windows ARM64, PE and ELF).

- `lifter.py`: Capstone → IR (registers by family, stack frame with escaped buffers, lazy flags,
  jump tables, SSE scalar/packed as `_mm_*` intrinsics, x87 stack, callee signatures computed
  from the callee's own data flow: parameter count/sizes/kinds, int/float/void return).
- `lifter_arm64.py`: AArch64 → the same IR (NZCV flags incl. ccmp, csel family, bitfields,
  writeback addressing, literal pools, PLT calls resolved to the library's own functions, jump
  tables, fp incl. fused multiply-add, NEON as SSE intrinsics / `cy_*` helpers so the C also
  compiles on x64). Prototypes list integer parameters first, then floating-point ones.
- `dataflow.py`: reaching definitions, propagation, dead code, return decision (eax, edx:eax,
  xmm0, st0), variable webs. `structure.py`: if/else, loops, switch, gotos with labels.
- `cgen.py`: types (signedness, pointers, float/double, vectors), names, C text; strict mode
  (modules) routes imports through `__imp_X` pointers and avoids names the headers declare
  (`reserved_names.txt`).

Checks: `app/tests/native_equivalence.py` decompiles the 30 functions of
`tests/fixtures/native/funcs.c` (x86/x64, /Od and /O2), recompiles them with MSVC and compares
original and decompiled code on random inputs (120/120 equivalent). Recompilation of real
binaries (cmd.exe x86/x64, msvcrt.dll x86, python311.dll: 2,089 functions) compiles without errors.

ARM64: `app/tests/arm64_equivalence.py` runs the original ARM64 fixtures (PE and ELF, -O0 / -O2,
built with VS's clang by `fixtures/native/build_arm64.cmd`) in the Unicorn emulator and compares
them with the decompiled C recompiled for x64 (120/120). Real ARM64 binaries shipped with Visual
Studio (vcruntime140.dll, msvcp140_2.dll, llvm-strings.exe: 1,329 functions) decompile and compile.
Modules: callees whose prototype keeps changing between passes are called unprototyped, so a
module always compiles.
