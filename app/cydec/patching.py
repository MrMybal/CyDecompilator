"""Compile an autonomous C function and replace it in a COPY of a native PE.

Deliberately conservative: no linker relocations, external references, new unwind
metadata, overwritten neighbours, or change of architecture. This is an on-disk patch,
not live process injection. The original project input is immutable.
"""
import hashlib
import re
import shutil
import struct
import uuid
from pathlib import Path

import capstone as cs
import pefile
from capstone import x86_const as x86
from cytools_core import CyToolError

from . import process
from .paths import read_json, write_json
from .workspace import visual_studio_tool


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def target(project, function, engine_id='', extended=False):
    fmt = project.meta()['detect']
    if fmt['format'] != 'pe' or fmt.get('arch') not in ('x86', 'x86_64'):
        raise CyToolError('Unsupported', 'Direct C patching supports native x86/x64 PE only. Rebuild other formats in the source workspace.')
    engine_id = project.resolve_engine(engine_id)
    record = project.find_function(engine_id, function)
    if not record.get('address') or not record.get('size'):
        raise CyToolError('Unsupported', 'This analysis has no bounded native function. Analyze with the built-in engine first.')
    raw = project.binary.read_bytes()
    if digest(raw) != project.meta()['sha256']:
        raise CyToolError('Conflict', 'The cached original binary changed. Open it again as a new project.')
    pe = pefile.PE(data=raw)
    address, size = int(record['address'], 16), int(record['size'])
    rva = address - pe.OPTIONAL_HEADER.ImageBase
    section = pe.get_section_by_rva(rva)
    if size <= 0 or section is None or not section.Characteristics & 0x20000000:
        raise CyToolError('Unsupported', 'The selected range is not executable code.')
    offset = section.PointerToRawData + rva - section.VirtualAddress
    if (rva < section.VirtualAddress or rva + size > section.VirtualAddress + section.SizeOfRawData
            or offset < section.PointerToRawData or offset + size > len(raw)):
        raise CyToolError('Unsupported', 'The function crosses a file-backed section boundary.')
    for other in project.functions(engine_id):
        start = int(other.get('address') or '0', 16)
        if other['id'] != record['id'] and start < address + size and start + int(other.get('size') or 1) > address:
            raise CyToolError('Unsupported', 'The function overlaps another analyzed function.')
    pe.parse_data_directories()
    for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', []):
        for entry in block.entries:
            width = {3: 4, 10: 8}.get(entry.type, 8)
            if entry.type and entry.rva < rva + size and entry.rva + width > rva:
                raise CyToolError('Unsupported', 'The original function contains loader relocations; rebuild the application.')
    # Keep existing unwind metadata valid: only accept functions without an entry.
    for entry in [] if extended else getattr(pe, 'DIRECTORY_ENTRY_EXCEPTION', []):
        if entry.struct.BeginAddress < rva + size and entry.struct.EndAddress > rva:
            raise CyToolError('Unsupported', 'This function has unwind metadata. Direct replacement requires a full rebuild.')
    return raw, pe, record, offset, size


def object_code(raw, symbol, machine):
    """Read a standard COFF object and extract exactly one function with no relocations."""
    if len(raw) < 20:
        raise CyToolError('EngineFailed', 'Invalid compiler object.')
    kind, count, _, symoff, symcount, optional, _ = struct.unpack_from('<HHIIIHH', raw)
    if kind != machine or optional or count > 1000 or symcount > 100000:
        raise CyToolError('Unsupported', 'Compiler object architecture or format does not match the original.')
    if 20 + count * 40 > len(raw) or symoff + symcount * 18 + 4 > len(raw):
        raise CyToolError('EngineFailed', 'Truncated COFF object.')
    sections = []
    for index in range(count):
        pos = 20 + index * 40
        _, _, _, length, offset, _, _, relocations, _, flags = struct.unpack_from('<8sIIIIIIHHI', raw, pos)
        if offset + length > len(raw):
            raise CyToolError('EngineFailed', 'Truncated COFF section.')
        sections.append((offset, length, relocations, flags))
    strings = symoff + symcount * 18
    names, index = [], 0
    while index < symcount:
        pos = symoff + index * 18
        label, value, section, typ, storage, aux = struct.unpack_from('<8sIhHBB', raw, pos)
        if label[:4] == b'\0' * 4:
            at = strings + int.from_bytes(label[4:], 'little')
            if at < strings + 4 or at >= len(raw):
                raise CyToolError('EngineFailed', 'Invalid COFF symbol name.')
            end = raw.find(b'\0', at)
            name = raw[at:end if end >= 0 else len(raw)].decode('ascii', 'replace')
        else:
            name = label.rstrip(b'\0').decode('ascii', 'replace')
        if 0 < section <= count and typ & 0x20:
            names.append((name, value, section))
        index += 1 + aux
    matches = [n for n in names if n[0] == symbol or n[0] == '_' + symbol
               or re.fullmatch(re.escape('_' + symbol) + r'@\d+', n[0])]
    if len(matches) != 1 or len(names) != 1:
        raise CyToolError('Unsupported', 'Provide exactly one C function with the specified symbol name.')
    _, start, section = matches[0]
    offset, length, relocations, flags = sections[section - 1]
    if relocations or not flags & 0x20000000 or start != 0 or not length:
        raise CyToolError('Unsupported', 'The function needs linker relocations or external data. Use a full project rebuild.')
    return raw[offset:offset + length]


def validate_code(code, bits):
    decoder = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64 if bits == 64 else cs.CS_MODE_32)
    decoder.detail = True
    instructions = list(decoder.disasm(code, 0))
    if not instructions or sum(i.size for i in instructions) != len(code):
        raise CyToolError('Unsupported', 'The replacement does not decode as complete instructions.')
    starts = {i.address for i in instructions}
    nonvolatile = {'rbx', 'ebx', 'bx', 'bl', 'bh', 'rbp', 'ebp', 'bp', 'bpl', 'rsi', 'rdi',
                   'r12', 'r13', 'r14', 'r15', 'r12d', 'r13d', 'r14d', 'r15d', 'rsp', 'esp', 'sp', 'spl'}
    if bits == 32:
        nonvolatile |= {'esi', 'edi', 'si', 'di'}
    else:
        nonvolatile |= {'esi', 'edi', 'si', 'di', 'sil', 'dil'}
        nonvolatile |= {f'{r}{suffix}' for r in ('r12', 'r13', 'r14', 'r15') for suffix in ('w', 'b')}
        nonvolatile |= {f'{v}{n}' for v in ('xmm', 'ymm', 'zmm') for n in range(6, 32)}
    for instruction in instructions:
        if (instruction.group(cs.CS_GRP_CALL) or instruction.group(cs.CS_GRP_INT)
                or instruction.group(cs.CS_GRP_PRIVILEGE) or instruction.mnemonic in ('syscall', 'sysenter', 'enter', 'leave')):
            raise CyToolError('Unsupported', 'Only autonomous leaf functions without calls or stack frames can be patched.')
        if any(decoder.reg_name(r) in nonvolatile for r in instruction.regs_access()[1]):
            if not instruction.group(cs.CS_GRP_RET):
                raise CyToolError('Unsupported', 'The replacement changes stack or preserved registers.')
        for operand in instruction.operands:
            if operand.type == x86.X86_OP_MEM:
                if operand.mem.base in (0, x86.X86_REG_RIP, x86.X86_REG_EIP) or operand.mem.segment:
                    raise CyToolError('Unsupported', 'Absolute, segmented and instruction-relative data references require relocation.')
        if instruction.group(cs.CS_GRP_JUMP):
            if not instruction.operands or instruction.operands[0].type != x86.X86_OP_IMM or instruction.operands[0].imm not in starts:
                raise CyToolError('Unsupported', 'Every branch must stay inside the replacement function.')
    # Compiler alignment padding is harmless, but the last reachable instruction must return.
    meaningful = [i for i in instructions if i.mnemonic not in ('nop', 'int3')]
    if not meaningful or not meaningful[-1].group(cs.CS_GRP_RET):
        raise CyToolError('Unsupported', 'The replacement must end with a return.')
    return '\n'.join('%04x  %-24s %s %s' % (i.address, i.bytes.hex(' '), i.mnemonic, i.op_str) for i in instructions)


def prepare(project, function, source, symbol, context, engine_id='', extended=False, bindings=None):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', symbol):
        raise CyToolError('InvalidParameters', 'Use a C function identifier for symbol.')
    raw, pe, record, offset, capacity = target(project, function, engine_id, extended)
    compiler = (shutil.which('clang') or visual_studio_tool('VC/Tools/Llvm/x64/bin/clang.exe')
                or visual_studio_tool('VC/Tools/Llvm/bin/clang.exe'))
    if not compiler:
        raise CyToolError('MissingDependency', 'Install clang or the Visual Studio LLVM C++ tools for C patching.')
    folder = Path(context.workdir) / ('patch-' + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    src, obj = folder / 'replacement.c', folder / 'replacement.obj'
    src.write_text(source, encoding='utf-8')
    bits = pe.OPTIONAL_HEADER.Magic == 0x20b and 64 or 32
    triple = 'x86_64-pc-windows-msvc' if bits == 64 else 'i686-pc-windows-msvc'
    flags = ['-funwind-tables', '-fasynchronous-unwind-tables'] if extended else ['-fno-asynchronous-unwind-tables', '-fno-unwind-tables']
    status, out, err = process.run([compiler, '--target=' + triple, '-O2', '-c', '-x', 'c',
                                  '-ffreestanding', '-fno-stack-protector', *flags, '-o', str(obj), str(src)], context=context, timeout=120,
                                  log_name='patch-compile')
    if status or not obj.is_file():
        raise CyToolError('EngineFailed', 'Replacement compilation failed:\n' + process.tail(out + '\n' + err))
    if extended:
        from .native_linker import link
        candidate, report = link(project, raw, pe, record, offset, capacity, obj.read_bytes(), symbol,
                                 project.resolve_engine(engine_id), bindings or {})
        context.check()
        plan_id = uuid.uuid4().hex
        saved = project.dir / 'patches/native' / plan_id
        saved.mkdir(parents=True)
        (saved / 'candidate.bin').write_bytes(candidate)
        value = {'kind': 'native-linked', 'planId': plan_id, 'projectId': project.id,
            'function': record['id'], 'engine': project.resolve_engine(engine_id), 'source': source, 'symbol': symbol,
            'originalHash': digest(raw), 'candidateHash': digest(candidate), 'offset': offset, 'capacity': capacity,
            'size': report['sectionSize'], **report,
            'note': 'The function entry redirects to appended code. Calls use existing functions/imports; compiler unwind data and ASLR relocations are linked. Keep the original ABI and test the modified copy.'}
        write_json(project.dir / 'patches/plans' / (plan_id + '.json'), value)
        return value
    replacement = object_code(obj.read_bytes(), symbol, pe.FILE_HEADER.Machine)
    assembly = validate_code(replacement, bits)
    if len(replacement) > capacity:
        raise CyToolError('Unsupported', 'Replacement needs %d bytes; original function has %d. Rebuild the project.' % (len(replacement), capacity))
    context.check()
    plan_id = uuid.uuid4().hex
    value = {'planId': plan_id, 'projectId': project.id, 'function': record['id'],
             'engine': project.resolve_engine(engine_id), 'symbol': symbol, 'source': source,
             'originalHash': digest(raw), 'offset': offset, 'capacity': capacity, 'bits': bits,
             'originalBytes': raw[offset:offset + capacity].hex(), 'replacementBytes': replacement.hex(),
             'replacementHash': digest(replacement), 'size': len(replacement), 'disassembly': assembly,
             'note': 'Keep the original signature and calling convention. A successful compilation does not prove ABI or behavior equivalence. Authenticode signatures become invalid.'}
    with project.lock:
        write_json(project.dir / 'patches/plans' / (plan_id + '.json'), value)
    return value


def apply(project, plan_id, destination='', context=None):
    if not re.fullmatch(r'[0-9a-f]{32}', plan_id):
        raise CyToolError('InvalidParameters', 'Invalid patch plan id.')
    with project.lock:
        plan = read_json(project.dir / 'patches/plans' / (plan_id + '.json'), {})
        if not plan or plan.get('projectId') != project.id:
            raise CyToolError('NotFound', 'Prepare this patch before applying it.')
        if plan.get('kind') == 'managed':
            from . import managed_patching
            return managed_patching.apply(project, plan, destination, context)
        if plan.get('kind') == 'native-linked':
            return apply_linked(project, plan, destination, context)
        raw, pe, _, offset, capacity = target(project, plan['function'], plan['engine'])
        replacement = bytes.fromhex(plan['replacementBytes'])
        if (digest(raw) != plan['originalHash'] or plan['offset'] != offset or plan['capacity'] != capacity
                or raw[offset:offset + capacity].hex() != plan['originalBytes']
                or digest(replacement) != plan['replacementHash'] or not replacement or len(replacement) > capacity):
            raise CyToolError('Conflict', 'The patch plan or original changed. Prepare it again.')
        validate_code(replacement, plan['bits'])
        path = Path(destination) if destination else project.dir / 'patches/output' / plan_id / project.binary.name
        if not path.is_absolute():
            raise CyToolError('InvalidParameters', 'destination must be an absolute file path.')
        if path.resolve() == project.binary.resolve() or path.resolve() == Path(project.meta()['sourcePath']).resolve():
            raise CyToolError('InvalidParameters', 'Choose a separate output copy; the original cannot be overwritten.')
        patched = bytearray(raw)
        patched[offset:offset + capacity] = replacement + b'\x90' * (capacity - len(replacement))
        result_pe = pefile.PE(data=bytes(patched))
        struct.pack_into('<I', patched, result_pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), result_pe.generate_checksum())
        if context:
            context.check()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('xb') as file:
                file.write(patched)
        except FileExistsError:
            raise CyToolError('Conflict', 'The output already exists. Choose a new output filename.')
        receipt = {'projectId': project.id, 'planId': plan_id, 'path': str(path),
                   'sha256': digest(patched), 'originalHash': digest(raw), 'function': plan['function'],
                   'offset': offset, 'size': len(replacement), 'originalPreserved': True,
                   'signatureInvalidated': bool(pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size)}
        from .execution import save_receipt
        return save_receipt(project, receipt)


def apply_linked(project, plan, destination, context):
    raw, _, _, _, _ = target(project, plan['function'], plan['engine'], True)
    candidate = (project.dir / 'patches/native' / plan['planId'] / 'candidate.bin').read_bytes()
    if digest(raw) != plan['originalHash'] or digest(candidate) != plan['candidateHash']:
        raise CyToolError('Conflict', 'The verified patch or original changed. Prepare it again.')
    path = Path(destination) if destination else project.dir / 'patches/output' / plan['planId'] / project.binary.name
    if not path.is_absolute() or path.resolve() in (project.binary.resolve(), Path(project.meta()['sourcePath']).resolve()):
        raise CyToolError('InvalidParameters', 'Choose a separate absolute output path.')
    if context:
        context.check()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as file:
            file.write(candidate)
    except FileExistsError:
        raise CyToolError('Conflict', 'The output already exists. Choose a new output filename.')
    from .execution import save_receipt
    return save_receipt(project, {'projectId': project.id, 'planId': plan['planId'], 'path': str(path),
        'sha256': plan['candidateHash'], 'originalHash': plan['originalHash'], 'function': plan['function'],
        'originalPreserved': True, 'size': plan['size'], 'replacementRva': plan['replacementRva'], 'nativeLinked': True})
