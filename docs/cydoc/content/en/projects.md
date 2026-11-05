---
id: projects
title: Editable source projects
description: Editable projects
section: Edit and rebuild
order: 6
revision: 1
---

Open [Project IDE](doc:projects) after selecting an analysis project. **Create source project** creates a supported editable workspace; opening/attaching an existing source folder is a separate action. An attached folder remains persistent user source: it must not be treated as a temporary job directory.

## Supported reconstruction targets {#supported-reconstruction-targets}

| Family | Produced project | Remaining requirements |
|---|---|---|
| .NET | ILSpy C#, resources, solution/project files | SDK, references, startup project and target framework |
| Native Windows PE | C, CMake, VC++ solution/project; EXE, DLL or static target | C++ toolchain, recovered entry/imports/resources |
| Native ELF | C sources and CMake target | Compatible host/toolchain, ABI and missing initialization |
| Node/TS/web | Recovered sources/resources and build configuration | Node.js, required dependencies and entry points |
| Electron | main/preload/renderer sources, ASAR-capable output | Matching Electron runtime and native-module ABI |

These targets are reconstruction paths, not a promise to recreate every application. Check reported blockers before assuming the output can run.

## Edit and build {#edit-and-build}

1. Create or attach the workspace and inspect the solution/file tree.
2. Select a file to open it. Source editing supports the retained native editor, undo/redo and the services available for its language.
3. Save changes before building. Choose the intended configuration and startup target for multi-project solutions.
4. Use Build/Rebuild/Clean as available. Review both **Build output** and **Problems**. Click a navigable diagnostic to open its source location.
5. Run or debug a newly validated output; stale or changed artifacts may require a new build.

```image
{"id": "project-ide-screenshot", "src": "assets/project-ide.png", "alt": "Project IDE displaying an example CMake project and editable C++ source. This illustration does not claim a successful build.", "title": "Project IDE displaying an example CMake project and editable C++ source. This illustration does not claim a successful build.", "controls": "minimal"}
```


## Source services and limits {#source-services-and-limits}

The C# assistance panel provides diagnostics and supported symbol operations using local SDK services. Completions and refactoring previews depend on references and project state. Review a rename/format preview before applying it. External edits and stale source revisions can cause an operation to be refused instead of overwriting newer text.

Use [Git history](doc:history) before broad edits and [reconstruct and validate](doc:reconstruction) for bounded automatic build/repair attempts. The project editor is an integrated reconstruction environment; it does not implement every Rider/Visual Studio feature or supply missing proprietary SDKs.
