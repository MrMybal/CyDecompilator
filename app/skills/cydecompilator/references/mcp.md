# MCP contract and connection

Connect a stdio MCP client to the installation's private Python and `app/tool.py`:

```json
{
  "mcpServers": {
    "cydecompilator": {
      "command": "C:/Tools/CyDecompilator/runtime/python/Scripts/python.exe",
      "args": ["C:/Tools/CyDecompilator/app/tool.py", "mcp"]
    }
  }
}
```

Adapt the installation path and the client's outer configuration format. For a
Linux installation use its Python executable. Do not start a second server with
the same jobs database as a running desktop/server instance; choose a separate
`--data-dir` before `mcp` if that database is already owned.

If the tools are absent, use the authorized local CLI fallback described in
[autonomous completion](autonomy.md) when the installation is accessible. Provide
the launch configuration if a client connection is still needed. Installing this
skill supplies instructions; it does not connect an MCP server. Do not invent calls
or claim a completed operation without a result.

## Calls and jobs

Business calls have a `parameters` envelope:

```json
{"tool":"op_open_file","arguments":{"parameters":{"path":"C:/samples/app.dll","engine":"ilspy"}}}
```

Controls have no envelope:

```json
{"tool":"cy_describe_operation","arguments":{"operationId":"workspace_create"}}
{"tool":"cy_get_job","arguments":{"jobId":"<returned-job-id>"}}
```

1. Discover tools. Describe the operation and inspect permissions/dependencies
   (`cy_status`, `cy_can_run`, component operations) if needed.
2. Submit `op_*`, retain its `jobId`, and poll `cy_get_job` with a bounded deadline
   and a reasonable interval (for example 0.2 to 1 second).
3. Stop polling at `Completed`, `Failed` or `Cancelled`. Read `error` for failure;
   read `outputs` only for completed jobs. An MCP `isError=false` response may
   contain a failed job. A completed build/capture may itself report failure.
4. Check domain results: build `status`/`exitCode`/diagnostics, scenario completion,
   and reconstruction status. Do not blindly retry a failing compile or extend a
   repair budget indefinitely. Inspect the cause and change an input first.
5. Cancel an unwanted owning job using `cy_cancel_job`. Debug sessions are a
   special long-running owning job; operate them while that job is still running.

Use returned IDs and paths, never manufactured ones. Current server contracts are
authoritative, including resource controls and any additional installation tools.

## Inputs and lifetime

`open_file` accepts an absolute local input and stages an immutable task copy
automatically. `application_open` snapshots a folder, ASAR or JS/TS/HTML artifact.
Use workspace-relative names for source edits, functions/method IDs from listings,
and absolute executable paths for behavior capture. Relative input files, when
accepted, are relative to the configured input root, not the shell directory.

`cy_import_file` explicitly stages a bundle and optional relative `companions`.
For ordinary .NET files prefer the original absolute DLL path so reconstruction
can resolve dependencies in its original folder. Imported bundles need the relevant
dependencies included and must be consumed before their task expires.

MCP task files are temporary. Export wanted job artifacts with `cy_export_job`
before `cy_finish_task`; keep a task alive while another consumer uses its files.
`cy_finish_task cancelRunning=true` stops owned work before cleanup. Decompilation
projects, source workspaces, patch receipts and private Git history are persistent
application data; task cleanup does not delete them. Use `op_delete_project` only
when project deletion is requested. Separate explicit output destinations survive
task cleanup too.

Never disclose authentication tokens or add them to the example configuration.
The local server provides its standalone identity; a configured restricted token
may intentionally disallow process spawning, downloads or external AI calls.
