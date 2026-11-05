---
id: reconstruction
title: Reconstruct, compile and validate
description: Reconstruct and validate
section: Edit and rebuild
order: 7
revision: 1
---

In **Project IDE → Reconstruction**, **Reconstruct and validate** chains workspace creation, builds, optional source repair and recorded behavior comparisons. Define the intended behavior before enabling automatic attempts. A missing entry point, unsupported dependency or unavailable original cannot be solved by increasing the retry count alone.

```diagram
{"type": "flow", "title": "Reconstruct with evidence", "nodes": [{"id": "step-0", "label": "1. Original behavior", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Editable project", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Resolve blockers", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Build and repair", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Replay tests", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Review result", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Original behavior** — Define a repeatable scenario.
2. **Editable project** — Recover sources and resources.
3. **Resolve blockers** — Check ABI, entries and dependencies.
4. **Build and repair** — Bound attempts; back up sources.
5. **Replay tests** — Run the intended assertions.
6. **Review result** — Separate builds from matching behavior.


## Prepare the run {#prepare-the-run}

1. Open/analyze the input and review the [project target](doc:projects).
2. Configure the compiler/runtime, references and startup target. Save all open files.
3. Configure test scenarios with expected behavior and the original/reconstructed launch commands. **Use investigation scenario** imports the current observation configuration.
4. Choose a bounded number of build attempts. Automatic AI repairs require a configured provider and Git; the first build counts toward the limit.
5. Start reconstruction. Sources are protected from concurrent editing while the workflow updates them. Cancel through the task controls if necessary.

Repairs are source changes with revision checks and Git backups. An outdated response or an external source modification interrupts application of the repair. AI text is not treated as an arbitrary terminal command.

## Interpret the final state {#interpret-the-final-state}

| Result | Meaning |
|---|---|
| Build failed / reconstruction blocked | Read diagnostics and unresolved prerequisites |
| Built; behavior unverified | A fresh build exists; sufficient execution evidence does not |
| Project tests failed | The project's requested tests failed |
| Behavior differs | At least one enabled comparison criterion differs |
| Recorded scenarios match | Enabled assertions agree for the recorded scenarios only |

Use **Inspect recorded comparison** to examine saved evidence in Investigation. Reports retain attempts, changes, source commits, diagnostics and capture identities. Libraries need an appropriate test executable. A GUI scenario must cover the interaction of interest; a launch-only check cannot validate a feature.

## Web and Electron projects {#web-and-electron-projects}

The workspace configuration records kind, entry, build script and output directory. A configured npm build/test script runs when requested; locked dependency installation uses its separate explicit action. Native modules still require a matching runtime/ABI. A generated ASAR is not a signed installer. Rebuild after source or artifact changes. Missing servers, remote APIs, credentials and external resources are not reconstructed automatically.

Continue with [observed behavior](doc:observations), [AI workflows](doc:ai) and [troubleshooting](doc:troubleshooting).
