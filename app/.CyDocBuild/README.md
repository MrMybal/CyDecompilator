# CyDecompilator documentation tooling

Human documentation is **[Documentation](https://mrmybal.github.io/CyDecompilator/#/en/start)**
([Français](https://mrmybal.github.io/CyDecompilator/#/fr/start)). This workspace is for
maintainers and is excluded from application releases and the human reader.

## Build

Python 3.11+ and Node.js 22+ are build-time dependencies only. From the repository root:

```powershell
runtime/python/Scripts/python.exe app/scripts/build_documentation.py --setup
runtime/python/Scripts/python.exe app/scripts/build_documentation.py
runtime/python/Scripts/python.exe app/scripts/build_documentation.py --check
runtime/python/Scripts/python.exe -m pytest app/tests/test_documentation.py -q
node app/tests/documentation_browser.mjs
```

The first command installs the locked production dependencies here. Following builds
use that installation. Our `--check` is a read-only hash/freshness check. The **official
CyDoc CLI `check` also writes an export** and is run against a fresh `.work/site/` tree
by the builder before installation into `app/Documentation/`.

`manual/en/` is the original, `manual/fr/` the complete translation. Maintain the
same IDs, explicit anchors, media/annotation IDs and parent hierarchy. Increment the
English `revision` on meaning changes and review French before matching `sourceRevision`.
The build rejects missing translations, outdated revisions and untracked pages.

The current application operation manifest produces the public parameter/result
reference. `api-fr.tsv` translates every operation and nested schema description;
new untranslated descriptions fail the build. The official `cydoc/extract` adapter
extracts only the annotated public help methods. No implementation bodies or source
trees enter the export. Agent contracts go into the separate `DocAI.md` sidecar.

Use only local media under `assets/`. The selected **image** module supports the
existing screenshots and annotations. Seven static SVG flows do not need graph.
No gallery, video, GIF, mesh or graph is needed, and Three.js is not installed.

CyDoc's current stock reader, styles and image module are exported unchanged. The
small application host template adds the existing logo and a compatibility adapter
for former chapter paths and translated heading slugs. Native routes use the same
catalogue. `Documentation.html` directly contains the reader, without a server or
iframe. `index.html` and the former `app/help/index.html` preserve old bookmarks.

## Distribution and Pages

Ship all of `app/Documentation/`: `Documentation.html`, `DocAI.md`, `DocData/`, modules,
assets and notices. `app/scripts/make_release.py` regenerates it, overlays the fresh
tree and excludes `.CyDocBuild/` and the former documentation sources from release
archives. Application updates replace `app/` and therefore carry this directory.
The GitHub Pages workflow uploads only `app/Documentation/`; the root index redirect
preserves existing public README addresses. No deployment happens until a push.

`build-info.json` is maintainer metadata, never a human page or shipped resource.
Working records and test output belong in `internal/`, which is ignored by Git.
Original developer/SDK and AI documents remain in the repository; they are not
copied into the human manual. Previous reference routes point to current task pages.

## Refresh CyDoc

The vendored local npm archive uses CyDoc revision
`6ddf9a582defb2f11fbb3f992afef6f98dcadc93` (package version 0.1.0).
`vendor/cydoc-source.json` records provenance and the required archive digest.
Read upstream `ai/README.md`, `UPDATE.md`, `INTEGRATION.md`, `AUTHORING.md`, `API.md`
before changing the pin. `package_cydoc.py <clean-checkout>` uses the documented
`npm pack` distribution workflow in a private Git archive, without editing upstream.
Refresh the npm lock, rebuild and exercise the offline reader afterwards.
