# CyDecompilator documentation — CyDoc

**[Documentation](https://mrmybal.github.io/CyDecompilator/#/en/start)** ·
[Français](https://mrmybal.github.io/CyDecompilator/#/fr/start)

The application is Python 3.11 + Dear ImGui/CyUI, with Windows x64 support and
experimental Linux x64 support. Its help reader is the **local CyDoc browser export**,
opened by the native Documentation page, command palette, contextual F1, and Xbox
guide button. No web server, browser framework embedded in the application, CDN,
engine, AI account, Node runtime or connection is required to read it.

`app/help/index.html` and its entire sibling directory are the distributable reader.
Keep the directory intact. Open it directly with a `file://` URL; `app/documentation.py`
validates native page, section, media and annotation destinations. Browser links may
point to upstream websites for optional research, but no remote resource is loaded
to display a page. Sources and generated examples never execute while reading.

## Generate and check

From the repository root, with Python 3.11+ and Node.js 22+ for build time only:

```powershell
runtime/python/Scripts/python.exe app/scripts/build_documentation.py --setup
runtime/python/Scripts/python.exe app/scripts/build_documentation.py
runtime/python/Scripts/python.exe app/scripts/build_documentation.py --check
runtime/python/Scripts/python.exe -m pytest app/tests/test_documentation.py -q
node app/tests/documentation_browser.mjs
```

The first command installs the locked production build dependencies into
`runtime/documentation-tools/`, with npm's cache under `runtime/cache/npm/`. It can
need network access once. Subsequent builds use that installation; reading never
does. `--check` needs only Python and verifies source freshness and every output hash.
The browser test uses an installed Windows Chrome or Edge; it downloads no browser.
Use `--browser=/absolute/path/to/chromium` for another available Chromium binary.

The build uses the **official CyDoc CLI `check`**, which both validates and exports.
It generates fresh inputs/output under `.generated/`, bundles the application-owned
`reader.mjs` through the public `cydoc/viewer` API, then installs the validated export
into `app/help/`. No generated CyDoc HTML/manifest is patched to repair content.
`index.html` is the application-owned host template. The module and packed-resource
providers use CyDoc's classic-script contracts, avoiding file-origin fetch/CORS.

`app/scripts/make_release.py` regenerates help and overlays the complete fresh export
into the committed-source release ZIP. Run `--setup` before the first release build.
Normal launcher startup needs no documentation generation. Commit authored inputs,
the pinned dependency archive and `app/help/` together after regeneration.

## GitHub Pages

`.github/workflows/documentation-pages.yml` regenerates this same CyDoc export on
every push to `main` and can also be run manually through Actions. Build-only Python
3.11 and Node.js 22 use the pinned CyDoc archive and npm lock; the application runtime
and optional engines are not installed by this workflow. Resource/link validation
and the exported hash check must succeed before deployment.

Only `app/help/` is uploaded to the Pages artifact. The repository root, runtime,
local projects and application data directories are not publishing sources.
Pages uses the GitHub Actions publishing mode and the `github-pages` environment.
The English README opens `#/en/start`; the French README opens `#/fr/start`.
Hash routes and relative asset/module URLs work under the repository subdirectory
as well as through `file://`; no separate web reader or documentation content is used.
The native help entry points continue opening the installed local export.

## Inputs and preservation

- `content/en/` and `content/fr/`: the 22 migrated user chapters. Stable IDs and
  explicit heading IDs are common between languages. `catalog.json` defines the
  native chapter selector; `compatibility.json` retains old chapter filenames,
  translated heading slugs and application-page contexts.
- `assets/`: three unchanged application captures and the reader icon. The captures
  show the supplied DXBC sample/example CMake project on Windows in version 1.5.0;
  they contain no game content or implied compatibility results.
- All `app/Docs/*.md`, developer/user READMEs and bundled AI skill/reference files
  are included as technical appendices. Original files remain for repository users,
  SDK contracts and machine readers. Source-language appendices carry explicit
  notices and **untracked** translation status, rather than pretending to be reviewed
  translations. Links to build/source files remain visible as paths.
- The changelog, CyTools authoring guide and experimental module READMEs/reports
  are retained as versioned snapshots. References to missing SDK guides, local
  work directories or historical proof files are marked in the migration audit;
  those unavailable files are never invented or copied from private work data.
- `app/CyTool.json`: generates complete operation contracts, preserving every input,
  output, permission, resource and job field. Localized explanatory wrappers do not
  translate schema string values or promise engine compatibility.
- `app/documentation.py`, `app/operations.py`, `app/cydec/engines/base.py`: the only
  files indexed by CyDoc. Python `@doc` docstrings provide annotated help API pages.
  This is a **lexical import index**, not semantic type reconstruction. Runtime data,
  optional engines, third-party sources, inspected inputs and private projects are
  excluded by an explicit allowlist, not a whole-workspace scan.

`app/help/migration-report.json` records original reference hashes, transformed links,
source scope and known limitations. `build-info.json` records input/output hashes.
Source text hashes use canonical LF endings so Git checkout conversions do not
invalidate them; exported resources retain byte-for-byte hashes. Media referenced
from local work, runtime or build directories stays outside the distributable reader.
Versioned SDK snapshots and historical performance claims remain labeled evidence
of their recorded scenario, not claims about today's builds or 60 FPS.

## Modules and appearance

Only **image** is enabled: screenshots use the minimal controls, pan/zoom, in-window
enlargement and a stable annotated navigation region. Seven bilingual workflows are
compiled from diagram fences into static SVG with full ordered text equivalents;
they need no graph module. There is no video, animated GIF, mesh or media collection
in the existing manual, so video/gif/mesh/gallery/graph and Three.js are excluded.
The export validator rejects other media modules; the production npm installation
also rejects an unexpected Three.js package.

The default **nord** theme matches the application's dark blue palette. CyDoc owns
keyboard/touch interaction, reading tabs/positions, search, language switching and
in-window media presentation. Reading state uses an application-specific storage
namespace; persistent storage for `file://` depends on the browser's local-file
policy. EN/FR are supported; other application UI locales fall back to English.

## Authoring and translation tracking

Use frontmatter with `id`, `title`, `section`, `order` and an English `revision`.
Set the French `sourceRevision` only after reviewing it against that English revision.
Keep page IDs, `{#explicit-heading-id}`, media IDs and annotation IDs identical.
Use `doc:page-id#heading-id` or `doc:page-id?media=media-id&note=annotation-id`.
Images use local `assets/...` paths. Do not add HTML scripts, remote images or CDN URLs.

CyDoc generates `translation-report.json` and the `translation-report` page. Current
chapters and generated operation wrappers are tracked; historical technical originals
are deliberately untracked. CyDoc 0.1.0 does not propagate translation revisions from
source annotations/source-index pages; do not invent a reviewed status for them.

## Pinned library and refresh

CyDoc 0.1.0, revision `774f2a7eabf7dd181a98ffc5add115b580b67f42`, MIT.
`vendor/cydoc-0.1.0.tgz` is a Git-source package with compiled public JS/types, CLI
and exporter, not a copied node_modules tree. Its SHA-256 is checked before building;
provenance is in `app/vendor/cydoc-source.json`. The MIT notice ships in the export.

To deliberately refresh the pinned library, review its `ai/README.md`,
`ai/INTEGRATION.md`, `ai/AUTHORING.md` and `ai/API.md`, update the pin in
`app/scripts/vendor_cydoc.py`, then run it against an authenticated, clean checkout.
Its temporary compilation files stay inside this project's `runtime/build/`;
the source checkout is read-only. Do not change CyDoc's own files to integrate help.
Keep the package lock and metadata synchronized and rerun both Python and browser checks.

## Platform validation

The browser test verifies the actual `file://` export, direct section/media links,
language switching, search, keyboard focus, image enlargement and offline resources.
Native frame tests cover the help launch panel and help routing without running a game.
Windows browser validation is recorded by the test output. Linux/macOS native launches
and their browser-specific local-file/storage behavior still need platform testing.
