"""Python bytecode engine (.pyc).

With the pydecompile component (xdis, uncompyle6, decompyle3), every Python version can be
listed and disassembled, and versions up to 3.8 are decompiled to source. For 3.9 and
newer no maintained open-source decompiler is complete: the engine shows the bytecode and
the AI "Reconstruct source" action rebuilds Python from it.

Without the component, a .pyc produced by the same Python version as the Tool's runtime is
still handled with the standard library (marshal + dis).
"""
import dis
import io
import json
import marshal
import os
import sys
import time
from pathlib import Path

from cytools_core import CyToolError

from .. import components, process
from .base import Engine

HELPER = Path(__file__).with_name('pyc_helper.py')


def _builtin_code(path):
    data = Path(path).read_bytes()
    import importlib.util
    if data[:4] != importlib.util.MAGIC_NUMBER:
        return None
    return marshal.loads(data[16:])


def _walk(code, prefix=''):
    name = code.co_name
    qualified = '<module>' if name == '<module>' else (getattr(code, 'co_qualname', None) or (prefix + '.' + name if prefix else name))
    yield qualified, code
    for const in code.co_consts:
        if hasattr(const, 'co_code'):
            yield from _walk(const, '' if name == '<module>' else qualified)


def _units(code):
    seen, units = {}, []
    for qualified, item in _walk(code):
        key = qualified
        if key in seen:
            seen[key] += 1
            key = '%s#%d' % (qualified, seen[qualified])
        else:
            seen[key] = 0
        units.append((key, qualified, item))
    return units


class PythonEngine(Engine):
    id = 'python'
    name = 'Python bytecode'
    license = 'GPL-3.0 (uncompyle6, decompyle3), GPL-2.0+ (xdis); built-in part: this Tool'
    url = 'https://github.com/rocky/python-xdis'
    description = ('All .pyc versions: code objects and bytecode. Source for Python <= 3.8 '
                   '(uncompyle6/decompyle3); AI reconstruction for newer versions.')
    formats = ('pyc',)
    components = ()
    language = 'python'
    supports_disassemble = True

    def availability(self):
        found = components.locate('pydecompile')
        if found:
            return {'available': True, 'missing': [], 'detail': 'Ready (all versions)'}
        return {'available': True, 'missing': ['pydecompile'],
                'detail': 'Only Python %d.%d .pyc without the pydecompile component' % sys.version_info[:2]}

    def _helper(self, context, *arguments, timeout=600):
        found = components.locate('pydecompile')
        if not found:
            return None
        env = {'PYTHONPATH': found['path'], 'PYTHONIOENCODING': 'utf-8'}
        return process.run([sys.executable, str(HELPER), *arguments], context=context, env=env,
                           timeout=timeout, log_name='pyc-' + arguments[0])

    def _version(self, project):
        return project.meta()['detect']['details'].get('pythonVersion', '')

    def analyze(self, project, context):
        started = time.monotonic()
        context.progress(10, 'Reading code objects')
        result = self._helper(context, 'list', str(project.binary))
        if result is not None:
            code, out, err = result
            if code != 0:
                raise CyToolError('EngineFailed', 'xdis could not read this file: ' + process.tail(err or out, 8))
            listing = json.loads(out)
            version, units = listing['version'], listing['units']
        else:
            code_object = _builtin_code(project.binary)
            if code_object is None:
                raise CyToolError('MissingDependency',
                                  'This .pyc was made by Python %s. Install the pydecompile component '
                                  'to read other versions.' % self._version(project), recoverable=True)
            version = '%d.%d' % sys.version_info[:2]
            units = [{'id': key, 'name': qualified,
                      'kind': 'module' if qualified == '<module>' else 'code',
                      'firstLine': item.co_firstlineno, 'args': item.co_argcount,
                      'varnames': list(item.co_varnames)[:64]}
                     for key, qualified, item in _units(code_object)]
        major_minor = tuple(int(x) for x in version.split('.')[:2]) if version[0].isdigit() else (0, 0)
        decompilable = major_minor <= (3, 8) and components.locate('pydecompile') is not None
        for unit in units:
            unit['lines'] = 0
        message = ('Source decompilation available (Python %s).' % version if decompilable else
                   'Python %s: bytecode view; use AI "Reconstruct source" for Python code.' % version)
        return {'functions': units, 'strings': [], 'imports': [], 'message': message,
                'python': {'version': version, 'sourceDecompiler': decompilable},
                'seconds': round(time.monotonic() - started, 3)}

    def decompile(self, project, analysis, function, context):
        info = analysis.get('python', {})
        if function['id'] != '<module>':
            # Decompilers work on whole modules: show the module source with the unit marked.
            text = self.decompile(project, analysis, {'id': '<module>'}, context)['code'] \
                if info.get('sourceDecompiler') else None
            if text is None:
                return self.disassemble(project, analysis, function, context)
            return {'code': '# Unit %s is defined in the module source below.\n\n%s'
                    % (function['name'], text), 'language': 'python'}
        if not info.get('sourceDecompiler'):
            result = self.disassemble(project, analysis, function, context)
            result['code'] = ('# Python %s has no maintained open-source decompiler.\n'
                              '# Bytecode below; use the AI "Reconstruct source" action.\n\n'
                              % info.get('version', '?')) + result['code']
            return result
        code, out, err = self._helper(context, 'decompile', str(project.binary), timeout=1200)
        if code != 0 or not out.strip():
            raise CyToolError('EngineFailed', 'Decompilation failed: ' + process.tail(err or out, 10))
        return {'code': out, 'language': 'python'}

    def disassemble(self, project, analysis, function, context):
        result = self._helper(context, 'disasm', str(project.binary), function['id'])
        if result is not None:
            code, out, err = result
            if code != 0:
                raise CyToolError('EngineFailed', 'Disassembly failed: ' + process.tail(err or out, 8))
            return {'code': out, 'language': 'pybytecode'}
        code_object = _builtin_code(project.binary)
        if code_object is None:
            raise CyToolError('MissingDependency', 'Install the pydecompile component.', recoverable=True)
        for key, qualified, item in _units(code_object):
            if key == function['id']:
                buffer = io.StringIO()
                dis.dis(item, file=buffer, depth=0)
                return {'code': '# %s (line %d)\n\n%s' % (qualified, item.co_firstlineno, buffer.getvalue()),
                        'language': 'pybytecode'}
        raise CyToolError('NotFound', 'Code object %s not found.' % function['id'])
