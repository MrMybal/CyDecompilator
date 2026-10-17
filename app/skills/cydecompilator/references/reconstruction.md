# Reconstruct, edit and validate

## Source workspace

Use `workspace_create` to reconstruct from the current project or `workspace_open`
to attach the user's source folder. Keep source and output paths returned by the
server. Use `workspace_info` to inspect kind/files/diagnostics. An explicit creation
destination is a new absolute folder; an attached folder must already exist.

| Kind | Build/run considerations |
|---|---|
| .NET | ILSpy C# project; SDK required, select `targetProject` for multi-project solutions; local assembly/resources must resolve |
| Native | `nativeTarget=auto/executable/shared/library`; inspect blockers for entry, imports, TLS, globals, data exports and ABI; a library needs a caller/harness |
| Node/TS | Private syntax/transpile pipeline, declared dependencies; syntax checking is not full semantic TS type checking |
| Web | Build artifacts plus a Chromium scenario; no inferred executable behavior from HTML alone |
| Electron | Resources, preload, IPC and ASAR; choose an explicit Electron runtime for execution; native modules may need a matching ABI |

Java/Android/Python/shader analysis does not mean a complete desktop-project rebuild
is available. Report the actual workspace support and unresolved target toolchain.

Read with `workspace_read` before saving; pass the returned `revision` unchanged
to `workspace_save`. An empty revision is for a new file. On conflict, reread and
reconcile instead of overwriting. Use relative paths confined to the workspace.
`workspace_search` finds source locations. C# semantic operations
(`workspace_csharp`) support completion, definitions, references, rename, formatting
and diagnostics, including unsaved buffers. Refactoring returns edits to review;
use `workspace_refactor_check` and fresh revisions before applying. Build diagnostics
remain authoritative; editor services do not execute every analyzer/generator.

`workspace_execute` actions are `build`, `rebuild`, `test`, `run`. A completed job
can return `status=failed` or `no-tests`; inspect output/diagnostics and exit code.
Running stale or modified artifacts is refused: rebuild after source changes.
`workspace_dependencies` is the explicit dependency-install step (npm lockfile,
scripts disabled). `workspace_evaluate` executes MSBuild reference resolution;
custom project targets may execute just as during a build.

## Git history

`workspace_history action=snapshot` with a meaningful message stores the current
saved source/resource tree in private local Git. It does not push or change the
user's repository. For restore: compare the selected full commit ID, review the
diff, and restore using that comparison's `revision`. The server saves a backup
first. Stale preview revisions are refused; repeat compare if files changed.

## Bounded reconstruction loop

Describe `reconstruction_run`, then choose the requested target and finite budget
(`maxRounds` 1–10). Start with an unmodified build. `repair=true` uses the configured
external AI to propose source edits guarded by revisions and private Git snapshots.
Use it when AI repair is requested. Otherwise edit with the source operations and
run the same validation loop. Do not change the user's provider or send secrets.

For behavioral validation, provide representative scenarios with identical stdin,
arguments, seed files, timeouts and observations. Native DLLs need an explicit
original/rebuilt harness. Web needs a URL and browser runtime; Electron needs its
runtime and replay steps. Describe the schema for `originalExecutable`,
`rebuiltExecutable`, argument overrides and `checks` before using them.
Disabling checks and normalizing Electron application file URLs are recorded
assumptions, not proof that omitted behavior matches.

Interpret the final report and retrieve `reconstruction_status` if needed:

- `scenarios-matched`: the recorded complete scenarios matched enabled checks.
- `compiled-unverified`: compiled, but runnable evidence is missing.
- `compilation-failed`, `tests-failed`, `behavior-differs`: inspect the attempt's
  diagnostics/captures; do not report a recreated equivalent application.
- `blocked`, `cancelled`: explain the concrete blocker or retained partial result.

Finish with artifact locations, build/test results, scenarios/checks performed,
differences and unknowns. More scenario matches increase coverage; they never
prove the application behaves identically for all inputs.
