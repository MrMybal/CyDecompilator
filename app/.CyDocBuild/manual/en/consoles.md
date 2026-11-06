---
id: consoles
title: Console inputs and native projects
description: Choose a console workflow and understand its prerequisites and limits.
section: Console workflows
order: 15
revision: 2
---

Start with complete, readable files that you can analyze. Keep the original separate
from generated projects and converted executables.

## Choose a workflow {#choose-a-workflow}

| Input or objective | Open | What it does |
|---|---|---|
| PS5 ELF, plaintext SELF, extracted application or supported container | [PS5 porting](doc:ps5) | Prepare input, configure AnyPS5/UltraPack, convert and run explicit scenarios |
| Xbox XBE, Xbox 360 XEX, extracted game or XDVDFS image | [Xbox porting](doc:xbox) | Prepare input; generate, compile or attach supported Xbox 360 native projects |
| Rebuild an understood subsystem in Unreal | [Unreal reconstruction](doc:unreal) | Consult rules and profiles, then implement and compare a specific feature |

These workflows do not supply a universal console-to-PC or console-to-Unreal port.
Original Xbox native recompilation and general PS3/PS4 conversion are not available
through these controls. A native analysis engine can inspect a readable executable
without making its operating-system or graphics interfaces compatible with the PC.

## Keep work manageable {#keep-work-manageable}

Check free space before importing a whole game. A preserved input, converted output,
native source tree and compiler cache occupy separate storage. Use an existing native
project attachment when you already have a suitable build; do not repeat an import
just to reopen it. See [storage](doc:storage) and the [Xbox methods](doc:xbox-methods).
