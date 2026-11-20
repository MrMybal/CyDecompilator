---
id: automation
title: MCP, CLI and operation reference
description: Connect an MCP client or CLI and follow the operation/job protocol.
section: AI and automation
parent: ai
order: 14
revision: 7
---

The GUI, CLI and MCP expose the same Runtime business operations. Open [Advanced operations](doc:automation) to browse the installed operation contracts, parameter forms, declared permissions and outputs. This live catalogue is the reference for the exact installed version; do not rely on a fixed operation count in a guide or an AI prompt.

## External AI through the SDK CLI {#external-ai-through-sdk-cli}

An external AI with terminal access can drive CyDecompilator without MCP, an integrated conversation or a model account inside this application. Use **--auto** to attach to the running window or work without a window when it is closed. The CLI manages the local connection and selected access profile and retains its local identity between commands.

```powershell
CyDecompilatorCLI.exe --auto list-operations
CyDecompilatorCLI.exe --auto describe-operation open_file
CyDecompilatorCLI.exe --auto invoke open_file --params-file input.json
CyDecompilatorCLI.exe --auto sdk describe
CyDecompilatorCLI.exe --auto sdk invoke open_file --params-file input.json
CyDecompilatorCLI.exe --auto jsonl
```

The **jsonl** command (also **sdk stdio**) uses the compiled SDK's native dispatch_app protocol: one request and response per line. Keep stdin open for asynchronous tasks and debugging. **invoke** returns a job; **sdk invoke** returns a domain result and _jobId. Use **jobs**, **job JOB_ID**, **wait JOB_ID --timeout 30**, **result JOB_ID --offset 0 --length 32768** and **cancel JOB_ID** with --auto to follow its durable work, including from another CLI process. An error remains an error; a wait timeout never authorizes replay. Source editing, compilation and testing use the same real business handlers. The external AI's own approval policy remains applicable.

## Connect an MCP client {#connect-an-mcp-client}

Full Windows packages provide **CyDecompilatorCLI.exe mcp** as a stdio server. Development venvs can still run their private Python with **app/tool.py mcp**. Replace these example installation paths with your actual location:

```json
{
  "mcpServers": {
    "cydecompilator": {
      "command": "C:/Tools/CyDecompilator/CyDecompilatorCLI.exe",
      "args": ["mcp"]
    }
  }
}
```

To control an already open desktop, connect to that same instance using the selected local HTTP profile as described below. A distinct absolute **--data-dir** before **mcp** creates a separate headless scheduler instead. Analysis projects remain shared by the installation: coordinate mutations across separate schedulers. Install the bundled CyDecompilator skill using **app/scripts/install_skill.py** when your client supports skills; installing it does not configure MCP automatically.

## Discover, submit, wait, inspect {#discover-submit-wait-inspect}

Use **cy_describe_operation** before constructing parameters. Native tools accept their domain arguments directly and return their result. Compatibility business tools named **op_...** use a **parameters** envelope and return a durable job. Control tools such as **cy_get_job** take their own arguments directly:

```json
{"tool":"op_open_file","arguments":{"parameters":{"path":"C:/samples/App.dll","engine":"ilspy"}}}
```

The returned job identifier is not the result. Poll **cy_get_job** until Completed, Failed or Cancelled, then read outputs/error. A completed job can still contain a build/test result whose status is failed or unverified. Preserve project, plan, receipt and capture IDs between dependent operations. Do not invent IDs or treat model prose as execution evidence.

## CLI and permissions {#cli-and-permissions}

The private interpreter can run **app/tool.py list-operations** and **invoke** with a parameters file and an explicit timeout. The installed contract determines which operations need network, process spawning or external filesystem permissions. A restricted client must have those permissions explicitly; never put a token in business parameters. Reading this manual or following its local links grants no execution permissions and runs no commands.

See [AI](doc:ai), [projects](doc:projects) and [observations](doc:observations) for the corresponding workflows.

## Connect to the open window {#connect-to-the-open-window}

**Free is the default local MCP profile.** Start **CyDecompilator.exe --mcp-port=8766** and connect your MCP client to **http://127.0.0.1:8766/mcp**. The address alone grants access to all exposed operations, including changes, without a token or additional confirmation. Argument validation remains active. The endpoint uses the same runtime, jobs and projects as the open window. Port 0 selects an available local port; copy the active address from **AI assistant settings → CyMCPSDK options and external tools**.

Choose a profile in that panel, save and restart. Existing configurations without a profile migrate to Free; explicit choices are preserved.

| Profile | Token | Operation access |
| --- | --- | --- |
| Free | None | All exposed operations without extra confirmation |
| Local controlled | None | Host permissions and confirmations |
| Token only | Required | All exposed operations without extra confirmation |
| Protected | Required | Host permissions and confirmations |

Free and Local controlled callers share a local identity. For Protected access, create a client before starting the window: **CyDecompilatorCLI.exe --data-dir D:/CyDecJobs create-client --name external --permission processSpawn --permission filesystemExternal**. Keep the returned token privately; supply it through **CYMCP_TOKEN** (legacy **CYTOOLS_TOKEN** is accepted) or an HTTP Authorization Bearer header. Never place credentials in business arguments.

For CLI access to the open window, use **CyDecompilatorCLI.exe --connect http://127.0.0.1:8766/v1 list-operations** or **invoke**. Free needs no token. The SDK server binds only to **127.0.0.1** and retains Host/Origin checks in every profile.

## Compact discovery and complete results {#compact-discovery-and-complete-results}

**mcp --compact** exposes **cy_tools_search**, **cy_tools_describe**, **cy_tools_call**, **cy_resources_read** and **cy_resources_grep**. Search by intent, read the complete schema and invoke with its validated arguments. **mcp --full** exposes all direct operations and compatibility job tools; full discovery remains the stdio default for existing clients. The integrated chat uses compact discovery independently.

Large transient results are private resource references. Read their manifest and follow chunk URIs while retention lasts. An expired reference reports an error and never replays a mutation. Durable job JSON survives restart and SDK retention: **cy_read_result** takes jobId, offset and length (up to 65536 bytes), returning base64 bytes, total size and nextOffset. Preserve stopped file outputs with **cy_export_job** before finishing a temporary task. **cy_finish_task** removes task files after workers stop, while durable job records remain.

The **cydec://operations** resource exposes the catalogue. Native resource grep searches registered text without traversing a disk. Optional **workspace_grep_native** and **workspace_read_native** require the host to enable ripgrep and choose an explicit workspaceRoot. They provide bounded cursors/ranges and revision checks; no search root is inferred from a prompt.

## Configure independent options {#configure-independent-options}

Open **AI assistant settings → CyMCPSDK options and external tools**. Compact discovery, cache, TTL, notifications, disk spooling/directory/quota/retention, chunk size, inline size, metadata-only measurements and API context projection are independent. Save and restart. Defaults use 32 KiB chunks, 16 KiB inline results, 16 MiB transient memory, 128 MiB transient disk and 15-minute retention. Set **spoolRoot** to an absolute directory to choose its disk independently; empty keeps it under the job root. These limits do not delete durable job outputs. Measurements are disabled by default and exclude messages, tool results and credentials. Host-history APIs use a configurable projection while retaining full histories; native CLI agents manage their own context.

## Connect another application {#connect-another-application}

Only user-configured servers and explicitly approved tool names are available to the integrated chat. A server configuration contains an executable plus structured arguments, or an HTTPS URL (HTTP only on loopback), and an **allowedTools** array. Keep credentials in the vault under **mcp:server-id**, not JSON. **remote_tools** returns approved schemas; **remote_call** invokes the real remote tool and preserves business errors. **remote_resources** reads explicitly approved URIs or resources referenced by an approved tool, and can watch/drain notifications on supported transports. The SDK follows pagination and invalidates compatible cached reads from change notifications. A missing/expired resource never authorizes repeating the original action.

Controlled profiles and independent standalone CLI identities require **--confirm** for destructive actions and enforce declared permissions. Free and Token only HTTP access do not add those confirmations. The integrated assistant excludes account settings, application updates and destructive actions. Consult the installed schema before each unfamiliar operation.
