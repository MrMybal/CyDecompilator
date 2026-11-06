---
id: languages
title: .NET, Java, Python and shaders
description: Understand the supported .NET, Java, Android, Python and shader workflows.
section: Analyze code
parent: workspace
order: 5
revision: 2
---

## Managed .NET {#managed-net}

Use ILSpy to inspect C# and recover a source project with available references/resources. A .NET SDK is needed to build; targeting packs and original dependencies may also be necessary. Recovered names and control flow can differ from original source, especially after obfuscation. A .NET single-file host may need extraction before selecting the managed assembly.

For source editing, diagnostics, completion and formatting, attach the recovered project in [Project IDE](doc:projects). Source-method replacement and debugging have their own requirements; see [patching](doc:patching) and [debugging](doc:debugging). Generated state-machine/helper methods should be edited through their owning source method rather than selected as independent replacement targets.

## Java and Android {#java-and-android}

Vineflower handles Java classes/JARs; JADX handles Android DEX/APK and supported Java inputs. Install their required Java runtime in [Engines](doc:engines). Check decompiler warnings and resource output. Recovered Java is useful for understanding, but a complete Android build may still need the original Gradle setup, SDK, signing configuration, assets and dependencies. There is no general one-click Android rebuild guarantee.

## Python bytecode {#python-bytecode}

The Python engine uses format-aware bytecode tools. Source recovery covers supported bytecode versions through Python 3.8; newer versions can still have bytecode views without original-source reconstruction. The application runtime's Python version does not change the version of the input bytecode. PyInstaller extraction can expose bundled files, which can then be opened individually. Missing modules, native extensions and runtime resources still need reconstruction separately.

## GPU shaders {#gpu-shaders}

The built-in shader engine handles supported DXBC SM4/5, DXIL SM6 and SPIR-V inputs. It produces HLSL/GLSL or instruction/bytecode views according to the format and available information. Compare register/resource bindings, entry points and control flow with the original shader evidence.

```image
{"id": "workspace-screenshot", "src": "assets/workspace.png", "alt": "Included DXBC sample reconstructed as HLSL in Workspace.", "title": "Included DXBC sample reconstructed as HLSL in Workspace.", "controls": "minimal", "annotations": [{"id": "function-list", "type": "rect", "x": 0.12, "y": 0.1, "toX": 0.33, "toY": 0.97, "label": "Functions and search"}]}
```


Compilation checks require the appropriate verifier/compiler and are reported separately from decompilation. A successful shader compile does not prove identical images, pipeline state, resource layouts or GPU performance. Use [observed behavior](doc:observations) and the real rendering scenario when validating graphics changes. A shader decompiler is not a complete graphics-engine source converter.
