# Capability coverage — CyDecompilator 1.4.0

Status values: **Tested** (exercised on this machine, with the proof named), **Implemented**
(code path present, not run end to end here), **Not exposed** (engine feature not offered),
**Planned**.

## Engines

| Capability | Operation / field | Standalone control | Status and proof |
|---|---|---|---|
| Format detection (PE native/.NET, ELF, Mach-O, jar, apk, dex, class, pyc, DXBC, DXIL, SPIR-V) | `open_file` → `format` | automatic | Tested: `test_detect_*` |
| Ghidra headless analysis + C decompilation | `analyze engine=ghidra`, `options.maxDecompile/functionTimeout/analysisTimeout/processor` | Engine combo, Engines tab options | Tested: find.exe (x86 PE), libm.so (ARM64 ELF), on-demand decompile |
| Ghidra raw binary with explicit processor | `options.processor` | Advanced operations | Implemented |
| Built-in C decompiler x86/x64 (cdec): structured C, floats (SSE, x87), SIMD intrinsics, callee signatures | `analyze engine=cdec`, `decompile` | Engine combo | Tested: `test_cdec_*`; MSVC equivalence 120/120 (30 functions x 4 builds) |
| Built-in C decompiler ARM64 (PE + ELF/.so): NZCV/ccmp, NEON as SSE, PLT, literal pools | `analyze engine=cdec`, `decompile`, `c_module` | Engine combo | Tested: `test_cdec_arm64_*`; Unicorn-emulated equivalence 120/120 (PE+ELF, -O0/-O2); vcruntime140/msvcp140_2/llvm-strings ARM64 compile |
| Recompilable C module (functions + callees, globals from the image, imports via `__imp_`) | `c_module` | Program tab buttons | Tested: `test_cdec_engine_on_fixtures`; cmd.exe x86/x64, msvcrt x86, python311 x64 compile with MSVC |
| Built-in disassembler (x86/x64/ARM64 PE+ELF) | `analyze engine=native` | Engine combo | Tested: `test_native_engine_on_windows_binary`, cmd.exe, libm.so |
| ILSpy C#, IL, resources list | `decompile view=decompiled/disassembly` | Views | Tested: System.Text.Json.dll, `test_ilspy_engine` |
| ILSpy compilable project | `export_sources csharpProject=true` | Program > Export | Implemented |
| Vineflower jar/class + javap | `analyze engine=vineflower` | Engine combo, Disassembly view | Tested: Ghidra jars, lone .class |
| JADX apk/dex/jar, manifest decoding, deobfuscation | `options.decodeResources/deobfuscate/javaHeapMb` | Advanced operations | Tested on jar; APK path Implemented (no APK with code available here) |
| Python ≤3.8 source, all-version bytecode | `analyze engine=python` | Views | Tested: CPython 3.11 bytecode (built-in and xdis); ≤3.8 source path Implemented |
| DXBC SM4/5 disassembly | `decompile view=disassembly` | Disassembly view | Tested: identical to fxc for 3 shaders |
| DXBC → HLSL with reflection names | `decompile` | Decompiled view | Tested: recompiled with D3DCompile (`test_decompiled_hlsl_recompiles`) |
| SPIR-V → GLSL, disassembly | `decompile` | Views | Tested: glslang fragment + compute fixtures |
| DXIL container metadata | `decompile view=disassembly` | Disassembly view | Tested: `test_dxil_container` |
| DXIL (SM6) bitcode → HLSL: LLVM bitstream reader, reflection names (STAT), structured CFG, dx.op intrinsics | `decompile` | Decompiled view | Tested: 7 dxc fixtures (ps/vs/cs 6.0, ps 6.2 16-bit, ps 6.6 bindings) recompile with dxc (`test_dxil_output_recompiles_with_dxc`) |
| Matrix element addressing (row/column major) | `decompile` | — | Tested: `_m00.._m30` for `mul(v, M)`; DXBC constant reads identical after recompilation (`test_dxbc_roundtrip_reads_same_constants`) |
| PyInstaller extraction (entry scripts, PYZ modules as .pyc, binaries) | `extract_embedded kind=pyinstaller` | Extract banner, extracted files list | Tested: real PyInstaller 6 onefile exe (161 files) and synthetic archive (`test_pyinstaller_extraction`) |
| .NET single-file bundle extraction | `extract_embedded kind=dotnet-bundle` | same | Tested: real .NET 8 bundle; compressed bundles Implemented (not exercised) |
| UPX unpacking | `extract_embedded kind=upx` (component `upx`) | same | Tested: find.exe packed with UPX 5.2.1 |
| Zip overlay extraction | `extract_embedded kind=zip-overlay` | same | Implemented |
| PE details (protections, version, manifest, Rich, exports+forwarders, TLS, entropy, overlay, packers/toolchains) | `project_info` → `pe`, `peSummary` | Program > Executable details | Tested: `test_pe_details_and_symbols` (find.exe, kernel32.dll) |
| PDB symbols (symbol server, local folders, GUID/age check, publics + procedures, MSVC demangling) | `load_symbols`, `symbols_configure`, `options.symbols` | Program / Engines tabs | Tested: cmd.exe, find.exe, kernel32.dll from msdl.microsoft.com; names injected into Ghidra (`FIND::SearchStream`) |
| Native discovery: data-section code pointers, x86 prologues, TLS callbacks | `analyze engine=native` | — | Tested: find.exe / cmd.exe 32-bit (no false functions from in-code relocations) |

## Investigation and observed behavior

| Capability | Operation / control | Status and limits |
|---|---|---|
| Native types, instruction references and high p-code SSA dependencies | `investigation_native`, selected Ghidra function | Tested: real x64 PE. Bounded within one function; indirect calls, aliases and inter-function values unresolved. |
| Immutable JS/TS/HTML folders and Electron ASAR snapshots | `application_open`, Investigation | Tested: private TypeScript parser, bounds and exclusions; modules never executed. |
| Imports, preload, window options, bridge/IPC, HTML resources and event candidates | `investigation_query` | Tested: unique/ambiguous IPC, shadowing, local resolution. Static candidates do not prove execution. |
| Local source-map v3 VLQ positions and names | Investigation evidence | Tested: valid, unmapped, invalid segments. Indexed, inline and remote maps unsupported. |
| Feature-to-source paths and hash-bound evidence | `investigation_query/source` | Tested: snapshot tampering, source lines and relationship paths. |
| Imported HAR correlations | `investigation_har` | Tested: observed metadata and inference edges, cookies/headers not retained. |
| Process versions, finite stdin, output/exit/file changes | `behavior_capture/compare/captures` | Tested: real processes, scenarios, timeout/output limits and child termination. External files remain outside scope. |
| Live HTTP and owned-process TCP observations | `behavior_capture/compare/evidence` | Tested: real Chromium fetch metadata/initiator and passive owned-process TCP; no headers/bodies, UDP or packet interception. Sampling and renderer scope are explicit. |
| Replayable GUI and visual comparisons | `behavior_capture/compare/evidence` | Tested: real Windows UI Automation controls, headless Chromium CSS steps and reconstructed Electron ASAR/preload/IPC scenarios; states, PNG hashes, failed steps and integrity checks. Native custom-rendered controls may be unavailable. |

See [Investigation.md](Investigation.md) for setup and limits.

## Projects and annotations

| Capability | Operation | Status |
|---|---|---|
| SHA256 dedup, persistent projects, delete | `open_file`, `list_projects`, `delete_project` | Tested |
| Global/local renames, comments, notes applied to every view | `rename`, `set_comment`, `set_notes` | Tested (`test_project_dedup_and_annotations`, MCP acceptance) |
| Cross references, strings, search (names, cached code, strings) | `xrefs`, `strings`, `search` | Tested |
| Export all units as files | `export_sources` | Tested (`test_export_and_search`) |
| Reconstruct Visual Studio C# solution, edit source, build and run | `workspace_create`, `workspace_read/save`, `workspace_execute` | Tested: `test_dotnet_decompile_edit_rebuild_roundtrip` |
| Reconstruct native VC++/CMake static-library project | `workspace_create nativeTarget=library` | Tested: `test_native_solution_build`, `test_native_test_harness` |
| Reconstruct native DLL exports/ordinals and executable entry/resources | `workspace_create nativeTarget=auto/executable/shared` | Tested: `test_shared_native_reconstruction_exports_and_behavior`, `test_native_executable_entry_resources_and_observed_exit`; unresolved entry/TLS/data exports remain explicit blockers |
| Reconstruct JS/TS/Node/web/Electron source and ASAR artifacts | `workspace_create`, `workspace_execute`, `workspace_dependencies` | Tested: syntax/transpile/maps, ASAR bytes, stale outputs and run conflicts; full semantic TS typechecking and signed installers are not provided |
| Bounded reconstruction/build/AI repair/Git/scenario loop | `reconstruction_run/status`, IDE Reconstruction | Tested: real builds, captures, revision/batch rollback, cancellation report, Runtime jobs; visual QA `project-ide-reconstruction.png`; AI responses are controlled test fixtures, configured live provider not exercised in this test |
| Reconstructed .NET, web and Electron behavioral scenarios | `reconstruction_run scenarios` | Tested: .NET console, Chromium clicks/screens, private official Electron with preload/IPC; file-URL mappings and disabled checks are recorded, matching scenarios do not imply universal equivalence |
| Attach C#/VC++/CMake folder, tabbed source editor, conflict-aware saves | `workspace_open/info/read/save` | Tested: source confinement, BOM/CRLF, disk conflicts; visual QA `data/reports/project-ide-editor.png` |
| Compile/review a C function and replace it in a native x86/x64 PE copy | `patch_prepare`, `patch_apply` | Tested: x86 patch, x64 DLL execution, original preserved; leaf functions only, no unwind or relocations |
| Multi-project .sln/.slnx builds and startup project selection | `workspace_open`, `workspace_execute targetProject` | Tested: `test_solution_build_and_startup_project` |
| Compile C# and replace one .NET IL method in the original assembly copy | `managed_methods`, `managed_patch_prepare`, `patch_apply` | Tested: ILSpy roundtrip, larger bodies, branches/strings/locals/try-catch, own generic members, unchanged original helpers/Main; `test_managed_patching.py` |
| Strong-name refusal and explicit removal; stale or tampered IL plan rejection | `managed_patch_prepare removeStrongName`, `patch_apply` | Tested: generated signed assembly, changed signature/new user helper refusal (including inside a closure), source/candidate conflicts |
| Isolated lambda/closure/local-function and async/iterator dependencies | `managed_patch_prepare`, `patch_apply` | Tested: nested captured variables, shared lambda caches, generic/instance async, async lambdas, iterators/async iterators in Debug/Release; successive patches preserve original method/type/field tokens and other bodies; visual QA `data/reports/project-ide-generated-patch.png` |
| Saved copy history and direct application-copy execution | `patch_outputs`, `patch_run` | Tested: real .NET copy run, spaced arguments, nonzero exit code, hashes/original protection, library refusal; `test_patch_execution.py` |
| Local Git source/resource/dependency versions, reviewed diffs and reversible restore | `workspace_history`, IDE Git history | Tested: real Git commits, exact BOM/CRLF/binary restore, added/deleted files, automatic backup, stale preview/foreign workspace refusal, original protection, user index/config/hooks/attributes isolation, matching managed receipt; `test_history.py` |
| Live build/run stdout and stderr, cancellation and timeout | `ProcessOutput` events | Tested: events before process completion, Runtime copy cancellation, descendant tree stopped, full job logs preserved; `test_patch_execution.py` |
| Search saved sources, whole-word/case filters, file and line navigation | `workspace_search`, IDE search tab/file filter/Go to line | Tested: literal metacharacters, UTF-8/CRLF coordinates, skipped binaries/build output/large files, result limits/cancellation; `test_source_search_coordinates_filters_and_limits` |
| Reload from disk without overwriting edits made during the read | `workspace_read`, IDE Reload file | Tested: `test_editor_reload_preserves_edits_made_during_read` |
| New referenced .NET types/methods and compatible fields | `managed_patch_prepare allowNewMembers=true` | Tested: helper method, initialized new type, property, default static field; existing initializer/layout changes refused |
| New fields affecting existing type layout/initialization, mixed-mode, ReadyToRun method replacement | — | Not exposed: full application rebuild required |
| C# semantic completion at cursor, member access, undoable insertion | `workspace_csharp action=complete`, Ctrl+Space | Tested: real Roslyn, visibility/static/instance, string members, emoji columns, undo/stale buffers; `test_csharp_services.py`; visual QA `project-ide-csharp.png` |
| C# definitions and declaration navigation across files/projects | `workspace_csharp action=definition/symbols`, F12, C# symbols | Tested: correct receiver type among same-named methods, unsaved definitions and ProjectReference source navigation |
| C# diagnostics while editing unsaved buffers | `workspace_csharp action=diagnostics`, C# assistance | Tested: syntax/name diagnostics, SDK implicit usings/reference packs, stale callback rejection, real Runtime job |
| Semantic rename, references and formatting with undoable previews | `workspace_csharp rename/references/format`, `workspace_refactor_check` | Tested: homonyms preserved, cross-file edits, stale source/buffers refusal, undo; visual QA `project-ide-refactoring.png` |
| Evaluated MSBuild editor metadata | `workspace_evaluate` | Tested: imported conditional defines, removed Compile items, resolved references; explicit ResolveReferences execution; cached reads during editing |
| Full analyzer/generator execution in editor, semantic services for other languages | — | Planned: Build remains authoritative; evaluated generated sources are read but not refactored |
| Rebuilt .NET source debugger: breakpoints, entry stop, threads, stack, locals, object expansion and stepping | `debug_start/status/control/breakpoints`, IDE Debugger panel | Tested: real NetCoreDbg + portable PDB, step in/over/out, pause/continue, normal exit; `test_debugger.py`; visual QA `project-ide-debugger.png` |
| Debugger lifecycle, cancellation/timeout/shutdown, original protection and stale handles | `debug_start` owning job, sessionId/stopId | Tested: Runtime controls while launch runs, restart identity, process/child cleanup on cancellation, timeout, protocol failure and shutdown |
| Patched .NET copy symbols and source debugger | `managed_patch_prepare symbols=true`, `debug_start receiptId` | Tested: changed body breakpoint/local variables, async MoveNext breakpoint, original Main unchanged, PDB/copy/source checks; visual QA `project-ide-debug-copy.png` |
| Native appended replacements with calls/data/ASLR/unwind | `patch_prepare extended=true` | Tested: x64 Debug/Release execution, original function/IAT calls, pointer relocation under ASLR, Windows unwind lookup, x86 Unicorn execution, tampered copy refusal; visual QA `project-ide-native-link.png` |
| Desktop/resource/dependency reconstruction | `workspace_create`, build/run, managed patch/run | Tested: reproducible WPF BAML and WinForms applications, embedded resources and local assembly with compact names; `test_desktop_roundtrip.py` |
| Native debugger, .NET Framework attach and hot reload | — | Planned |

## Components

| Capability | Operation | Status |
|---|---|---|
| Install from official sources with hash verification | `install_component` | Tested: ghidra 12.1.4, dotnet 10.0.12 (SHA512), ilspycmd 11.1, vineflower 1.12.0, jadx 1.5.6, pydecompile (pip) |
| JDK download | `install_component component=jdk` | Implemented (system JBR 21 used here) |
| Use an existing installation | `set_component_path` | Implemented |
| Remove a private version | `remove_component` | Implemented |
| NetCoreDbg official release installation | `install_component component=netcoredbg` | Tested: 3.2.0-1092 Windows x64 release, published SHA256 verified |
| Private Electron runtime | `install_component component=electron` | Tested: official Windows x64 release 44.7.0, published SHA256 verified; original runtime version/ABI may require an override |
| Archive traversal refused | — | Tested (`test_extract_refuses_traversal`) |

## AI

| Capability | Operation | Status |
|---|---|---|
| Explain | `ai_explain` | Implemented (same call path as convert) |
| Rename proposals, apply | `ai_rename apply=true` | Tested with Claude Code on a Ghidra function of find.exe (proposal); apply path Implemented |
| Convert to source + compile check + repair | `ai_convert target verify instructions` | Tested with Claude Code: DXBC pixel shader → HLSL, check passed (D3DCompile) |
| Agentic Q&A with tools | `ai_ask` | Tested with Claude Code: 4 tool calls, answer produced |
| Autonomous project work with verified completion | `ai_agent/status`, AI panel | Tested: `test_autonomous_agent.py`, actual Node compiler recovery/scenario comparisons, native DLL replacement/harness assertions, scoped authenticated child jobs, cancellation, checkpoints, source freshness and editor freezing; real configured Claude Code repaired and validated three Node scenarios. Model prose cannot mark an unverified task completed. Account administration and unrelated projects remain outside the selected task. |
| Batch naming | `ai_batch_rename` | Implemented |
| Providers | Claude Code, Codex, Antigravity, OpenCode (CLI); Anthropic, OpenAI, OpenRouter, OpenAI-compatible, Ollama (HTTP) | Claude Code Tested; others Implemented (vendored from CyTools_AIChat where they are tested) |
| Compile checks | Python, Java (javac), HLSL (D3DCompile), C/C++ (MSVC via vswhere, clang, gcc), C# (dotnet SDK), Rust, Go | Python/HLSL/Java/C/C++ Tested; others Implemented |

## Interfaces

| Interface | Status |
|---|---|
| CyUI Dear ImGui window (10 languages, sidebar, project/AI views, Options, log, advanced operations) | Tested: `tests/test_cyui_integration.py` for preferences, actual five-theme styles and DPI; native screenshots of all five themes, French/Chinese, 1100px windows, 150% DPI and main panels in `data/reports/cyui-qa`. Native GUI exercised on Windows; Linux rendering not exercised here. |
| CLI `invoke` | Tested |
| MCP (stdio) | Tested: `tests/acceptance_mcp.py` and `tests/test_mcp_workflows.py`: every declared operation discoverable/describable; real Node/Git/conflicts, native reconstruction/patch/captures, .NET local dependency/reconstruction/managed-copy run/debug cancellation, Chromium HTTP/graphics/evidence integrity. Not every engine/operation combination has a transport-level scenario. |
| Dedicated AI skill and client guide | Tested: `tests/test_skill_delivery.py`, self-contained reference links, install/copy parity, idempotence and existing-customization protection; bundled `app/skills/cydecompilator`, `Docs/AIIntegration.md`. Installing a skill does not configure a client's MCP connection. |
| HTTP / JSONL | Provided by CyToolsCore, not exercised here |
| Windows launcher | Tested: built with MSVC |
| Linux launcher | Implemented, not run (no Linux runtime prepared) |
| Application update stream | Implemented; check tested without a repository (no release exists) |

## Unreal reconstruction knowledge

| Capability | Operation / control | Status and limits |
|---|---|---|
| Portable rules and ten campaign profiles | `unreal_rules`, Unreal reconstruction | Read-only catalog from the Anniversary prototype; source snapshot hashes, scoped filters, generic methodology and explicit limits. No automatic conversion or enforcement. |
| Copyable guide and agent discovery | `unreal_guide`, Copy reconstruction guide | The same data is exposed to native UI, CLI, MCP and the integrated agent. Rule consultation is not build/gameplay evidence. See `tests/test_unreal.py` and the integration receipt for exercised paths. |
