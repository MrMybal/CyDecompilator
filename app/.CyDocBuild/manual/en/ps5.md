---
id: ps5
title: PS5 input preparation and desktop conversion
description: Prepare readable inputs, configure AnyPS5/UltraPack and test converted output.
section: Console and Unreal workflows
parent: consoles
order: 15
revision: 2
---

Open [PS5 porting](doc:ps5). CyDecompilator handles preserved inputs, analysis, conversion jobs, receipts and test scenarios. Optional **AnyPS5** supplies executable conversion and console API/GPU compatibility; **UltraPack** supplies supported container extraction. These are separate backends, not an original graphics engine automatically rewritten as native PC source.

```diagram
{"type": "flow", "title": "Console input to a tested desktop output", "nodes": [{"id": "step-0", "label": "1. Preserve resources", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Select backend", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Convert or generate", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Record identities", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Asserted run", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Assess compatibility", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Preserve resources** — Inspect complete, readable input.
2. **Select backend** — Install the optional compatible tool.
3. **Convert or generate** — Review unsupported code and imports.
4. **Record identities** — Keep the output receipt and logs.
5. **Asserted run** — Test intended behavior explicitly.
6. **Assess compatibility** — Build success is not full gameplay.


## Prepare and convert {#prepare-and-convert}

1. Under Porting tools, install/configure the converter and libraries for the intended desktop OS. Configure UltraPack for supported PKG/PFS/archive inputs; building its package helper requires .NET SDK 9+.
2. Select an application file or a complete extracted folder containing its entry, modules and resources. Choose a relative entry if multiple applications are present.
3. Use **Prepare input**, inspect metadata and missing prerequisites, then **Convert for desktop**. The original stays separate. Opaque/encrypted essential executable bytes are not made available merely by importing a container.
4. Review converter diagnostics. Automatic failure analysis can connect a converter attempt to bounded C/disassembly evidence and unresolved imports. A diagnosis failure is separate from conversion failure.
5. Configure asserted scenarios and run the verified output. Inspect receipts and failures before reusing a conversion.

Standalone homebrew is an explicit mode with stricter module assumptions. Secondary root executables differ from shared PRX modules and need a capable converter. Converting the entry alone does not establish a complete application.

## Test evidence and performance {#test-evidence-and-performance}

Conversion starts as **converted-unverified**. Execution without assertions remains **executed-unverified**. Define expected stdout/exit values or other supported checks from independent intended behavior; do not copy the new output merely to make a test pass. A passing assertion covers that scenario only.

Experimental native graphics profiles replace specific compatibility paths and have their own identity/driver constraints. They do not prove complete graphics reconstruction, full gameplay or 60 FPS. Measure the same representative scene only after a meaningful change, with a bounded deadline and preserved evidence. Keep conversion disk use under review: [storage](doc:storage) explains originals, generated outputs and caches. Use [AI Port and test](doc:ai) for the same operations through an agent.
