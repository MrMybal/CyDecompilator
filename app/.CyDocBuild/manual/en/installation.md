---
id: installation
title: Installation and first launch
description: Keep a complete installation and check the runtime and task prerequisites.
section: Get started
parent: start
order: 1
revision: 3
---

## Keep the complete installation together {#keep-the-complete-installation-together}

Windows x64 provides two complete packages, both including Python and required libraries. No system Python installation is needed.

- **Installer:** run the setup EXE, choose its language and destination, then launch from the Start menu. The default location is writable by your current user and needs no administrator rights. The desktop shortcut is optional.
- **Portable ZIP:** extract the whole archive to a writable directory, then start **CyDecompilator.exe**. Keep **app/** and **runtime/** beside the executable.
- **Application-update ZIP:** this smaller archive is for an existing compatible installation; keep its **runtime/** and **data/** directories. The built-in updater selects this archive rather than the complete portable package.

Linux x64 remains experimental and uses **CyDecompilator.sh** with a Linux-created runtime. Windows bundles cannot run on Linux. Optional analysis engines and build toolchains are installed separately from the Engines page.

| Folder | Role |
|---|---|
| app/ | Application code, translations, bundled manual and notices |
| runtime/python/ | Private interpreter and installed Python dependencies |
| runtime/engines/ | Optional analysis engines and toolchains |
| data/ | Projects, settings, history, jobs and reports |

Do not move an existing Python virtual environment and assume it will still work: its launcher paths can be absolute. For a new development installation, create it in its final directory, then install the application requirements and the pinned CyToolsCore SDK. The developer setup is recorded in **app/README.md**. Linux execution and individual engines have platform-specific validation limits; Windows results do not establish Linux compatibility.

## Check prerequisites by task {#check-prerequisites-by-task}

1. Open [Engines](doc:engines). Install only what your target format requires, or select an existing compatible tool.
2. For native source builds, install a matching C/C++ toolchain. Windows PE projects generally use the Visual Studio C++ workload and Windows SDK.
3. For managed projects, provide a compatible .NET SDK and the target framework's references. Java analysis/builds need the appropriate Java installation. JavaScript/Electron workflows need Node.js and the selected optional components.
4. Git is required for project history and automated source-repair backups.
5. Configure an [AI provider](doc:ai) only if you want AI assistance. Manual decompilation does not require an AI provider.

## Confirm the installation {#confirm-the-installation}

Open **Options**, select a language and theme, then press F1. The manual must open even without a project. Open a small known input before analyzing a large application. An installed engine and a successful analysis are separate states: check the job result if a component is present but produces no functions.

## When launch fails {#when-launch-fails}

A missing-runtime error means the Windows launcher cannot find its private interpreter. Re-extract the full portable archive or reinstall. Full packages use **runtime/python/pythonw.exe**; existing development venvs use **runtime/python/Scripts/pythonw.exe**. If a native library or Python import fails, check **Application log** and the matching runtime requirements rather than installing packages into an unrelated system Python. See [troubleshooting](doc:troubleshooting) and [storage](doc:storage) before removing anything.


The portable application keeps user data in **data/** beside it. Uninstalling an installed copy preserves user-created projects, settings and downloaded engines. Back them up before removing the remaining application directory manually.
