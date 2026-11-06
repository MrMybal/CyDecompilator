---
id: shortcuts
title: Shortcuts, glossary and reference map
description: Find keyboard controls, workflow terms and the matching help page.
section: Settings and reference
parent: settings
order: 21
revision: 2
---

## Keyboard and mouse {#keyboard-and-mouse}

| Control | Context | Action |
|---|---|---|
| F1 | Application page | Open its documentation chapter |
| Ctrl+K | CyDoc reader | Search the local documentation |
| Ctrl+Shift+P | Application | Open/close the command palette |
| Ctrl+O | Application | Choose an input file |
| Double-click function name | Recognized source symbol | Navigate to that function |
| Right-click source name | Workspace | Available name/search actions |
| F5 | Active paused .NET debugger | Continue |
| F9 | Focused source editor with .NET debugging | Toggle breakpoint |
| Mouse wheel | Enlarged manual/capture image | Zoom around pointer |
| Drag | Enlarged image | Pan |
| Double-click | Enlarged image | Fit to viewport |
| Escape | Enlarged manual image | Close the image |

Editor text shortcuts apply when that editor has focus; available commands depend on the current widget and workflow. Use visible buttons if keyboard focus belongs to a different control. Documentation Back/Forward is distinct from Workspace function navigation and source-editor Undo/Redo.

## Terms used in reports {#terms-used-in-reports}

| Term | Meaning |
|---|---|
| Analysis project | Persistent identity/results/annotations for an imported input |
| Source workspace | Editable files attached to or generated for that project |
| Engine | Decompiler, parser, converter or other separately selected backend |
| Runtime job | Scheduled operation with progress, cancellation, outputs/error |
| Plan | Checked proposed replacement before writing a copy |
| Receipt | Identity-bound record of a created conversion/modified copy |
| Scenario | Defined inputs, actions, checks and deadlines |
| Evidence | Recorded output tied to target identities and observed steps |
| Unverified | Required behavior evidence has not been established |
| Blocker | Missing prerequisite or unsupported case preventing the requested result |

## Reference map {#reference-map}

Use [Advanced operations](doc:automation) for the installed operation/parameter reference, [Engines](doc:engines) for format selection, [storage](doc:storage) for persistent data, and [troubleshooting](doc:troubleshooting) for failures. [Reconstruction](doc:reconstruction), [patching](doc:patching) and [observations](doc:observations) explain what their validation states mean. Use the [operation API](doc:operation-api) for public parameters and results, and the [native help-link API](doc:help-api) to open a precise chapter from Python.
