"""Persistent decompilation projects.

A project is one input file, identified by its SHA256, with everything learned about it:
the detected format, one analysis per engine (functions, strings, imports...), the cached
decompiled code of each function and the user's annotations (renames, comments). Opening
the same bytes twice reuses the same project, whatever path they were opened from.

Projects are the Tool's own persistent store, like a conversation in a chat Tool: they
survive jobs and sessions. The file is copied into the project when it is created, so
deleting or moving the original later does not break the analysis.
"""
import hashlib
import re
import shutil
import threading
import time
from pathlib import Path

from cytools_core import CyToolError

from . import detect as detection
from .paths import PROJECTS, read_json, write_json

_locks = {}
_locks_guard = threading.Lock()
# Parsed analysis.json files keyed by path, invalidated by mtime/size. A large binary's
# analysis is tens of MB of JSON: re-reading it on every decompile request would dominate.
_analysis_cache = {}
_analysis_order = []
_ANALYSIS_CACHE_SIZE = 4


def _lock(project_id):
    with _locks_guard:
        return _locks.setdefault(project_id, threading.RLock())


def sha256_file(path, cancellation=None):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(1 << 20)
            if not block:
                break
            digest.update(block)
            if cancellation is not None:
                cancellation.check()
    return digest.hexdigest()


def safe_name(text, limit=80):
    value = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(text)).strip('._') or 'item'
    if len(value) > limit:
        value = value[:limit - 13] + '_' + hashlib.sha1(str(text).encode('utf-8')).hexdigest()[:12]
    return value


IDENTIFIER = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
EMPTY_ANNOTATIONS = {'symbols': {}, 'locals': {}, 'comments': {}, 'notes': ''}


class Project:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.id = self.dir.name
        self.lock = _lock(self.id)

    # ------------------------------------------------------------------ metadata

    @property
    def meta_path(self):
        return self.dir / 'project.json'

    def meta(self):
        value = read_json(self.meta_path, None)
        if not isinstance(value, dict) or 'sha256' not in value:
            raise CyToolError('NotFound', 'Project %s is missing or damaged.' % self.id)
        return value

    def update_meta(self, **changes):
        with self.lock:
            value = self.meta()
            value.update(changes)
            write_json(self.meta_path, value)
            return value

    @property
    def binary(self):
        meta = self.meta()
        return self.dir / 'input' / meta['fileName']

    def summary(self):
        meta = self.meta()
        analyses = {}
        for engine_id, record in meta.get('analyses', {}).items():
            analyses[engine_id] = {k: record.get(k) for k in
                                   ('state', 'analyzedAt', 'functionCount', 'seconds', 'message')}
        return {'projectId': self.id, 'name': meta['name'], 'fileName': meta['fileName'],
                'sha256': meta['sha256'], 'size': meta['size'], 'format': meta['detect'],
                'sourcePath': meta.get('sourcePath', ''), 'createdAt': meta.get('createdAt'),
                'binaryPath': str(self.binary), 'analyses': analyses,
                'defaultEngine': self.default_engine()}

    def default_engine(self):
        meta = self.meta()
        analysed = [k for k, v in meta.get('analyses', {}).items() if v.get('state') == 'Completed']
        for engine_id in meta['detect'].get('engines', []):
            if engine_id in analysed:
                return engine_id
        return analysed[0] if analysed else ''

    # ------------------------------------------------------------------ analyses

    def engine_dir(self, engine_id):
        return self.dir / 'engines' / safe_name(engine_id)

    def analysis(self, engine_id):
        path = self.engine_dir(engine_id) / 'analysis.json'
        try:
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            key = None
        with _locks_guard:
            cached = _analysis_cache.get(str(path))
        if cached is not None and key is not None and cached[0] == key:
            return cached[1]
        value = read_json(path, None)
        if isinstance(value, dict) and key is not None:
            with _locks_guard:
                _analysis_cache[str(path)] = (key, value)
                if str(path) in _analysis_order:
                    _analysis_order.remove(str(path))
                _analysis_order.append(str(path))
                while len(_analysis_order) > _ANALYSIS_CACHE_SIZE:
                    _analysis_cache.pop(_analysis_order.pop(0), None)
        if not isinstance(value, dict):
            raise CyToolError('NotAnalyzed', 'Project %s has no %s analysis yet. Run analyze first.'
                              % (self.id, engine_id), recoverable=True)
        return value

    def has_analysis(self, engine_id):
        return (self.engine_dir(engine_id) / 'analysis.json').is_file()

    def save_analysis(self, engine_id, analysis, seconds=0.0):
        with self.lock:
            directory = self.engine_dir(engine_id)
            # A new analysis invalidates the cached code of the previous one.
            if (directory / 'code').is_dir():
                shutil.rmtree(directory / 'code', ignore_errors=True)
            analysis.setdefault('functions', [])
            analysis['engine'] = engine_id
            write_json(directory / 'analysis.json', analysis)
            meta = self.meta()
            meta.setdefault('analyses', {})[engine_id] = {
                'state': 'Completed', 'analyzedAt': time.time(),
                'functionCount': len(analysis['functions']), 'seconds': round(seconds, 3),
                'message': analysis.get('message', '')}
            write_json(self.meta_path, meta)

    def resolve_engine(self, engine_id=''):
        engine_id = engine_id or self.default_engine()
        if not engine_id:
            raise CyToolError('NotAnalyzed', 'Project %s has not been analyzed yet.' % self.id,
                              recoverable=True)
        return engine_id

    def functions(self, engine_id):
        return self.analysis(engine_id)['functions']

    def find_function(self, engine_id, reference):
        """Accept an id, an original or renamed name, or an address (0x401000 / 401000)."""
        reference = str(reference).strip()
        functions = self.functions(engine_id)
        for item in functions:
            if item['id'] == reference:
                return item
        symbols = self.annotations()['symbols']
        reverse = {v: k for k, v in symbols.items()}
        original = reverse.get(reference, reference)
        for item in functions:
            if item.get('name') == original:
                return item
        address = reference.lower()
        if address.startswith('0x'):
            address = address[2:]
        if re.fullmatch(r'[0-9a-f]+', address):
            value = int(address, 16)
            for item in functions:
                if item.get('address') and int(item['address'], 16) == value:
                    return item
        raise CyToolError('NotFound', 'No function or unit %r in the %s analysis of %s.'
                          % (reference, engine_id, self.id))

    # ------------------------------------------------------------------ code cache

    def code_path(self, engine_id, function_id, kind):
        return self.engine_dir(engine_id) / 'code' / kind / (safe_name(function_id) + '.txt')

    def cached_code(self, engine_id, function_id, kind='decompiled'):
        path = self.code_path(engine_id, function_id, kind)
        try:
            return path.read_text(encoding='utf-8')
        except OSError:
            return None

    def store_code(self, engine_id, function_id, text, kind='decompiled'):
        path = self.code_path(engine_id, function_id, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(text, encoding='utf-8')
        temp.replace(path)
        return path

    # ------------------------------------------------------------------ annotations

    def annotations(self):
        value = read_json(self.dir / 'annotations.json', {})
        result = {k: (dict(v) if isinstance(v, dict) else v) for k, v in EMPTY_ANNOTATIONS.items()}
        if isinstance(value, dict):
            for key in result:
                if isinstance(value.get(key), type(result[key])):
                    result[key] = value[key]
        return result

    def update_annotations(self, mutate):
        with self.lock:
            value = self.annotations()
            mutate(value)
            write_json(self.dir / 'annotations.json', value)
            return value

    def display_name(self, function):
        return self.annotations()['symbols'].get(function.get('name', ''), function.get('name', ''))

    def apply_annotations(self, code, function_id=None):
        """Rewrite identifiers with the user's names. Comments are prepended, not merged."""
        notes = self.annotations()
        mapping = dict(notes['symbols'])
        if function_id is not None:
            mapping.update(notes['locals'].get(function_id, {}))
        if mapping:
            code = IDENTIFIER.sub(lambda m: mapping.get(m.group(0), m.group(0)), code)
        comment = notes['comments'].get(function_id) if function_id is not None else None
        if comment:
            lines = ['// ' + line for line in comment.splitlines()]
            code = '\n'.join(lines) + '\n' + code
        return code


class ProjectStore:
    def __init__(self, root=PROJECTS):
        self.root = Path(root)

    def get(self, project_id):
        project_id = str(project_id)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', project_id) or project_id in ('.', '..'):
            raise CyToolError('InvalidParameters', 'Invalid project id.')
        project = Project(self.root / project_id)
        project.meta()
        return project

    def list(self):
        result = []
        if not self.root.is_dir():
            return result
        for directory in sorted(self.root.iterdir()):
            if (directory / 'project.json').is_file():
                try:
                    result.append(Project(directory).summary())
                except CyToolError:
                    continue
        result.sort(key=lambda item: item.get('createdAt') or 0, reverse=True)
        return result

    def find_by_hash(self, sha256):
        prefix = sha256[:16]
        if self.root.is_dir():
            for directory in self.root.glob(prefix + '-*'):
                meta = read_json(directory / 'project.json', {})
                if meta.get('sha256') == sha256:
                    return Project(directory)
        return None

    def open(self, path, source_path='', cancellation=None):
        """Create the project for this file, or return the existing one for the same bytes."""
        path = Path(path)
        if not path.is_file():
            raise CyToolError('NotFound', 'File not found: %s' % path)
        digest = sha256_file(path, cancellation)
        existing = self.find_by_hash(digest)
        if existing is not None:
            return existing, False
        info = detection.detect(path)
        if info['format'] == 'empty':
            raise CyToolError('InvalidParameters', 'The file is empty.')
        name = Path(source_path or path).name
        directory = self.root / (digest[:16] + '-' + safe_name(Path(name).stem, 40))
        (directory / 'input').mkdir(parents=True, exist_ok=True)
        file_name = safe_name(name, 120)
        shutil.copyfile(path, directory / 'input' / file_name)
        write_json(directory / 'project.json', {
            'id': directory.name, 'name': name, 'fileName': file_name, 'sha256': digest,
            'size': path.stat().st_size, 'detect': info, 'sourcePath': str(source_path or path),
            'createdAt': time.time(), 'analyses': {}})
        return Project(directory), True

    def delete(self, project_id):
        project = self.get(project_id)
        with project.lock:
            shutil.rmtree(project.dir)
        return {'projectId': project_id, 'deleted': True}
