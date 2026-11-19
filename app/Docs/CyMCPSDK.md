# CyMCPSDK integration

CyDecompilator uses **CyMCPSDK 0.7.0**, compiled from revision
`791d4d7d7680213b282ec8529d248a10f8494d77`. The native library links Core,
Platform, Http, MCP and AI. Local is unnecessary: optional analysis engines retain
their existing installers, and local model services are connected through AI.
ChatUI is a C++ ImGui/CyUI component; this application's `imgui_bundle` Python
context uses its existing CyUI transcript/composer with the native Conversation
service. No second ImGui context, Three.js, model weights or web server is needed
to read the bundled documentation.

## Build and distribution

```powershell
runtime/python/Scripts/python.exe -m pip install -r app/requirements.txt -r app/requirements-dev.txt
runtime/python/Scripts/python.exe app/scripts/build_mcp_sdk.py --bundled
powershell -ExecutionPolicy Bypass -File app/build_launcher.ps1
runtime/python/Scripts/python.exe app/build_manifest.py
runtime/python/Scripts/python.exe app/scripts/build_documentation.py
```

The build prefers a clean sibling `CyMCPSDK` checkout, records its exact Git revision and
compiles the sources rather than importing an upstream executable. An unavailable
checkout can use the hash-verified source archive in `app/native/vendor/`; only
when neither is available does the build clone the official Git repository.
`--source` and `--output` choose explicit directories. `--bundled` selects the
hash-verified, pinned source archive even while the sibling SDK checkout is being
modified. Distribution builds always use this pinned archive; no sibling changes
are committed or incorporated implicitly. Source hashes, MIT notices,
module selection and the archive digest are in `app/native/cymcpsdk-source.json`.
The build receipt includes the native binary and host-source hashes. MSVC `/EHsc`
is mandatory for cancellation cleanup; Release uses `/O2` and a static CRT.

`native/sdk_overlay.py` applies one recorded compatibility extension in a private
copy of the SDK sources: the existing API sampling-temperature option is forwarded
to Chat Completions, Responses, Messages and Ollama requests. The upstream checkout
and source archive remain unchanged. `hostExtensions` in the binary receipt names
the extension and hashes every modified source. Default SDK behavior is unchanged
when temperature is null; a model may still reject a setting it does not support.

The Windows distribution builder compiles and copies `app/native/bin/cydec_mcp.dll`
beside the application sources, then installs the separately locked Python wheels
into a fresh relocatable runtime. It never copies a development venv or `data/`.
The former Python SDK wheel is removed. The application-update ABI is now
`python311-cymcp070-imgui192-cydec02`: an older installation needs a complete
package rather than applying code with an incompatible native runtime.

## Registry and application lifecycle

`operations.py` and the generated `CyTool.json` remain the stable application
contract. `tool.py` binds real `cydec/` handlers. The C ABI in `native/bridge.cpp`
registers these operations in **CyMCPSDK Registry**. Its policy invokes the host's
authenticated permission checks; the SDK validates inputs and outputs. The same
registry serves GUI jobs, native tool calls, CLI and MCP. The historical
`x-cy-kind` metadata stays in the host manifest for input staging and is omitted
from the SDK schema because it is not a supported validation keyword.

Every call retains network/process/external-filesystem requirements, revision
guards, original-input preservation, Git backup behavior and cancellation.
`delete_project`, `remove_component`, `update_apply` and `update_rollback` need
explicit confirmation. CLI requires `--confirm`; advanced forms provide a
confirmation checkbox. The integrated assistant excludes credentials, application
updates and destructive operations. A selected-project conversation cannot pass
another `projectId`. Local storage/theme/provider preferences remain host UI
configuration rather than assistant tools.

`cydec/mcp/runtime.py` owns application jobs because SDK tool calls return direct
results rather than durable scheduled jobs. It reads the existing SQLite
`records(kind,id,value)` database, clients, token hashes, sessions and completed
outputs without rewriting user projects. Interrupted jobs become `Failed` with
`Interrupted`, never rerun. Results remain durable beyond SDK resource retention.
Queued priorities, exclusive groups, progress, process cancellation and owner
isolation are retained. GUI work consumes worker events on its ImGui thread;
business handlers run on workers and do not call ImGui.

The local/shared download and installed-CUDA settings retain their paths and
environment compatibility. The small application-owned storage/HTTPS helpers
preserve existing behavior with source provenance and MIT attribution in
`native/legacy-storage-source.json`; they do not import the former SDK.

## CLI

The native console launcher forwards arguments, stdin, stdout and exit codes.
The Python entry point is equivalent and works without opening a window:

```powershell
CyDecompilatorCLI.exe --help
CyDecompilatorCLI.exe sdk-info
CyDecompilatorCLI.exe list-operations
CyDecompilatorCLI.exe describe-operation open_file
CyDecompilatorCLI.exe invoke open_file --params-file input.json --timeout 300
```

Example `input.json`: `{"path":"C:/samples/shader.spv","engine":"shader"}`.
`describe`, `list-backends`, `list-models`, `estimate`, `can-run`, `diagnose`,
`create-client`, `stdio`, `serve`, `mcp`, `--data-dir`, `--params`,
`--params-file`, `--backend`, `--model`, `--timeout` and `--connect` remain
available. The public executable and `app/tool.py` default to `data/jobs`; the
embedded `run_cli` helper retains its historical `.cytools` default. Select the
same explicit `--data-dir` for both when sharing a live instance. `stdio` preserves the existing application JSONL envelope. Successful
invocations print one JSON job to stdout and exit 0; failed/cancelled calls exit 1
and diagnose on stderr. Invalid CLI syntax uses argparse's exit 2. A timeout does
not authorize replaying a mutation: inspect the stored job.

## Autonomous external AI through the SDK CLI

An external AI with command execution can operate the application directly. No
CyDecompilator model account, integrated chat or MCP client is required. The
external AI performs the reasoning; the CLI calls the compiled SDK registry.

```powershell
CyDecompilatorCLI.exe --auto list-operations
CyDecompilatorCLI.exe --auto describe-operation open_file
CyDecompilatorCLI.exe --auto invoke open_file --params-file input.json
CyDecompilatorCLI.exe --auto sdk describe
CyDecompilatorCLI.exe --auto sdk invoke open_file --params-file input.json
CyDecompilatorCLI.exe --auto jsonl
```

`invoke <name> input.json` also accepts the SDK example's positional JSON file.
The existing `invoke` returns a durable job; `sdk invoke` returns its domain result
and `_jobId`. `jsonl`/`sdk stdio` use the actual native **dispatch_app** protocol:

```json
{"method":"describe"}
{"method":"invoke","name":"list_projects","arguments":{}}
{"method":"invoke","name":"cy_describe_operation","arguments":{"operationId":"workspace_create"}}
```

Keep JSONL stdin open throughout a multi-step/asynchronous/debugging task. Each
line gets one JSON response. Errors stay structured; subsequent lines continue;
a stream containing errors exits 1. Historical `stdio` keeps its old envelope.

`--auto` uses the selected running instance through private local IPC, or runs
without a window if the database is free. A stable account-protected local
identity preserves access to its jobs between commands/chats. Explicit credentials
retain their restrictions. The CLI manages the local connection; no terminal token
copy or MCP configuration is needed for this path. The owning headless process
must stay alive while its asynchronous jobs run; closing it stops that work.

```powershell
CyDecompilatorCLI.exe --auto jobs
CyDecompilatorCLI.exe --auto job JOB_ID
CyDecompilatorCLI.exe --auto wait JOB_ID --timeout 30
CyDecompilatorCLI.exe --auto result JOB_ID --offset 0 --length 32768
CyDecompilatorCLI.exe --auto cancel JOB_ID
```

A long-lived automatic CLI/JSONL owner publishes its endpoint, so a second CLI
process can inspect and cancel its jobs. Result chunks are base64 JSON bytes;
follow `nextOffset` to recover the complete output. Read/cancel controls enforce
ownership. A failed/cancelled wait exits 1; a wait deadline does not replay work.

Ordinary authorized business actions do not require a UI popup. Explicitly
requested destructive operations retain `--confirm`, or `confirmed:true` on an
`op_*` SDK request. The caller's own external AI execution/approval policy remains
applicable. `ai_*`/`assistant_send` explicitly use the application's configured
provider; direct edits/builds/test operations do not. The distributed
[CLI agent guide](../skills/cydecompilator/references/cli.md) describes autonomous
reconstruction, recovery, validation and cleanup.

## MCP and a running instance

```powershell
CyDecompilatorCLI.exe --data-dir D:/CyDecJobs mcp --full
CyDecompilatorCLI.exe --data-dir D:/CyDecJobs mcp --compact
```

Stdio defaults to full discovery for existing clients. Native operations accept
their domain arguments directly and return their result. Compatibility tools
`op_<operation>` accept `{"parameters":{...}}`, submit a durable job and return
its identifier. Poll `cy_get_job`; `cy_cancel_job`, `cy_events`, task controls and
`cy_read_result` remain available. Read large durable JSON results with
`cy_read_result {jobId,offset,length}`: bytes are base64 encoded, with total size
and the next offset. `cy_read_result` never reruns its originating action.

Compact discovery provides `cy_tools_search`, `cy_tools_describe`,
`cy_tools_call`, `cy_resources_read` and `cy_resources_grep`. Every operation
remains reachable. Load a complete schema before invoking an unfamiliar tool.
Only the host metadata annotation is removed; supported schema assertions remain.

One runtime owns a job database. The GUI now advertises an authenticated ephemeral
loopback endpoint by default; `--no-mcp` disables it. `mcp --auto` attaches or runs
headless, and `mcp-config` prints an installation-specific client declaration
without credentials. This optional MCP path is independent of SDK CLI/JSONL.
Automatic MCP discovery defaults to compact; `--full` remains available.

For an explicit token-based connection to an already open GUI, create a restricted
client **before** starting that instance, retain its token privately, then launch
the GUI with `--mcp-port=8766` (or `--mcp-port=0` for an ephemeral port reported on
stderr). A standalone server can use `serve --port 8766`.

```powershell
CyDecompilatorCLI.exe --data-dir D:/CyDecJobs create-client --name external --permission processSpawn --permission filesystemExternal
# Supply that client's token through CYMCP_TOKEN in this terminal.
CyDecompilator.exe --data-dir D:/CyDecJobs --mcp-port=8766
CyDecompilatorCLI.exe --connect http://127.0.0.1:8766/v1 list-operations
CyDecompilatorCLI.exe --connect http://127.0.0.1:8766/v1 invoke list_projects
```

`CYTOOLS_TOKEN` remains a credential-variable alias for existing configurations.
No token belongs in business arguments, a screenshot or a checked-in config.
The GUI's own identity is retained in its credential vault so its conversation
ownership survives restarts. External clients authenticate with their own token.
`/v1` is the application JSON endpoint; `/mcp` is MCP over authenticated loopback
HTTP JSON. It acts on the **same runtime and store** as the open window. An MCP
client can configure `/mcp` and an `Authorization: Bearer …` header. HTTP endpoints
reject non-loopback binding and browser origins. This adapter uses JSON responses,
not persistent HTTP SSE subscriptions. Stdio supports native notifications;
HTTP clients retain TTL/explicit refresh.
This SDK revision negotiates MCP `2026-07-28`, with legacy `2025-11-25` and
`2025-06-18`. Native `subscriptions/listen` requires the modern protocol;
legacy peers use TTL/explicit refresh. Older protocol dates are not advertised
as compatible.

## Integrated conversation and providers

Open **AI → Application assistant** without needing a selected application.
Choose providers/models in **AI assistant settings**. Send a request, watch text
deltas and tool events, cancel an active turn, refresh saved conversations and
restore one exact session. Attach explicit files up to 8 MiB each; the provider
validates supported media and reports unsupported types. Project-specific
conversation/function/autonomous modes remain available.

The SDK provider catalogue exposes 23 profiles. A detected executable is not
proof of authentication or generation. Codex receives the registry through native
dynamic tools. Compatible HTTP, Responses, Messages and Ollama providers use the
SDK's implemented tool exchange. Claude Code receives an authenticated, ephemeral
MCP connection to the application with an explicitly limited conversation
delegation; its own shell/file actions remain disabled. Delegated credentials
are private, revocable and are never written into checkpoints. Other CLI/ACP
profiles remain available for function assistance; the business chat reports
`Unsupported` until that transport has an explicit application MCP path.

Full histories/checkpoints remain private in `data/ai/sdk-conversations` relative
to the chosen job root's parent. Native agents reconnect exact IDs; API providers
restore host history. Old project conversation files are preserved and copied
into the new checkpoint format on explicit continuation. SDK context projection
is configurable for host-history APIs, pins system/active turns and preserves
tool exchanges. Native CLI agents keep their own context management. No automatic
summary or hidden model call is performed.

## Independent optimizations and external tools

The collapsible **CyMCPSDK options and external tools** panel saves host-selected
configuration. Restart after editing. The independent settings in `data/settings/mcp.json`
are `compactDiscovery`, `cache`, `cacheTtlMs`, `notifications`, `diskSpool`,
`diskBytes`, `memoryBytes`, `spoolRoot`, `retentionSeconds`, `chunkBytes`, `inlineBytes`,
`telemetry`, `contextBytes`, `recentTurns`, `ripgrep` and `workspaceRoot`.

Defaults enable compact chat discovery, a 30 s cache TTL, SDK change-feed wiring,
32 KiB chunks, 16 KiB inline results, a 16 MiB memory budget, a 128 MiB disk
budget and 15-minute transient retention. Durable job outputs are independent.
Performance JSONL is off by default and records durations, byte counts, status
and cache metadata only. The full history stays on disk when a context projection
is sent to a provider. Result expiration produces an error, never an action replay.
`spoolRoot` can select an absolute disk directory independently of the job root;
empty uses the private SDK directory below the chosen `--data-dir`. SDK-created
transient children are private; durable SQLite results remain in the job storage.

The `cydec://operations` MCP resource exposes the operation catalogue. Native
resource grep searches registered text snapshots without filesystem traversal.
`workspace_grep_native`/`workspace_read_native` are optional SDK FileSearch
operations: enable `ripgrep` and explicitly choose an existing absolute
`workspaceRoot`. The host never infers a root from an AI prompt. Ripgrep is not
downloaded automatically; results use paged cursors and revision-checked ranges.

External MCP servers are opt-in in `data/settings/mcp-assistant.json`:

```json
{"servers":{"other-app":{"executable":"C:/Tools/OtherApp/OtherAppCLI.exe","arguments":["mcp"],"allowedTools":["document.inspect","document.export"],"allowedResources":["otherapp://manual"]}}}
```

Alternatively configure an HTTPS URL (HTTP is allowed only for loopback).
Credentials are resolved from the application's vault under `mcp:<server-id>`;
they are not configuration fields. `remote_tools` returns only approved tools;
`remote_call` forwards to SDK McpClient and propagates business errors.
`remote_resources` lists approved resources, reads approved/referenced URIs and
optionally starts/drains native notifications on supported transports. Tool and
resource pagination is handled by the SDK client. Discovery/read caches can be
explicitly refreshed; mutation results are not cached or replayed.

## Validation and limits

Local validation includes the compiled bridge, old and new CLI/MCP calls, actual
shader analysis, permissions/refusals, durable jobs, source/project/Git/build
workflows, streamed loopback provider tool calls, conversation restoration and
cancellation, a second real application MCP server, context projection and
metadata-only measurements. A real Codex CLI 0.169.0-alpha.11.1 conversation with
`gpt-6.2-sol` called `project_info` and `set_notes` on an isolated shader project,
and produced text deltas. Tests use no GitHub workflow.

Direct MCP request cancellation is propagated from the SDK to the Python job
token and the existing process-tree cancellation path. The targeted test cancels
a running native MCP tool, verifies that its handler stops and retains its
durable `Cancelled` child job. Existing asynchronous `op_*` jobs continue to use
`cy_cancel_job` independently of the lifetime of their submission request.

The native cache test reads a resource twice, observes a cache hit, subscribes to
changes, executes two distinct mutations and reads the updated value before TTL.
The large-result test reconstructs the complete retained text through every chunk,
then verifies owner isolation and expiration. External tool success and errors are
also exercised through the chat's actual provider loop. Workspace search tests
cover the explicit root, traversal refusal and changed-file revisions. Delegation
tests initialize the MCP session and check active-turn, project and job scope,
then revocation. The real Claude Code attempt reached its native transport but
returned `AuthenticationRequired` on this machine; it made no project changes.

```powershell
runtime/python/Scripts/python.exe -m pytest app/tests/test_cymcp_integration.py -q
runtime/python/Scripts/python.exe app/tests/acceptance_mcp.py
```

Available-platform coverage is Windows x64. Linux/macOS native compilation and
graphical execution still need validation. Provider capabilities depend on their
actual transport, account and model; the other profiles are not all live-tested.
Windows computer-use capture timed out on this machine, so application-native
render captures and service-level checks are distinguished from interactive clicks.
The app and installer remain unsigned. No publication is performed by this migration.
