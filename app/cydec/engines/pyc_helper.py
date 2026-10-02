"""Subprocess helper for the Python engine. Runs with the pydecompile component on sys.path.

    python pyc_helper.py list <file.pyc>              -> JSON: version and code objects
    python pyc_helper.py disasm <file.pyc> <code id>  -> text disassembly of one code object
    python pyc_helper.py decompile <file.pyc>         -> Python source of the module

Kept separate from the Tool process: the decompilers are GPL packages with deep recursion
and their own global state, and a crash in them must not take the interface down.
"""
import io
import json
import sys


def load(path):
    from xdis.load import load_module
    version, timestamp, magic, code, pypy, source_size, sip_hash = load_module(path)[:7]
    return version, magic, code, pypy


def iscode(value):
    return hasattr(value, 'co_code') and hasattr(value, 'co_name')


def walk(code, prefix=''):
    name = code.co_name
    qualified = getattr(code, 'co_qualname', None) or (prefix + '.' + name if prefix else name)
    if name == '<module>':
        qualified = '<module>'
    yield qualified, code
    for const in code.co_consts:
        if iscode(const):
            yield from walk(const, '' if name == '<module>' else qualified)


def command_list(path):
    version, magic, code, pypy = load(path)
    units = []
    seen = {}
    for qualified, item in walk(code):
        key = qualified
        if key in seen:
            seen[key] += 1
            key = '%s#%d' % (qualified, seen[qualified])
        else:
            seen[key] = 0
        kind = 'module' if qualified == '<module>' else (
            'lambda' if item.co_name == '<lambda>' else
            'comprehension' if item.co_name.startswith('<') else 'code')
        units.append({'id': key, 'name': qualified, 'kind': kind,
                      'firstLine': getattr(item, 'co_firstlineno', 0),
                      'args': getattr(item, 'co_argcount', 0),
                      'varnames': list(getattr(item, 'co_varnames', ()))[:64]})
    print(json.dumps({'version': '.'.join(map(str, version[:2])), 'magic': magic,
                      'pypy': bool(pypy), 'units': units}))


def command_disasm(path, unit):
    from xdis.bytecode import Bytecode
    from xdis.op_imports import get_opcode_module
    version, magic, code, pypy = load(path)
    opc = get_opcode_module(version, 'pypy' if pypy else '')
    seen = {}
    for qualified, item in walk(code):
        key = qualified
        if key in seen:
            seen[key] += 1
            key = '%s#%d' % (qualified, seen[qualified])
        else:
            seen[key] = 0
        if key == unit:
            header = '# %s  (line %s, %d args)\n# varnames: %s\n# names: %s\n\n' % (
                qualified, getattr(item, 'co_firstlineno', '?'), getattr(item, 'co_argcount', 0),
                ', '.join(getattr(item, 'co_varnames', ())), ', '.join(getattr(item, 'co_names', ())))
            print(header + Bytecode(item, opc).dis())
            return
    raise SystemExit('unit not found: ' + unit)


def command_decompile(path):
    version, magic, code, pypy = load(path)
    out = io.StringIO()
    if version[:2] in ((3, 7), (3, 8)):
        try:
            from decompyle3.main import decompile_file
            decompile_file(path, out)
            print(out.getvalue())
            return
        except Exception as exc:  # fall back to uncompyle6 below
            print('# decompyle3 failed: %s' % exc, file=sys.stderr)
            out = io.StringIO()
    if version[:2] <= (3, 8):
        from uncompyle6.main import decompile_file
        decompile_file(path, out)
        print(out.getvalue())
        return
    raise SystemExit('UNSUPPORTED %d.%d' % version[:2])


if __name__ == '__main__':
    sys.setrecursionlimit(20000)
    action = sys.argv[1]
    if action == 'list':
        command_list(sys.argv[2])
    elif action == 'disasm':
        command_disasm(sys.argv[2], sys.argv[3])
    elif action == 'decompile':
        command_decompile(sys.argv[2])
    else:
        raise SystemExit('unknown action')
