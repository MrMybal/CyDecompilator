---
id: troubleshooting
title: Troubleshooting and result states
description: Troubleshooting
section: Settings and reference
order: 20
revision: 1
---

Open [Application log](doc:troubleshooting) and the relevant task output. Record the operation, selected input/project, engine, source revision, final state and error. Read the first actionable error as well as the final summary; later compiler messages can be consequences of an earlier missing dependency.

## Locate the failure {#locate-the-failure}

| Symptom | Next check |
|---|---|
| Application does not start | Private interpreter, matching native dependencies and launcher log |
| Engine missing | Engines page, executable path and required Java/.NET/Node version |
| No functions / partial code | Detected format, architecture, packing and unsupported instructions |
| Build fails | Compiler, references, entry point, resources and current diagnostics |
| Build succeeds but Run is refused | Fresh artifact identity, startup target and required runtime |
| Patch preparation fails | Signature/ABI, capacity, relocations, donor method and source revision |
| Debugger has no variables | Active pause/frame, symbols and optimization |
| AI request fails | Selected provider/model, existing login/key, limits and provider output |
| Scenario incomplete | Driver, selectors, deadlines, unsupported actions and capture limits |
| Menu absent | Installed application/module version and applicable workflow |
| Disk fills up | Imported/extracted resources, repeated outputs, snapshots and test copies |

## Interpret states instead of only colors {#interpret-states-instead-of-only-colors}

Queued, Preparing and Running are intermediate job states. Completed, Failed and Cancelled are terminal Runtime states. **Completed** means the handler returned: inspect its business result, which may still report a failed build, differences or unverified execution. A cancelled job can retain useful partial diagnostics without a successful result.

For reconstruction, distinguish build success from project tests and recorded scenario agreement. For console conversion, distinguish prepared, converted-unverified, executed-unverified and asserted scenario success. For patches, a valid plan precedes creation of a verified modified-copy receipt. Never promote an old successful run after its input/output hashes changed.

## Recover without losing work {#recover-without-losing-work}

Save editor buffers, stop related processes and inspect the latest source-history checkpoint. Rebuild or regenerate a plan after relevant changes. Fix missing tools before retrying; do not repeatedly run the same long scenario when no meaningful change occurred. Before clearing files, consult [storage](doc:storage). Use a small representative example to separate a general installation problem from one unsupported application.
