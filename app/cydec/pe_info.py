"""Facts about a Windows PE file (EXE, DLL, SYS) that a reverse engineer looks at first.

Headers and protections (ASLR, high-entropy VA, DEP, CFG, SafeSEH...), timestamps, the
CodeView/PDB reference, the Rich header (compiler/linker builds), version resources and
manifest, exports with ordinals and forwarders, TLS callbacks, section entropy, overlay,
Authenticode presence, and what the file is built with or packed by (UPX, PyInstaller,
.NET single-file bundle, Nuitka, Go, Rust, Delphi, Electron, NSIS, Inno Setup, AutoIt...).
"""
import math
import struct
import time
from collections import Counter

DLL_CHARACTERISTICS = {0x20: 'HIGH_ENTROPY_VA', 0x40: 'DYNAMIC_BASE (ASLR)', 0x80: 'FORCE_INTEGRITY',
                       0x100: 'NX_COMPAT (DEP)', 0x200: 'NO_ISOLATION', 0x400: 'NO_SEH', 0x800: 'NO_BIND',
                       0x1000: 'APPCONTAINER', 0x2000: 'WDM_DRIVER', 0x4000: 'GUARD_CF (CFG)',
                       0x8000: 'TERMINAL_SERVER_AWARE'}
SUBSYSTEMS = {1: 'Native', 2: 'Windows GUI', 3: 'Windows console', 5: 'OS/2 console', 7: 'POSIX console',
              9: 'Windows CE GUI', 10: 'EFI application', 11: 'EFI boot driver', 12: 'EFI runtime driver',
              13: 'EFI ROM', 14: 'Xbox', 16: 'Windows boot application'}
PYINSTALLER_MAGIC = b'MEI\x0c\x0b\x0a\x0b\x0e'
NSIS_MAGIC = b'\xef\xbe\xad\xdeNullsoftInst'
DOTNET_BUNDLE_SIGNATURE = bytes([0x8b, 0x12, 0x02, 0xb9, 0x6a, 0x61, 0x20, 0x38, 0x72, 0x7b, 0x93, 0x02, 0x14, 0xd7,
                                 0xa0, 0x32, 0x13, 0xf5, 0xb9, 0xe6, 0xef, 0xae, 0x33, 0x18, 0xee, 0x3b, 0x2d, 0xce,
                                 0x24, 0xb3, 0x6a, 0xae])
# Rich header product ids of the Visual Studio toolchain (subset, enough to name the compiler).
RICH_PRODUCTS = {0x0104: 'Utc1900_C (VS2015+)', 0x0105: 'Utc1900_CPP (VS2015+)', 0x0103: 'Masm1400',
                 0x0102: 'Linker 14.x', 0x0101: 'Export 14.x', 0x0100: 'Implib 14.x', 0x00ff: 'Cvtres 14.x',
                 0x00e0: 'Masm1200', 0x00e1: 'Utc1810_C', 0x00e2: 'Utc1810_CPP', 0x00de: 'Linker 12.x',
                 0x00aa: 'Utc1700_C', 0x00ab: 'Utc1700_CPP', 0x009d: 'Linker 10.x', 0x00ce: 'Utc1800_C',
                 0x00cf: 'Utc1800_CPP', 0x0093: 'Utc1600_CPP', 0x0092: 'Utc1600_C', 0x0001: 'Import (old)'}


def entropy(data):
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum(c / total * math.log2(c / total) for c in counts.values())


def detect_packers(pe, data, overlay_offset):
    found = []
    names = [s.Name.rstrip(b'\0').decode('ascii', 'replace').upper() for s in pe.sections]
    if any(n.startswith('UPX') for n in names) or b'UPX!' in data[:0x1000]:
        found.append({'id': 'upx', 'name': 'UPX packer', 'extractable': True})
    if PYINSTALLER_MAGIC in data[-(8 << 20):]:
        found.append({'id': 'pyinstaller', 'name': 'PyInstaller bundle (Python)', 'extractable': True})
    position = data.find(DOTNET_BUNDLE_SIGNATURE)
    if position >= 8 and struct.unpack_from('<q', data, position - 8)[0] > 0:
        found.append({'id': 'dotnet-bundle', 'name': '.NET single-file bundle', 'extractable': True})
    lowered = data.lower()
    if b'nuitka' in lowered and (b'__nuitka' in lowered or b'nuitka_onefile' in lowered or b'nuitka-' in lowered):
        found.append({'id': 'nuitka', 'name': 'Nuitka (Python compiled to C)', 'extractable': False})
    if b'\xff Go build ID: ' in data or b'go.buildid' in data or b'.go.buildinfo' in data or b'runtime.gopanic' in data:
        found.append({'id': 'go', 'name': 'Go program', 'extractable': False})
    if b'/rustc/' in data or b'rust_panic' in data or b'rust_begin_unwind' in data:
        found.append({'id': 'rust', 'name': 'Rust program', 'extractable': False})
    if b'Embarcadero' in data or (b'Borland' in data and b'TObject' in data):
        found.append({'id': 'delphi', 'name': 'Delphi / C++Builder program', 'extractable': False})
    if overlay_offset and NSIS_MAGIC in data[overlay_offset:overlay_offset + (1 << 20)]:
        found.append({'id': 'nsis', 'name': 'NSIS installer', 'extractable': False})
    if b'Inno Setup Setup Data' in data:
        found.append({'id': 'inno', 'name': 'Inno Setup installer', 'extractable': False})
    if b'AU3!EA06' in data or b'AutoIt v3' in data:
        found.append({'id': 'autoit', 'name': 'AutoIt script', 'extractable': False})
    if b'electron.asar' in lowered or (b'app.asar' in lowered and b'chrome_elf' in lowered):
        found.append({'id': 'electron', 'name': 'Electron application', 'extractable': False})
    if overlay_offset and b'PK\x03\x04' in data[overlay_offset:overlay_offset + 4096]:
        found.append({'id': 'zip-overlay', 'name': 'Zip archive appended (self-extractor)', 'extractable': True})
    return found


def rich_header(data):
    end = data.find(b'Rich', 0x80, 0x400)
    if end < 0:
        return []
    key = struct.unpack_from('<I', data, end + 4)[0]
    start = data.find(struct.pack('<I', 0x536e6144 ^ key), 0x40, end)  # 'DanS'
    if start < 0:
        return []
    entries = []
    for offset in range(start + 16, end, 8):
        comp_id, count = struct.unpack_from('<II', data, offset)
        comp_id ^= key
        count ^= key
        product, build = comp_id >> 16, comp_id & 0xffff
        entries.append({'product': RICH_PRODUCTS.get(product, 'product 0x%04x' % product), 'build': build, 'count': count})
    return entries


def analyse(path):
    import pefile
    data = open(path, 'rb').read()
    pe = pefile.PE(data=data, fast_load=True)
    dirs = pefile.DIRECTORY_ENTRY
    pe.parse_data_directories(directories=[dirs['IMAGE_DIRECTORY_ENTRY_EXPORT'], dirs['IMAGE_DIRECTORY_ENTRY_TLS'],
                                           dirs['IMAGE_DIRECTORY_ENTRY_RESOURCE'], dirs['IMAGE_DIRECTORY_ENTRY_DEBUG'],
                                           dirs['IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG']])
    header = pe.FILE_HEADER
    optional = pe.OPTIONAL_HEADER
    characteristics = header.Characteristics
    dll_chars = optional.DllCharacteristics
    is64 = optional.Magic == 0x20b
    info = {
        'kind': 'DLL' if characteristics & 0x2000 else ('Driver' if optional.Subsystem == 1 else 'EXE'),
        'machine': pefile.MACHINE_TYPE.get(header.Machine, hex(header.Machine)),
        'bits': 64 if is64 else 32,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(header.TimeDateStamp))
        if 0 < header.TimeDateStamp < 0x7fffffff else 'reproducible build / not a date (0x%08x)' % header.TimeDateStamp,
        'subsystem': SUBSYSTEMS.get(optional.Subsystem, str(optional.Subsystem)),
        'imageBase': '0x%x' % optional.ImageBase,
        'entryPoint': '0x%x' % (optional.ImageBase + optional.AddressOfEntryPoint) if optional.AddressOfEntryPoint else '',
        'linker': '%d.%d' % (optional.MajorLinkerVersion, optional.MinorLinkerVersion),
        'osVersion': '%d.%d' % (optional.MajorOperatingSystemVersion, optional.MinorOperatingSystemVersion),
        'largeAddressAware': bool(characteristics & 0x20),
        'protections': [label for bit, label in DLL_CHARACTERISTICS.items() if dll_chars & bit],
        'checksum': {'stored': '0x%x' % optional.CheckSum, 'valid': optional.CheckSum == 0 or pe.verify_checksum()},
        'dotnet': bool(optional.DATA_DIRECTORY[14].VirtualAddress),
        'signed': bool(optional.DATA_DIRECTORY[4].VirtualAddress and optional.DATA_DIRECTORY[4].Size),
    }
    missing = []
    if not dll_chars & 0x40:
        missing.append('ASLR')
    if not dll_chars & 0x100:
        missing.append('DEP')
    if not dll_chars & 0x4000:
        missing.append('CFG')
    if is64 and dll_chars & 0x40 and not dll_chars & 0x20:
        missing.append('high-entropy ASLR')
    info['missingProtections'] = missing
    sections = []
    for section in pe.sections:
        raw = section.get_data()
        flags = section.Characteristics
        sections.append({'name': section.Name.rstrip(b'\0').decode('ascii', 'replace'),
                         'address': '0x%x' % (optional.ImageBase + section.VirtualAddress),
                         'virtualSize': section.Misc_VirtualSize, 'rawSize': section.SizeOfRawData,
                         'entropy': round(entropy(raw), 2),
                         'flags': ''.join(c for bit, c in ((0x40000000, 'R'), (0x80000000, 'W'), (0x20000000, 'X'))
                                          if flags & bit)})
    info['sections'] = sections
    packed = [s['name'] for s in sections if 'X' in s['flags'] and s['entropy'] > 7.2]
    if packed:
        info['highEntropyCode'] = packed
    overlay = pe.get_overlay_data_start_offset()
    info['overlay'] = {'offset': overlay, 'size': len(data) - overlay} if overlay else None
    info['packers'] = detect_packers(pe, data, overlay or 0)
    info['rich'] = rich_header(data)
    exports = []
    export = getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None)
    if export is not None:
        info['exportName'] = export.name.decode('ascii', 'replace') if export.name else ''
        for symbol in export.symbols:
            exports.append({'ordinal': symbol.ordinal,
                            'name': symbol.name.decode('ascii', 'replace') if symbol.name else '',
                            'address': '0x%x' % (optional.ImageBase + symbol.address) if symbol.address else '',
                            'forwarder': symbol.forwarder.decode('ascii', 'replace') if symbol.forwarder else ''})
    info['exports'] = exports
    callbacks = []
    tls = getattr(pe, 'DIRECTORY_ENTRY_TLS', None)
    if tls is not None and tls.struct.AddressOfCallBacks:
        rva = tls.struct.AddressOfCallBacks - optional.ImageBase
        size = 8 if is64 else 4
        for index in range(64):
            try:
                pointer = pe.get_qword_at_rva(rva + index * size) if is64 else pe.get_dword_at_rva(rva + index * size)
            except Exception:
                break
            if not pointer:
                break
            callbacks.append('0x%x' % pointer)
    info['tlsCallbacks'] = callbacks
    from . import pdb
    try:
        info['pdb'] = pdb.codeview(path)
    except Exception:
        info['pdb'] = None
    info['version'] = version_info(pe)
    info['manifest'] = manifest(pe)
    resources = Counter()
    for entry in getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', None).entries if hasattr(pe, 'DIRECTORY_ENTRY_RESOURCE') else []:
        label = pefile.RESOURCE_TYPE.get(entry.id, str(entry.name) if entry.name else str(entry.id))
        resources[label] += len(entry.directory.entries) if hasattr(entry, 'directory') else 1
    info['resources'] = dict(resources)
    pe.close()
    return info


def version_info(pe):
    result = {}
    try:
        pe.parse_data_directories(directories=[2])
        for file_info in getattr(pe, 'FileInfo', []) or []:
            for entry in file_info if isinstance(file_info, list) else [file_info]:
                for table in getattr(entry, 'StringTable', []) or []:
                    for key, value in table.entries.items():
                        result[key.decode('utf-8', 'replace')] = value.decode('utf-8', 'replace')
    except Exception:
        pass
    return result


def manifest(pe):
    import pefile
    for entry in getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', None).entries if hasattr(pe, 'DIRECTORY_ENTRY_RESOURCE') else []:
        if entry.id != pefile.RESOURCE_TYPE['RT_MANIFEST']:
            continue
        for name in entry.directory.entries:
            for language in name.directory.entries:
                data = pe.get_data(language.data.struct.OffsetToData, language.data.struct.Size)
                return data.decode('utf-8', 'replace')[:20000]
    return ''


def summary_lines(info):
    """Human-readable lines for the program panel and the AI context."""
    lines = ['%s, %s-bit %s, %s' % (info['kind'], info['bits'], info['machine'], info['subsystem']),
             'Built: %s, linker %s' % (info['timestamp'], info['linker'])]
    if info.get('version'):
        version = info['version']
        lines.append('Version: %s' % ', '.join('%s=%s' % (k, version[k]) for k in
                                               ('CompanyName', 'ProductName', 'FileDescription', 'FileVersion',
                                                'OriginalFilename') if version.get(k)))
    lines.append('Protections: %s' % (', '.join(info['protections']) or 'none'))
    if info['missingProtections']:
        lines.append('Missing: %s' % ', '.join(info['missingProtections']))
    if info['packers']:
        lines.append('Detected: %s' % ', '.join(p['name'] for p in info['packers']))
    if info.get('pdb'):
        lines.append('PDB: %s (%s)' % (info['pdb']['pdb'], info['pdb']['id']))
    if info['tlsCallbacks']:
        lines.append('TLS callbacks: %s' % ', '.join(info['tlsCallbacks']))
    if info.get('highEntropyCode'):
        lines.append('High-entropy code sections (packed/encrypted?): %s' % ', '.join(info['highEntropyCode']))
    if info['overlay']:
        lines.append('Overlay: %d bytes at 0x%x' % (info['overlay']['size'], info['overlay']['offset']))
    lines.append('Signed (Authenticode present): %s' % ('yes' if info['signed'] else 'no'))
    return lines
