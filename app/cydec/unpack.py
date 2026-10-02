"""Extract what an executable carries inside it, so each part can be decompiled.

- PyInstaller (CArchive + PYZ): entry scripts and every bundled module become real .pyc
  files (with the header PyInstaller strips), plus bundled DLLs, .pyd and data files.
- .NET single-file bundles (apphost): managed assemblies, native libraries, deps.json and
  runtimeconfig.json, decompressed when the bundle is compressed (.NET 6+).
- UPX: unpacked with the official `upx -d` (component), producing the original executable.
- Zip overlays (self-extractors, launchers with an appended archive).

Output goes to data/projects/<id>/extracted/<kind>/ and is listed with the detected format
of every file, so the interface and MCP can open any of them as a new project.
"""
import io
import marshal
import os
import re
import shutil
import struct
import zipfile
import zlib
from pathlib import Path

from cytools_core import CyToolError

from . import detect as detection
from .pe_info import DOTNET_BUNDLE_SIGNATURE, PYINSTALLER_MAGIC

MAX_ENTRY = 2 * 1024 ** 3
PYC_MAGIC_BY_VERSION = {
    (2, 7): 62211, (3, 5): 3351, (3, 6): 3379, (3, 7): 3394, (3, 8): 3413, (3, 9): 3425, (3, 10): 3439,
    (3, 11): 3495, (3, 12): 3531, (3, 13): 3571,
}


def safe_relative(name):
    name = name.replace('\\', '/').lstrip('/')
    parts = [p for p in name.split('/') if p not in ('', '.', '..')]
    cleaned = [re.sub(r'[<>:"|?*\x00-\x1f]', '_', p) for p in parts]
    return '/'.join(cleaned) or 'unnamed'


def write_file(root, name, data):
    target = (root / safe_relative(name)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise CyToolError('IntegrityFailure', 'Entry escapes the extraction folder: %s' % name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def pyc_header(magic_word, version):
    """16-byte header for Python 3.7+ (magic, flags, mtime, size); 12 bytes for 3.3-3.6; 8 before."""
    magic = struct.pack('<H', magic_word) + b'\r\n'
    if version >= (3, 7):
        return magic + b'\0' * 12
    if version >= (3, 3):
        return magic + b'\0' * 8
    return magic + b'\0' * 4


# ---------------------------------------------------------------------- PyInstaller

def pyinstaller(data, out, context=None):
    position = data.rfind(PYINSTALLER_MAGIC)
    if position < 0:
        raise CyToolError('NotFound', 'No PyInstaller archive in this file.')
    # Cookie: magic(8) package_length(4) toc_offset(4) toc_length(4) python_version(4) [libname(64)]
    length, toc_offset, toc_length, python_version = struct.unpack_from('!IIII', data, position + 8)
    cookie_size = 88 if data[position + 24:position + 88].split(b'\0', 1)[0].lower().startswith(b'python') else 24
    package_start = position + cookie_size - length
    if package_start < 0:
        raise CyToolError('InvalidArchive', 'Inconsistent PyInstaller cookie.')
    if python_version >= 100:
        version = (python_version // 100, python_version % 100)
    else:
        version = (python_version // 10, python_version % 10)
    toc = data[package_start + toc_offset:package_start + toc_offset + toc_length]
    entries = []
    cursor = 0
    while cursor + 18 <= len(toc):
        entry_size, entry_pos, compressed_size, size, compressed, kind = struct.unpack_from('!IIIIBc', toc, cursor)
        if entry_size < 18:
            break
        name = toc[cursor + 18:cursor + entry_size].rstrip(b'\0').decode('utf-8', 'replace')
        entries.append((name, package_start + entry_pos, compressed_size, size, compressed, kind.decode('latin-1')))
        cursor += entry_size
    magic_word = PYC_MAGIC_BY_VERSION.get(version)
    files = []
    scripts = []
    for index, (name, offset, compressed_size, size, compressed, kind) in enumerate(entries):
        if context is not None and index % 50 == 0:
            context.check()
            context.progress(10 + 70 * index / max(len(entries), 1), 'Extracting %s' % name[:60])
        blob = data[offset:offset + compressed_size]
        if compressed:
            try:
                blob = zlib.decompress(blob)
            except zlib.error:
                files.append({'name': name, 'error': 'decompression failed'})
                continue
        if kind in ('z', 'Z'):  # PYZ archive of modules
            pyz = out / (safe_relative(name) + '_extracted')
            magic_word = struct.unpack_from('<H', blob, 4)[0] if blob[:4] == b'PYZ\0' else magic_word
            files += pyz_archive(blob, pyz, version, magic_word, context)
            write_file(out, name, blob)
            continue
        if kind == 's':  # entry script: marshalled code without header
            target = write_file(out, name + '.pyc', pyc_header(magic_word or 0, version) + blob)
            scripts.append(str(target))
            files.append({'name': name + '.pyc', 'path': str(target), 'type': 'entry script'})
            continue
        if kind in ('m', 'M'):  # module/package: full pyc already
            target = write_file(out, name + '.pyc', blob if blob[2:4] == b'\r\n' else pyc_header(magic_word or 0, version) + blob)
            files.append({'name': name + '.pyc', 'path': str(target), 'type': 'module'})
            continue
        if kind == 'o':
            continue  # runtime options
        target = write_file(out, name, blob)
        files.append({'name': name, 'path': str(target), 'type': {'b': 'binary', 'x': 'data', 'd': 'dependency',
                                                                  'n': 'link'}.get(kind, kind)})
    return {'kind': 'pyinstaller', 'pythonVersion': '%d.%d' % version, 'entries': len(entries),
            'entryScripts': scripts, 'files': files}


def pyz_archive(blob, out, version, magic_word, context=None):
    if blob[:4] != b'PYZ\0':
        return [{'name': 'PYZ', 'error': 'unknown PYZ header'}]
    toc_offset = struct.unpack_from('!I', blob, 8)[0]
    try:
        toc = marshal.loads(blob[toc_offset:])
    except Exception as exc:
        return [{'name': 'PYZ', 'error': 'table of contents unreadable with this Python (%s); the archive was kept' % exc}]
    if isinstance(toc, dict):
        toc = list(toc.items())
    files = []
    header = pyc_header(magic_word or 0, version)
    for index, item in enumerate(toc):
        name, info = item
        if isinstance(name, bytes):
            name = name.decode('utf-8', 'replace')
        is_package, position, length = info[0], info[1], info[2]
        raw = blob[position:position + length]
        try:
            code = zlib.decompress(raw)
        except zlib.error:
            files.append({'name': name, 'error': 'encrypted or corrupt (PyInstaller --key archives are not supported)'})
            continue
        relative = name.replace('.', '/') + ('/__init__' if is_package in (1, True) else '') + '.pyc'
        target = write_file(out, relative, header + code)
        files.append({'name': relative, 'path': str(target), 'type': 'module'})
        if context is not None and index % 200 == 0:
            context.check()
    return files


# ---------------------------------------------------------------------- .NET bundle

def read_string(data, position):
    length = 0
    shift = 0
    while True:
        byte = data[position]
        position += 1
        length |= (byte & 0x7f) << shift
        if not byte & 0x80:
            break
        shift += 7
    return data[position:position + length].decode('utf-8', 'replace'), position + length


def dotnet_bundle(data, out, context=None):
    signature = data.find(DOTNET_BUNDLE_SIGNATURE)
    if signature < 8:
        raise CyToolError('NotFound', 'No .NET single-file bundle marker.')
    header = struct.unpack_from('<q', data, signature - 8)[0]
    if header <= 0 or header >= len(data):
        raise CyToolError('NotFound', 'This apphost is not bundled (header offset 0).')
    major, minor, count = struct.unpack_from('<IIi', data, header)
    bundle_id, position = read_string(data, header + 12)
    if major >= 2:
        position += 8 * 4 + 8  # deps.json and runtimeconfig.json locations, flags
    kinds = {0: 'unknown', 1: 'assembly', 2: 'native', 3: 'deps.json', 4: 'runtimeconfig.json', 5: 'symbols'}
    files = []
    for index in range(count):
        offset, size = struct.unpack_from('<qq', data, position)
        position += 16
        compressed_size = 0
        if major >= 6:
            compressed_size = struct.unpack_from('<q', data, position)[0]
            position += 8
        kind = data[position]
        position += 1
        name, position = read_string(data, position)
        if context is not None and index % 20 == 0:
            context.check()
            context.progress(10 + 70 * index / max(count, 1), 'Extracting %s' % name[:60])
        if compressed_size:
            blob = zlib.decompress(data[offset:offset + compressed_size], -15)
        else:
            blob = data[offset:offset + size]
        target = write_file(out, name, blob)
        files.append({'name': name, 'path': str(target), 'type': kinds.get(kind, str(kind))})
    return {'kind': 'dotnet-bundle', 'bundleVersion': '%d.%d' % (major, minor), 'bundleId': bundle_id,
            'files': files}


# ---------------------------------------------------------------------- zip overlay / UPX

def zip_overlay(data, out, overlay_offset, context=None):
    start = data.find(b'PK\x03\x04', overlay_offset or 0)
    if start < 0:
        raise CyToolError('NotFound', 'No zip archive appended to this file.')
    files = []
    with zipfile.ZipFile(io.BytesIO(data[start:])) as archive:
        for index, member in enumerate(archive.infolist()):
            if member.is_dir() or member.file_size > MAX_ENTRY:
                continue
            target = write_file(out, member.filename, archive.read(member))
            files.append({'name': member.filename, 'path': str(target), 'type': 'file'})
    return {'kind': 'zip-overlay', 'files': files}


def upx(binary, out, context=None):
    from . import components, process
    located = components.locate('upx')
    if located is None:
        raise CyToolError('MissingDependency', 'Install the upx component (Engines tab) to unpack UPX files.',
                          recoverable=True)
    out.mkdir(parents=True, exist_ok=True)
    target = out / ('unpacked_' + Path(binary).name)
    code, stdout, stderr = process.run([located['exe'], '-d', '-o', str(target), str(binary)], context=context,
                                       timeout=600, log_name='upx')
    if code != 0 or not target.is_file():
        raise CyToolError('EngineFailed', 'upx -d failed: ' + process.tail(stderr or stdout, 6))
    return {'kind': 'upx', 'files': [{'name': target.name, 'path': str(target), 'type': 'unpacked executable'}]}


# ---------------------------------------------------------------------- entry point

def extract(project, kind='', context=None):
    from . import pe_info
    data = project.binary.read_bytes()
    info = pe_info.analyse(project.binary) if project.meta()['detect']['format'] in ('pe', 'pe-dotnet') else {
        'packers': [], 'overlay': None}
    available = [p['id'] for p in info['packers'] if p.get('extractable')]
    if not kind:
        if not available:
            raise CyToolError('NotFound', 'Nothing extractable was detected in this file.')
        kind = available[0]
    out = project.dir / 'extracted' / kind
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    if context is not None:
        context.progress(5, 'Extracting ' + kind)
    if kind == 'pyinstaller':
        result = pyinstaller(data, out, context)
    elif kind == 'dotnet-bundle':
        result = dotnet_bundle(data, out, context)
    elif kind == 'zip-overlay':
        result = zip_overlay(data, out, (info.get('overlay') or {}).get('offset'), context)
    elif kind == 'upx':
        result = upx(project.binary, out, context)
    else:
        raise CyToolError('Unsupported', 'No extractor for %s.' % kind)
    for item in result['files']:
        if item.get('path'):
            try:
                record = detection.detect(item['path'])
                item['format'] = record['format']
                item['size'] = record['size']
                text_like = item['path'].lower().endswith(('.json', '.txt', '.xml', '.config', '.md', '.ini', '.cfg'))
                item['openable'] = bool(record['engines']) and not (record['format'] == 'raw' and text_like)
            except OSError:
                item['openable'] = False
    result['directory'] = str(out)
    result['detected'] = available
    if context is not None:
        context.progress(100, 'Extracted %d files' % len(result['files']))
    return result
