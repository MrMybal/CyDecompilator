---
id: start
title: Welcome to CyDecompilator
description: Choose a workflow, inspect a first input and navigate this manual.
section: Get started
order: 0
revision: 2
---

CyDecompilator inspects compiled applications, recovers code, and helps create, edit and test supported source projects. This manual is included with the application: reading it needs no internet, installed analysis engine, AI account or open project.

## Find your way {#find-your-way}

Press **F1** from any page to open its guide. Select **Documentation** in the sidebar or the Ctrl+Shift+P command palette to open the installed CyDoc reader in your browser using a local file URL. Use the global search field at the top or **Ctrl+K** to search the complete text, the section list to jump within a chapter, and the browser’s **Back** / **Forward** controls to revisit pages. Use the image enlargement control to expand it inside the reader window; scroll to zoom, drag to pan and double-click to reset. Escape reduces an enlarged view. Code blocks have a Copy button. Documentation links open another chapter; external website links open separately and are unnecessary for reading the local manual.

English is the default. The manual follows an English/French interface preference until you select its own language. Other interface languages use the English manual. Both translations contain the same chapters, illustrations and workflows.

## First useful result {#first-useful-result}

1. Read [installation](doc:installation) and open [Engines](doc:engines) to check the tool you need.
2. Open [Workspace](doc:workspace). Choose a supported file with **Ctrl+O**, or paste its path and press Enter.
3. Select an engine, wait for analysis, then select a function. Inspect the recovered source and disassembly together.
4. Use [Project IDE](doc:projects) for editable sources, [Investigation](doc:investigation) for evidence, or [AI](doc:ai) for an assisted workflow.
5. Save useful notes and source changes. Keep the original input and review the recorded errors and unknowns.

```diagram
{"type": "flow", "title": "From input to understanding", "nodes": [{"id": "step-0", "label": "1. Preserve input", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Inspect format", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Choose an engine", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Analyze", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Inspect code", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Record findings", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Preserve input** — Keep original bytes separate.
2. **Inspect format** — Confirm architecture and contents.
3. **Choose an engine** — Check its prerequisites.
4. **Analyze** — Read progress and diagnostics.
5. **Inspect code** — Compare functions and instructions.
6. **Record findings** — Keep evidence and unknowns.


```image
{"id": "workspace-screenshot", "src": "assets/workspace.png", "alt": "Workspace displaying an included DXBC vertex shader decompiled to HLSL, with function navigation and the AI panel.", "title": "Workspace displaying an included DXBC vertex shader decompiled to HLSL, with function navigation and the AI panel.", "controls": "minimal", "annotations": [{"id": "function-list", "type": "rect", "x": 0.12, "y": 0.1, "toX": 0.33, "toY": 0.97, "label": "Functions and search"}]}
```


## Choose a goal {#choose-a-goal}

| Goal | Guide |
|---|---|
| Understand a function or recover names | [Workspace](doc:workspace) and [native analysis](doc:native) |
| Rebuild an editable application | [Projects](doc:projects) and [reconstruct and validate](doc:reconstruction) |
| Change one function in an application copy | [Function replacement](doc:patching) |
| Investigate an Electron feature | [JavaScript and native investigation](doc:investigation) |
| Compare two versions, network and UI behavior | [Observed behavior](doc:observations) |
| Drive work through an AI client | [AI](doc:ai) and [MCP / CLI](doc:automation) |
| Prepare console input or consult Unreal rules | [PS5](doc:ps5), [Xbox](doc:xbox), [Unreal](doc:unreal) |

## Read results accurately {#read-results-accurately}

Recovered code is not the original source project. Compilation establishes that a toolchain accepted the generated project; it does not establish the original behavior. Matching scenarios cover only their recorded interactions and assertions. Unsupported instructions, missing dependencies, unavailable resources and untested platforms remain explicit limitations. A page absent from your installed version is unavailable in that version; updating application code does not install its optional engines.
