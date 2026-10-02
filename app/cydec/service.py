"""The business API shared by the interface, the CLI and MCP.

Every Runtime handler in tool.py is a thin wrapper around one function here, so the
desktop window and an AI client reach exactly the same behaviour. Functions take an
EngineContext for long work (cancellation, progress, log, workdir) and return plain JSON.
"""
import re
import shutil
import time
from pathlib import Path

from cytools_core import CyToolError

from . import components
from .engines import ENGINES, get as get_engine
from .project import ProjectStore

store = ProjectStore()

MAX_PAGE = 200000


# ---------------------------------------------------------------------- engines

def engines_status():
    result = []
    for engine in ENGINES.values():
        item = engine.descriptor()
        item.update(engine.availability())
        result.append(item)
    return result


def choose_engine(project, engine_id=''):
    """The requested engine, or the best available one for the detected format."""
    detected = project.meta()['detect']
    if engine_id:
        engine = get_engine(engine_id)
        if not engine.accepts(detected):
            raise CyToolError('Unsupported', '%s does not handle %s files. Suitable engines: %s'
                              % (engine.name, detected['formatName'], ', '.join(detected['engines']) or 'none'))
        return engine
    from .detect import ENGINES_BY_FORMAT
    # Current order for the format (projects created before an engine existed keep working).
    candidates = [c for c in ENGINES_BY_FORMAT.get(detected.get('format'), detected.get('engines', []))
                  if c in ENGINES and ENGINES[c].accepts(detected)]
    if not candidates:
        raise CyToolError('Unsupported', 'No engine handles %s files.' % detected['formatName'])
    for candidate in candidates:
        if ENGINES[candidate].availability()['available']:
            return ENGINES[candidate]
    raise CyToolError('MissingDependency', 'No installed engine for %s. Install one of: %s'
                      % (detected['formatName'], ', '.join(candidates)), recoverable=True)


# ---------------------------------------------------------------------- projects

def open_file(path, context=None, source_path=''):
    project, created = store.open(path, source_path=source_path,
                                  cancellation=getattr(context, 'cancellation', None))
    summary = project.summary()
    summary['created'] = created
    return summary


def project_for(project_id):
    return store.get(project_id)


def analyze(project_id, engine_id='', context=None, force=False):
    project = store.get(project_id)
    engine = choose_engine(project, engine_id)
    if project.has_analysis(engine.id) and not force:
        summary = project.summary()
        summary.update(engine=engine.id, reused=True)
        return summary
    engine.require()
    started = time.monotonic()
    context.log('Analyzing %s with %s' % (project.meta()['name'], engine.name))
    analysis = engine.analyze(project, context)
    code = analysis.pop('_code', [])
    context.progress(97, 'Saving project')
    project.save_analysis(engine.id, analysis, time.monotonic() - started)
    for unit_id, text in code:
        project.store_code(engine.id, unit_id, text)
    context.progress(100, 'Done')
    summary = project.summary()
    summary.update(engine=engine.id, reused=False, message=analysis.get('message', ''))
    return summary


def _name_map(project, engine_id):
    symbols = project.annotations()['symbols']
    return {f['id']: symbols.get(f.get('name', ''), f.get('name', '')) for f in project.functions(engine_id)}


def _public(project, function, names=None, detail=False):
    names = names or {}
    notes = project.annotations()
    item = {k: function[k] for k in ('id', 'name', 'address', 'size', 'kind', 'signature', 'parent',
                                     'thunk', 'exported', 'lines', 'instructionCount')
            if k in function}
    item['displayName'] = notes['symbols'].get(function.get('name', ''), function.get('name', ''))
    item['hasComment'] = function['id'] in notes['comments']
    if detail:
        item['callers'] = [{'id': c, 'name': names.get(c, c)} for c in function.get('callers', [])]
        item['callees'] = [{'id': c, 'name': names.get(c, c)} for c in function.get('callees', [])]
        for key in ('imports', 'strings', 'callingConvention'):
            if key in function:
                item[key] = function[key]
        item['comment'] = notes['comments'].get(function['id'], '')
        item['localRenames'] = notes['locals'].get(function['id'], {})
    return item


def list_functions(project_id, engine_id='', query='', offset=0, limit=500, kind=''):
    project = store.get(project_id)
    engine_id = project.resolve_engine(engine_id)
    functions = project.functions(engine_id)
    notes = project.annotations()
    pattern = query.lower().strip()
    selected = []
    for function in functions:
        if kind and function.get('kind') != kind:
            continue
        if pattern:
            display = notes['symbols'].get(function.get('name', ''), function.get('name', ''))
            haystack = ' '.join(str(function.get(k, '')) for k in ('id', 'name', 'address', 'parent')) + ' ' + display
            if pattern not in haystack.lower():
                continue
        selected.append(function)
    limit = max(1, min(int(limit), MAX_PAGE))
    page = selected[int(offset):int(offset) + limit]
    return {'projectId': project.id, 'engine': engine_id, 'total': len(functions),
            'matched': len(selected), 'offset': int(offset),
            'functions': [_public(project, f) for f in page]}


def function_info(project_id, function, engine_id=''):
    project = store.get(project_id)
    engine_id = project.resolve_engine(engine_id)
    record = project.find_function(engine_id, function)
    return {'projectId': project.id, 'engine': engine_id,
            'function': _public(project, record, _name_map(project, engine_id), detail=True)}


def decompile(project_id, function, engine_id='', context=None, refresh=False, view='decompiled',
              annotate=True):
    """Code of one unit. view: 'decompiled' (pseudo/source) or 'disassembly'."""
    project = store.get(project_id)
    engine_id = project.resolve_engine(engine_id)
    engine = get_engine(engine_id)
    analysis = project.analysis(engine_id)
    record = project.find_function(engine_id, function)
    kind = 'disassembly' if view == 'disassembly' or not engine.supports_decompile else 'decompiled'
    if kind == 'disassembly' and not engine.supports_disassemble:
        raise CyToolError('Unsupported', '%s has no disassembly view.' % engine.name)
    cached = None if refresh else project.cached_code(engine_id, record['id'], kind)
    language = engine.language if kind == 'decompiled' else 'asm'
    if cached is None:
        if context is not None:
            context.progress(5, 'Decompiling ' + record.get('name', record['id']))
        result = (engine.disassemble if kind == 'disassembly' else engine.decompile)(
            project, analysis, record, context)
        cached = result['code']
        language = result.get('language', language)
        project.store_code(engine_id, record['id'], cached, kind)
        project.store_code(engine_id, record['id'], language, kind + '.language')
        from_cache = False
    else:
        language = project.cached_code(engine_id, record['id'], kind + '.language') or (
            engine.language if kind == 'decompiled' else 'asm')
        from_cache = True
    code = project.apply_annotations(cached, record['id']) if annotate else cached
    return {'projectId': project.id, 'engine': engine_id, 'function': _public(project, record),
            'view': kind, 'language': language.strip(), 'code': code, 'cached': from_cache,
            'note': '' if engine.supports_decompile or view == 'disassembly' else
                    '%s shows disassembly only. Use Ghidra, CyDecompilator C or the AI "lift" action for C.' % engine.name}


def xrefs(project_id, function, engine_id=''):
    info = function_info(project_id, function, engine_id)['function']
    return {'projectId': project_id, 'function': info['id'], 'name': info['displayName'],
            'callers': info.get('callers', []), 'callees': info.get('callees', []),
            'imports': info.get('imports', [])}


def strings(project_id, engine_id='', query='', offset=0, limit=500):
    project = store.get(project_id)
    engine_id = project.resolve_engine(engine_id)
    items = project.analysis(engine_id).get('strings', [])
    pattern = query.lower()
    if pattern:
        items = [s for s in items if pattern in s.get('text', '').lower()]
    limit = max(1, min(int(limit), MAX_PAGE))
    return {'projectId': project.id, 'engine': engine_id, 'matched': len(items),
            'strings': items[int(offset):int(offset) + limit]}


def program_info(project_id, engine_id=''):
    project = store.get(project_id)
    summary = project.summary()
    engine_id = engine_id or project.default_engine()
    if engine_id and project.has_analysis(engine_id):
        analysis = project.analysis(engine_id)
        summary['engine'] = engine_id
        for key in ('arch', 'bits', 'imageBase', 'entryPoint', 'program', 'sections', 'exports',
                    'resources', 'shader', 'python', 'message', 'pe'):
            if key in analysis:
                summary[key] = analysis[key]
        summary['imports'] = analysis.get('imports', [])[:2000]
        summary['importCount'] = len(analysis.get('imports', []))
        summary['stringCount'] = len(analysis.get('strings', []))
        summary['functionCount'] = len(analysis.get('functions', []))
    if 'pe' not in summary and project.meta()['detect']['format'] in ('pe', 'pe-dotnet'):
        try:
            from . import pe_info
            summary['pe'] = pe_info.analyse(project.binary)
        except Exception:
            pass
    if summary.get('pe'):
        from . import pe_info
        summary['peSummary'] = pe_info.summary_lines(summary['pe'])
    extracted = project.dir / 'extracted'
    if extracted.is_dir():
        summary['extracted'] = sorted(p.name for p in extracted.iterdir() if p.is_dir())
    summary['annotations'] = project.annotations()
    return summary


# ---------------------------------------------------------------------- PE extras

def extract_embedded(project_id, kind='', context=None):
    from . import unpack
    project = store.get(project_id)
    result = unpack.extract(project, kind, context)
    result['projectId'] = project.id
    return result


def extracted_files(project_id, kind):
    """Files previously extracted (kind folder), with formats, without extracting again."""
    from . import detect as detection
    project = store.get(project_id)
    folder = project.dir / 'extracted' / kind
    if not folder.is_dir():
        raise CyToolError('NotFound', 'Nothing extracted for %s yet.' % kind)
    files = []
    for path in sorted(folder.rglob('*')):
        if path.is_file():
            record = detection.detect(path)
            files.append({'name': path.relative_to(folder).as_posix(), 'path': str(path), 'format': record['format'],
                          'size': record['size'], 'openable': bool(record['engines'])})
    return {'projectId': project.id, 'kind': kind, 'directory': str(folder), 'files': files}


def load_symbols(project_id, context=None, force=True):
    from . import symbols
    project = store.get(project_id)
    loaded = symbols.for_project(project, context, force=force)
    return {'projectId': project.id, 'pdb': loaded.get('pdb'), 'status': loaded.get('status'),
            'symbols': len(loaded.get('symbols', [])),
            'functions': sum(1 for s in loaded.get('symbols', []) if s['kind'] == 'function'),
            'note': 'Re-analyze the project to apply the names to the function list and to Ghidra.'}


def search(project_id, query, engine_id='', in_code=True, limit=200):
    project = store.get(project_id)
    engine_id = project.resolve_engine(engine_id)
    if not query:
        raise CyToolError('InvalidParameters', 'Empty search query.')
    pattern = query.lower()
    hits = []
    names = _name_map(project, engine_id)
    for function in project.functions(engine_id):
        if pattern in (function.get('name', '') + ' ' + names.get(function['id'], '')).lower():
            hits.append({'type': 'function', 'id': function['id'], 'name': names.get(function['id'])})
        elif in_code:
            text = project.cached_code(engine_id, function['id'])
            if text and pattern in text.lower():
                line = next((l.strip() for l in text.splitlines() if pattern in l.lower()), '')
                hits.append({'type': 'code', 'id': function['id'], 'name': names.get(function['id']),
                             'line': line[:200]})
        if len(hits) >= limit:
            break
    for item in project.analysis(engine_id).get('strings', []):
        if len(hits) >= limit:
            break
        if pattern in item.get('text', '').lower():
            hits.append({'type': 'string', 'address': item.get('address', ''), 'text': item['text'][:200]})
    return {'projectId': project.id, 'engine': engine_id, 'query': query, 'hits': hits,
            'truncated': len(hits) >= limit}


# ---------------------------------------------------------------------- annotations

IDENT = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$]*$')


def rename(project_id, old, new, function='', engine_id=''):
    """Rename a global symbol (function, global) or, with `function`, a local identifier."""
    project = store.get(project_id)
    old, new = str(old).strip(), str(new).strip()
    if not IDENT.match(new):
        raise CyToolError('InvalidParameters', 'The new name must be a valid identifier: %r' % new)
    function_id = ''
    if function:
        engine_id = project.resolve_engine(engine_id)
        function_id = project.find_function(engine_id, function)['id']

    def mutate(notes):
        if function_id:
            locals_ = notes['locals'].setdefault(function_id, {})
            original = next((k for k, v in locals_.items() if v == old), old)
            if original == new:
                locals_.pop(original, None)
            else:
                locals_[original] = new
        else:
            original = next((k for k, v in notes['symbols'].items() if v == old), old)
            if original == new:
                notes['symbols'].pop(original, None)
            else:
                notes['symbols'][original] = new
    notes = project.update_annotations(mutate)
    return {'projectId': project.id, 'old': old, 'new': new, 'scope': function_id or 'global',
            'symbols': len(notes['symbols'])}


def rename_many(project_id, renames, function='', engine_id=''):
    applied, errors = [], []
    for old, new in renames.items():
        try:
            rename(project_id, old, new, function, engine_id)
            applied.append({'old': old, 'new': new})
        except CyToolError as exc:
            errors.append({'old': old, 'new': new, 'error': str(exc)})
    return {'applied': applied, 'errors': errors}


def set_comment(project_id, function, text, engine_id=''):
    project = store.get(project_id)
    engine_id = project.resolve_engine(engine_id)
    function_id = project.find_function(engine_id, function)['id']

    def mutate(notes):
        if text.strip():
            notes['comments'][function_id] = text.strip()
        else:
            notes['comments'].pop(function_id, None)
    project.update_annotations(mutate)
    return {'projectId': project.id, 'function': function_id, 'comment': text.strip()}


def set_notes(project_id, text):
    project = store.get(project_id)
    project.update_annotations(lambda notes: notes.__setitem__('notes', str(text)))
    return {'projectId': project.id, 'notes': str(text)}


# ---------------------------------------------------------------------- export

EXTENSIONS = {'c': '.c', 'csharp': '.cs', 'java': '.java', 'python': '.py', 'hlsl': '.hlsl',
              'glsl': '.glsl', 'asm': '.asm', 'il': '.il', 'xml': '.xml', 'jvm': '.txt'}


def c_module(project_id, functions=(), destination='', include_callees=True, context=None):
    """Recompilable C (built-in decompiler) for some functions and their callees, as one file.

    functions: references (id, name or address); empty = every exported function, or the entry
    point when nothing is exported."""
    project = store.get(project_id)
    engine = get_engine('cdec')
    if not engine.accepts(project.meta()['detect']):
        raise CyToolError('Unsupported', 'The built-in C decompiler handles x86 / x86-64 / ARM64 PE and ELF files only.')
    if not project.has_analysis('cdec'):
        analyze(project_id, 'cdec', context)
    analysis = project.analysis('cdec')
    if functions:
        records = [project.find_function('cdec', reference) for reference in functions]
    else:
        records = [f for f in analysis['functions'] if f.get('exported')]
        if not records and analysis.get('entryPoint'):
            records = [f for f in analysis['functions'] if f['address'] == analysis['entryPoint']]
        if not records:
            raise CyToolError('InvalidParameters', 'Nothing exported; name the functions to decompile.')
    code = engine.module_c(project, analysis, records, include_callees, context)
    code = project.apply_annotations(code)
    result = {'projectId': project.id, 'functions': [r['name'] for r in records],
              'lines': code.count('\n') + 1, 'language': 'c'}
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding='utf-8')
        result['path'] = str(path)
    result['code'] = code
    return result


def export_sources(project_id, destination, engine_id='', context=None, decompile_missing=False,
                   max_units=0):
    """Write every unit's code (annotations applied) under `destination`."""
    project = store.get(project_id)
    engine_id = project.resolve_engine(engine_id)
    engine = get_engine(engine_id)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    functions = project.functions(engine_id)
    if max_units:
        functions = functions[:int(max_units)]
    written, missing = 0, 0
    for index, function in enumerate(functions):
        if context is not None and index % 50 == 0:
            context.check()
            context.progress(100 * index / max(len(functions), 1), 'Exporting %d / %d' % (index, len(functions)))
        kind = 'decompiled' if engine.supports_decompile else 'disassembly'
        text = project.cached_code(engine_id, function['id'], kind)
        if text is None and decompile_missing:
            try:
                text = decompile(project_id, function['id'], engine_id, context)['code']
                written += 1
                _write_unit(destination, project, function, text, engine, kind, annotated=True)
                continue
            except CyToolError:
                text = None
        if text is None:
            missing += 1
            continue
        _write_unit(destination, project, function, project.apply_annotations(text, function['id']),
                    engine, kind, annotated=True)
        written += 1
    notes = project.annotations()
    if notes['notes']:
        (destination / 'NOTES.md').write_text(notes['notes'], encoding='utf-8')
    return {'projectId': project.id, 'engine': engine_id, 'directory': str(destination),
            'written': written, 'missing': missing}


def _write_unit(destination, project, function, text, engine, kind, annotated):
    from .project import safe_name
    language = project.cached_code(engine.id, function['id'], kind + '.language') or engine.language
    extension = EXTENSIONS.get(language.strip(), '.txt')
    if function.get('file'):
        relative = Path(function['file'])
    elif function.get('kind') in ('class', 'interface', 'struct', 'enum', 'delegate'):
        relative = Path(*function['id'].split('.')).with_suffix(extension)
    else:
        name = project.display_name(function) or function['id']
        relative = Path(safe_name(name, 100) + extension)
    target = (destination / relative).resolve()
    if not target.is_relative_to(destination.resolve()):
        target = destination / (safe_name(function['id']) + extension)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')
