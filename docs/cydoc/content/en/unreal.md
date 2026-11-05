---
id: unreal
title: Unreal reconstruction knowledge
description: Unreal reconstruction
section: Console and Unreal workflows
order: 17
revision: 1
---

Open [Unreal reconstruction](doc:unreal) to consult the bundled methodology and campaign-profile catalogue. This page provides reconstruction knowledge and source identities. It does not automatically convert a console game into a working Unreal project or embed the Unreal Editor inside CyDecompilator.

## Use the catalogue {#use-the-catalogue}

1. Select the general methodology or an available specific profile.
2. Filter rules by category and inspect prerequisites, evidence and unresolved behavior.
3. Copy the displayed reconstruction guide when needed; it includes relevant source identities/hashes.
4. Use the corresponding Runtime/MCP rule and guide operations for an agent-driven investigation.

The catalogue covers reconstruction concerns such as geometry/UVs, materials, animation, navigation, weapons, AI, vehicles, effects and audio. Specific profiles retain their own executable identity and model assumptions. A game title alone is insufficient to establish that a profile applies to your files.

## From knowledge to a validated subsystem {#from-knowledge-to-a-validated-subsystem}

Define one observable feature, identify its input resources and functions, record the relevant original behavior, then implement and test the proposed replacement in an appropriate source project. Compare representative rendering, controls, timing and outputs. Keep unsupported behavior explicit instead of treating rules as implementation proof.

```diagram
{"type": "flow", "title": "Reconstruct with evidence", "nodes": [{"id": "step-0", "label": "1. Original behavior", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Editable project", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Resolve blockers", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Build and repair", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Replay tests", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Review result", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Original behavior** — Define a repeatable scenario.
2. **Editable project** — Recover sources and resources.
3. **Resolve blockers** — Check ABI, entries and dependencies.
4. **Build and repair** — Bound attempts; back up sources.
5. **Replay tests** — Run the intended assertions.
6. **Review result** — Separate builds from matching behavior.


## What remains separate {#what-remains-separate}

Asset import, project generation, code implementation, an Unreal installation and actual builds/execution remain separate work. The rules catalogue can be read without game files; an actual conversion needs the appropriate sources/resources and development environment. No generic PS3/PS4/PS5/Xbox-to-Unreal conversion or performance guarantee follows from rule consultation.

Use [native analysis](doc:native) and [Investigation](doc:investigation) to find evidence, [Projects](doc:projects) for source work, and [observations](doc:observations) to compare testable behavior. The catalogue's original reference snapshots are distinct from the reconstructed output's own version history.
