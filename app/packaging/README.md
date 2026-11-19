# Windows distribution

The complete Windows x64 installer and portable ZIP share one freshly built payload.
Python 3.11.18 comes from the pinned python-build-standalone Windows distribution;
the required runtime wheels are locked by version and SHA-256. CyMCPSDK 0.7.0 is compiled from the pinned local or bundled source archive; the selected native modules and notices are included under `app/native/`. No former Python SDK wheel is installed.
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

`CyDecompilator.exe` opens the GUI. `CyDecompilatorCLI.exe --auto` runs SDK CLI
business commands against the owning instance or without a window. `jsonl`/`sdk stdio`
use the native SDK protocol; job controls preserve ownership between commands.
`CyDecompilatorCLI.exe mcp` runs the stdio MCP
server; other arguments are passed to `app/tool.py`. The legacy
`runtime/python/Scripts/python.exe` proxy keeps existing MCP commands working.
The interpreter itself is at `runtime/python/python.exe`; no system Python is required.

The installer defaults to the current user's writable Programs directory and creates
Start menu shortcuts. A desktop shortcut is optional. Uninstall removes installed
files and retains user-created projects, settings and downloaded engines.
The portable ZIP keeps everything inside its extracted directory, which must be writable.
The existing `make_release.py` ZIP remains the smaller application-only update;
the updater explicitly selects it when a release also contains full packages.
Upgrading from 1.5.2's former Python SDK requires the complete 1.5.3 installer or
portable package because the runtime ABI changed. Preserve `data/` when replacing
an existing portable installation. The application-only ZIP requires the new ABI.

Keep complete Python/wheel license texts in the payload. `windows-runtime.json`
records upstream download hashes and SDK provenance. The installer is unsigned
unless a distributor supplies its own code-signing certificate; no certificate is fabricated.

The native build uses MSVC `/EHsc`, `/O2` and a static CRT. See [CyMCPSDK integration](../Docs/CyMCPSDK.md) for provenance, transport compatibility, independent options and validation. Python MCP is a development test dependency, not a shipped server dependency.
