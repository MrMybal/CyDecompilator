# PS5 desktop porting

Discover the server's `porting_*` schemas before using them. This workflow prepares
and tests a desktop port through separate AnyPS5/UltraPack tools; it does not recover
the original source project or guarantee compatibility with a game.

Use `porting_open` with exactly one absolute `file` or `directory`. Files are staged
by the Runtime. `entry` selects a relative executable when there are multiple apps.
The server snapshots modules/resources and records hashes, title metadata, ELF
program headers, unwrapped plaintext SELF files and any opaque SELF metadata.
Encrypted primary executables and required runtime modules are unsupported; metadata
under `sce_sys` may remain opaque and is explicitly listed in `unpreparedSelf`.
Inspect those unknowns instead of asserting that every file was decompiled.

ELF, supported plaintext SELF and ZIP need no extraction backend. PKG, PFS, exFAT,
RAR and 7z use UltraPack. Inspect `porting_tools` and, within an authorized conversion
task, use `porting_install backend=ultrapack` for its private environment. Its package
helper needs .NET SDK 9+. `buildPkgHelper=false` installs PFS/archive preparation
without that helper. RAR may still require unrar or 7-Zip. Existing CLI, Python and
helper paths can be configured with `porting_tools`.

Use `porting_info`, then `porting_plan target=windows|linux`. When allowed, install
the converter with `porting_install backend=anyps5 target=...`. Official release
assets require published SHA-256 digests. Target libraries and the host converter
are separate. Never invent missing game modules or use standalone mode to hide them.

`porting_convert` returns `converted-unverified` only after format/hash checks and
creates a persistent output receipt. Inspect `output`, blockers and limits on a
failure. `standalone=true` is explicit, module-free homebrew only; it is not a fallback
for an incomplete dump. `toIntel` requests only instruction rewrites that the installed
converter supports. Conversion uses the actual CLI capabilities of that version.
Additional root executables are distinguished from shared PRX modules and passed
through the supported `--executable` option. Inspect `secondaryExecutables` and
`additionalExecutables`; never treat a successfully converted primary as proof
that every secondary program works. Ambiguous loose-module layouts fail explicitly.

For large packages, inspect free space and any available container metadata before
whole-tree work. A selected-code extraction can test analysis/conversion, but must
be reported as partial; missing game assets are not a meaningful gameplay test.
The SDK and extraction use private container copies; the preparation record retains
the digest and prepared files instead of another permanent container copy. Conversion
copies the full resource tree into output once; execution needs a fresh complete copy.
The job drive may differ from the persistent project drive when space is limited.
Unmapped non-load note/version/comment metadata is listed as `omittedMetadata`;
missing code/dynamic-link segments and encrypted executable data remain unsupported.

Use `porting_diagnose` to connect saved converter/run evidence to the verified guest
image through `cdec`, `native` or installed `ghidra`. The built-in engines support
sectionless load headers. Optional `module` selects a prepared executable, and
`attemptId`/`conversionId` selects saved evidence. By default, converter failures
also invoke bounded built-in C analysis (`analyzeOnFailure=true`). Read `diagnosis`
or `diagnosisError`; neither changes the failed conversion into success.

Diagnoses contain source/registry hashes, syscall sites, NID import references,
decoded instruction/function links, coverage and C/assembly samples. Some releases
label guest virtual addresses as offsets. Do not reinterpret ambiguous locations or
unattributed module errors as exact ownership. A runtime host address is not a guest
address; traced NID matches yield static source candidates only. Unmodeled C instructions
(`hasUnmodeledInstructions`) and unresolved console dynamic NIDs are explicit unknowns.
Do not substitute that C for guest code, invent API stubs or weaken syscall checks to pass.

For Windows failures, `diagnostics=true` and, when appropriate, `traceImports=true`
request supported AnyPS5 instrumentation switches. Import instrumentation requires
libc.prx among the selected guest dependencies. `porting_run traceLibraries=all`
or comma-separated names enables bounded captured tracing only for an instrumented
conversion. No emitted trace means no observed calls. Inspect a failure's evidence,
choose a justified next analysis or repair and retest; do not blindly reconvert.

`porting_run` executes a fresh verified copy on the matching x86-64 Windows/Linux
host. Supply finite `scenarios` with arguments/stdin and explicit expected exit codes
or exact stdout derived from the user's objective or independent observations.
Do not make expectations from the converted application's own output merely to pass.
No assertions means `executed-unverified`; only all asserted, successful cases yield
`scenarios-passed`. A later failed run or conversion invalidates an agent's old proof.

For source/function investigation, use the imported project with existing analysis
operations. For richer comparison, use the existing behavior capture/query tools and
report what they cover. These porting scenarios do not themselves prove graphical,
network, audio, controller or whole-game equivalence. Linux output can be produced
on Windows but must be tested on Linux; do not report it as executed locally.

The integrated agent accepts `ai_agent workflow=port` on an already prepared project.
It can inspect/configure tools, install backends when `allowInstall=true`, convert,
test and recover from reported failures. Server completion requires a successful
asserted `porting_run` and unchanged converted files. Report receipt/job identifiers,
actual scenarios and remaining unknowns. Use bounded checkpoints, not unlimited retries.
