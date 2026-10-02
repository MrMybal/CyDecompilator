"""Identify what a file is from its bytes, never from its extension alone.

The result names the container format, the architecture when it applies and the engines
able to decompile it, best first. An extension is only used to break a tie (a zip that is
neither a jar nor an apk stays a plain archive, which no engine claims).
"""
import struct
import zipfile
from pathlib import Path

# Last magic number of each CPython release; the first entry >= the file magic wins.
PYC_MAGIC = ((3131, '3.0'), (3151, '3.1'), (3180, '3.2'), (3230, '3.3'), (3310, '3.4'),
             (3351, '3.5'), (3379, '3.6'), (3394, '3.7'), (3413, '3.8'), (3425, '3.9'),
             (3439, '3.10'), (3495, '3.11'), (3531, '3.12'), (3571, '3.13'), (3700, '3.14'))

PE_MACHINES = {0x14c: ('x86', 32), 0x8664: ('x86_64', 64), 0xaa64: ('arm64', 64),
               0x1c0: ('arm', 32), 0x1c4: ('arm', 32)}
ELF_MACHINES = {3: ('x86', 32), 62: ('x86_64', 64), 40: ('arm', 32), 183: ('arm64', 64),
                8: ('mips', 32), 20: ('ppc', 32), 21: ('ppc64', 64), 243: ('riscv', 64)}
MACHO_CPUS = {7: ('x86', 32), 0x01000007: ('x86_64', 64), 12: ('arm', 32),
              0x0100000c: ('arm64', 64)}

ENGINES_BY_FORMAT = {
    'pe': ['ghidra', 'cdec', 'native'],
    'pe-dotnet': ['ilspy', 'ghidra', 'cdec', 'native'],
    'elf': ['ghidra', 'cdec', 'native'],
    'macho': ['ghidra', 'native'],
    'java-class': ['vineflower', 'jadx'],
    'jar': ['vineflower', 'jadx'],
    'apk': ['jadx'],
    'dex': ['jadx'],
    'pyc': ['python'],
    'dxbc': ['shader'],
    'dxil': ['shader'],
    'spirv': ['shader'],
    'raw': ['ghidra', 'cdec', 'native'],
}

FORMAT_NAMES = {
    'pe': 'Windows PE (native)', 'pe-dotnet': 'Windows PE (.NET assembly)',
    'elf': 'ELF', 'macho': 'Mach-O', 'java-class': 'Java class', 'jar': 'Java archive',
    'apk': 'Android package', 'dex': 'Dalvik executable', 'pyc': 'Python bytecode',
    'dxbc': 'DirectX bytecode (SM4/SM5)', 'dxil': 'DirectX IL (SM6)', 'spirv': 'SPIR-V',
    'zip': 'Zip archive', 'raw': 'Raw binary', 'empty': 'Empty file',
}


def _result(fmt, **details):
    value = {'format': fmt, 'formatName': FORMAT_NAMES.get(fmt, fmt),
             'arch': details.pop('arch', ''), 'bits': details.pop('bits', 0),
             'engines': list(ENGINES_BY_FORMAT.get(fmt, [])), 'details': details}
    if value['arch'] not in ('x86', 'x86_64', 'arm64') and 'cdec' in value['engines']:
        value['engines'].remove('cdec')
    return value


def _pe(path, head):
    try:
        offset = struct.unpack_from('<I', head, 0x3c)[0]
    except struct.error:
        return _result('raw')
    with open(path, 'rb') as handle:
        handle.seek(offset)
        header = handle.read(0x108)
    if header[:4] != b'PE\0\0':
        return _result('raw', note='MZ header without a PE signature (DOS executable?)')
    machine = struct.unpack_from('<H', header, 4)[0]
    arch, bits = PE_MACHINES.get(machine, ('unknown', 0))
    characteristics = struct.unpack_from('<H', header, 22)[0]
    magic = struct.unpack_from('<H', header, 24)[0]
    # The CLR runtime header is data directory 14; its RVA is non-zero for managed code.
    directory_base = 24 + (112 if magic == 0x20b else 96)
    clr_rva = 0
    try:
        clr_rva = struct.unpack_from('<I', header, directory_base + 14 * 8)[0]
    except struct.error:
        pass
    kind = 'dll' if characteristics & 0x2000 else 'exe'
    if clr_rva:
        return _result('pe-dotnet', arch=arch, bits=bits, kind=kind)
    return _result('pe', arch=arch, bits=bits, kind=kind)


def _elf(head):
    bits = 64 if head[4] == 2 else 32
    endian = '<' if head[5] == 1 else '>'
    machine = struct.unpack_from(endian + 'H', head, 18)[0]
    arch, _ = ELF_MACHINES.get(machine, ('unknown', bits))
    elf_type = {1: 'relocatable', 2: 'executable', 3: 'shared', 4: 'core'}.get(
        struct.unpack_from(endian + 'H', head, 16)[0], 'unknown')
    return _result('elf', arch=arch, bits=bits, kind=elf_type,
                   endian='little' if endian == '<' else 'big')


def _zip(path):
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return _result('raw')
    lower = [n.lower() for n in names]
    if 'androidmanifest.xml' in lower and any(n.endswith('.dex') for n in lower):
        return _result('apk', entries=len(names))
    classes = sum(1 for n in lower if n.endswith('.class'))
    if classes:
        return _result('jar', entries=len(names), classes=classes)
    return _result('zip', entries=len(names))


def _pyc(head):
    magic = struct.unpack_from('<H', head, 0)[0]
    if magic >= 20000:
        return _result('pyc', pythonVersion='2.x', magic=magic)
    for last, version in PYC_MAGIC:
        if magic <= last:
            return _result('pyc', pythonVersion=version, magic=magic)
    return _result('pyc', pythonVersion='unknown (newer than 3.14)', magic=magic)


def _dxbc(path):
    data = Path(path).read_bytes()
    try:
        count = struct.unpack_from('<I', data, 28)[0]
        chunks = []
        for index in range(min(count, 64)):
            offset = struct.unpack_from('<I', data, 32 + index * 4)[0]
            chunks.append(data[offset:offset + 4].decode('ascii', 'replace'))
    except struct.error:
        return _result('raw', note='Truncated DXBC container')
    if 'DXIL' in chunks:
        return _result('dxil', chunks=chunks)
    return _result('dxbc', chunks=chunks)


def detect(path):
    """Return the format record of `path`. Raises OSError if the file cannot be read."""
    path = Path(path)
    size = path.stat().st_size
    with open(path, 'rb') as handle:
        head = handle.read(4096)
    if not head:
        return _result('empty', size=0)
    result = None
    if head[:2] == b'MZ':
        result = _pe(path, head)
    elif head[:4] == b'\x7fELF':
        result = _elf(head)
    elif head[:4] in (b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe',
                      b'\xcf\xfa\xed\xfe'):
        little = head[0] in (0xce, 0xcf)
        cpu = struct.unpack_from('<I' if little else '>I', head, 4)[0]
        arch, bits = MACHO_CPUS.get(cpu, ('unknown', 0))
        result = _result('macho', arch=arch, bits=bits)
    elif head[:4] == b'\xca\xfe\xba\xbe':
        # Java classes and fat Mach-O share this magic. A fat header counts architectures
        # (a handful); a class file has its major version (>= 45) at the same place.
        second = struct.unpack_from('>I', head, 4)[0]
        if second < 45:
            result = _result('macho', arch='universal', bits=0, architectures=second)
        else:
            major = struct.unpack_from('>H', head, 6)[0]
            result = _result('java-class', classVersion=major, java=max(1, major - 44))
    elif head[:2] == b'PK':
        result = _zip(path)
    elif head[:4] == b'dex\n':
        result = _result('dex', version=head[4:7].decode('ascii', 'replace'))
    elif head[:4] == b'DXBC':
        result = _dxbc(path)
    elif head[:4] in (b'\x03\x02\x23\x07', b'\x07\x23\x02\x03'):
        result = _result('spirv', endian='little' if head[0] == 3 else 'big')
    elif len(head) >= 4 and head[2:4] == b'\r\n':
        result = _pyc(head)
    if result is None:
        result = _result('raw')
    result['size'] = size
    result['fileName'] = path.name
    return result
