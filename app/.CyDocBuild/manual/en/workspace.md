---
id: workspace
title: Workspace: inspect and navigate
description: Analyze a file, follow functions, rename symbols and inspect executable details.
section: Analyze code
order: 3
revision: 2
---

Open [Workspace](doc:workspace) for binary inspection. An analysis project stores the input identity, engine results, annotations and source caches separately from the original application.

## Open and analyze {#open-and-analyze}

1. Press **Ctrl+O**, select a file, or paste its path into the toolbar and press Enter. Recent projects reopen previous analyses.
2. Check the detected format and architecture. Pick an available engine; install missing components through [Engines](doc:engines).
3. Wait for the analysis task. The status bar and Application log show progress and failures. Cancel a running job when needed; do not confuse partial output with a completed analysis.
4. Select a function to decompile it. Use the name/address filter to reduce the function list.

```image
{"id": "workspace-screenshot", "src": "assets/workspace.png", "alt": "A real DXBC shader analysis showing HLSL, the function list and the dedicated AI workflow controls.", "title": "A real DXBC shader analysis showing HLSL, the function list and the dedicated AI workflow controls.", "controls": "minimal", "annotations": [{"id": "function-list", "type": "rect", "x": 0.12, "y": 0.1, "toX": 0.33, "toY": 0.97, "label": "Functions and search"}]}
```


## Follow the code {#follow-the-code}

Double-click a recognized function name to navigate to it. Back and forward controls revisit the function navigation history. Right-click names for available rename/search actions. The code tabs separate decompiled output, disassembly/bytecode and AI-converted source. A converted snippet has its own verification state; it does not overwrite the original binary.

Use **Strings** and search results to locate visible messages or constants. References/calls help connect a function to callers and callees. The **Program** view displays available executable details: imports/exports, sections, protections, version/manifest information and embedded-content indicators. **Details** contains the selected function's properties and notes; on narrow windows it moves beside the code instead of occupying a permanent right pane.

## Names, notes and symbols {#names-notes-and-symbols}

Recovered names may come from exports, PDB symbols, engine inference or your annotations. Confirm the symbol identity before relying on names. Local PDB lookup and the configured symbol server use matching identifiers; a similar filename is insufficient. Rename/comment actions change the analysis annotations, not the input's machine code. Export notes or generated source when you need them outside the analysis project.

## Continue the workflow {#continue-the-workflow}

Use [Projects](doc:projects) for editable source files and build commands, [function replacement](doc:patching) to produce a modified application copy, or [Investigation](doc:investigation) to record feature evidence. AI explanations are hypotheses to check against code and execution evidence. For a packed input, inspect extraction results and open the relevant extracted executable as its own project.
