<p align="center"><img src="app/assets/logo-256.png" width="160" alt="CyDecompilator"></p>

<h1 align="center">CyDecompilator</h1>

<p align="center">
AI-assisted multi-engine decompiler — Windows, Linux · x86, x64, ARM64 · .NET, Java, Android, Python, shaders
<br>
<img src="https://img.shields.io/badge/version-1.4.0-1f4e8c" alt="version 1.4.0">
<img src="https://img.shields.io/badge/license-GPL--3.0-1f4e8c" alt="GPL-3.0">
</p>

**English** · [Français](LISEZ-MOI.md)

CyDecompilator opens a wide range of binaries and displays their reconstructed code. An AI
assistant helps explain, rename and rewrite that code into editable source. It also works
as an MCP server, so AI clients such as Claude Code and Codex can use it directly.

## Launch

- **Windows**: double-click `CyDecompilator.exe`.
- **Linux**: run `./CyDecompilator.sh` (requires a `runtime/python` environment created on Linux;
  see the [developer guide](app/README.md)).

The application requires its private Python runtime. Release archives contain the application
and Windows launcher; keep the existing `runtime/` and `data/` folders when updating.
For a new installation, follow the [runtime setup instructions](app/README.md#set-up-a-development-runtime-windows).

The interface defaults to English. In the **Options** sidebar page, select *Language*: English,
Français, Deutsch, Español, Italiano, Português, Русский, 简体中文, 日本語 or 한국어.
Changes take effect immediately, without restarting. The AI assistant responds in the selected language.

The interface uses **CyUI**: permanent sidebar navigation, toolbars with tooltips, resizable
explorer and code panes, and a task status bar. **Options** provides five themes (Mid grey,
Light grey, Amber night, Violet and Navy), compact or comfortable density, and text scaling.
Existing theme preferences migrate automatically. In smaller windows, AI remains available
from its dedicated sidebar page, and function details move into a tab beside the code.

## Supported inputs

| File | Engine | Output |
|---|---|---|
| `.exe`, `.dll`, ELF / Android `.so` (x86, x64, ARM64) | **CyDecompilator C** (built in) | Structured, recompilable C without additional engine dependencies |
| `.exe`, `.dll`, `.so`, ELF, Mach-O, raw firmware | **Ghidra** | C pseudocode; preferred when installed |
| `.exe`, `.dll`, ELF (x86, x64, ARM64) | **Built-in disassembler** (Capstone) | Annotated assembly, calls, strings and imports |
| .NET assemblies (managed `.dll`, `.exe`) | **ILSpy** | C# |
| `.class`, `.jar` | **Vineflower** | Java |
| `.apk`, `.dex` and `.jar` | **JADX** | Java + AndroidManifest |
| `.pyc` | **Python** (xdis, uncompyle6, decompyle3) | Source through Python 3.8; bytecode for all versions |
| DXBC shaders (`.cso`, `.fxc`), DXIL SM6, SPIR-V (`.spv`) | **CyDecompilator shader engine** | HLSL (SM4/5 and SM6), GLSL |

Formats are detected from file contents rather than extensions.

## PS5 desktop porting

The **PS5 porting** sidebar page accepts an application folder, ELF/plaintext SELF,
ZIP or a container such as PKG/PFS. It prepares a preserved input snapshot, converts
through the optional separate **AnyPS5** backend, and tests the desktop output with
explicit scenarios. **UltraPack** supplies container extraction; official backend
installation is available in the page. The AI workflow **Port and test** uses the
same MCP operations and verifies execution evidence before completion.

CyDecompilator's native/C engines also analyze sectionless guest ELF images and link
AnyPS5 failures/import registries to source instructions and functions. Failed conversions
can automatically produce a C/assembly dossier with evidence and unresolved cases.

Real Windows conversion/execution and PFS/PKG preparation have been exercised on
owned test applications. Game/API/GPU compatibility still depends on the backend;
conversion does not establish that a game works. See [setup and limits](app/Docs/PS5Porting.md).

## Built-in C decompiler

- x86 (cdecl, stdcall, thiscall, MSVC helpers), x64 (Win64, System V) and ARM64 (AAPCS64,
  Windows ARM64), with PE and ELF support.
- `if` / `else`, loops, `switch` jump tables, floating point (SSE, x87, VFP), SIMD (SSE and
  NEON expressed as SSE intrinsics), and called-function prototypes inferred from their code.
- In the *Program* tab, *Exported functions* / *This function and its callees* export a single
  `.c` file for recompilation with MSVC or clang: initialized globals recovered from the binary,
  embedded constants and linked imports.
- Verified by recompiling generated C and comparing execution with the original: x86/x64
  120/120; emulated ARM64 120/120. Generated C from real Windows binaries (cmd.exe, msvcrt,
  python311, ARM64 vcruntime and others) compiles without errors.

## Windows applications (x86, x64, ARM64, DLL)

- **PDB symbols**: searches local folders, then the Microsoft symbol server. GUID and age are
  verified, and symbols are cached in `data/symbols`. Recovered function and class names are
  used throughout the application.
- **Executable details** (*Program* tab): protections (ASLR, DEP, CFG), version, manifest,
  build tools (Rich header), exports, TLS callbacks, section entropy, overlay, signature and
  indicators of the original toolchain (Go, Rust, Delphi, Electron, Nuitka and others).
- **Embedded content**: *Extract* handles **PyInstaller** bundles, **.NET single-file**
  applications, **UPX** files and appended ZIP archives. Each extracted file can open as a new project.

## Getting started

1. Open **Engines** and *Install* the engines you need. Downloads come from official sources
   and are verified. An existing Java 21+, .NET or Ghidra installation can be selected with *Browse* / *Use*.
2. Open **Workspace**, then *Open file...*, press **Ctrl+O**, or paste a path and press Enter.
3. Select a function on the left to display its code. Double-click a name to navigate to it,
   right-click for rename and search actions, and use the back/forward buttons to navigate history.
4. In the right-hand **AI** pane or dedicated **AI** page, select **Autonomous workflow** for
   a complete task, **Conversation** for questions, or **Function** for focused actions:
   - **Explain**: explains the selected function.
   - **Suggest names** (+ *Apply*): proposes meaningful names for the function and its variables.
   - **Convert to source**: rewrites code into C, C++, C#, Java, Python, Rust, Go, HLSL, GLSL
     and other supported targets, with compilation checks and automatic error repair.
   - **Conversation → Send**: asks an open-ended question; the assistant can inspect the program before answering.
   - **Name functions**: names batches of automatically named functions (`FUN_*`, `sub_*`).

## Edit, reconstruct and test a project

The **Git history** tab in Project IDE keeps local versions of the reconstructed project.
Git must be installed and available on PATH. Enter a description and select **Save Git version**
to snapshot sources, resources and local dependencies. **Compare with saved sources** shows
changes before you choose **Restore this version**. Restoration first saves the current state
in a recoverable commit, then creates a restoration commit. Open files are reloaded; save
their edits before comparing. Modified .NET copies display the source commit when a matching
version was saved before they were created.

The private Git repository lives in the analysis data, separately from any repository already
present in the source folder. Build directories, caches and Git metadata are excluded.
Binary files are versioned, but their differences are not displayed as text. Snapshots are
limited to 4,000 files, 128 MiB total and 32 MiB per file. Restoration checks that sources
have not changed since the preview and protects the original application.

After opening an application, **Project IDE → Create source project** provides:

- **.NET**: an ILSpy C# project, recovered resources and a `.sln` solution that opens in Visual Studio.
- **Native PE/ELF**: C sources for exported functions, or a selected function and its callees;
  executable, DLL or static-library targets; a `.vcxproj` project, `.sln` solution and CMake
  configuration. Recovered entry points, imports, exports and resources are reconstructed;
  unknown elements remain explicit blockers. ELF requires a suitable toolchain and environment.
- **JavaScript, TypeScript, web and Electron**: editable sources and resources, build
  configuration, separate output folders and an Electron ASAR archive. Dependencies and the
  runtime must be available; native modules require a compatible runtime version and architecture.

**Project IDE → Reconstruction → Reconstruct and validate** chains project creation, builds,
optional tests and comparisons with the original. Enable AI repairs for multiple attempts,
saved in Git, up to the selected limit. Investigation scenarios can be reused to compare
interfaces, files, output and network activity. Reports distinguish a successful build from
behavior validated against recorded scenarios.
See the [reconstruction guide](app/Docs/Reconstruction.md) for setup and limitations.

The solution explorer opens multiple files in editable tabs with syntax highlighting.
**Save all**, **Build**, **Rebuild**, **Test** and **Run** use cancellable jobs.
Compiler errors appear in **Problems**; selecting an error opens its source location.
**Open source project** can also attach an existing C#, VC++ or CMake folder. External file
changes prevent accidental overwrites, and edited tabs are protected when closing.
Multi-project `.sln`/`.slnx` solutions are supported: **Build / startup project** selects
the project to build or launch. **Entire solution** builds or tests the complete solution;
select an executable C# project to use **Run**.
**Search source project** searches saved files with case and whole-word options; selecting
a result opens its line. **Filter files** filters the explorer, and **Go to line** navigates
the active file. **Reload file** reloads changes from disk, with confirmation before
discarding unsaved edits.

C# builds require a **.NET SDK**, separate from the runtime installed for ILSpy. Native C
uses Visual Studio C++ tools on Windows, or CMake and a compiler elsewhere. **Test** requires
actual project tests; **Run** on a native library requires a test executable.
The C# editor uses **Roslyn** from a **.NET 8 or newer SDK** with dotnet-format components.
**Complete (Ctrl+Space)** lists accessible members and signatures; selecting a suggestion
inserts it with undo support. **Go to definition (F12)** finds declarations, including those
in another file or referenced C# project. **C# symbols** lists project types and members.
**C# assistance** displays diagnostics while editing and supports manual analysis. Unsaved C#
edits are included without changing files on disk; stale suggestions are rejected if the code
or cursor has changed.
**Preview semantic rename** renames the selected symbol and its references in affected files
and projects without touching unrelated symbols with the same name. **Find symbol references**
lists usages. **Preview C# formatting** proposes Roslyn formatting. Review the differences,
then **Apply preview to editor buffers**: changes remain in the editor, can be undone, and
must be saved. Source or buffer changes invalidate the preview before application.

Restored package references and referenced assemblies are used when available. Custom build
steps, conditional properties, analyzers and generated sources may require a build for complete
diagnostics; missing references are reported. The editor helper is built locally without
downloading packages. **Evaluate project with MSBuild** explicitly resolves references and
accounts for imports, conditional properties and Compile items. Subsequent editor queries
read that model without rerunning targets; configuration or project-file changes require
reevaluation. Multi-target projects use their first target. Semantic services for other
languages remain to be implemented.

To replace a function directly, choose **Edit function / patch** in Workspace or
**Function patch** in Project IDE:

- **.NET**: select **Load .NET methods**, choose a method, then **Edit declaring type** to open
  its C# source. **Build and verify method patch** rebuilds the project and replaces only the
  selected IL body in the original assembly. The new method may be larger; locals, branches,
  strings, internal calls and try/catch blocks are supported. Lambdas, closures, local
  functions, async methods and iterators are supported: generated dependencies are imported
  under isolated names and listed in the preview. Select the source method rather than a
  generated function. Other method bodies and existing tokens are checked for preservation,
  including after repeated replacements. If the build produces multiple assemblies, specify
  the rebuilt assembly path relative to the project. This uses the .NET SDK and a dnlib 4.5.0
  helper, restored automatically from official NuGet with a pinned hash.
  **Import referenced new .NET members** can add compatible helpers, types and fields used
  by the replacement. New types retain their constructors, properties and events; the preview
  lists every addition. Adding instance fields to an existing type or changing its initializer
  requires full reconstruction, as do signature changes, mixed-mode images and ReadyToRun.
  Incompatible dependencies or imports exceeding configured limits are refused. A strong-name
  signature must be retained through a signed rebuild or explicitly removed using the offered
  option; removal may break dependencies. **Generate symbols for modified copy** produces a
  portable PDB matching the imported methods.
- **Native x86/x64 PE**: edit its C while preserving the signature and calling convention,
  then select **Compile and verify patch**. Self-contained functions without external calls,
  relocations or unwind metadata are accepted when the code fits the original location.
  Clang, including LLVM supplied with Visual Studio, is required. Incompatible cases are refused.
  **Link a larger native function with calls and exception data** adds a PE section and redirects
  the original entry: helpers, calls to existing functions/imports, data, ASLR relocations and
  x64 exception tables are linked. Known symbols resolve automatically; the JSON field maps
  C names to existing function or import addresses. The original entry must provide five complete
  bytes, and the PE must have room for another section header. CFG, new TLS, unresolved external
  symbols and incompatible relocations require a full link.

**Write modified copy** creates a separate copy with a SHA-256 receipt; the original and
existing outputs cannot be overwritten. For .NET, keeping the original filename in a new
folder also copies the runtime configuration and build-produced dependencies when those
files do not already exist. Save sources and prepare the replacement again after any source
change. **Analyze modified copy** reopens the result. A successful build does not establish
ABI compatibility or equivalent behavior; any existing Authenticode signature is invalidated.

**Saved modified copies** lists previously created copies, including after restarting.
**Run modified copy** launches a selected copy with arguments and a configurable 1–900 second
timeout. Executable and copied-dependency hashes are rechecked before launch. Build and
application stdout/stderr appear while they run. **Cancel** and timeouts also stop child
processes. DLLs require a test harness and are not loaded into the decompiler. A successful
status means a zero exit code; it does not establish correct behavior. The console captures
output but does not yet provide interactive input. The application's matching .NET runtime
must be installed.

The **Debugger** panel supports rebuilt .NET projects. Install **NetCoreDbg** from that panel
or Engines, select a C# startup project, then choose **Debug (F5)**. Sources are saved and rebuilt
in Debug with PDB symbols before launch. **F9** toggles a breakpoint at the cursor line in a
saved file; breakpoints persist across restarts. **F5** continues, **F10** steps over,
**F11** steps in, **Shift+F11** steps out and **Shift+F5** stops debugging.
The panel displays call stacks, local variables and object members. Selecting a stack frame
opens its source line; the debug console displays application output.

Sources are read-only during a debug session; stop debugging to edit and rebuild. Stopping,
cancellation, timeouts and application shutdown also stop child processes. A .NET 8+ SDK
and the application's runtime are required. This covers rebuilt .NET Core executable projects
with portable PDBs; libraries need a test harness. **Debug modified copy** launches a prepared
.NET copy with its symbols directly, without rebuilding it. Breakpoints, variables and async
state machines use regenerated mappings for imported methods. Unchanged methods have no
regenerated source mapping. Sources and copy/dependency hashes must still match the receipt;
keep the original assembly filename in a new folder. Native and .NET Framework debugging
remain to be added. The console does not support interactive input or variable modification.

Verification includes WinForms and WPF test applications with embedded resources, BAML,
local dependencies and short names: decompilation, reconstruction, execution and method
reinjection are exercised. Local dependencies are copied into exported projects using relative
HintPath entries. XAML files are editable when present; this does not guarantee recovery of
every interface or protection in third-party obfuscated applications.

## Investigate evidence and compare versions

**Investigation** analyzes JavaScript/Electron folders, ASAR archives and JS/TS/HTML files.
Install the JS analyzer from this page (Node.js required), then search for a feature, IPC
channel or URL. Results link files, functions, preload scripts, resources and calls with
supporting evidence. Local source maps and imported HAR captures provide additional links.

For native code, select a Ghidra-analyzed function and choose **Inspect selected native
function** to examine types, call sites, instructions and value dependencies.

In **Version behavior**, capture two executables with the same inputs and initial files to
compare output, exit codes and created/modified/deleted files. Open **Network and graphical
scenario** to record TCP connections and replay steps against Windows controls or a
Chromium/Electron renderer (Node.js 22+). Comparisons include renderer HTTP requests, console
output, graphical states and screenshots. **Captured screens** displays versions side by side.
Incomplete results and scope limits are reported; files outside the working directory are
not observed.

See the [investigation guide](app/Docs/Investigation.md) for instructions and limitations.

## Choose an AI provider

Open **AI assistant settings**:

- **Claude Code**, **Codex**, **Antigravity**, **OpenCode** use the account already signed
  into those programs; no API key is needed. Provider processes run in read-only mode.
- **Anthropic**, **OpenAI**, **OpenRouter**, **OpenAI-compatible servers** (LM Studio, vLLM),
  and **Ollama** use an API key or local URL. Keys are encrypted with Windows DPAPI when stored.

The AI receives the selected function's code and information requested through its tools.
With an online provider, that code leaves your machine.

## Use from an AI client (MCP)

```text
claude mcp add cydecompilator -- "<folder>\runtime\python\Scripts\python.exe" "<folder>\app\tool.py" mcp
```

Declared operations are available over MCP, including analysis, reconstruction, builds, Git,
method reinjection, .NET debugging and network/graphical comparisons. The [MCP and AI guide](app/Docs/AIIntegration.md)
documents connections and workflows. A dedicated [cydecompilator skill](app/skills/cydecompilator/SKILL.md)
is included:

```powershell
runtime/python/Scripts/python.exe app/scripts/install_skill.py
```

This installs instructions into the Codex skills folder; configure the MCP connection
separately. Tests cover the full catalog and real MCP workflows, not every possible engine
and option combination.

The **AI** panel also offers **Run autonomous task**: choose a workflow, enter an objective,
and let the assistant investigate, repair, build and test. MCP tools `ai_agent` and
`ai_agent_status` expose the same mode, with progress tracking, resume support, Git backups
and mandatory validation before completion.

## Application updates

In **Engines → Application updates**, **Check for updates** queries this repository's
[releases](https://github.com/MrMybal/CyDecompilator/releases). **Download and verify** stages
the update and verifies its SHA-256 digest, identity and Python compilation. **Apply update**
activates it while retaining the previous version for **Restore previous version**.
`data/` is never replaced. While the repository is private, a GitHub token with read access
is required in the **GitHub token** field or the `GITHUB_TOKEN` environment variable.

## File locations

- `data/projects/`: a folder per opened file, containing analysis, cached code, renames,
  comments and AI results.
- `data/settings/`: preferences, AI settings, encrypted keys and tokens.
- `data/logs/`: logs, also available from **Application log**.
- `runtime/`: private Python environment, downloaded engines and staged updates.
- [Developer guide](app/README.md): architecture, tests and releases.

## Known limitations

- Python 3.9+: no complete open-source source decompiler; bytecode and AI reconstruction are available.
- DXIL libraries (`lib_6_x`, ray tracing) currently expose only their first function.
- Encrypted PyInstaller archives (`--key`) and NSIS/Inno installers are detected but not extracted.
- The built-in C decompiler has limited type reconstruction: structures may appear as
  `*(type *)(p + offset)`. On ARM64, integer parameters are listed before floating-point parameters.
- Large binaries take time in Ghidra; adjust the number of functions decompiled during
  analysis in **Engines**.

## License

[GPL-3.0](LICENSE). Downloaded engines retain their own licenses, displayed in **Engines**
and **Options → Licenses**.

Only decompile software you have the right to analyze.

### Unreal reconstruction rules

The **Unreal reconstruction** page integrates the Halo Anniversary prototype’s rules and ten campaign profiles through the same Runtime, CLI, MCP and agent tools. This exposes reconstruction knowledge; game conversion remains separate. [Guide](app/Docs/UnrealReconstruction.md).
