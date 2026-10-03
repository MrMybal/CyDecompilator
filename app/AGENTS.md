# Working on CyDecompilator

Read `README.md` (architecture, commands) and `Docs/CapabilityCoverage.md` first. The
CyToolsCore contracts copied in `Docs/` (StandaloneDelivery, Localization, TaskFiles...) apply.

- Operation contracts live in `operations.py`; regenerate `CyTool.json` with
  `build_manifest.py`, then register the handler in `tool.py`. A declared operation without a
  handler makes `create_runtime` fail on purpose.
- Business logic goes in `cydec/` (service, engines, ai). Handlers and the window stay thin;
  the window only submits jobs to the Runtime and reads projects through `service`.
- Engines never print to stdout. External programs run through `cydec.process.run`, which
  stops the whole tree on cancellation. Engines return `_code` pairs instead of writing the
  cache themselves.
- Downloads only from official sources, hash-verified when the source publishes one, into
  `runtime/engines/<id>/<version>`. Never install engines into the Tool's Python.
- Shader engine changes: keep `tests/test_cydec.py` green — DXBC disassembly must equal the
  fxc listings and decompiled HLSL must recompile with D3DCompile.
- Every visible string goes through `tr()`/`label()`; add French to `locales/cydec-fr.json`,
  run `scripts/merge_translations.py`, and add the string to every `locales/ui.<code>.json`
  (de, es, it, pt, ru, zh, ja, ko): `test_interface_translations_complete_and_safe` fails otherwise.
- No API key in parameters, settings JSON, jobs or logs (`cydec/ai/credentials.py` only).
- Declare `processSpawn` / `network` / `filesystemExternal` on operations that really do it.
- Tests: `runtime/python/Scripts/python.exe -m pytest app/tests -q` and
  `app/tests/acceptance_mcp.py`.
