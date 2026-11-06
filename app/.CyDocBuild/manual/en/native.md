---
id: native
title: Native code and executable details
description: Inspect PE/ELF code, references, symbols and recoverable C functions.
section: Analyze code
parent: workspace
order: 4
revision: 2
---

## What native analysis recovers {#what-native-analysis-recovers}

The built-in C engine covers supported x86, x64 and ARM64 paths in PE/ELF files. It can recover structured control flow, arithmetic, selected floating-point/SIMD operations and inferred call prototypes. The native disassembler exposes instructions even when a function cannot be reconstructed as C. Ghidra provides an optional deeper investigation path with types, instructions and high-pcode evidence.

Treat inferred types, function boundaries, calling conventions and indirect-call targets as working interpretations. Unsupported instructions or incomplete control flow are reasons to inspect disassembly and the report, not to assume the pseudocode is complete.

## Inspect one feature {#inspect-one-feature}

1. Open the executable and confirm its architecture, load layout and entry points.
2. Find a related string, import, export or known symbol in [Workspace](doc:workspace).
3. Follow callers/callees and compare recovered C with the corresponding instructions.
4. Use [Investigation](doc:investigation) for an instruction/type/value dossier when the Ghidra path is available.
5. Record the function/address, input identity, evidence and remaining unknowns before changing code.

## Export C and reconstruct {#export-c-and-reconstruct}

The Program controls can export selected native functions, exported functions, or a function and its callees as supported. Recovered globals, constants and imports are included where available. [Project IDE](doc:projects) can prepare executable, DLL or static-library targets with CMake and Windows Visual Studio project files. Missing entry points, imports, data exports, TLS initialization or resources can still block a runnable reconstruction.

Generated C that compiles is not automatically behaviorally equivalent. Check pointer widths, structure layouts, ownership, callback conventions and initialization. A leaf-function patch has stricter constraints than a full reconstructed project; see [replacement plans](doc:patching).

## Containers, packing and symbols {#containers-packing-and-symbols}

Available executable details include section entropy, overlay, embedded resources, protections, manifests and toolchain indicators. Extraction supports recognized PyInstaller, .NET single-file, UPX and appended ZIP cases. Extracted material needs its own analysis; detection does not imply successful unpacking or decryption.

Symbols can improve names, but do not recover every original type or source file. Sectionless ELF input may use validated load segments; missing symbol/relocation information still limits results. Console module identities and indirect native value dependencies may remain unresolved. Keep these gaps in the final investigation report.
