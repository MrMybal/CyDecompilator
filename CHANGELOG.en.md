# Changes

[Français](CHANGELOG.md) · [Application README](README.md) · [Releases](https://github.com/MrMybal/CyDecompilator/releases)

CyDecompilator is **in development**. Windows x64 is supported; Linux x64 is experimental.
Full Windows packages include their runtime; the smaller application-only update requires a compatible existing runtime. The version number does not establish reconstruction or console compatibility.

## 1.5.2 — 7 November 2026

- Complete Windows x64 installer and portable ZIP with a relocatable Python 3.11.18 runtime, 37 hash-locked dependencies and the source-identified CyToolsCore 0.10.1 SDK.
- English/French installer, current-user destination, Start menu and optional desktop shortcuts. Uninstall preserves user-created data and downloaded engines.
- Native GUI/CLI launchers, legacy Python-path compatibility proxy, and support for existing development venvs.
- Application updater selects the small application-only ZIP even when full packages appear first.
- Updated README and built-in English/French installation/MCP guides, runtime provenance and component notices.

### Availability and limits

[Release 1.5.2](https://github.com/MrMybal/CyDecompilator/releases/tag/v1.5.2) provides an installer, a complete portable ZIP, an application-only update and their SHA-256 files. Optional engines and target build toolchains remain separate. Windows artifacts are unsigned; no code-signing certificate is configured. Linux remains experimental. Known workflow limitations from 1.5.1 below still apply; consult the [issue tracker](https://github.com/MrMybal/CyDecompilator/issues).

## 1.5.1 — 6 November 2026

- Updated CyDoc documentation: complete English and French human manual, hierarchical
  navigation, global header search and detailed tooltips.
- Public operation and help-link references with parameters, results and translated examples;
  AI instructions remain separate in `DocAI.md`.
- New self-contained `app/Documentation/` folder for offline use; F1, contextual help
  and previous documentation links are retained.
- Generation and distribution of the complete reader with the application and on GitHub Pages.
  Documentation sources and tools are separate in `.CyDocBuild/`.

### Availability and known issues

[Release 1.5.1](https://github.com/MrMybal/CyDecompilator/releases/tag/v1.5.1) contains the Windows
launcher, application and offline manual. Keep the existing compatible `runtime/` and `data/`
directories. Source/documentation changes after the release tag are not additions to that archive.

The release does not publish a bug-by-bug list. Consult the actual
[issue tracker](https://github.com/MrMybal/CyDecompilator/issues) and
[capability coverage](app/Docs/CapabilityCoverage.md); the absence of a listed ticket is not
evidence that a workflow is bug-free.

### Documented limitations

- Linux x64 is experimental; there is no packaged Linux or macOS release here.
- Python 3.9+ inputs do not have complete source decompilation; bytecode and AI reconstruction are available.
- DXIL libraries (`lib_6_x`, ray tracing) currently expose only their first function.
- Encrypted PyInstaller archives (`--key`) and NSIS/Inno installers are detected but not extracted.
- Native C type reconstruction is limited: structures can appear as pointer-offset expressions.
  ARM64 prototypes list integer parameters before floating-point parameters.
- C# services need appropriate .NET SDK references. Native and .NET Framework debugging are not available;
  the execution/debug console does not provide interactive input or variable modification.
- Reconstruction and function replacement have format, dependency, ABI and signing constraints.
  A successful build does not establish equivalent behavior.
- PS5/Xbox conversions remain experimental and depend on separately installed backends and the game.
  Original Xbox is inspection/preparation only. Playability and 60 FPS are not established by conversion.
- Ghidra analysis of large binaries can be lengthy; the analysis function limit is configurable in Engines.

These are scope limitations, not invented confirmed bug tickets. Follow the
[manual](https://mrmybal.github.io/CyDecompilator/manual/Documentation.html#/en/start) for each workflow.

## 1.5.0 — 2 November 2026

- Migrated to modular CyUI 1.2: code views, JSON editing, Git/refactoring differences,
  filterable logs, diagnostics, Markdown and AI conversations.
- Ctrl+Shift+P command palette, filterable function properties, and captured screens
  with zoom, pan and fit-to-window.
- Pinned CyUI revision, source hashes and MIT license link, with an included notice
  available without access to the private source repository.
- Optional AnyPS5/UltraPack preparation and conversion, diagnostics linked to functions
  and experimental native graphics profiles. Game compatibility and the 60 FPS target remain unestablished.
- Unreal reconstruction rules and profiles exposed to the Runtime, MCP and agent;
  game conversion remains separate.
- Retained native editor for completion, debugging and Undo/Redo.
- Rebuilt Windows launcher; private runtime and engines must be retained separately.

## 1.4.0 — 17 October 2026

- CyUI interface: sidebar navigation, five themes, adjustable density/text size,
  toolbars with tooltips and layouts for smaller windows.
- Assistant organized into autonomous workflows, conversation and function actions.
- Autonomous agent available in the application and through MCP, with resume support,
  Git backups, repairs, builds and validation evidence before completing reconstruction.
- Complete MCP catalog, connection guide and installable CyDecompilator skill.
- Preserved original application paths during input preparation and protected open
  sources during autonomous modifications.
- Rebuilt Windows launcher included in the application archive; private runtime and
  engines retained in the existing installation.
