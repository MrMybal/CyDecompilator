<p align="center"><img src="assets/logo-256.png" width="160" alt="CyDecompilator"></p>

# CyDecompilator — developer guide

AI-assisted multi-engine decompiler built on CyToolsCore 0.10 (Python 3.11, Dear ImGui).
User guide (French): `../LISEZ-MOI.md`.

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
runtime\python\Scripts\python.exe -m pytest app\tests -q           # 31 tests
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
