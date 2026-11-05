---
id: engines
title: Engines and supported inputs
description: Engine selection
section: Get started
order: 2
revision: 1
---

Open [Engines](doc:engines) to inspect component status, install an optional engine or configure an existing compatible executable. Downloads use official sources and available integrity metadata; engines stay separate from the application's private Python. Engine installation may require a network connection even though this manual does not.

## Pick an engine {#pick-an-engine}

| Input | Engine | Expected view |
|---|---|---|
| Native PE/ELF, x86/x64/ARM64 | CyDecompilator C | Structured C where supported |
| Native binaries and firmware | Ghidra, when installed | C pseudocode and richer native analysis |
| Native machine code | Built-in disassembler | Instructions, calls, imports and strings |
| Managed .NET assemblies | ILSpy | C# and source-project export |
| Java classes/JAR | Vineflower | Java sources |
| Android APK/DEX | JADX | Java and Android resources/manifest |
| Python bytecode | Python engine | Supported recovered source or bytecode view |
| DXBC, DXIL, SPIR-V shaders | Built-in shader engine | HLSL/GLSL and bytecode/instructions |
| JS/TS/HTML/ASAR application | Investigation parser | Modules, source-map and feature evidence |

The program detects input contents, not just the filename extension. A renamed executable does not become another format. Available engines appear in the Workspace selector. Selecting an engine without cached results starts its analysis; **Re-analyze** refreshes results for that engine. A different engine may recover different functions, names or pseudocode without either output being original source.

## Install or select an existing tool {#install-or-select-an-existing-tool}

1. Find the component, inspect its status and prerequisites, then choose Install when necessary.
2. For an existing Java, .NET, Ghidra or other supported tool, use its path-selection control and validate the selected executable/version.
3. Return to Workspace and start analysis. Check the task output for missing dependencies, unsupported architecture or timeouts.

Ghidra/Java, managed services, TypeScript/Node.js and console-conversion tools have separate prerequisites. Installing one does not install all the others. Compiler/debugger availability is also separate from decompiler availability.

## Format-specific limits {#format-specific-limits}

See [native analysis](doc:native) for inferred types and unsupported instructions; [.NET, Java, Python and shaders](doc:languages) for source recovery limits. Packed applications may first need extraction. Encryption, unavailable original dependencies, protected code and dynamically generated code can prevent analysis. Increase bounded analysis limits only when the report identifies a limit; a longer timeout cannot recover unavailable bytes.
