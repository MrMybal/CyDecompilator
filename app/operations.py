"""Single source of the operation contracts. build_manifest.py writes CyTool.json from it.

Each entry: id, name, description, input properties, required inputs, output properties,
permissions, exclusive groups, RAM estimate. Every option an engine or task accepts is
declared here, so MCP, CLI, HTTP and the window see the same contract.
"""

S = lambda description, **extra: dict({'type': 'string', 'description': description}, **extra)  # noqa: E731
B = lambda description, default=None: dict({'type': 'boolean', 'description': description},  # noqa: E731
                                           **({'default': default} if default is not None else {}))
I = lambda description, default=None, minimum=None, maximum=None: dict(  # noqa: E731
    {'type': 'integer', 'description': description},
    **({'default': default} if default is not None else {}),
    **({'minimum': minimum} if minimum is not None else {}),
    **({'maximum': maximum} if maximum is not None else {}))
OBJ = lambda description: {'type': 'object', 'description': description}  # noqa: E731
ARR = lambda description: {'type': 'array', 'description': description}  # noqa: E731

ENGINE_IDS = ['', 'ghidra', 'native', 'ilspy', 'vineflower', 'jadx', 'python', 'shader']
COMPONENT_IDS = ['jdk', 'ghidra', 'dotnet', 'ilspycmd', 'vineflower', 'jadx', 'pydecompile', 'upx']
TARGETS = ['same', 'c', 'cpp', 'csharp', 'java', 'python', 'rust', 'go', 'hlsl', 'glsl', 'javascript']
PROVIDERS = ['', 'claude-code', 'codex', 'antigravity', 'opencode', 'anthropic', 'openai', 'openrouter',
             'openai-compatible', 'ollama']

PROJECT = S('Project id returned by open_file or list_projects.')
ENGINE = S('Engine id. Empty selects the analysed (or best available) engine for the file.', enum=ENGINE_IDS, default='')
FUNCTION = S('Unit to use: function id, original or renamed name, or address (0x401000). '
             'For .NET/Java units are fully qualified type names; shaders use the entry point name.')
LANGUAGE = S('Answer language for the AI.', enum=['en', 'fr', 'de', 'es', 'it', 'pt', 'ru', 'zh', 'ja', 'ko'],
             default='en')
AI_PROVIDER = S('Override the configured AI provider for this call.', enum=PROVIDERS, default='')
AI_MODEL = S('Override the model id for this call (empty = configured/default).', default='')
ANALYSIS_OPTIONS = {
    'type': 'object', 'description': 'Engine options.', 'additionalProperties': False,
    'properties': {
        'maxDecompile': I('Ghidra: functions decompiled during analysis; others on demand.', 2000, 0, 1000000),
        'functionTimeout': I('Ghidra: decompiler timeout per function, seconds.', 60, 5, 3600),
        'analysisTimeout': I('Ghidra: auto-analysis timeout, seconds.', 3600, 60, 86400),
        'processor': S('Ghidra: language id for raw binaries, e.g. ARM:LE:32:v8 or x86:LE:64:default.'),
        'decodeResources': B('JADX: decode AndroidManifest.xml and resources.', True),
        'deobfuscate': B('JADX: rename obfuscated short names.', False),
        'javaHeapMb': I('JADX: Java heap in MiB.', 4096, 512, 65536),
        'symbols': B('PE files: load PDB debug symbols (local folders, then the configured symbol server) '
                     'and apply their names (native engine and Ghidra).', True),
    }}

OPERATIONS = [
    # ------------------------------------------------------------------ projects
    dict(id='open_file', name='Open file',
         description='Open a binary, assembly, archive, bytecode or shader file as a project (deduplicated by '
                     'SHA256), detect its format and, by default, analyze it with the best installed engine.',
         inputs={'path': dict(S('Absolute path of the file to open.'), **{'x-cy-kind': 'File'}),
                 'analyze': B('Run the analysis immediately.', True), 'engine': ENGINE,
                 'force': B('Re-analyze even if an analysis already exists.', False),
                 'options': ANALYSIS_OPTIONS},
         required=['path'], ram=2 * 1024 ** 3, groups=['analysis'], permissions=['processSpawn', 'network'],
         outputs={'projectId': S('Project id.'), 'format': OBJ('Detected format.'),
                  'analyses': OBJ('Analyses by engine.'), 'engine': S('Engine used.')}),
    dict(id='analyze', name='Analyze',
         description='Analyze a project with an engine (Ghidra, native, ILSpy, Vineflower, JADX, Python, shader).',
         inputs={'projectId': PROJECT, 'engine': ENGINE, 'force': B('Re-analyze even if done.', False),
                 'options': ANALYSIS_OPTIONS},
         required=['projectId'], ram=2 * 1024 ** 3, groups=['analysis'], permissions=['processSpawn', 'network'],
         outputs={'projectId': S('Project id.'), 'engine': S('Engine used.'), 'analyses': OBJ('Analyses.')}),
    dict(id='list_projects', name='List projects', description='Every project with its analyses.',
         inputs={}, outputs={'projects': ARR('Projects.')}),
    dict(id='project_info', name='Project info',
         description='Format, architecture, sections, imports, exports, counts, shader reflection and notes.',
         inputs={'projectId': PROJECT, 'engine': ENGINE}, required=['projectId'],
         outputs={'projectId': S('Project id.')}),
    dict(id='delete_project', name='Delete project',
         description='Delete a project and its analyses, caches and AI results. The original file is untouched.',
         inputs={'projectId': PROJECT}, required=['projectId'], outputs={'deleted': B('Deleted.')}),
    dict(id='list_functions', name='List functions',
         description='Functions, types or code units of an analysis, filtered and paginated.',
         inputs={'projectId': PROJECT, 'engine': ENGINE, 'query': S('Substring filter on id/name/address.', default=''),
                 'offset': I('First result.', 0, 0), 'limit': I('Page size.', 500, 1, 200000),
                 'kind': S('Only this kind (function, class, entry, code...).', default='')},
         required=['projectId'], outputs={'functions': ARR('Units.'), 'total': I('All units.'),
                                          'matched': I('Matching units.')}),
    dict(id='function_info', name='Function info',
         description='One unit: signature, callers, callees, imports, strings, comment and local renames.',
         inputs={'projectId': PROJECT, 'function': FUNCTION, 'engine': ENGINE},
         required=['projectId', 'function'], outputs={'function': OBJ('Unit details.')}),
    dict(id='decompile', name='Decompile',
         description='Decompiled source (or disassembly) of one unit, with the user\'s renames and comments applied.',
         inputs={'projectId': PROJECT, 'function': FUNCTION, 'engine': ENGINE,
                 'view': S('decompiled source or disassembly/bytecode.', enum=['decompiled', 'disassembly'],
                           default='decompiled'),
                 'refresh': B('Ignore the cache and decompile again.', False),
                 'annotate': B('Apply renames and comments.', True)},
         required=['projectId', 'function'], permissions=['processSpawn'],
         outputs={'code': S('Code.'), 'language': S('Language of the code.'), 'view': S('View produced.')}),
    dict(id='xrefs', name='Cross references', description='Callers, callees and imports of a unit.',
         inputs={'projectId': PROJECT, 'function': FUNCTION, 'engine': ENGINE}, required=['projectId', 'function'],
         outputs={'callers': ARR('Callers.'), 'callees': ARR('Callees.')}),
    dict(id='strings', name='Strings', description='Strings found by the analysis, filtered and paginated.',
         inputs={'projectId': PROJECT, 'engine': ENGINE, 'query': S('Substring filter.', default=''),
                 'offset': I('First result.', 0, 0), 'limit': I('Page size.', 500, 1, 5000)},
         required=['projectId'], outputs={'strings': ARR('Strings.'), 'matched': I('Matches.')}),
    dict(id='search', name='Search',
         description='Search function names, cached decompiled code and strings.',
         inputs={'projectId': PROJECT, 'query': S('Text to find (case-insensitive).'), 'engine': ENGINE,
                 'inCode': B('Also search decompiled code.', True), 'limit': I('Maximum hits.', 200, 1, 5000)},
         required=['projectId', 'query'], outputs={'hits': ARR('Hits.')}),
    dict(id='rename', name='Rename symbol',
         description='Rename a function/global (or, with function, a local identifier). Applied to every view.',
         inputs={'projectId': PROJECT, 'old': S('Current (original or renamed) name.'), 'new': S('New identifier.'),
                 'function': S('Unit for a local rename; empty for a global rename.', default=''), 'engine': ENGINE},
         required=['projectId', 'old', 'new'], outputs={'scope': S('global or the unit id.')}),
    dict(id='set_comment', name='Set comment', description='Attach a comment to a unit (empty text removes it).',
         inputs={'projectId': PROJECT, 'function': FUNCTION, 'text': S('Comment text.'), 'engine': ENGINE},
         required=['projectId', 'function', 'text'], outputs={'comment': S('Stored comment.')}),
    dict(id='set_notes', name='Set project notes', description='Free-form notes for the whole project.',
         inputs={'projectId': PROJECT, 'text': S('Notes (Markdown).')}, required=['projectId', 'text'],
         outputs={'notes': S('Stored notes.')}),
    dict(id='export_sources', name='Export sources',
         description='Write every unit\'s code (annotations applied) as files: into the job workspace, or into '
                     'destination when given. .NET can also produce a compilable C# project.',
         inputs={'projectId': PROJECT, 'engine': ENGINE,
                 'destination': S('Absolute folder to write into (created if missing). Empty = job workspace.', default=''),
                 'decompileMissing': B('Decompile units not yet cached (slow on large binaries).', False),
                 'maxUnits': I('Limit the number of units (0 = all).', 0, 0),
                 'csharpProject': B('.NET only: also write a compilable C# project with ILSpy.', False)},
         required=['projectId'], ram=2 * 1024 ** 3, groups=['analysis'], permissions=['filesystemExternal', 'processSpawn'],
         outputs={'directory': S('Folder written.'), 'written': I('Files written.')}),
    dict(id='c_module', name='Recompilable C module',
         description='x86 / x86-64 / ARM64: decompile functions (and, by default, everything they call) with the '
                     'built-in C decompiler into ONE C file meant to compile again (MSVC / clang): globals are '
                     'initialised from the image, constants inlined, prototypes emitted. Empty functions = every '
                     'exported function.',
         inputs={'projectId': PROJECT,
                 'functions': {'type': 'array', 'items': {'type': 'string'}, 'default': [],
                               'description': 'Functions (id, name or address). Empty = exported functions.'},
                 'includeCallees': B('Also decompile every function they call.', True),
                 'destination': S('Absolute .c file to write. Empty = only returned.', default='')},
         required=['projectId'], ram=1024 ** 3, permissions=['filesystemExternal'],
         outputs={'code': S('C source.'), 'functions': ARR('Root functions.'), 'path': S('File written.')}),
    # ------------------------------------------------------------------ executables (PE)
    dict(id='extract_embedded', name='Extract embedded content',
         description='Extract what an executable carries: PyInstaller bundles (entry scripts and modules as .pyc), '
                     '.NET single-file bundles (assemblies), UPX-packed files (unpacked original) and appended zip '
                     'archives. Each extracted file can then be opened with open_file.',
         inputs={'projectId': PROJECT, 'kind': S('pyinstaller, dotnet-bundle, upx or zip-overlay; empty = first detected.',
                                                 enum=['', 'pyinstaller', 'dotnet-bundle', 'upx', 'zip-overlay'], default='')},
         required=['projectId'], ram=1024 ** 3, groups=['analysis'], permissions=['processSpawn'],
         outputs={'files': ARR('Extracted files with their detected format.'), 'directory': S('Extraction folder.')}),
    dict(id='extracted_files', name='Extracted files', description='List the files of a previous extraction.',
         inputs={'projectId': PROJECT, 'kind': S('Extraction kind.', enum=['pyinstaller', 'dotnet-bundle', 'upx', 'zip-overlay'])},
         required=['projectId', 'kind'], outputs={'files': ARR('Files.')}),
    dict(id='load_symbols', name='Load debug symbols',
         description='Find the PDB of a PE file (local folders, next to the original file, then the symbol server) '
                     'and read its function names. Re-analyze afterwards to apply them.',
         inputs={'projectId': PROJECT, 'force': B('Search again even if symbols were already looked up.', True)},
         required=['projectId'], network=True, permissions=['network'],
         outputs={'status': S('Result.'), 'functions': I('Named functions.')}),
    dict(id='symbols_configure', name='Configure symbols',
         description='PDB lookup: enable/disable, symbol server (HTTPS; empty = local folders only) and local folders.',
         inputs={'enabled': B('Load PDB symbols during analysis.'),
                 'server': S('Symbol server URL, e.g. https://msdl.microsoft.com/download/symbols; empty = none.'),
                 'localFolders': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Folders searched for PDBs first.'}},
         outputs={'enabled': B('Enabled.')}),
    # ------------------------------------------------------------------ engines
    dict(id='list_engines', name='List engines', description='Engines with formats, licence and availability.',
         inputs={}, outputs={'engines': ARR('Engines.')}),
    dict(id='list_components', name='List components',
         description='Downloadable components (JDK, Ghidra, .NET, ILSpy, Vineflower, JADX, Python decompilers) '
                     'with installed versions, system installs and overrides.',
         inputs={'refresh': B('Probe the system again.', False)}, outputs={'components': ARR('Components.')}),
    dict(id='install_component', name='Install component',
         description='Download the current release of a component from its official source, verify it '
                     '(SHA256/SHA512 when published) and install it under runtime/engines.',
         inputs={'component': S('Component id.', enum=COMPONENT_IDS),
                 'includeRequirements': B('Also install what it needs (e.g. the JDK for Ghidra).', True)},
         required=['component'], ram=512 * 1024 ** 2, groups=['install'], permissions=['network', 'processSpawn'],
         network=True, outputs={'installed': ARR('Installed components.'), 'status': OBJ('Component status.')}),
    dict(id='remove_component', name='Remove component',
         description='Remove a privately installed component version (system installs are never touched).',
         inputs={'component': S('Component id.', enum=COMPONENT_IDS),
                 'version': S('Version to remove; empty removes every private version.', default='')},
         required=['component'], groups=['install'],
         outputs={'removed': ARR('Removed versions.')}),
    dict(id='set_component_path', name='Use existing installation',
         description='Use a component already installed elsewhere (e.g. a Ghidra folder or a JDK). Empty clears it.',
         inputs={'component': S('Component id.', enum=COMPONENT_IDS),
                 'path': S('Folder or file of the existing installation; empty to clear.', default='')},
         required=['component'], groups=['install'], outputs={'installed': B('Usable now.')}),
    # ------------------------------------------------------------------ AI
    dict(id='ai_status', name='AI status',
         description='Configured AI provider/model, availability of every provider and compile checkers.',
         inputs={'refresh': B('Probe providers (spawns CLIs / contacts endpoints).', True)},
         outputs={'settings': OBJ('AI settings.'), 'providers': ARR('Providers.')}),
    dict(id='ai_configure', name='Configure AI',
         description='Choose the AI provider and model and the assistant limits. API keys are not accepted here; '
                     'store them in the window (Options > AI) or in the provider environment variable.',
         inputs={'provider': S('Provider id.', enum=PROVIDERS[1:]), 'model': S('Model id (empty = provider default).'),
                 'transport': S('Transport for agent CLIs (empty = preferred).'),
                 'temperature': {'type': ['number', 'null'], 'description': 'Sampling temperature (null = default).'},
                 'maxTokens': I('Maximum tokens per reply.', None, 256, 200000),
                 'maxToolSteps': I('Tool calls allowed per question.', None, 1, 60),
                 'allowEdits': B('Let the assistant rename and comment when asked.'),
                 'verifyRounds': I('Repair rounds after a failed compile check.', None, 0, 10),
                 'providers': OBJ('Per-provider options: {"ollama": {"base_url": "..."}}; keys: base_url, '
                                  'timeout_seconds, executable.')},
         outputs={'settings': OBJ('Saved settings.')}),
    dict(id='ai_explain', name='AI: explain',
         description='Explain a function/unit in Markdown: summary, step by step, inputs/outputs, notable details.',
         inputs={'projectId': PROJECT, 'function': FUNCTION, 'engine': ENGINE, 'language': LANGUAGE,
                 'provider': AI_PROVIDER, 'model': AI_MODEL},
         required=['projectId', 'function'], groups=['ai'], network=True, permissions=['network', 'processSpawn'],
         outputs={'text': S('Explanation (Markdown).')}),
    dict(id='ai_rename', name='AI: rename',
         description='Propose names for the function and its variables (and a one-line comment); apply=true '
                     'stores them as renames.',
         inputs={'projectId': PROJECT, 'function': FUNCTION, 'engine': ENGINE,
                 'apply': B('Apply the proposal.', False), 'provider': AI_PROVIDER, 'model': AI_MODEL},
         required=['projectId', 'function'], groups=['ai'], network=True, permissions=['network', 'processSpawn'],
         outputs={'functionName': S('Proposed function name.'), 'variables': ARR('Proposed variable names.')}),
    dict(id='ai_convert', name='AI: convert to source',
         description='Turn pseudo-code, disassembly or bytecode into clean compilable source in a target language, '
                     'then compile-check it and let the AI repair errors.',
         inputs={'projectId': PROJECT, 'function': FUNCTION, 'engine': ENGINE,
                 'target': S('Target language; same keeps the source language (asm -> C).', enum=TARGETS, default='same'),
                 'verify': B('Compile-check and repair.', True),
                 'instructions': S('Extra instructions for the rewrite.', default=''),
                 'language': LANGUAGE, 'provider': AI_PROVIDER, 'model': AI_MODEL},
         required=['projectId', 'function'], groups=['ai'], network=True, permissions=['network', 'processSpawn'],
         outputs={'code': S('Converted source.'), 'verification': S('passed, failed, unavailable or skipped.'),
                  'file': S('Saved file.')}),
    dict(id='ai_ask', name='AI: ask',
         description='Ask a question about the program. The assistant navigates the analysis with tools (list, '
                     'decompile, xrefs, strings, search) and answers; conversations can be continued.',
         inputs={'projectId': PROJECT, 'question': S('Question.'), 'function': S('Currently open unit (context).', default=''),
                 'engine': ENGINE, 'conversationId': S('Continue this conversation.', default=''),
                 'allowEdits': B('Allow rename/comment tools.'), 'language': LANGUAGE,
                 'provider': AI_PROVIDER, 'model': AI_MODEL},
         required=['projectId', 'question'], groups=['ai'], network=True, permissions=['network', 'processSpawn'],
         outputs={'answer': S('Answer (Markdown).'), 'conversationId': S('Conversation id.'), 'tools': ARR('Tool calls.')}),
    dict(id='ai_batch_rename', name='AI: name functions',
         description='Name many auto-named functions (FUN_*, sub_*) in one job and apply the names.',
         inputs={'projectId': PROJECT, 'engine': ENGINE, 'limit': I('Functions to process.', 20, 1, 2000),
                 'onlyUnnamed': B('Only functions with generated names.', True),
                 'provider': AI_PROVIDER, 'model': AI_MODEL},
         required=['projectId'], groups=['ai'], network=True, permissions=['network', 'processSpawn'],
         outputs={'results': ARR('Per-function results.')}),
    dict(id='ai_conversations', name='AI: conversations', description='Conversations stored for a project.',
         inputs={'projectId': PROJECT}, required=['projectId'], outputs={'conversations': ARR('Conversations.')}),
    dict(id='ai_conversation', name='AI: conversation', description='Turns of one conversation.',
         inputs={'projectId': PROJECT, 'conversationId': S('Conversation id.')},
         required=['projectId', 'conversationId'], outputs={'turns': ARR('Turns.')}),
    # ------------------------------------------------------------------ application updates
    dict(id='update_state', name='Update state', description='Installed version, configured repository, staged update and kept versions.',
         inputs={}, outputs={'current': S('Installed version.')}),
    dict(id='update_configure', name='Configure updates',
         description='Set the GitHub repository (owner/name) that publishes CyDecompilator releases, and automatic checks.',
         inputs={'repository': S('owner/name, or empty to clear.'), 'automaticCheck': B('Check at start-up.')},
         groups=['install'], outputs={'applicationRepository': S('Configured repository.')}),
    dict(id='update_check', name='Check for updates', description='Ask GitHub for the latest application release.',
         inputs={}, network=True, permissions=['network', 'processSpawn'], outputs={'updateAvailable': B('A newer release exists.')}),
    dict(id='update_download', name='Download update',
         description='Download a release into runtime/updates and verify it (identity, runtime ABI, digest, compilation).',
         inputs={'version': S('Release tag; empty = latest.', default='')}, groups=['install'], network=True,
         permissions=['network', 'processSpawn'], ram=512 * 1024 ** 2, outputs={'staged': B('Staged and verified.')}),
    dict(id='update_apply', name='Apply update',
         description='Activate the staged update (keeps the current app/ in runtime/backups; data/ is untouched). Restart afterwards.',
         inputs={}, groups=['install'], permissions=['processSpawn'], outputs={'applied': B('Applied.')}),
    dict(id='update_rollback', name='Restore previous version', description='Restore the app/ kept by the last update.',
         inputs={}, groups=['install'], outputs={'restored': B('Restored.')}),
]
