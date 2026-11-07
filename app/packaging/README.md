# Windows distribution

The complete Windows x64 installer and portable ZIP share one freshly built payload.
Python 3.11.18 comes from the pinned python-build-standalone Windows distribution;
the 37 runtime wheels are locked by version and SHA-256. The source-identified
CyToolsCore 0.10.1 wheel is included under `vendor/`, with its MIT notice and Python sources.
No development venv, settings, optional engines or external module working tree is copied.

From the repository root, using Python 3.11+, Node.js 22+, Git, Visual Studio C++ tools
and the official Inno Setup 7 compiler:

```powershell
runtime/python/Scripts/python.exe app/scripts/build_documentation.py --setup
runtime/python/Scripts/python.exe app/scripts/build_windows.py --iscc "C:/Tools/Inno Setup 7/ISCC.exe"
```

The normal build requires committed inputs. Stage new packaging sources and use
`--allow-working-tree` only to validate a local candidate before committing.
`--portable-only` omits the installer. Artifacts and `.sha256` sidecars are written
to `dist/`; the owned staging tree, wheel cache and verification reports stay under
`runtime/build/windows-packaging/`. The builder requires at least 2 GiB free space.

`CyDecompilator.exe` opens the GUI. `CyDecompilatorCLI.exe mcp` runs the stdio MCP
server; other arguments are passed to `app/tool.py`. The legacy
`runtime/python/Scripts/python.exe` proxy keeps existing MCP commands working.
The interpreter itself is at `runtime/python/python.exe`; no system Python is required.

The installer defaults to the current user's writable Programs directory and creates
Start menu shortcuts. A desktop shortcut is optional. Uninstall removes installed
files and retains user-created projects, settings and downloaded engines.
The portable ZIP keeps everything inside its extracted directory, which must be writable.
The existing `make_release.py` ZIP remains the smaller application-only update;
the updater explicitly selects it when a release also contains full packages.

Keep complete Python/wheel license texts in the payload. `windows-runtime.json`
records upstream download hashes and SDK provenance. The installer is unsigned
unless a distributor supplies its own code-signing certificate; no certificate is fabricated.
