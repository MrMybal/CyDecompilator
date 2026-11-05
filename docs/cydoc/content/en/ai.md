---
id: ai
title: AI assistance and autonomous workflows
description: AI workflows
section: AI and automation
order: 13
revision: 1
---

Open [AI assistant settings](doc:ai) to configure a supported signed-in CLI or HTTP provider, model and limits. A CLI connection uses its existing account; an HTTP provider may require its own key and billing. Keys belong in the application's credential mechanism, never source files, scenario JSON, screenshots or job parameters. Local providers still need their own running service/model.

## Choose an interaction mode {#choose-an-interaction-mode}

| Mode | Use |
|---|---|
| Autonomous workflow | Investigate, reconstruct, patch or port/test through tool operations |
| Conversation | Ask about a program; review tool use and the answer |
| Function | Explain, suggest names or convert the selected function |

The Workspace side panel and dedicated [AI page](doc:ai) expose these modes. Select a project/function before a focused action. Conversion produces editable source with a separate compiler-check state; it does not by itself patch the executable.

```diagram
{"type": "flow", "title": "An autonomous task still needs proof", "nodes": [{"id": "step-0", "label": "1. Define the task", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Inspect evidence", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Plan bounded work", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Back up and edit", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Build and verify", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Report or resume", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Define the task** — Specify scope and expected behavior.
2. **Inspect evidence** — Discover tools and prerequisites.
3. **Plan bounded work** — Keep steps and retries finite.
4. **Back up and edit** — Check source revisions and history.
5. **Build and verify** — Require actual recorded results.
6. **Report or resume** — Retain checkpoints and unknowns.


## Give a testable task {#give-a-testable-task}

Describe the target, intended change, permitted source scope, required output and a concrete acceptance scenario. For example: explain a selected export routine, reconstruct its project, change the output format, build it and compare a specified input/output case. Configure bounded tool steps, repair attempts and token limits rather than asking for unlimited retries.

The agent discovers Runtime operations, records checkpoints, creates source-history backups and inspects errors. Saved source buffers are protected while it changes the project. Progress and resumable status are available through the agent status operation. Provider failures, cancellation, missing tools and stale source revisions can interrupt the run; inspect the last checkpoint before resuming.

## Verify the result {#verify-the-result}

Read changes, compilation output, source commits, modified-copy receipts and recorded scenarios. Completion of a workflow requires its validation evidence, not just a confident response. A successful model request is distinct from a successful build, test or equivalent application. No AI provider can recover missing encrypted bytes or guarantee every game/application will rebuild.

For external clients, see [MCP / CLI](doc:automation). For automatic repair behavior, see [reconstruction](doc:reconstruction); for function changes, see [replacement](doc:patching).
