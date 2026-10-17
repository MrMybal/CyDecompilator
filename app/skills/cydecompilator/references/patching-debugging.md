# Replace a function and debug a copy

## Native x86/x64 PE

List/decompile the selected function and inspect its ABI and dependencies. Call
`patch_prepare` with the original function ID, replacement C `source` and its
`symbol`. Review its disassembly, capacity, imports/bindings and assumptions.
Default mode is a bounded leaf replacement. `extended=true` supports appended
linked code/data, original-function/IAT bindings, relocation and x64 unwind data;
it still requires supported PE architecture and valid call signatures.

Apply the returned `planId` with `patch_apply` to a new separate copy. Original and
existing-output protection is enforced. Retain `receiptId`, output path, hash and
warnings. Native libraries need a harness calling their exports; do not load the
target DLL into the Tool process. Compare original and modified outputs for cases
that both exercise the intended change and preserve unaffected behavior.

## Managed .NET IL

1. Reconstruct/attach a matching C# workspace. Use `managed_methods` to find an
   editable method token; type names from `list_functions` are not method tokens.
2. Read/save the selected source with revisions and compile it. Choose
   `targetProject`/relative `donor` if multiple outputs match.
3. Use `managed_patch_prepare methodId=...`. It builds by default and imports
   the selected IL method while checking unchanged existing bodies/tokens.
4. Review generated closures/async dependencies, new members, strong-name effect
   and source/output hashes. `allowNewMembers=true` permits reachable new members
   where compatible; existing initialization/layout changes require a full rebuild.
   Enable `symbols=true` when debugging the modified copy. Removing a strong name
   is a separate explicit option; do not silently enable it to make a plan succeed.
5. Apply the reviewed `planId` to a new output; test using `patch_run receiptId=...`
   and appropriate arguments. `patch_outputs` lists receipts and last run. Run
   verifies the copy and companions; stale sources/candidates need a new plan.

Mixed-mode/ReadyToRun images and incompatible signatures are explicit blockers.
Assembly/authenticode signing and redistribution are separate from patch success.

## .NET source debugger

`debug_start` owns a long-running asynchronous job. Submit it and retain `jobId`;
**do not wait for that job to finish before issuing debugger commands.**

Set `debug_breakpoints` with workspace-relative paths and one-based lines, or
use `stopAtEntry=true`. A rebuilt workspace needs portable PDBs and NetCoreDbg.
To debug a modified assembly pass its verified `receiptId` prepared with symbols;
the server checks matching sources/copy/PDB and preserves the original Main.

Poll `debug_status` while the launch job is running. On `paused`, obtain fresh
`sessionId` and `stopId`; use `debug_control action=inspect` for frames and locals.
Use current variable references for expansion and current pause handles for
`next`, `stepIn`, `stepOut` or `continue`. References from a previous pause or
session must not be reused. To stop, use `debug_control action=stop` or cancel the
owning job. Poll the owning job to its terminal state so adapter/child cleanup is
confirmed. Inspect debugger status/output when launch fails.

Native debugging, .NET Framework attach and hot reload are not implied by this
.NET source debugger. Check the actual server's capability before promising them.
