# Finish an autonomous task

The user's requested outcome determines completion. For reconstruct-and-test work,
an exported project is an intermediate artifact. Continue through build diagnostics,
source repairs, executable output and representative comparisons. Choose defaults
from the actual format, architecture, available engines and supplied scenarios.
Use the existing authorization without asking again at each intermediate operation.

## Drive the operations yourself

1. Open the original. For a missing binary engine, `open_file analyze=false`
   preserves the project so you can inspect format and component availability first.
   JS/TS/Electron uses `application_open` and its parser component.
2. Discover the needed operations and component status. Install missing official
   components needed by the authorized task; preserve user-selected versions/runtime
   overrides and compatible Electron native-module ABI. Do not change the host's
   provider/account settings or install unrelated software.
3. Analyze and gather source/evidence. Reconstruct or attach a separate workspace.
   Save a Git snapshot, read source revisions, make real implementation changes,
   compile and inspect errors. Correct errors and repeat within a finite budget.
4. Replay representative scenarios against original and rebuilt applications,
   including arguments, finite input, files, network and UI when relevant.
   Build a harness for a library if needed. Do not omit a requested check simply
   to obtain a match. For a deliberate patch, assert the requested changed behavior
   and test unaffected behavior instead of expecting every output to match.
5. Finish with actual artifacts, run/capture IDs, test results and concrete limits.
   If blocked, save the partial project, diagnostics and the precise missing fact.

If MCP is unavailable but the local installation is accessible, the same operations
can be executed through its CLI. Write a JSON parameter file, then invoke the
installation's private Python with `app/tool.py --data-dir <separate-jobs-directory>
invoke <operationId> --params-file <absolute-json-path> --timeout <seconds>`.
Read the job's terminal state and domain result. Do not wait for the user to connect
MCP when this authorized local route can complete the task. CLI invocation of a
long-running `debug_start` needs concurrent controls; prefer MCP for debugging.

## Delegate to the integrated application agent

Use `ai_agent` when the task calls for CyDecompilator's configured AI provider.
An external AI can also complete the task directly with MCP; another provider is
not necessary for direct source edits. Describe `ai_agent` before submitting:

```json
{"parameters":{"projectId":"<id>","objective":"Reconstruct, fix compiler errors and compare the supplied export scenario.","workflow":"reconstruct","maxSteps":60,"allowInstall":true}}
```

Workflows: `investigate` reads/analyzes the selected project; `reconstruct` adds
source edits, builds, debugging and captures; `patch` additionally prepares/applies
separate native/.NET copies and validates them. The agent does not administer
accounts, update the running app, delete projects or switch to unrelated projects.
Those tasks remain available through their explicit MCP operations when requested.

`ai_agent` uses authenticated scheduler jobs and current schemas. It cannot grant
itself permissions, run arbitrary shell commands from a model response or recursively
launch another AI loop. Ordinary child calls wait automatically; debugger owning
jobs run concurrently with controls. Cancellation stops all children before exit.

Poll its owning job and `ai_agent_status`. Reports contain `runId`, decisions,
child jobs, results and server-checked validation. Status meanings:

- `completed`: recorded proof satisfies this workflow. Reconstruction requires
  matching complete scenarios and unchanged source revisions. A patch requires
  a verified-copy run or completed harness captures/comparison, plus copy integrity.
  The agent's prose alone is never completion evidence.
- `budget-exhausted`: preserve and resume the checkpoint with the same objective
  and workflow and an appropriate remaining budget. Resume when the user's existing
  request and budget authorize continued work; do not silently start unlimited loops.
- `blocked`: inspect the evidence, resolve a recoverable prerequisite yourself and
  resume. Ask the user only for a genuinely missing credential, license, scenario
  expectation or other required fact.
- `cancelled` / `failed`: retrieve status, confirm child cleanup, and decide whether
  the cause permits a retry. A restart can resume an interrupted checkpoint after
  its previous owning job is no longer active in the same Runtime.

Never equate finite successful scenarios with universal program equivalence.
