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
