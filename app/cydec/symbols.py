"""Debug symbols for a project: PDB lookup settings and the per-project symbol cache.

Settings (data/settings/symbols.json): enabled, server (HTTPS symbol server, Microsoft's by
default, empty = local only) and localFolders searched first. The symbols found for a
project are cached in its folder (symbols.json) so later analyses and engines reuse them.
"""
from cytools_core import CyToolError

from . import pdb
from .paths import SETTINGS, read_json, write_json

SETTINGS_FILE = SETTINGS / 'symbols.json'
DEFAULTS = {'enabled': True, 'server': pdb.MICROSOFT, 'localFolders': []}


def settings():
    value = read_json(SETTINGS_FILE, {})
    result = dict(DEFAULTS)
    if isinstance(value, dict):
        result.update({k: v for k, v in value.items() if k in DEFAULTS})
    return result


def configure(enabled=None, server=None, local_folders=None):
    current = settings()
    if enabled is not None:
        current['enabled'] = bool(enabled)
    if server is not None:
        if server and not str(server).startswith('https://'):
            raise CyToolError('InvalidParameters', 'Symbol servers must use HTTPS (or leave empty for local only).')
        current['server'] = str(server)
    if local_folders is not None:
        current['localFolders'] = [str(f) for f in local_folders if str(f).strip()]
    write_json(SETTINGS_FILE, current)
    return current


def for_project(project, context=None, force=False):
    """{'pdb': info, 'symbols': [{'va', 'name', 'display', 'kind', 'size'}], 'status': ...}."""
    cache = project.dir / 'symbols.json'
    if not force:
        value = read_json(cache, None)
        if isinstance(value, dict) and 'symbols' in value:
            return value
    current = settings()
    result = {'pdb': None, 'symbols': [], 'status': 'none'}
    if project.meta()['detect']['format'] not in ('pe', 'pe-dotnet'):
        return result
    try:
        info = pdb.codeview(project.binary)
    except Exception as exc:
        result['status'] = 'unreadable debug directory: %s' % exc
        return result
    if info is None:
        result['status'] = 'no PDB reference in the binary'
        write_json(cache, result)
        return result
    result['pdb'] = info
    if not current['enabled']:
        result['status'] = 'symbols disabled'
        return result
    from pathlib import Path
    source = project.meta().get('sourcePath', '')
    try:
        path = pdb.fetch(info, server=current['server'], local_folders=current['localFolders'],
                         original_dir=str(Path(source).parent) if source else None, context=context)
    except CyToolError as exc:
        result['status'] = str(exc)
        if context is not None:
            context.log('Symbols: %s' % exc, 'Warning')
        return result
    import pefile
    pe = pefile.PE(str(project.binary), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    sections = [s.VirtualAddress for s in pe.sections]
    pe.close()
    symbols = pdb.read_symbols(path, sections)
    for symbol in symbols:
        symbol['va'] = base + symbol.pop('rva')
    result.update(symbols=symbols, status='loaded %d symbols from %s' % (len(symbols), path.name), path=str(path))
    write_json(cache, result)
    if context is not None:
        context.log('Symbols: ' + result['status'])
    return result


def function_names(project, context=None):
    """{va: (display name, raw name)} for functions, plus data labels under 'data'."""
    loaded = for_project(project, context)
    functions = {}
    for symbol in loaded.get('symbols', []):
        if symbol['kind'] == 'function':
            functions[symbol['va']] = (symbol['display'], symbol['name'], symbol.get('size', 0))
    return functions, loaded
