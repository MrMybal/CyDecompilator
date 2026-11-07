# CyDecompilator showcase

A buildless, bilingual static presentation, prepared for GitHub Pages. The visual
reference is the CyDaw showcase; the blue identity and all product descriptions
belong to CyDecompilator. There are no fonts, scripts, images or analytics loaded
from a third-party server.

## Build and preview

From the repository root, with the existing application runtime:

```powershell
runtime/python/Scripts/python.exe app/scripts/build_documentation.py --setup
runtime/python/Scripts/python.exe app/scripts/build_documentation.py --check
runtime/python/Scripts/python.exe app/scripts/build_website.py
runtime/python/Scripts/python.exe app/scripts/build_website.py --check
runtime/python/Scripts/python.exe -m http.server 0 --bind 127.0.0.1 --directory dist/site
```

Open the local URL printed by the server (English), or append `?lang=fr`. Windows
selects an available port. The generated
`dist/site/index.html` also works directly from the filesystem; scripts use local
resources and do not fetch translated copy. The manual remains the actual CyDoc
reader under `manual/Documentation.html`, with its complete local resource tree.

The first documentation setup is needed only when its locked Node dependencies
are missing. Later site-only edits need just the last build/check commands.

## Content and interactions

`content.json` contains English and complete French copy with common keys.
`index.html` is a template, rendered with readable English before JavaScript runs.
The manifest supplies the application version and corresponding GitHub release.
An explicit `?lang=en|fr` wins over the remembered site language; the default is
English. All manual links follow the selected language. Previous root bookmarks
such as `#/fr/workspace/follow-the-code` redirect to the unchanged HTML reader.

Captures open in a native modal dialog. Escape closes it and restores focus;
arrow keys and buttons move between images. Workspace tabs support arrow keys,
Home and End. The header keeps GitHub visible on mobile. No motion is required
to use the page, and the main screenshot uses containment rather than cropping.

The build fingerprints image, CSS, translated-copy and JavaScript filenames by
content hash. It verifies matching translation keys, local links, common CyDoc
topics/anchors, real image dimensions, generated file hashes and byte-identical
manual contents. It stages only this website and the documentation export.
Runtime data and application projects are never used as build inputs.

## Capture sources

The full native views were captured from CyDecompilator 1.5.1 on Windows x64,
using its real Dear ImGui screenshot path. They show the repository's authored
`lit_vs.cso`, `lit_frag.spv` and `funcs_x64_o2.dll` fixtures; an authored CMake
vector sample and its actual local Git diff; and an inert Electron report-viewer
example analyzed with the installed parser. The function-assistance and scenario
views show controls, not invented AI answers or a claimed successful comparison.
Only the demonstration labels appear in the path fields.

`code-detail.png` is a crop of `workspace.png`; `diff-detail.png` is a crop of
`history.png`. No captured application content was painted or synthesized.
`documentation.png` shows the actual CyDoc reader. The logo is the application's
existing logo. Captures are illustrative, not evidence of arbitrary application
or game compatibility. Their interface is English; the page's captions are EN/FR.

## Deployment preparation

The existing Pages workflow generates and checks both the documentation and the
showcase, and uploads only `dist/site`. Preparing or committing these changes does
not deploy anything. Deployment occurs on a later authorized push to `main` or a
manual workflow dispatch. The application's offline documentation and release
packaging continue to use `app/Documentation` directly.
