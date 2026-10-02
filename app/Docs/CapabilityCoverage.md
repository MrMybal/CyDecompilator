# Capability coverage — CyDecompilator 0.1.0

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

## Projects and annotations

| Capability | Operation | Status |
|---|---|---|
| SHA256 dedup, persistent projects, delete | `open_file`, `list_projects`, `delete_project` | Tested |
| Global/local renames, comments, notes applied to every view | `rename`, `set_comment`, `set_notes` | Tested (`test_project_dedup_and_annotations`, MCP acceptance) |
| Cross references, strings, search (names, cached code, strings) | `xrefs`, `strings`, `search` | Tested |
| Export all units as files | `export_sources` | Tested (`test_export_and_search`) |

## Components

| Capability | Operation | Status |
|---|---|---|
| Install from official sources with hash verification | `install_component` | Tested: ghidra 12.1.4, dotnet 10.0.12 (SHA512), ilspycmd 11.1, vineflower 1.12.0, jadx 1.5.6, pydecompile (pip) |
| JDK download | `install_component component=jdk` | Implemented (system JBR 21 used here) |
| Use an existing installation | `set_component_path` | Implemented |
| Remove a private version | `remove_component` | Implemented |
| Archive traversal refused | — | Tested (`test_extract_refuses_traversal`) |

## AI

| Capability | Operation | Status |
|---|---|---|
| Explain | `ai_explain` | Implemented (same call path as convert) |
| Rename proposals, apply | `ai_rename apply=true` | Tested with Claude Code on a Ghidra function of find.exe (proposal); apply path Implemented |
| Convert to source + compile check + repair | `ai_convert target verify instructions` | Tested with Claude Code: DXBC pixel shader → HLSL, check passed (D3DCompile) |
| Agentic Q&A with tools | `ai_ask` | Tested with Claude Code: 4 tool calls, answer produced |
| Batch naming | `ai_batch_rename` | Implemented |
| Providers | Claude Code, Codex, Antigravity, OpenCode (CLI); Anthropic, OpenAI, OpenRouter, OpenAI-compatible, Ollama (HTTP) | Claude Code Tested; others Implemented (vendored from CyTools_AIChat where they are tested) |
| Compile checks | Python, Java (javac), HLSL (D3DCompile), C/C++ (MSVC via vswhere, clang, gcc), C# (dotnet SDK), Rust, Go | Python/HLSL/Java/C/C++ Tested; others Implemented |

## Interfaces

| Interface | Status |
|---|---|
| Dear ImGui window (EN/FR, Options, log, advanced operations) | Tested: screenshots in data/reports |
| CLI `invoke` | Tested |
| MCP (stdio) | Tested: `tests/acceptance_mcp.py` |
| HTTP / JSONL | Provided by CyToolsCore, not exercised here |
| Windows launcher | Tested: built with MSVC |
| Linux launcher | Implemented, not run (no Linux runtime prepared) |
| Application update stream | Implemented; check tested without a repository (no release exists) |
