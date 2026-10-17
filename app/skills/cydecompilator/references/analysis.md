# Analysis and evidence

## Binary entry point

Use `open_file`, then `project_info`, `list_functions`, `decompile`, `xrefs`,
`strings`, `search` and export operations as needed. Inspect detected format before
choosing an engine. Keep `projectId` for subsequent operations.

| Input | Engine / approach | Important boundary |
|---|---|---|
| Native PE/ELF/Mach-O | Ghidra for type/call/value investigation; cdec for supported recompilable C; native for disassembly | Inferred C is not recovered original source; architecture and ABI matter |
| .NET IL | ILSpy, `managed_methods` | Mixed-mode/ReadyToRun method replacement needs a full IL rebuild |
| Java class/JAR, Android APK/DEX | Vineflower or JADX according to availability | Resource/framework/toolchain recovery still requires verification |
| Python/PyInstaller | Python bytecode analysis, `extract_embedded` | Newer bytecode may have disassembly without reliable source reconstruction |
| DXBC/DXIL/SPIR-V | Shader engine, decompiled/disassembly views | Test with the appropriate compiler; metadata alone is not executable shader source |
| Packed/bundled image | `extract_embedded`, then open selected extracted executable/module | Extraction is not itself a successful reconstruction |

Use `load_symbols` only when needed; honor user settings for symbol downloads.
`rename`, comments and notes annotate cached views, they do not patch the executable.

For a selected Ghidra function, `investigation_native` supplies typed instruction,
call and high-pcode SSA evidence. `investigation_query` links evidence nodes.
Differentiate direct calls from candidates; indirect calls, aliases and values
crossing function boundaries may remain unresolved.

## JavaScript, Electron and web

`application_open` snapshots the application without executing its modules. Query
features with `investigation_query`, follow relationship paths and read the exact
hashed snapshot with `investigation_source`. Use source lines and SHA256 evidence
to connect a visible feature to modules, event handlers, resources, routes,
preload bridges and IPC candidates. Ambiguous/shadowed/dynamic relationships are
not proven execution. Local source-map v3 data may recover names/locations; do not
claim remote, inline or indexed maps are supported unless the server says so.

## Observed process, network and graphical behavior

For an authorized runtime scenario, use `behavior_capture` with a specific
executable, argument array, finite timeout, initial files and stdin. Compare capture
IDs with `behavior_compare`. Read `behavior_evidence` to obtain integrity-checked
runtime/screenshot evidence and `behavior_captures` to find earlier recordings.

Describe `behavior_capture` before creating the `observation` object:

- `driver=windows`: controls in the owned process via UI Automation, selectors
  by automation ID/name/control type. Custom-drawn controls may be unavailable.
- `driver=chromium`: Chromium executable, CSS steps, optional headless mode and URL.
- `driver=electron`: Electron executable and app argument, CSS steps against its
  renderer. This driver is not headless Chromium. Select `targetUrl` for ambiguity.
- `network=true`: selected renderer HTTP metadata and sampled owned-process TCP.
  This is not packet capture, UDP coverage, or inspection of headers/bodies.
- Replay `fill`, `click`, `assertText`, `snapshot` and bounded waits. Use returned
  states and screenshots to assess outcomes, including failed or incomplete steps.

Imported HAR observations (`investigation_har`) are distinct from a live capture.
Correlation edges are inferences. State which evidence supports each conclusion
and what the scope cannot observe (external files, privileged helpers, remote side
effects, unexecuted paths). A matching screenshot or network list alone does not
establish complete equivalence.
