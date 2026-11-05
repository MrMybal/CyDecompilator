---
id: xbox
title: Xbox preparation and native projects
description: Xbox porting
section: Console and Unreal workflows
order: 16
revision: 1
---

The **Xbox porting** workflow is available only in installations containing that module. It handles XBE/XEX, extracted folders and supported XDVDFS ISO/ZIP inputs. Original Xbox input currently supports inspection/preparation, not a general native recompiler. Xbox 360 uses the separately installed **ReXGlue** SDK for supported PowerPC-to-C++ reconstruction.

## Create a project {#create-a-project}

1. Open [Xbox porting](doc:xbox) when present. Prepare a complete folder or supported disc image; importing a bare executable does not import all sibling game resources.
2. Select the intended entry and inspect input metadata.
3. Install/configure the optional ReXGlue SDK. Native Windows x64 builds need CMake, Ninja, Visual Studio C++ tools, Clang and the Windows SDK.
4. Create/build the native project, then inspect generation and compiler output. **Edit native sources** attaches the generated sources to Project IDE.
5. Launch the output explicitly and inspect its job log. The launcher verifies the relevant executable identities; compilation alone leaves game compatibility unverified.

```diagram
{"type": "flow", "title": "Console input to a tested desktop output", "nodes": [{"id": "step-0", "label": "1. Preserve resources", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Select backend", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Convert or generate", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Record identities", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Asserted run", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Assess compatibility", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Preserve resources** — Inspect complete, readable input.
2. **Select backend** — Install the optional compatible tool.
3. **Convert or generate** — Review unsupported code and imports.
4. **Record identities** — Keep the output receipt and logs.
5. **Asserted run** — Test intended behavior explicitly.
6. **Assess compatibility** — Build success is not full gameplay.


## Existing native projects {#existing-native-projects}

Register an existing native project without assuming its assets have been copied into CyDecompilator. It still depends on its original folder. Launching creates a job-owned process; cancellation stops that process tree. Saves/cache belong to the native project's own data location. Saved display settings can override requested fullscreen/window settings.

## Compatibility and experimental profiles {#compatibility-and-experimental-profiles}

Game-specific overlays require the exact supported guest identity. Timing, frame rate, animation interpolation, UI/input routing, occlusion and rendering need separate checks. A compatible profile for one executable revision must not be applied to another by filename alone. Graphics backends and compatibility runtimes still provide console behavior; a generated C++ project is not a recovered original source engine.

Experimental ray tracing, campaign networking or split-screen profiles do not establish general compatibility. Direct-IP and competitive networking are not interchangeable, and unsupported multiplayer paths remain unavailable. Consult the module's **methods and pitfalls** guide when present. If the page is absent, your application version does not include this module; the manual does not install it.
