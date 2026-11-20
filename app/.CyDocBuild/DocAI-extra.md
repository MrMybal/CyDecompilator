## CyDecompilator agent entry points

Use the application's MCP server (`app/tool.py mcp`) and its installed operation
schemas. Discover each operation before submitting parameters. A returned job ID
is not a completed result: wait for the terminal job state and inspect outputs.
Use revision guards for source writes and retain project/plan/receipt identities.
Never infer behavioral equivalence from a successful build or a model answer.

The full agent skill is shipped in `app/skills/cydecompilator/SKILL.md`; its
`references/` directory explains analysis, reconstruction, patching, debugging and
task completion. Those instructions are deliberately outside the human reader.
The human manual is `Documentation.html`; the native help adapter is
`app/documentation.py`. English is the default, French is fully translated.

Installation-specific paths, user projects and credentials do not belong in this
sidecar. The operation contracts below are declarative API data, not permission
to execute an operation or install a component.

## Native SDK discovery

The runtime uses CyMCPSDK 0.7.2. Full discovery retains op_<operation> asynchronous jobs and adds direct business tools. Compact discovery exposes cy_tools_search, cy_tools_describe and cy_tools_call; complete schemas remain accessible. Native resources and chunk reads preserve private large results. Expiration must never cause an action to be repeated; use durable job results through cy_read_result. For an open GUI use its loopback /mcp endpoint (Free by default, address only; explicit controlled/token profiles are preserved) rather than starting another scheduler on the same database. The CLI preserves its commands and supports --connect for /v1. SDK business chat, external allowlists and independent options are documented in the human automation/AI chapters.


## External CLI agents

An external AI can use CyDecompilatorCLI.exe --auto directly, without MCP or a model configured inside the app. SDK describe/invoke and jsonl call the native dispatch_app registry. Preserve existing authorization and complete the requested business workflow autonomously. Read app/skills/cydecompilator/references/cli.md for native JSONL, stable ownership, job controls and process lifetime. Never replace a wait timeout with a mutation replay.
