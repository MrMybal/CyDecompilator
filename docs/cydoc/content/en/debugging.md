---
id: debugging
title: Debug reconstructed .NET sources
description: .NET debugging
section: Edit and rebuild
order: 10
revision: 1
---

The integrated debugger uses NetCoreDbg for supported .NET projects and modified managed copies. It is not a general native/Java/Python debugger. Debugging requires a runnable compatible output, matching source files and usable symbols, usually portable PDBs.

## Start a session {#start-a-session}

1. Install/configure the debugger from its offered component control.
2. Open the source project, save changes, build the desired configuration and select its startup target.
3. Open the relevant source file and place a breakpoint. Unsaved files must be saved first.
4. Start debugging the project, or use **Debug modified copy** for a verified saved managed patch.
5. Read **Debugger** status. A requested breakpoint may remain unverified until matching symbols are loaded.

## Pause and inspect {#pause-and-inspect}

When paused, use **Stack and variables** to select a thread/frame and inspect available locals. Add watches and evaluate supported expressions in the selected context. Continue/Pause, Step over, Step into and Step out control execution. F5 continues a paused active session; F9 toggles a breakpoint in the focused source editor. Use the visible controls when focus is elsewhere.

Debugger values and pause handles belong to the active session. Do not reuse them after continuing, restarting or stopping. A failed watch can mean an unavailable variable, invalid expression, optimized code or a stale frame rather than a target crash.

## Keep source correspondence {#keep-source-correspondence}

Source files become read-only during debugging. If they change externally, stop, rebuild and restart before trusting line correspondence. The debugger is a job-owned process: **Stop debugging** ends the session, and cancellation handles its process tree. An exit code is recorded separately from breakpoint/inspection success.

## Diagnose common failures {#diagnose-common-failures}

| Symptom | Check |
|---|---|
| No runnable target | Startup project, executable output and matching .NET runtime |
| Breakpoint not bound | PDB identity, source revision and optimization |
| Wrong source location | Rebuild after changes; confirm the selected module |
| Variables unavailable | Selected frame, scope, optimized code and pause state |
| Copy no longer accepted | Patch receipt integrity and fresh build/plan |

See [projects](doc:projects), [method replacement](doc:patching) and [troubleshooting](doc:troubleshooting).
