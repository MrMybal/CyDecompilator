"""Program database (PDB) symbols for PE files: locate, download and read public symbols.

- `codeview(path)`: the RSDS record of the PE debug directory (PDB name, GUID, age).
- `fetch(...)`: the matching PDB from a local folder, from next to the original binary, or
  from a symbol server (Microsoft's by default), cached under data/symbols/<name>/<id>/.
- `read_publics(pdb_path, sections)`: S_PUB32 public symbols and S_*PROC32 procedures from
  the MSF 7.00 container, mapped to RVAs, with a light MSVC demangler for display names.

The PDB identity (GUID + age) is checked against the binary before any name is used.
"""
import re
import struct
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from cytools_core import CyToolError

from .paths import DATA

SYMBOLS = DATA / 'symbols'
MICROSOFT = 'https://msdl.microsoft.com/download/symbols'
MSF_MAGIC = b'Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0'
S_PUB32 = 0x110E
PROCS = {0x110F: 'local', 0x1110: 'global', 0x1146: 'local', 0x1147: 'global'}  # S_LPROC32, S_GPROC32 (+ _ID)


def codeview(path):
    """{'pdb': name, 'guid': str, 'age': int, 'id': symbol server id} or None."""
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DEBUG']])
        for entry in getattr(pe, 'DIRECTORY_ENTRY_DEBUG', []) or []:
            if entry.struct.Type != 2:  # IMAGE_DEBUG_TYPE_CODEVIEW
                continue
            data = pe.get_data(entry.struct.AddressOfRawData, entry.struct.SizeOfData) if entry.struct.AddressOfRawData \
                else pe.__data__[entry.struct.PointerToRawData:entry.struct.PointerToRawData + entry.struct.SizeOfData]
            if data[:4] != b'RSDS' or len(data) < 24:
                continue
            guid = uuid.UUID(bytes_le=bytes(data[4:20]))
            age = struct.unpack_from('<I', data, 20)[0]
            name = bytes(data[24:]).split(b'\0', 1)[0].decode('utf-8', 'replace')
            return {'pdb': name, 'file': re.split(r'[\\/]', name)[-1], 'guid': str(guid), 'age': age,
                    'id': guid.hex.upper() + '%X' % age}
    finally:
        pe.close()
    return None


def cached(info):
    path = SYMBOLS / info['file'] / info['id'] / info['file']
    return path if path.is_file() else None


def fetch(info, server=MICROSOFT, local_folders=(), original_dir=None, context=None, allow_download=True):
    """Path of a PDB matching `info`, downloading it when needed. Raises NotFound."""
    found = cached(info)
    if found:
        return found
    candidates = [Path(folder) / info['file'] for folder in local_folders if folder]
    if original_dir:
        candidates.append(Path(original_dir) / info['file'])
    candidates.append(Path(info['pdb']))
    for candidate in candidates:
        try:
            if candidate.is_file() and identity(candidate) == (info['guid'], info['age']):
                return candidate
        except (OSError, CyToolError):
            continue
    if not allow_download or not server:
        raise CyToolError('NotFound', 'No matching PDB found locally for %s.' % info['file'], recoverable=True)
    url = '%s/%s/%s/%s' % (server.rstrip('/'), info['file'], info['id'], info['file'])
    if not url.startswith('https://'):
        raise CyToolError('InvalidParameters', 'Symbol servers must use HTTPS.')
    target = SYMBOLS / info['file'] / info['id'] / info['file']
    target.parent.mkdir(parents=True, exist_ok=True)
    if context is not None:
        context.log('Downloading symbols %s from %s' % (info['file'], server))
    request = urllib.request.Request(url, headers={'User-Agent': 'Microsoft-Symbol-Server/10.0.0.0'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(str(target) + '.part', 'wb') as sink:
            total = int(response.headers.get('Content-Length') or 0)
            done = 0
            while True:
                if context is not None:
                    context.check()
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                sink.write(chunk)
                done += len(chunk)
                if context is not None and total:
                    context.progress(10 + 40 * done / total, 'Downloading symbols %.1f MB' % (done / 1e6))
    except urllib.error.HTTPError as exc:
        Path(str(target) + '.part').unlink(missing_ok=True)
        raise CyToolError('NotFound', 'The symbol server has no PDB for %s (HTTP %d).' % (info['file'], exc.code),
                          recoverable=True)
    except (OSError, urllib.error.URLError) as exc:
        Path(str(target) + '.part').unlink(missing_ok=True)
        raise CyToolError('DownloadFailed', 'Cannot reach the symbol server: %s' % exc, recoverable=True)
    part = Path(str(target) + '.part')
    if part.read_bytes()[:4] == b'MSCF':
        part.unlink()
        raise CyToolError('Unsupported', 'The server returned a compressed (.pd_) PDB; this is not supported.')
    if identity(part) != (info['guid'], info['age']):
        part.unlink()
        raise CyToolError('IntegrityFailure', 'The downloaded PDB does not match the binary (GUID/age).')
    part.replace(target)
    return target


# ---------------------------------------------------------------------- MSF

class Msf:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if not self.data.startswith(MSF_MAGIC):
            raise CyToolError('Unsupported', 'Not an MSF 7.00 PDB (old PDB 2.0 files are not supported).')
        self.block_size, _, self.block_count, directory_bytes, _, map_block = struct.unpack_from('<6I', self.data, 32)
        directory_blocks = (directory_bytes + self.block_size - 1) // self.block_size
        map_offset = map_block * self.block_size
        blocks = struct.unpack_from('<%dI' % directory_blocks, self.data, map_offset)
        directory = b''.join(self.block(b) for b in blocks)[:directory_bytes]
        count = struct.unpack_from('<I', directory, 0)[0]
        sizes = struct.unpack_from('<%dI' % count, directory, 4)
        position = 4 + 4 * count
        self.streams = []
        for size in sizes:
            if size == 0xffffffff:
                self.streams.append(([], 0))
                continue
            needed = (size + self.block_size - 1) // self.block_size
            stream_blocks = struct.unpack_from('<%dI' % needed, directory, position)
            position += 4 * needed
            self.streams.append((stream_blocks, size))

    def block(self, index):
        return self.data[index * self.block_size:(index + 1) * self.block_size]

    def stream(self, index):
        if index >= len(self.streams):
            return b''
        blocks, size = self.streams[index]
        return b''.join(self.block(b) for b in blocks)[:size]


def identity(path):
    """(guid, age) of a PDB file from its PDB info stream (age from the DBI stream when present)."""
    msf = Msf(path)
    info = msf.stream(1)
    if len(info) < 28:
        raise CyToolError('Unsupported', 'PDB info stream missing.')
    version, signature, age = struct.unpack_from('<III', info, 0)
    guid = str(uuid.UUID(bytes_le=bytes(info[12:28])))
    dbi = msf.stream(3)
    if len(dbi) >= 12:
        age = struct.unpack_from('<I', dbi, 8)[0]
    return guid, age


def demangle(name):
    """Readable form of common MSVC names: ?Method@Class@Namespace@@... -> Namespace::Class::Method."""
    if not name.startswith('?'):
        # x86 C decorations: _name (cdecl), _name@N (stdcall), @name@N (fastcall).
        match = re.fullmatch(r'[_@]([A-Za-z_][A-Za-z0-9_]*)(?:@\d+)?', name)
        return match.group(1) if match and (name.startswith('@') or '@' in name or name.count('_') == 1) else name
    if name.startswith('??_C@'):
        return '`string\''
    special = {'0': '{ctor}', '1': '{dtor}', '_G': '{scalar deleting dtor}', '_E': '{vector deleting dtor}',
               '2': 'operator new', '3': 'operator delete', '4': 'operator=', '8': 'operator==',
               '9': 'operator!=', 'A': 'operator[]', 'R': 'operator()', '_7': '`vftable\'', '_R4': '`RTTI locator\'',
               '_U': 'operator new[]', '_V': 'operator delete[]', 'B': 'operator cast'}
    head = None
    rest = name[1:]
    if name.startswith('??'):
        for key in sorted(special, key=len, reverse=True):
            if name[2:].startswith(key):
                head = special[key]
                rest = name[2 + len(key):]
                break
    scope_text = rest.split('@@', 1)[0]
    parts = [p for p in scope_text.split('@') if p]
    if not parts:
        return name
    if head is None:
        method, parts = parts[0], parts[1:]
    elif head in ('{ctor}', '{dtor}'):
        method = ('~' if head == '{dtor}' else '') + parts[0]
    else:
        method = head
    parts = [p if not p.startswith('?$') else p[2:] + '<>' for p in parts]
    scope = '::'.join(reversed(parts))
    return (scope + '::' + method) if scope else method


def read_symbols(path, sections):
    """Functions and publics: [{'rva', 'name', 'display', 'kind', 'size'}], sections = [(va_rel, ...)] by index."""
    msf = Msf(path)
    dbi = msf.stream(3)
    if len(dbi) < 64:
        raise CyToolError('Unsupported', 'PDB has no DBI stream.')
    (signature, version, age, global_stream, build, public_stream, dll_version, record_stream, rbld,
     module_info_size, section_contribution_size, section_map_size, source_info_size, type_server_size,
     mfc_index, optional_debug_size, ec_size, flags, machine, pad) = struct.unpack_from('<iIIHHHHHHiiiiiIiiHHI', dbi, 0)
    symbols = {}

    def rva_of(segment, offset):
        if 1 <= segment <= len(sections):
            return sections[segment - 1] + offset
        return None

    def parse_records(data, start=0, end=None, procs_only=False):
        end = len(data) if end is None else end
        position = start
        while position + 4 <= end:
            length, kind = struct.unpack_from('<HH', data, position)
            if length < 2:
                break
            record = data[position + 4:position + 2 + length]
            if kind == S_PUB32 and not procs_only and len(record) >= 10:
                flags_, offset, segment = struct.unpack_from('<IIH', record, 0)
                name = record[10:].split(b'\0', 1)[0].decode('utf-8', 'replace')
                rva = rva_of(segment, offset)
                if rva is not None and (flags_ & 2 or rva not in symbols):  # bit 1 = function
                    symbols.setdefault(rva, {'rva': rva, 'name': name, 'display': demangle(name),
                                             'kind': 'function' if flags_ & 2 else 'data', 'size': 0})
            elif kind in PROCS and len(record) >= 35:
                parent, end_, next_, size, dbg_start, dbg_end, type_index, offset, segment, proc_flags = \
                    struct.unpack_from('<IIIIIIIIHB', record, 0)
                name = record[35:].split(b'\0', 1)[0].decode('utf-8', 'replace')
                rva = rva_of(segment, offset)
                if rva is not None:
                    current = symbols.get(rva)
                    entry = {'rva': rva, 'name': name, 'display': demangle(name), 'kind': 'function', 'size': size}
                    if current is None or current['kind'] != 'function' or not current['size']:
                        if current is not None and current['name'].startswith('?'):
                            entry['name'] = current['name']
                            entry['display'] = demangle(current['name']) if current['name'].startswith('?') else name
                        symbols[rva] = entry
            position += 2 + length

    parse_records(msf.stream(record_stream))
    # Module streams carry S_GPROC32/S_LPROC32 with sizes (and static functions absent from publics).
    position = 64
    end = 64 + module_info_size
    while position + 64 <= end:
        stream_index = struct.unpack_from('<H', dbi, position + 34)[0]
        symbol_bytes = struct.unpack_from('<I', dbi, position + 36)[0]
        position += 64
        names_end = dbi.index(b'\0', position)
        names_end = dbi.index(b'\0', names_end + 1)
        position = (names_end + 1 + 3) & ~3
        if stream_index != 0xffff and symbol_bytes > 4:
            data = msf.stream(stream_index)
            parse_records(data, 4, min(symbol_bytes, len(data)), procs_only=True)
    return sorted(symbols.values(), key=lambda s: s['rva'])
