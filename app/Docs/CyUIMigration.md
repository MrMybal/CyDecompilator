# Modular CyUI integration

The desktop uses the Python port of CyUI 1.2, pinned to
`ff023e646c6a3038b3dfbfd53f6d2b4a2f5955e3`. Selected sources are shipped unchanged,
with SHA-256 hashes in `vendor/cyui-source.json` and the upstream MIT notice in
`vendor/CYUI_LICENSE.txt`. The application does not need a sibling repository or
an installed `cyui` package to run.

[CyUI repository](https://github.com/MrMybal/CyUI) ·
[MIT license at the pinned revision](https://github.com/MrMybal/CyUI/blob/ff023e646c6a3038b3dfbfd53f6d2b4a2f5955e3/LICENSE).
The repository is currently private, so GitHub access is required for those links.
The bundled MIT notice remains available in every application archive.

## Selected modules

| Module | Application use |
| --- | --- |
| Core | Themes, DPI, density, fonts, layout, notifications, navigation/property filtering and shared localization |
| Code | Investigation/porting sources, converted code, operation contracts and syntax in diffs/documents |
| CodeEditor | Python JSON editing in Advanced operations and PS5 scenarios, including ImGui Undo; advanced parameters also have a syntax preview |
| Diff | Per-file Git comparisons, C# rename/format previews and observed behavior comparisons |
| Diagnostics | Application/build/debugger/PS5/Xbox logs and navigable build/C# diagnostics |
| DocumentViews | Markdown AI reports and cached, streaming conversation transcripts |
| Commands | Ctrl+Shift+P palette for navigation, opening a file, saving sources and building |
| Inspector | Read-only, filterable function properties |
| Images | Captured-screen presentation, pointer-anchored zoom, pan and double-click fit |
| Canvas | Dependency of Images; no additional engine or renderer |

`ui_views.py` adapts application data to these models. Services, filesystem writes,
revision checks, Git actions, build processes, language services, debugger sessions
and project history remain in the existing application/Runtime layer. Rendering
never invokes a toolchain. Document/diff preparation is cached until inputs change.
IDs come from stable 64-bit hashes; translated captions do not change their identity.

The EN/FR user manual now uses the separate bundled **CyDoc** file reader. Its native
launcher panel uses CyUI, while documentation search, images and SVG diagrams belong
to the offline browser export. See [CyDoc integration](../../docs/cydoc/README.md).

The shared views retain a raw-text mode for text selection, Ctrl+A/Ctrl+C and exact
copying. Diagnostic requests are resolved inside the attached source directory.
Binary/truncated comparisons retain their explicit notices. Following a Markdown
link copies its URL; the renderer does not launch an external browser or a process.

## Intentional adapters and limits

Python's shared `CodeEditor` is an ImGui multiline editor with a syntax preview.
It does not expose the C++ editor's multiple cursors, completion hooks, breakpoint
markers, fine source edits or document coordinates. Consequently the existing
`imgui_bundle.imgui_color_text_edit` backend remains for editable project sources,
native function patches and the main decompiler view with symbol navigation.
Refactorings retain one native Undo step per affected buffer. No second ImGui or
local copy of a TextEditor implementation is added.

The existing binding's palette objects are immutable. Its built-in light/dark
syntax palettes still follow CyUI's theme luminance; common Code/Diff/DocumentViews
use semantic token roles. Debugger markers use the CyUI palette. Python Code uses
the documented heuristic lexer; it does not expose the C++ 101-language catalogue.

The project explorer retains its application-specific tree and single-click file
opening. Python Assets does not currently expose a way to suppress unsupported
rename/remove requests; replacing the tree would introduce actions without matching
Runtime contracts. Engine installation, reconstruction and porting forms retain
their application-specific validation and service interactions.

There is no embedded web frontend, Unreal Editor plugin, audio UI or scene renderer
in this desktop integration. Web/CEF, Unreal packaging, Audio/AudioViews, Gallery,
Plots, Nodes, Timeline, Assets and external adapters are not shipped or enabled.
The Unreal reconstruction page is an application workflow, not a CyUI Unreal host.

## Reproducible update and delivery

From a checkout containing the pinned Git revision:

```sh
python app/scripts/vendor_cyui.py ../CyUI
```

The script reads only the pinned Git objects, selects the required dependency
closure and writes hashes for every shipped upstream file. It never copies dirty
working-tree sources or installs packages. To adopt a new revision, review the
upstream AI guide/module contracts, change `REVISION`, refresh and validate.
`.gitattributes` preserves vendored source bytes on Windows checkouts.

This is a Python/imgui-bundle application: no CMake target or optional C++/CEF
dependency is built. The existing pinned imgui-bundle supplies one compatible
ImGui implementation. The selected modules add only Python standard-library code.
Audio, Gallery and demo defaults in upstream CMake do not affect this integration.

## Verification

```sh
python -m pytest app/tests/test_cyui_integration.py app/tests/test_modular_ui.py -q
python -m pytest app/tests/test_cydec.py::test_interface_translations_complete_and_safe -q
python app/desktop.py --smoke-test --ui-test-theme=navy --ui-test-language=en
python app/desktop.py --ui-test-options --ui-test-theme=light-grey --ui-test-language=fr
```

Tests render actual ImGui frames in all five themes, both densities and DPI 1/1.5;
exercise command keyboard navigation/cancellation, native source Undo/Redo, JSON
Undo, diagnostic confinement, source revisions, raw text, image pan/zoom and data
preservation. Source hashes and every application translation catalogue are checked.
Native launch/captures are validated on Windows. Linux/macOS retain portable imports
and font fallbacks but have not been executed for this migration.
