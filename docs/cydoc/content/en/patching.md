---
id: patching
title: Replace a function in an application copy
description: Replace a function
section: Edit and rebuild
order: 9
revision: 1
---

The **Function patch** page produces a modified copy after compiling and checking a replacement. It does not edit arbitrary functions in place while an application is running. Keep the original, source version and patch receipt together so a result remains traceable.

```diagram
{"type": "flow", "title": "Change one function", "nodes": [{"id": "step-0", "label": "1. Select target", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Edit source", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Compile a plan", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Review warnings", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Create a copy", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Validate behavior", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Select target** — Confirm method and input identity.
2. **Edit source** — Preserve the external contract.
3. **Compile a plan** — Check code and required bindings.
4. **Review warnings** — Inspect size, IL or relocations.
5. **Create a copy** — Retain original and receipt.
6. **Validate behavior** — Test the requested change.


## Native x86/x64 Windows PE {#native-x86-x64-windows-pe}

1. Select the function in Workspace, then open **Project IDE → Function patch → Edit selected function**.
2. Preserve its signature, calling convention, pointer sizes and observable contract. Start with an autonomous supported C function.
3. Choose the replacement symbol and use **Compile and verify patch**. Review compiled instructions, byte capacity, warnings and bindings.
4. For supported larger functions, the extended linking option can append a native section and redirect the original entry. Calls, data, relocations and unwind information need valid bindings; this is not an unrestricted native linker.
5. Choose **Write modified copy** only for a current valid plan. Then analyze/run the saved copy and compare the intended behavior.

Unsupported architectures/formats, entry sizes, unresolved symbols and unsafe relocations can block a plan. C pseudocode that compiles in isolation is not sufficient proof of a compatible replacement.

## Managed .NET method {#managed-net-method}

1. Create/attach the C# source project and choose **Load .NET methods**.
2. Select an editable source method, then **Edit declaring type**. Change its source and save.
3. Use **Build and verify method patch**. The donor assembly must correspond to the selected project/method.
4. Review IL changes, generated dependencies and verification of other methods before writing the modified copy.
5. Run or debug the saved copy with matching symbols and a defined scenario.

Supported compiler-generated dependencies can be imported with the owning method; they are not separate free-form targets. Strong-name removal is an explicit option and can break dependencies. Signing requirements are not automatically repaired.

## After creation {#after-creation}

**Saved modified copies** retains receipts and source commits where available. **Analyze modified copy** reopens it for inspection. **Run modified copy** needs valid arguments and a timeout; a library needs a test harness. New source edits require saving and preparing a fresh plan. Do not reuse a receipt after changing its binary or dependencies. See [debugging](doc:debugging), [history](doc:history) and [validation](doc:observations).
