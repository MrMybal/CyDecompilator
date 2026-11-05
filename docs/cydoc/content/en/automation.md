---
id: automation
title: MCP, CLI and operation reference
description: MCP and CLI
section: AI and automation
order: 14
revision: 1
---

The GUI, CLI and MCP expose the same Runtime business operations. Open [Advanced operations](doc:automation) to browse the installed operation contracts, parameter forms, declared permissions and outputs. This live catalogue is the reference for the exact installed version; do not rely on a fixed operation count in a guide or an AI prompt.

## Connect an MCP client {#connect-an-mcp-client}

Use the installation's private Python and **app/tool.py mcp** as a stdio server. Replace these example installation paths with your actual location:

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

If the desktop/another server already owns the job database, use a distinct absolute job directory with **--data-dir**, placed before **mcp** in the arguments. Analysis projects are still shared by the installation: coordinate mutations to the same project across clients. Install the bundled CyDecompilator skill using **app/scripts/install_skill.py** when your client supports skills; installing it does not configure MCP automatically.

## Discover, submit, wait, inspect {#discover-submit-wait-inspect}

Use **cy_describe_operation** before constructing parameters. Business tools are named **op_...** and use a **parameters** envelope. Control tools such as **cy_get_job** take their own arguments directly:

```json
{"tool":"op_open_file","arguments":{"parameters":{"path":"C:/samples/App.dll","engine":"ilspy"}}}
```

The returned job identifier is not the result. Poll **cy_get_job** until Completed, Failed or Cancelled, then read outputs/error. A completed job can still contain a build/test result whose status is failed or unverified. Preserve project, plan, receipt and capture IDs between dependent operations. Do not invent IDs or treat model prose as execution evidence.

## CLI and permissions {#cli-and-permissions}

The private interpreter can run **app/tool.py list-operations** and **invoke** with a parameters file and an explicit timeout. The installed contract determines which operations need network, process spawning or external filesystem permissions. A restricted client must have those permissions explicitly; never put a token in business parameters. Reading this manual or following its local links grants no execution permissions and runs no commands.

See [AI](doc:ai), [projects](doc:projects) and [observations](doc:observations) for the corresponding workflows.
