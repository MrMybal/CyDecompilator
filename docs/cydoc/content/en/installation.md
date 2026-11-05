---
id: installation
title: Installation and first launch
description: Install and launch
section: Get started
order: 1
revision: 1
---

## Keep the complete installation together {#keep-the-complete-installation-together}

On Windows, start **CyDecompilator.exe**. On Linux, use **CyDecompilator.sh** with a Python runtime created for Linux. The desktop uses one private Python environment and optional, separately installed engines. A source ZIP or application update is not a complete runtime bundle. Keep the existing **runtime/** and **data/** directories when applying an application update.

| Folder | Role |
|---|---|
| app/ | Application code, translations, bundled manual and notices |
| runtime/python/ | Private interpreter and installed Python dependencies |
| runtime/engines/ | Optional analysis engines and toolchains |
| data/ | Projects, settings, history, jobs and reports |

Do not move an existing Python virtual environment and assume it will still work: its launcher paths can be absolute. For a new development installation, create it in its final directory, then install the application requirements and the owner's CyToolsCore SDK. The developer setup is recorded in **app/README.md**. Linux execution and individual engines have platform-specific validation limits; Windows results do not establish Linux compatibility.

## Check prerequisites by task {#check-prerequisites-by-task}

1. Open [Engines](doc:engines). Install only what your target format requires, or select an existing compatible tool.
2. For native source builds, install a matching C/C++ toolchain. Windows PE projects generally use the Visual Studio C++ workload and Windows SDK.
3. For managed projects, provide a compatible .NET SDK and the target framework's references. Java analysis/builds need the appropriate Java installation. JavaScript/Electron workflows need Node.js and the selected optional components.
4. Git is required for project history and automated source-repair backups.
5. Configure an [AI provider](doc:ai) only if you want AI assistance. Manual decompilation does not require an AI provider.

## Confirm the installation {#confirm-the-installation}

Open **Options**, select a language and theme, then press F1. The manual must open even without a project. Open a small known input before analyzing a large application. An installed engine and a successful analysis are separate states: check the job result if a component is present but produces no functions.

## When launch fails {#when-launch-fails}

An error about **runtime/python/Scripts/pythonw.exe** means the Windows launcher cannot find its private interpreter. Restore or recreate that environment at the installation location. If a native library or Python import fails, check **Application log** and the matching runtime requirements rather than installing packages into an unrelated system Python. See [troubleshooting](doc:troubleshooting) and [storage](doc:storage) before removing anything.
