"""Bounded COFF linker for on-disk PE function replacements.

Append compiler code/data/unwind metadata to a new section and redirect the original
entry with a relative jump. Imports resolve only to existing IAT slots/functions.
"""
import re
import struct

import capstone as cs
import pefile
from cytools_core import CyToolError


def align(value, alignment):
    return (value + alignment - 1) // alignment * alignment


def coff(raw, machine):
    if len(raw) < 20 or len(raw) > 16 * 1024 * 1024:
        raise CyToolError('Unsupported', 'Invalid or oversized COFF object.')
    kind, count, _, symoff, symcount, optional, _ = struct.unpack_from('<HHIIIHH', raw)
    if kind != machine or optional or not 0 < count < 1000 or symcount > 100000:
        raise CyToolError('Unsupported', 'Unsupported COFF architecture or header.')
    strings = symoff + symcount * 18
    if 20 + count * 40 > len(raw) or strings + 4 > len(raw):
        raise CyToolError('Unsupported', 'Truncated COFF object.')
    string_size = struct.unpack_from('<I', raw, strings)[0]
    if string_size < 4 or strings + string_size > len(raw):
        raise CyToolError('Unsupported', 'Invalid COFF string table.')
    def string(index):
        if not 4 <= index < string_size:
            raise CyToolError('Unsupported', 'Invalid COFF symbol string.')
        end = raw.find(b'\0', strings + index, strings + string_size)
        if end < 0:
            raise CyToolError('Unsupported', 'Unterminated COFF symbol string.')
        return raw[strings + index:end].decode('ascii')
    sections = []
    for index in range(count):
        name, _, _, length, offset, reloc, _, reloc_count, _, flags = struct.unpack_from('<8sIIIIIIHHI', raw, 20 + index * 40)
        name = name.rstrip(b'\0').decode('ascii')
        if name.startswith('/'):
            name = string(int(name[1:]))
        if length > 8 * 1024 * 1024 or (offset and offset + length > len(raw)) or reloc + reloc_count * 10 > len(raw):
            raise CyToolError('Unsupported', 'Invalid COFF section bounds.')
        if flags & 0x01000000:
            raise CyToolError('Unsupported', 'Extended COFF relocation counts are unsupported.')
        data = bytearray(raw[offset:offset + length] if offset else bytes(length))
        rows = [struct.unpack_from('<IIH', raw, reloc + n * 10) for n in range(reloc_count)]
        included = bool(flags & 0xe0) and not name.startswith('.debug')
        if name == '.drectve' and data:
            raise CyToolError('Unsupported', 'Linker directives require a full project link.')
        sections.append({'name': name, 'data': data, 'relocations': rows, 'included': included,
                         'alignment': 1 << max(0, ((flags >> 20) & 15) - 1), 'flags': flags})
    symbols, index = {}, 0
    while index < symcount:
        name, value, section, typ, storage, aux = struct.unpack_from('<8sIhHBB', raw, symoff + index * 18)
        name = string(int.from_bytes(name[4:], 'little')) if name[:4] == bytes(4) else name.rstrip(b'\0').decode('ascii')
        symbols[index] = {'name': name, 'value': value, 'section': section, 'type': typ, 'storage': storage}
        if index + aux >= symcount:
            raise CyToolError('Unsupported', 'Invalid COFF auxiliary symbols.')
        index += 1 + aux
    return sections, symbols


def bindings_for(project, pe, engine, requested):
    result, valid = {}, set()
    for row in project.functions(engine):
        if row.get('address'):
            rva = int(row['address'], 16) - pe.OPTIONAL_HEADER.ImageBase
            valid.add(rva)
            if re.fullmatch(r'[\w?$@]+', row.get('name', '')):
                result[row['name']] = rva
    for row in getattr(pe, 'DIRECTORY_ENTRY_EXPORT', object()).symbols if hasattr(pe, 'DIRECTORY_ENTRY_EXPORT') else []:
        if row.name and not row.forwarder:
            result[row.name.decode('ascii')] = row.address
            valid.add(row.address)
    for dll in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
        for entry in dll.imports:
            if entry.name:
                name = entry.name.decode('ascii')
                rva = entry.address - pe.OPTIONAL_HEADER.ImageBase
                result['__imp_' + name] = rva
                result['__imp__' + name] = rva
                valid.add(rva)
    if not isinstance(requested, dict) or len(requested) > 200:
        raise CyToolError('InvalidParameters', 'Use a symbol-to-original-address map with at most 200 bindings.')
    for name, address in requested.items():
        try:
            rva = int(str(address), 0) - pe.OPTIONAL_HEADER.ImageBase
        except ValueError:
            raise CyToolError('InvalidParameters', 'Native bindings require original virtual addresses.')
        if rva not in valid or not re.fullmatch(r'[\w?$@]+', name):
            raise CyToolError('InvalidParameters', 'Bind only an existing analyzed function, export or IAT slot.')
        result[name] = rva
    return result


def link(project, raw, pe, record, offset, capacity, obj, symbol, engine, requested):
    sections, symbols = coff(obj, pe.FILE_HEADER.Machine)
    matches = [s for s in symbols.values() if s['section'] > 0 and s['type'] & 0x20 and
               (s['name'] == symbol or s['name'] == '_' + symbol or re.fullmatch(re.escape('_' + symbol) + r'@\d+', s['name']))]
    if len(matches) != 1:
        raise CyToolError('Unsupported', 'A unique replacement function symbol is required.')
    root = matches[0]
    if pe.OPTIONAL_HEADER.DllCharacteristics & 0x4000:
        raise CyToolError('Unsupported', 'Control Flow Guard metadata requires a full native link.')
    header = pe.sections[-1].get_file_offset() + 40
    first_raw = min(s.PointerToRawData for s in pe.sections if s.SizeOfRawData)
    if header + 40 > min(first_raw, pe.OPTIONAL_HEADER.SizeOfHeaders) or any(raw[header:header + 40]):
        raise CyToolError('Unsupported', 'No unused PE section header is available; rebuild the application.')
    if any(s['name'].startswith('.tls') for s in sections):
        raise CyToolError('Unsupported', 'New TLS data requires a full link.')
    base = align(max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in pe.sections), pe.OPTIONAL_HEADER.SectionAlignment)
    content = bytearray()
    for section in sections:
        if not section['included']:
            continue
        at = align(len(content), max(16, section['alignment']))
        content.extend(bytes(at - len(content)))
        section['at'] = at
        content.extend(section['data'])
    externals = bindings_for(project, pe, engine, requested)
    loader_relocations = []
    def resolve(index):
        if index not in symbols:
            raise CyToolError('Unsupported', 'Relocation references an auxiliary or missing symbol.')
        sym = symbols[index]
        if 0 < sym['section'] <= len(sections) and 'at' in sections[sym['section'] - 1]:
            target = sections[sym['section'] - 1]
            if not 0 <= sym['value'] <= len(target['data']):
                raise CyToolError('Unsupported', 'COFF symbol is outside its section.')
            return base + target['at'] + sym['value']
        if sym['section'] == 0:
            name = sym['name']
            found = externals.get(name, externals.get(name[1:]) if name.startswith('_') else None)
            if found is None and name.startswith('__imp_'):
                found = externals.get(re.sub(r'@\d+$', '', name))
            if found is not None:
                return found
        raise CyToolError('Unsupported', 'Unresolved native symbol: ' + sym['name'])
    x64 = pe.FILE_HEADER.Machine == 0x8664
    for section in sections:
        if 'at' not in section:
            continue
        for address, index, kind in section['relocations']:
            if kind == 0:
                continue
            width = 8 if x64 and kind == 1 else 4
            if address + width > len(section['data']):
                raise CyToolError('Unsupported', 'COFF relocation is outside its section.')
            at = section['at'] + address
            destination = resolve(index)
            addend = int.from_bytes(content[at:at + width], 'little')
            if (x64 and 4 <= kind <= 9) or (not x64 and kind == 0x14):
                extra = kind - 4 if x64 else 0
                signed = int.from_bytes(content[at:at + 4], 'little', signed=True)
                value = destination + signed - (base + at + 4 + extra)
                if not -(1 << 31) <= value < (1 << 31):
                    raise CyToolError('Unsupported', 'Relative native reference exceeds 2 GiB.')
                content[at:at + 4] = struct.pack('<i', value)
            elif (x64 and kind in (1, 2)) or (not x64 and kind == 6):
                value = pe.OPTIONAL_HEADER.ImageBase + destination + addend
                if value >= 1 << (width * 8):
                    raise CyToolError('Unsupported', 'Absolute native reference overflows its relocation width.')
                content[at:at + width] = value.to_bytes(width, 'little')
                loader_relocations.append((base + at, 10 if width == 8 else 3))
            elif (x64 and kind == 3) or (not x64 and kind == 7):
                content[at:at + 4] = struct.pack('<I', destination + addend)
            else:
                raise CyToolError('Unsupported', 'Unsupported COFF relocation type: ' + str(kind))
    root_section = sections[root['section'] - 1]
    if 'at' not in root_section or not root_section['flags'] & 0x20000000:
        raise CyToolError('Unsupported', 'The replacement symbol is not executable.')
    replacement_rva = base + root_section['at'] + root['value']
    original_rva = int(record['address'], 16) - pe.OPTIONAL_HEADER.ImageBase
    decoder = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64 if x64 else cs.CS_MODE_32)
    overwritten = 0
    for ins in decoder.disasm(raw[offset:offset + capacity], original_rva):
        overwritten += ins.size
        if overwritten >= 5:
            break
    if not 5 <= overwritten <= capacity:
        raise CyToolError('Unsupported', 'The original entry has fewer than five complete bytes for a jump.')
    distance = replacement_rva - original_rva - 5
    if not -(1 << 31) <= distance < (1 << 31):
        raise CyToolError('Unsupported', 'Replacement section is too far from the function entry.')
    # Preserve other runtime entries; the redirected entry itself is a leaf jump.
    runtime = []
    for entry in getattr(pe, 'DIRECTORY_ENTRY_EXCEPTION', []):
        begin, end, unwind = entry.struct.BeginAddress, entry.struct.EndAddress, entry.struct.UnwindData
        if begin < original_rva + capacity and end > original_rva:
            if begin != original_rva or end > original_rva + capacity:
                raise CyToolError('Unsupported', 'The selected analysis range does not contain its complete unwind entry.')
        else:
            runtime.append((begin, end, unwind))
    for section in sections:
        if section['name'].startswith('.pdata') and 'at' in section:
            if len(section['data']) % 12 or not x64:
                raise CyToolError('Unsupported', 'Unsupported native exception table.')
            for at in range(section['at'], section['at'] + len(section['data']), 12):
                begin, end, unwind = struct.unpack_from('<III', content, at)
                if not base <= begin < end <= base + len(content) or not base <= unwind < base + len(content):
                    raise CyToolError('Unsupported', 'Invalid compiler unwind range.')
                runtime.append((begin, end, unwind))
    runtime_at = align(len(content), 4)
    content.extend(bytes(runtime_at - len(content)))
    for row in sorted(runtime):
        content.extend(struct.pack('<III', *row))
    # Rebuild base relocations so absolute references survive ASLR.
    pages = {}
    for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', []):
        for entry in block.entries:
            if entry.type:
                pages.setdefault(entry.rva & ~0xfff, set()).add((entry.type << 12) | (entry.rva & 0xfff))
    for rva, kind in loader_relocations:
        pages.setdefault(rva & ~0xfff, set()).add((kind << 12) | (rva & 0xfff))
    reloc_at = align(len(content), 4)
    content.extend(bytes(reloc_at - len(content)))
    for page, entries in sorted(pages.items()):
        values = sorted(entries)
        if len(values) % 2:
            values.append(0)
        content.extend(struct.pack('<II', page, 8 + len(values) * 2))
        content.extend(struct.pack('<' + 'H' * len(values), *values))
    if len(content) > 16 * 1024 * 1024:
        raise CyToolError('Unsupported', 'Native patch section exceeds 16 MiB.')
    raw_offset = align(len(raw), pe.OPTIONAL_HEADER.FileAlignment)
    raw_size = align(len(content), pe.OPTIONAL_HEADER.FileAlignment)
    patched = bytearray(raw)
    patched.extend(bytes(raw_offset - len(patched)))
    patched.extend(content)
    patched.extend(bytes(raw_size - len(content)))
    patched[offset:offset + overwritten] = b'\xe9' + struct.pack('<i', distance) + b'\x90' * (overwritten - 5)
    flags = 0xe0000060 if any(s['included'] and s['flags'] & 0x80000000 for s in sections) else 0x60000060
    struct.pack_into('<8sIIIIIIHHI', patched, header, b'.cydec\0\0', len(content), base, raw_size, raw_offset, 0, 0, 0, 0, flags)
    def field(name, value):
        struct.pack_into('<I', patched, pe.OPTIONAL_HEADER.get_field_absolute_offset(name), value)
    struct.pack_into('<H', patched, pe.FILE_HEADER.get_field_absolute_offset('NumberOfSections'), pe.FILE_HEADER.NumberOfSections + 1)
    field('SizeOfImage', align(base + len(content), pe.OPTIONAL_HEADER.SectionAlignment))
    field('SizeOfCode', pe.OPTIONAL_HEADER.SizeOfCode + raw_size)
    field('SizeOfInitializedData', pe.OPTIONAL_HEADER.SizeOfInitializedData + raw_size)
    for index, rva, size in [(3, base + runtime_at, len(runtime) * 12), (5, base + reloc_at, len(content) - reloc_at)]:
        if index == 3 and not x64:
            continue
        struct.pack_into('<II', patched, pe.OPTIONAL_HEADER.DATA_DIRECTORY[index].get_file_offset(), rva if size else 0, size)
    if loader_relocations:
        struct.pack_into('<H', patched, pe.FILE_HEADER.get_field_absolute_offset('Characteristics'), pe.FILE_HEADER.Characteristics & ~1)
    verified = pefile.PE(data=bytes(patched))
    field('CheckSum', verified.generate_checksum())
    verified.parse_data_directories()
    # All existing sections keep their RVAs and bytes except the entry jump.
    for section in pe.sections:
        start, end = section.PointerToRawData, section.PointerToRawData + section.SizeOfRawData
        expected = bytearray(raw[start:end])
        if start <= offset < end:
            expected[offset - start:offset - start + overwritten] = patched[offset:offset + overwritten]
        if patched[start:end] != expected:
            raise CyToolError('EngineFailed', 'An original native section changed unexpectedly.')
    instructions = list(decoder.disasm(bytes(content[root_section['at'] + root['value']:root_section['at'] + len(root_section['data'])]), replacement_rva))
    return bytes(patched), {'redirectedBytes': overwritten, 'replacementRva': replacement_rva,
        'sectionSize': len(content), 'linkedSymbols': len(symbols), 'unwindEntries': len(runtime),
        'loaderRelocations': len(loader_relocations), 'disassembly': '\n'.join('%08x %s %s' % (i.address, i.mnemonic, i.op_str) for i in instructions)}
