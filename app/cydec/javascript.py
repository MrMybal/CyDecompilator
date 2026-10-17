"""Bounded immutable application snapshots and inert JS/TS/Electron/web analysis."""
import hashlib
import json
import os
import posixpath
import shutil
import struct
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from cytools_core import CyToolError
from . import components, investigation as inv, process
from .paths import read_json, write_json

MAX_FILES, MAX_BYTES, MAX_FILE = 10000, 128 * 1024 ** 2, 16 * 1024 ** 2
SOURCE_SUFFIXES = {'.js', '.cjs', '.mjs', '.ts', '.tsx', '.jsx'}
IGNORED = {'.git', '.svn', '.hg', 'node_modules', 'bin', 'obj', '.cydec'}


def safe_relative(value):
    value = str(value).replace('\\', '/')
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(p in ('..', '') or ':' in p for p in path.parts):
        raise CyToolError('IntegrityFailure', 'Unsafe application artifact path.')
    # Preserve names exactly; Windows cannot represent trailing dots/spaces or device names.
    if any(p.endswith(('.', ' ')) or p.split('.')[0].upper() in
           {'CON', 'PRN', 'AUX', 'NUL', *('COM%d' % i for i in range(1, 10)),
            *('LPT%d' % i for i in range(1, 10))} for p in path.parts):
        raise CyToolError('IntegrityFailure', 'Unsafe application artifact path.')
    return path.as_posix()


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def read_tree(root, context, excluded_directories=()):
    """No symlinks/reparse traversal, bounded reads, report every excluded subtree."""
    root = Path(root).absolute()
    if not root.is_dir() or any(is_link(p) for p in (root, *root.parents)):
        raise CyToolError('InvalidParameters', 'Select a regular application folder without links.')
    files, skipped, total = {}, [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        context.check()
        base = Path(directory)
        kept = []
        for name in sorted(dirs):
            path = base / name
            if name in IGNORED or name in excluded_directories or is_link(path):
                skipped.append({'code': 'excluded-directory', 'path': path.relative_to(root).as_posix()})
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            path = base / name
            relative = safe_relative(path.relative_to(root).as_posix())
            if is_link(path) or not path.is_file():
                skipped.append({'code': 'excluded-link', 'path': relative})
                continue
            size = path.stat().st_size
            if len(files) >= MAX_FILES or size > MAX_FILE or total + size > MAX_BYTES:
                skipped.append({'code': 'snapshot-limit', 'path': relative, 'size': size})
                continue
            data = path.read_bytes()
            if len(data) > MAX_FILE or total + len(data) > MAX_BYTES:
                raise CyToolError('InvalidParameters', 'The application changed during capture; retry.')
            files[relative], total = data, total + len(data)
    return files, skipped


def read_asar(path, context):
    """Parse the official Pickle layout without executing Electron or archive links."""
    files, skipped, total = {}, [], 0
    with Path(path).open('rb') as stream:
        prefix = stream.read(16)
        if len(prefix) != 16:
            raise CyToolError('InvalidParameters', 'Invalid ASAR header.')
        outer, header_size, payload_size, json_size = struct.unpack('<IIII', prefix)
        if outer != 4 or not 8 <= header_size <= 16 * 1024 ** 2 or payload_size + 4 != header_size or json_size > header_size - 8:
            raise CyToolError('InvalidParameters', 'Invalid ASAR header.')
        try:
            header = json.loads(stream.read(json_size))
        except (ValueError, UnicodeError):
            raise CyToolError('InvalidParameters', 'Invalid ASAR header.')
        data_start, archive_size = 8 + header_size, Path(path).stat().st_size
        seen = set()

        def walk(entries, prefix='', depth=0):
            nonlocal total
            if depth > 64 or not isinstance(entries, dict) or len(entries) > 100000:
                raise CyToolError('InvalidParameters', 'Invalid ASAR directory.')
            for name, entry in entries.items():
                context.check()
                relative = safe_relative(prefix + name)
                if '/' in name or '\\' in name or relative.casefold() in seen or not isinstance(entry, dict):
                    raise CyToolError('IntegrityFailure', 'Unsafe application artifact path.')
                seen.add(relative.casefold())
                if 'files' in entry:
                    if name in IGNORED:
                        skipped.append({'code': 'excluded-directory', 'path': relative})
                    else:
                        walk(entry['files'], relative + '/', depth + 1)
                    continue
                if 'link' in entry:
                    skipped.append({'code': 'excluded-link', 'path': relative})
                    continue
                size = entry.get('size')
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    raise CyToolError('InvalidParameters', 'Invalid ASAR file bounds.')
                if len(files) >= MAX_FILES or size > MAX_FILE or total + size > MAX_BYTES:
                    skipped.append({'code': 'snapshot-limit', 'path': relative, 'size': size})
                    continue
                if entry.get('unpacked'):
                    root = Path(str(path) + '.unpacked')
                    target = root / relative
                    if not target.is_file() or any(is_link(p) for p in (target, *target.parents)):
                        skipped.append({'code': 'missing-unpacked-file', 'path': relative})
                        continue
                    if target.stat().st_size != size:
                        raise CyToolError('IntegrityFailure', 'ASAR file integrity verification failed.')
                    data = target.read_bytes()
                else:
                    try:
                        offset = int(entry['offset'])
                    except (ValueError, KeyError, TypeError):
                        raise CyToolError('InvalidParameters', 'Invalid ASAR file bounds.')
                    if offset < 0 or data_start + offset + size > archive_size:
                        raise CyToolError('InvalidParameters', 'Invalid ASAR file bounds.')
                    stream.seek(data_start + offset)
                    data = stream.read(size)
                integrity = entry.get('integrity', {})
                if len(data) != size or (integrity and (integrity.get('algorithm') != 'SHA256' or
                        hashlib.sha256(data).hexdigest() != integrity.get('hash'))):
                    raise CyToolError('IntegrityFailure', 'ASAR file integrity verification failed.')
                files[relative], total = data, total + size
        walk(header.get('files'))
    return files, skipped


def artifact_root(project):
    return project.dir / 'input/artifacts'


def open_application(store, path, context):
    path = Path(path).absolute()
    context.check()
    if path.is_dir():
        files, skipped = read_tree(path, context)
        kind = 'folder'
    elif path.is_file() and path.suffix.lower() == '.asar':
        files, skipped = read_asar(path, context)
        kind = 'asar'
    elif path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES | {'.html', '.htm'}:
        files, skipped, kind = {safe_relative(path.name): path.read_bytes()}, [], 'source'
        if len(files[path.name]) > MAX_FILE:
            raise CyToolError('InvalidParameters', 'Select an application artifact smaller than 16 MB.')
    else:
        raise CyToolError('InvalidParameters', 'Select an application folder, ASAR, JavaScript, TypeScript or HTML file.')
    if not files:
        raise CyToolError('InvalidParameters', 'No application artifacts could be captured.')
    manifest = {'cydecApplication': 1, 'kind': kind,
                'files': [{'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(files.items())], 'unknowns': skipped[:1000] +
                ([{'code': 'snapshot-exclusion-limit', 'omitted': len(skipped)-1000}] if len(skipped)>1000 else [])}
    marker = Path(context.workdir) / (path.stem + '.cyapp.json')
    write_json(marker, manifest)
    project, created = store.open(marker, str(path), context.cancellation)
    with project.lock:
        root = artifact_root(project)
        for name, data in files.items():
            target = root / name
            if target.exists() and hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(data).digest():
                raise CyToolError('IntegrityFailure', 'The application snapshot has changed; open it again.')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        meta = project.meta()
        meta['detect'] = {'format': 'javascript-app', 'formatName': 'JavaScript / Electron / Web',
                          'engines': ['javascript'], 'size': sum(len(d) for d in files.values())}
        meta['name'] = path.name
        write_json(project.meta_path, meta)
    return project


class HtmlFacts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.facts = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        line, column = self.getpos()
        for attr in ('src', 'href', 'action'):
            if attrs.get(attr):
                self.facts.append({'kind': 'resource', 'label': attrs[attr], 'line': line, 'column': column + 1,
                                   'details': {'value': attrs[attr], 'element': tag, 'attribute': attr}})
        if attrs.get('id'):
            self.facts.append({'kind': 'ui', 'label': attrs['id'], 'line': line, 'column': column + 1,
                               'details': {'element': tag, 'attributes': attrs}})
    def handle_data(self, data):
        if data.strip():
            line, column = self.getpos()
            self.facts.append({'kind': 'ui', 'label': data.strip()[:600], 'line': line, 'column': column + 1,
                               'details': {}})


def _resolve(file, value, available, module=False):
    if not isinstance(value, str) or '://' in value or value.startswith(('data:', '#')):
        return None
    value = value.split('?', 1)[0].split('#', 1)[0]
    if module and not value.startswith('.'):
        return None
    normalized = posixpath.normpath(posixpath.join(posixpath.dirname(file), value))
    candidates = [normalized]
    if module:
        candidates += [normalized + ext for ext in ('.js', '.ts', '.mjs', '.cjs', '.tsx', '.jsx')]
        candidates += [normalized + '/index' + ext for ext in ('.js', '.ts', '.mjs', '.cjs')]
    matches = [p for p in candidates if p in available]
    return matches[0] if len(matches) == 1 else None


def analyze(project, context):
    manifest = read_json(project.binary)
    if manifest.get('cydecApplication') != 1:
        raise CyToolError('InvalidParameters', 'Open an application snapshot first.')
    root, report = artifact_root(project), inv.graph(project, 'javascript')
    for item in manifest.get('unknowns', []):
        inv.unknown(report, **item)
    inv.unknown(report, 'static-analysis-does-not-prove-execution')
    inv.unknown(report, 'dynamic-code-and-framework-routing-not-resolved')
    available, sources, units = {}, [], []
    entries = {r['path']: r for r in manifest['files']}
    total_source = 0
    for item in manifest['files']:
        context.check()
        name = item['path']
        data = (root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise CyToolError('IntegrityFailure', 'The application snapshot has changed; open it again.')
        available[name] = inv.node(report, 'file', name, {'path': name, 'sha256': item['sha256']}, size=len(data))
        if Path(name).suffix.lower() in SOURCE_SUFFIXES:
            if len(data) > 4 * 1024 ** 2 or total_source + len(data) > 32 * 1024 ** 2:
                inv.unknown(report, 'source-parser-limit', path=name)
            else:
                total_source += len(data)
                sources.append({'path': name, 'absolute': str(root / name)})
    facts, maps = [], {}
    if sources:
        parser = components.locate('typescript')
        node = shutil.which('node')
        if not parser or not node:
            raise CyToolError('MissingDependency', 'Install the TypeScript parser component and Node.js to analyze application sources.')
        request, output = Path(context.workdir) / 'js-request.json', Path(context.workdir) / 'js-result.json'
        write_json(request, {'files': sources})
        helper = Path(__file__).resolve().parents[1] / 'javascript/inspect.cjs'
        code, out, err = process.run([node, '--max-old-space-size=512', str(helper), parser['parser'], str(request), str(output)],
                                     context=context, timeout=180, log_name='javascript-ast',
                                     env={'NODE_OPTIONS': None, 'NODE_PATH': None})
        if code != 0 or not output.is_file():
            raise CyToolError('EngineFailed', 'JavaScript AST analysis failed: ' + process.tail(err or out, 8))
        parsed = read_json(output)
        report['parserVersion'] = parsed['parserVersion']
        for result in parsed['results']:
            name, local = result['path'], {}
            for item in result['unknowns']:
                inv.unknown(report, **item, path=name)
            for item in result['facts']:
                if len(report['nodes']) >= 60000:
                    report['truncated'] = True
                    inv.unknown(report, 'graph-node-limit')
                    break
                location = {'path': name, 'sha256': entries[name]['sha256'],
                            **{k: item[k] for k in ('line', 'column', 'start', 'end')}}
                key = inv.node(report, item['kind'], item['label'], location, **item['details'])
                local[item['key']] = key
                # Ownership by function keeps feature queries focused; top-level facts belong to the file.
                inv.edge(report, local.get(item.get('owner'), available[name]), key, 'contains', location)
                if item['details'].get('call') in local:
                    inv.edge(report, key, local[item['details']['call']], 'at-call', location)
                facts.append((name, key, item))
            units.append({'id': name, 'name': name, 'kind': 'code', 'size': (root / name).stat().st_size,
                          'hasCode': True, 'callees': [], 'callers': []})
    for name in available:
        context.check()
        if Path(name).suffix.lower() in ('.html', '.htm') and (root / name).stat().st_size <= 4 * 1024 ** 2:
            parser = HtmlFacts()
            parser.feed((root / name).read_text('utf-8', 'replace'))
            for item in parser.facts[:10000]:
                if len(report['nodes']) >= 60000:
                    inv.unknown(report, 'graph-node-limit')
                    report['truncated'] = True
                    break
                location = {'path': name, 'sha256': entries[name]['sha256'],
                            'line': item['line'], 'column': item['column']}
                key = inv.node(report, item['kind'], item['label'], location, **item['details'])
                inv.edge(report, available[name], key, 'contains', location)
                facts.append((name, key, item))
            units.append({'id': name, 'name': name, 'kind': 'code', 'hasCode': True})
        if Path(name).suffix.lower() == '.map':
            try:
                sm = json.loads((root / name).read_text('utf-8-sig'))
                if sm.get('version') != 3 or not isinstance(sm.get('sources'), list):
                    raise ValueError()
                for index, original in enumerate(sm['sources'][:5000]):
                    if len(report['nodes']) >= 60000:
                        inv.unknown(report, 'graph-node-limit')
                        report['truncated'] = True
                        break
                    embedded = (sm.get('sourcesContent') or [])
                    data = embedded[index] if index < len(embedded) else None
                    key = inv.node(report, 'original-source', str(original), {'path': name, 'sha256': entries[name]['sha256'], 'sourceIndex': index},
                                   sourceRoot=sm.get('sourceRoot', ''), embedded=isinstance(data, str),
                                   contentSha256=hashlib.sha256(data.encode()).hexdigest() if isinstance(data, str) else None)
                    inv.edge(report, available[name], key, 'source-map-metadata')
                from .source_maps import decode
                maps[name] = (sm, decode(sm.get('mappings', ''), len(sm['sources']), len(sm.get('names', []))))
                if sm.get('sections'):
                    inv.unknown(report, 'indexed-source-map-not-supported', path=name)
            except (ValueError, TypeError, AttributeError):
                inv.unknown(report, 'invalid-source-map', path=name)
    ipc, functions_by_name, ui_elements, bridges = {}, {}, {}, {}
    for name, key, item in facts:
        if item['kind'] == 'function' and item['label'] != '<callback>':
            functions_by_name.setdefault((name,item['label']),[]).append(key)
        if item['kind'] == 'ui':
            ui_elements.setdefault(item['label'],[]).append(key)
        if item['kind'] == 'bridge' and item['details'].get('value'):
            for method in item['details']['methods']:
                bridges.setdefault('window.'+item['details']['value']+'.'+method,[]).append(key)
    source_map_links = {}
    for name, key, item in facts:
        kind, value = item['kind'], item['details'].get('value')
        if kind == 'source-map' and value:
            target = _resolve(name, value, available)
            if target and target in maps:
                source_map_links[name] = target
                inv.edge(report, key, available[target], 'resolves-to')
            else:
                inv.unknown(report, 'unresolved-source-map', path=name)
        if kind in ('module', 'preload', 'resource') and value:
            target = _resolve(name, value, available, module=kind == 'module')
            if target:
                inv.edge(report, key, available[target], 'resolves-to', status='inferred')
            elif kind != 'resource' or not str(value).startswith(('http:', 'https:')):
                inv.unknown(report, 'unresolved-artifact', path=name, value=value)
        if kind == 'ipc' and value is not None:
            ipc.setdefault((value,item['details']['direction']), {'sender': [], 'handler': []})[item['details']['role']].append(key)
        if kind == 'call':
            targets = functions_by_name.get((name,item['details']['callee']),[])
            if len(targets) == 1:
                inv.edge(report,key,targets[0],'local-call-candidate',status='inferred')
            bridge_targets = bridges.get(item['details']['callee'],[])
            if len(bridge_targets)==1:
                inv.edge(report,key,bridge_targets[0],'bridge-api-candidate',status='inferred')
            elif len(bridge_targets)>1:
                inv.unknown(report,'ambiguous-bridge-api',path=name,value=item['details']['callee'])
        if kind == 'ui-binding':
            for element in ui_elements.get(value,[]):
                inv.edge(report,element,key,'ui-event-candidate',status='inferred')
            targets = functions_by_name.get((name,item['details']['callback']),[])
            if len(targets)==1:
                inv.edge(report,key,targets[0],'event-callback-candidate',status='inferred')
    for (channel,direction), roles in ipc.items():
        if len(roles['handler']) == 1:
            for sender in roles['sender']:
                inv.edge(report, sender, roles['handler'][0], 'ipc-channel-candidate', status='inferred')
        else:
            inv.unknown(report, 'ambiguous-or-missing-ipc-handler', channel=channel, direction=direction, handlers=len(roles['handler']))
    from .source_maps import lookup
    for name, key, item in facts:
        if name not in source_map_links:
            continue
        map_name = source_map_links[name]
        sm, decoded = maps[map_name]
        mapped = lookup(decoded, item['line'], item['column'])
        if mapped:
            original = inv.node(report, 'original-position', sm['sources'][mapped['source']],
                {'path': map_name, 'sha256': entries[map_name]['sha256'], 'sourceIndex': mapped['source'], 'line': mapped['line'] + 1,
                 'column': mapped['originalColumn'] + 1}, sourceRoot=sm.get('sourceRoot', ''),
                 mappedName=sm.get('names', [])[mapped['name']] if 'name' in mapped else '')
            inv.edge(report, key, original, 'source-map-position', status='inferred')
    if manifest['unknowns'] or any(u['code'].endswith('limit') for u in report['unknowns']):
        report['truncated'] = True
    inv.save(project, report)
    return {'functions': units, 'strings': [], 'imports': [], 'sections': [],
            'program': {'name': project.meta()['name'], 'parserVersion': report.get('parserVersion', ''),
                        'artifacts': len(available), 'evidenceNodes': len(report['nodes'])},
            'message': 'Static application analysis; consult Investigation for evidence and unknowns.'}
