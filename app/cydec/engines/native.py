"""Built-in native engine: PE/ELF loader, recursive function discovery and disassembly.

It needs nothing but Python packages (pefile, pyelftools, Capstone), so it works the
moment the Tool is installed. It does not produce C: it finds functions, imports, strings
and the call graph, and shows clean annotated assembly. The AI "Lift to C" action or the
Ghidra engine turn that into pseudo-code.

Discovery seeds: entry point, exports, symbols and, for x64 PE files, the .pdata unwind
table (which lists every non-leaf function). Direct call targets found while walking the
code become new functions. Indirect jumps (switch tables) end a block: functions reached
only through them can be missed, which the analysis message says.
"""
import bisect
import re
import struct
import time

from cytools_core import CyToolError

from .base import Engine

MAX_FUNCTIONS = 50000
MAX_INSTRUCTIONS = 4_000_000
MAX_FUNCTION_INSTRUCTIONS = 30000
MAX_STRINGS = 60000
PRINTABLE = re.compile(rb'[\x20-\x7e\t]{5,}')
PRINTABLE_WIDE = re.compile(rb'(?:[\x20-\x7e\t]\x00){5,}')


class Segment:
    __slots__ = ('va', 'data', 'executable', 'name', 'end', 'writable', 'virtual_end')

    def __init__(self, va, data, executable, name, writable=False, virtual_size=0):
        self.va, self.data, self.executable, self.name = va, data, executable, name
        self.writable = writable
        self.end = va + len(data)
        self.virtual_end = va + max(len(data), virtual_size)


class Image:
    """A loaded binary: segments, entry, symbols and import slots, all in virtual addresses."""

    def __init__(self):
        self.arch = ''
        self.bits = 0
        self.base = 0
        self.entry = None
        self.segments = []
        self.symbols = {}        # va -> name (functions)
        self.exports = {}        # va -> name
        self.import_slots = {}   # va of the pointer slot (IAT / GOT) -> 'lib!name'
        self.plt = {}            # va of a PLT stub -> 'name'
        self.seeds = set()
        self.reloc_targets = set()
        self.sections = []
        self.imports = []
        self._starts = []

    def finish(self):
        self.segments.sort(key=lambda s: s.va)
        self._starts = [s.va for s in self.segments]

    def segment(self, va):
        index = bisect.bisect_right(self._starts, va) - 1
        if index >= 0:
            seg = self.segments[index]
            if va < seg.end:
                return seg
        return None

    def data_segment(self, va):
        """Segment covering va including its zero-filled (virtual) tail, e.g. .bss."""
        index = bisect.bisect_right(self._starts, va) - 1
        if index >= 0:
            seg = self.segments[index]
            if va < seg.virtual_end:
                return seg
        return None

    def executable(self, va):
        seg = self.segment(va)
        return seg is not None and seg.executable

    def read(self, va, size):
        seg = self.segment(va)
        if seg is None:
            return b''
        offset = va - seg.va
        return seg.data[offset:offset + size]


def load_pe(path):
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    dirs = pefile.DIRECTORY_ENTRY
    pe.parse_data_directories(directories=[dirs['IMAGE_DIRECTORY_ENTRY_IMPORT'],
                                           dirs['IMAGE_DIRECTORY_ENTRY_EXPORT'],
                                           dirs['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT'],
                                           dirs['IMAGE_DIRECTORY_ENTRY_EXCEPTION']])
    image = Image()
    machine = pe.FILE_HEADER.Machine
    image.arch, image.bits = {0x14c: ('x86', 32), 0x8664: ('x86_64', 64),
                              0xaa64: ('arm64', 64)}.get(machine, ('', 0))
    if not image.arch:
        raise CyToolError('Unsupported', 'The built-in engine does not support PE machine 0x%x. '
                          'Use Ghidra.' % machine)
    image.base = pe.OPTIONAL_HEADER.ImageBase
    for section in pe.sections:
        name = section.Name.rstrip(b'\0').decode('ascii', 'replace')
        va = image.base + section.VirtualAddress
        data = section.get_data()
        virtual = max(section.Misc_VirtualSize, 0)
        if virtual and len(data) > virtual:
            data = data[:virtual]
        executable = bool(section.Characteristics & 0x20000000)
        image.segments.append(Segment(va, data, executable, name, bool(section.Characteristics & 0x80000000),
                                      section.Misc_VirtualSize))
        image.sections.append({'name': name, 'address': '0x%x' % va, 'size': len(data),
                               'executable': executable})
    image.finish()
    if pe.OPTIONAL_HEADER.AddressOfEntryPoint:
        image.entry = image.base + pe.OPTIONAL_HEADER.AddressOfEntryPoint
        image.symbols.setdefault(image.entry, 'entry')
    for attribute in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT'):
        for module in getattr(pe, attribute, []) or []:
            library = module.dll.decode('ascii', 'replace') if module.dll else '?'
            for item in module.imports:
                label = item.name.decode('ascii', 'replace') if item.name else 'ord_%d' % (item.ordinal or 0)
                if item.address:
                    image.import_slots[item.address] = library + '!' + label
                image.imports.append({'library': library, 'name': label,
                                      'address': '0x%x' % item.address if item.address else ''})
    export = getattr(pe, 'DIRECTORY_ENTRY_EXPORT', None)
    if export is not None:
        for symbol in export.symbols:
            if not symbol.address:
                continue
            va = image.base + symbol.address
            name = symbol.name.decode('ascii', 'replace') if symbol.name else 'ord_%d' % symbol.ordinal
            image.exports[va] = name
            if image.executable(va):
                image.symbols[va] = name
    for entry in getattr(pe, 'DIRECTORY_ENTRY_EXCEPTION', []) or []:
        begin = getattr(entry.struct, 'BeginAddress', 0)
        if begin:
            image.seeds.add(image.base + begin)
    if image.arch == 'arm64':
        # ARM64 .pdata: 8-byte entries (function start RVA, unwind data), not read by pefile.
        directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[dirs['IMAGE_DIRECTORY_ENTRY_EXCEPTION']]
        raw = image.read(image.base + directory.VirtualAddress, directory.Size) if directory.Size else b''
        for offset in range(0, len(raw) - 7, 8):
            begin = int.from_bytes(raw[offset:offset + 4], 'little')
            if begin:
                image.seeds.add(image.base + begin)
    # Pointers the loader relocates that land in code: vtables, callbacks, function tables.
    try:
        pe.parse_data_directories(directories=[dirs['IMAGE_DIRECTORY_ENTRY_BASERELOC'],
                                               dirs['IMAGE_DIRECTORY_ENTRY_TLS']])
        size = 8 if image.bits == 64 else 4
        for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', []) or []:
            for entry in block.entries:
                if entry.type not in (3, 10):  # HIGHLOW, DIR64
                    continue
                # Only pointers stored in data (vtables, callback tables): relocations inside code
                # are operands, jump tables or the IAT, and would split real functions.
                if image.executable(image.base + entry.rva):
                    continue
                raw = image.read(image.base + entry.rva, size)
                if len(raw) == size:
                    target = int.from_bytes(raw, 'little')
                    if image.executable(target):
                        image.reloc_targets.add(target)
        tls = getattr(pe, 'DIRECTORY_ENTRY_TLS', None)
        if tls is not None and tls.struct.AddressOfCallBacks:
            for index in range(64):
                raw = image.read(tls.struct.AddressOfCallBacks + index * size, size)
                pointer = int.from_bytes(raw, 'little') if len(raw) == size else 0
                if not pointer:
                    break
                if image.executable(pointer):
                    image.symbols.setdefault(pointer, 'tls_callback_%d' % index)
    except Exception:
        pass
    pe.close()
    return image


def load_elf(path):
    from elftools.elf.elffile import ELFFile
    from elftools.elf.relocation import RelocationSection
    from elftools.elf.sections import SymbolTableSection
    image = Image()
    with open(path, 'rb') as handle:
        elf = ELFFile(handle)
        image.arch, image.bits = {'EM_386': ('x86', 32), 'EM_X86_64': ('x86_64', 64),
                                  'EM_AARCH64': ('arm64', 64)}.get(elf['e_machine'], ('', 0))
        if not image.arch:
            raise CyToolError('Unsupported', 'The built-in engine does not support ELF machine %s. '
                              'Use Ghidra.' % elf['e_machine'])
        plt_sections = []
        for section in elf.iter_sections():
            flags = section['sh_flags']
            if not flags & 0x2 or section['sh_type'] == 'SHT_NOBITS':  # SHF_ALLOC
                continue
            va = section['sh_addr']
            executable = bool(flags & 0x4)
            data = section.data()
            image.segments.append(Segment(va, data, executable, section.name, bool(flags & 0x1)))
            image.sections.append({'name': section.name, 'address': '0x%x' % va,
                                   'size': len(data), 'executable': executable})
            if section.name.startswith('.plt'):
                plt_sections.append(section)
        if not image.segments:
            # Stripped console ELF images can have only program headers. Those
            # headers are the loader's source of truth when sections are absent.
            file_size=handle.seek(0,2)
            total=0
            ranges=[]
            for index,segment in enumerate(elf.iter_segments()):
                if segment['p_type']!='PT_LOAD':continue
                offset,size=segment['p_offset'],segment['p_filesz']
                address,memory=segment['p_vaddr'],segment['p_memsz']
                total+=size
                if (offset+size>file_size or size>memory or address+memory>1<<64 or total>512*1024**2):
                    raise CyToolError('Unsupported','Invalid or oversized sectionless ELF load ranges.')
                if any(max(address,start)<min(address+size,end) for start,end in ranges):
                    raise CyToolError('Unsupported','Overlapping sectionless ELF load ranges need a specialized loader.')
                ranges.append((address,address+size))
                flags=segment['p_flags']
                name='PT_LOAD_'+str(index)
                image.segments.append(Segment(address,segment.data(),bool(flags&1),name,bool(flags&2),memory))
                image.sections.append({'name':name,'address':hex(address),'size':size,
                                       'executable':bool(flags&1),'source':'program-header'})
        image.finish()
        image.entry = elf['e_entry'] or None
        if image.entry:
            image.symbols.setdefault(image.entry, '_start')
        for section in elf.iter_sections():
            if isinstance(section, SymbolTableSection):
                for symbol in section.iter_symbols():
                    if symbol['st_info']['type'] != 'STT_FUNC' or not symbol.name:
                        continue
                    value = symbol['st_value']
                    if value and symbol['st_shndx'] != 'SHN_UNDEF':
                        image.symbols.setdefault(value, symbol.name)
                        if section.name == '.dynsym':
                            image.exports[value] = symbol.name
                    elif symbol['st_shndx'] == 'SHN_UNDEF':
                        image.imports.append({'library': '', 'name': symbol.name, 'address': ''})
        for section in elf.iter_sections():
            if isinstance(section, RelocationSection) and section['sh_link']:
                symbols = elf.get_section(section['sh_link'])
                if not isinstance(symbols, SymbolTableSection):
                    continue
                for relocation in section.iter_relocations():
                    index = relocation['r_info_sym']
                    if not index:
                        continue
                    name = symbols.get_symbol(index).name
                    if name:
                        image.import_slots[relocation['r_offset']] = name
    if image.arch == 'arm64':
        arm64_plt_names(image)
    return image


def arm64_plt_names(image):
    """AArch64 PLT stubs (adrp x16, GOT page; ldr x17, [x16, slot]; ...; br x17) -> symbol."""
    import capstone
    from capstone import arm64
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True
    for seg in image.segments:
        if not seg.name.startswith('.plt'):
            continue
        pages = {}
        for insn in md.disasm(seg.data, seg.va):
            ops = insn.operands
            if insn.mnemonic == 'adrp' and len(ops) == 2:
                pages[ops[0].reg] = ops[1].imm
            elif insn.mnemonic == 'ldr' and len(ops) == 2 and ops[1].type == arm64.ARM64_OP_MEM and \
                    ops[1].mem.base in pages:
                name = image.import_slots.get(pages[ops[1].mem.base] + ops[1].mem.disp)
                if name:
                    image.plt[insn.address - 4] = name


def load(path, detect_record):
    fmt = detect_record.get('format')
    if fmt in ('pe', 'pe-dotnet'):
        return load_pe(path)
    if fmt == 'elf':
        return load_elf(path)
    raise CyToolError('Unsupported', 'The built-in native engine reads PE and ELF files. '
                      'Use Ghidra for %s.' % detect_record.get('formatName', fmt))


def disassembler(image):
    import capstone
    if image.arch == 'x86':
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    elif image.arch == 'x86_64':
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    elif image.arch == 'arm64':
        md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    else:
        raise CyToolError('Unsupported', 'No disassembler for ' + image.arch)
    md.detail = True
    md.skipdata = False
    return md


class Walker:
    """Follows the control flow of one function and reports what it touches."""

    def __init__(self, image, md):
        import capstone
        self.image, self.md, self.cs = image, md, capstone
        self.x86 = image.arch in ('x86', 'x86_64')
        self.decoded = 0

    def branch_target(self, insn):
        cs = self.cs
        if self.x86:
            from capstone import x86
            if insn.operands and insn.operands[0].type == x86.X86_OP_IMM:
                return insn.operands[0].imm
            return None
        from capstone import arm64
        for operand in reversed(insn.operands):
            if operand.type == arm64.ARM64_OP_IMM:
                return operand.imm
        return None

    def memory_refs(self, insn):
        """Absolute addresses read by the instruction (rip-relative or absolute)."""
        refs = []
        if not self.x86:
            return refs
        from capstone import x86
        for operand in insn.operands:
            if operand.type == x86.X86_OP_MEM:
                mem = operand.mem
                if mem.base == x86.X86_REG_RIP:
                    refs.append(insn.address + insn.size + mem.disp)
                elif mem.base == 0 and mem.index == 0 and mem.disp > 0:
                    refs.append(mem.disp & 0xffffffffffffffff)
            elif operand.type == x86.X86_OP_IMM and self.image.bits == 32 and operand.imm > 0x10000:
                refs.append(operand.imm)
        return refs

    def linear(self, seg, address):
        """Decode forward from `address` in small windows (no large buffer copies)."""
        view = memoryview(seg.data)
        while seg.va <= address < seg.end:
            offset = address - seg.va
            last = None
            for insn in self.md.disasm(bytes(view[offset:offset + 256]), address):
                last = insn
                yield insn
            if last is None:
                return
            address = last.address + last.size

    def walk(self, start, known_starts):
        """Return (instructions sorted, callees set of va, import names set, refs set)."""
        cs = self.cs
        instructions = {}
        callees, imports, refs = set(), set(), set()
        pending = [start]
        seen_blocks = set()
        while pending and len(instructions) < MAX_FUNCTION_INSTRUCTIONS:
            address = pending.pop()
            if address in seen_blocks or address in instructions:
                continue
            seen_blocks.add(address)
            seg = self.image.segment(address)
            if seg is None or not seg.executable:
                continue
            for insn in self.linear(seg, address):
                self.decoded += 1
                if insn.address in instructions:
                    break
                instructions[insn.address] = insn
                for ref in self.memory_refs(insn):
                    refs.add(ref)
                groups = set(insn.groups)
                mnemonic = insn.mnemonic
                if cs.CS_GRP_RET in groups or mnemonic in ('hlt', 'ud2', 'int3'):
                    break
                if cs.CS_GRP_CALL in groups:
                    target = self.branch_target(insn)
                    if target is not None and self.image.executable(target):
                        callees.add(target)
                    else:
                        for ref in self.memory_refs(insn):
                            if ref in self.image.import_slots:
                                imports.add(self.image.import_slots[ref])
                    continue
                if cs.CS_GRP_JUMP in groups:
                    target = self.branch_target(insn)
                    unconditional = mnemonic in ('jmp', 'b', 'br', 'ljmp')
                    if target is None:
                        for ref in self.memory_refs(insn):
                            if ref in self.image.import_slots:
                                imports.add(self.image.import_slots[ref])
                        if unconditional:
                            break
                        continue
                    if unconditional:
                        if target in known_starts and target != start:
                            callees.add(target)  # tail call
                        elif self.image.executable(target):
                            pending.append(target)
                        break
                    if self.image.executable(target):
                        pending.append(target)
                    continue
                if len(instructions) >= MAX_FUNCTION_INSTRUCTIONS:
                    break
        return [instructions[a] for a in sorted(instructions)], callees, imports, refs


def plt_names(image, md, walker):
    """Map PLT stubs (jmp [GOT slot]) to the imported symbol names they forward to."""
    for seg in image.segments:
        if not seg.name.startswith('.plt'):
            continue
        for insn in md.disasm(seg.data, seg.va):
            if insn.mnemonic in ('jmp', 'bnd jmp'):
                for ref in walker.memory_refs(insn):
                    name = image.import_slots.get(ref)
                    if name:
                        stub = insn.address
                        # The stub begins at the 16-byte boundary holding this jmp.
                        image.plt[stub - (stub - seg.va) % 16] = name


def scan_strings(image):
    found = []
    for seg in image.segments:
        if seg.executable and seg.name not in ('.rdata', '.rodata'):
            continue
        for pattern, encoding in ((PRINTABLE, 'ascii'), (PRINTABLE_WIDE, 'utf-16le')):
            for match in pattern.finditer(seg.data):
                text = match.group(0).decode(encoding, 'replace')
                found.append({'address': '0x%x' % (seg.va + match.start()), 'text': text[:400],
                              'encoding': encoding})
                if len(found) >= MAX_STRINGS:
                    return found
    found.sort(key=lambda s: int(s['address'], 16))
    return found


PROLOGUES = (b'\x55\x8b\xec', b'\x8b\xff\x55\x8b\xec', b'\x55\x89\xe5')
PADDING = (0xcc, 0x90, 0xc3)


def prologue_candidates(image, excluded):
    """push ebp / mov ebp, esp (and the hot-patch form) right after padding or a return."""
    found = []
    for seg in image.segments:
        if not seg.executable:
            continue
        data = seg.data
        for pattern in PROLOGUES:
            position = data.find(pattern)
            while position >= 0:
                va = seg.va + position
                previous = data[position - 1] if position > 0 else 0xcc
                aligned_return = position >= 3 and data[position - 3] == 0xc2  # ret imm16
                if (previous in PADDING or aligned_return) and va not in excluded:
                    found.append(va)
                position = data.find(pattern, position + 1)
    return sorted(set(found))


def function_name(image, va):
    return image.symbols.get(va) or image.plt.get(va) or 'sub_%x' % va


class NativeEngine(Engine):
    id = 'native'
    name = 'Built-in disassembler (Capstone)'
    license = 'BSD-3-Clause (Capstone), MIT (pefile), Unlicense (pyelftools)'
    url = 'https://www.capstone-engine.org/'
    description = ('Always available. PE/ELF x86, x86-64 and ARM64: functions, call graph, '
                   'imports, strings and annotated disassembly. No C output; use Ghidra or the '
                   'AI "Lift to C" action for pseudo-code.')
    formats = ('pe', 'pe-dotnet', 'elf')
    components = ()
    language = 'asm'
    supports_decompile = False
    supports_disassemble = True

    def _image(self, project):
        return load(project.binary, project.meta()['detect'])

    def analyze(self, project, context):
        started = time.monotonic()
        context.progress(2, 'Loading')
        image = self._image(project)
        md = disassembler(image)
        walker = Walker(image, md)
        plt_names(image, md, walker)
        pdb_names = {}
        symbol_status = ''
        if project.meta()['detect']['format'] in ('pe', 'pe-dotnet') and context.options.get('symbols', True):
            from .. import symbols as symbol_store
            context.progress(3, 'Debug symbols')
            pdb_names, loaded = symbol_store.function_names(project, context)
            symbol_status = loaded.get('status', '')
            for va, (display, raw, size) in pdb_names.items():
                if image.executable(va):
                    image.symbols[va] = display
        seeds = set(image.symbols) | set(image.exports) | image.seeds
        if image.entry:
            seeds.add(image.entry)
        seeds = {s for s in seeds if image.executable(s)}
        queue = sorted(seeds)
        known = set(queue)
        functions = {}
        state = {'truncated': False}

        def walk_queue(queue, start_index=0, base=5, span=70):
            index = start_index
            while index < len(queue):
                if len(functions) >= MAX_FUNCTIONS or walker.decoded >= MAX_INSTRUCTIONS:
                    state['truncated'] = True
                    return
                start = queue[index]
                index += 1
                if index % 200 == 0:
                    context.check()
                    context.progress(base + span * index / max(len(queue), 1),
                                     'Walking functions (%d found)' % len(functions))
                if start in functions:
                    continue
                if start in image.plt:
                    functions[start] = {'instructions': [], 'callees': set(), 'imports': set(),
                                        'refs': set(), 'thunk': image.plt[start]}
                    continue
                instructions, callees, imports, refs = walker.walk(start, known)
                functions[start] = {'instructions': instructions, 'callees': callees,
                                    'imports': imports, 'refs': refs}
                for callee in sorted(callees):
                    if callee not in known:
                        known.add(callee)
                        queue.append(callee)

        walk_queue(queue)
        sources = {'symbols/exports/unwind/calls': len(functions)}
        # Second pass: relocated code pointers not inside a known function (vtables, callbacks).
        covered = set()
        for record in functions.values():
            covered.update(i.address for i in record['instructions'])
        extra = sorted(t for t in image.reloc_targets if t not in covered and t not in known)
        if extra and not state['truncated']:
            context.progress(76, 'Function pointers')
            before = len(functions)
            known.update(extra)
            walk_queue(extra, 0, 76, 8)
            sources['code pointers'] = len(functions) - before
            for record in list(functions.values())[before:]:
                covered.update(i.address for i in record['instructions'])
        # Third pass (32-bit x86, no unwind table): classic prologues after padding.
        if image.arch == 'x86' and not state['truncated']:
            context.progress(85, 'Prologue scan')
            before = len(functions)
            candidates = prologue_candidates(image, covered | known)
            known.update(candidates)
            walk_queue(candidates, 0, 85, 5)
            sources['prologue scan'] = len(functions) - before
        truncated = state['truncated']
        context.progress(92, 'Strings')
        strings = scan_strings(image)
        string_at = {int(s['address'], 16): s['text'] for s in strings}
        callers = {}
        for start, record in functions.items():
            for callee in record['callees']:
                callers.setdefault(callee, set()).add(start)
        result = []
        for start in sorted(functions):
            record = functions[start]
            instructions = record['instructions']
            end = max((i.address + i.size for i in instructions), default=start)
            item = {
                'id': '0x%x' % start, 'name': function_name(image, start),
                'address': '0x%x' % start, 'size': end - start, 'kind': 'function',
                'instructionCount': len(instructions),
                'callees': ['0x%x' % c for c in sorted(record['callees']) if c in functions],
                'imports': sorted(record['imports'] | ({record['thunk']} if record.get('thunk') else set())),
                'callers': ['0x%x' % c for c in sorted(callers.get(start, ()))],
                'strings': [string_at[r][:120] for r in sorted(record['refs']) if r in string_at][:40],
                'exported': start in image.exports,
            }
            if start in pdb_names:
                display, raw, size = pdb_names[start]
                item['symbol'] = raw
                if size:
                    item['size'] = size
            result.append(item)
        message = '%d functions (%s)' % (len(result), ', '.join('%s: %d' % kv for kv in sources.items()))
        if symbol_status:
            message += '; symbols: ' + symbol_status
        if truncated:
            message += '. Discovery stopped at the safety limit (%d functions, %d instructions).' % (
                len(functions), walker.decoded)
        analysis = {'arch': image.arch, 'bits': image.bits, 'imageBase': '0x%x' % image.base,
                    'entryPoint': '0x%x' % image.entry if image.entry else '',
                    'functions': result, 'strings': strings, 'imports': image.imports,
                    'exports': [{'name': n, 'address': '0x%x' % a} for a, n in sorted(image.exports.items())],
                    'sections': image.sections, 'message': message,
                    'seconds': round(time.monotonic() - started, 3)}
        if project.meta()['detect']['format'] in ('pe', 'pe-dotnet'):
            try:
                from .. import pe_info
                analysis['pe'] = pe_info.analyse(project.binary)
            except Exception as exc:
                context.log('PE details unavailable: %s' % exc, 'Warning')
        return analysis

    def disassemble(self, project, analysis, function, context):
        image = self._image(project)
        md = disassembler(image)
        walker = Walker(image, md)
        plt_names(image, md, walker)
        start = int(function['address'], 16)
        known = {int(f['address'], 16) for f in analysis['functions']}
        names = {int(f['address'], 16): f['name'] for f in analysis['functions']}
        strings = {int(s['address'], 16): s['text'] for s in analysis.get('strings', [])}
        instructions, _, _, _ = walker.walk(start, known)
        targets = set()
        for insn in instructions:
            if self.cs_jump(walker, insn):
                target = walker.branch_target(insn)
                if target is not None and target != start and target not in known:
                    targets.add(target)
        lines = ['; %s  @ %s  (%d bytes, %d instructions)'
                 % (function['name'], function['address'], function.get('size', 0), len(instructions))]
        if function.get('callers'):
            lines.append('; called by: ' + ', '.join(names.get(int(c, 16), c) for c in function['callers'][:12]))
        if function.get('imports'):
            lines.append('; imports used: ' + ', '.join(function['imports'][:20]))
        lines.append('')
        previous_end = None
        for insn in instructions:
            if previous_end is not None and insn.address != previous_end:
                lines.append('')
            if insn.address == start:
                lines.append(function['name'] + ':')
            elif insn.address in targets:
                lines.append('.L_%x:' % insn.address)
            comment = self.comment(walker, image, insn, names, strings, start, targets)
            text = '    %-10x %-24s %s %s' % (insn.address, insn.bytes.hex()[:24], insn.mnemonic, insn.op_str)
            if comment:
                text = text.ljust(78) + ' ; ' + comment
            lines.append(text.rstrip())
            previous_end = insn.address + insn.size
        return {'code': '\n'.join(lines) + '\n', 'language': 'asm'}

    @staticmethod
    def cs_jump(walker, insn):
        return walker.cs.CS_GRP_JUMP in insn.groups

    @staticmethod
    def comment(walker, image, insn, names, strings, start, targets):
        cs = walker.cs
        groups = set(insn.groups)
        if cs.CS_GRP_CALL in groups or cs.CS_GRP_JUMP in groups:
            target = walker.branch_target(insn)
            if target is not None:
                if target in names and target != start:
                    return names[target]
                if target in image.plt:
                    return image.plt[target]
                if target in targets:
                    return '.L_%x' % target
        for ref in walker.memory_refs(insn):
            if ref in image.import_slots:
                return image.import_slots[ref]
            if ref in strings:
                return repr(strings[ref][:60])
            if ref in names:
                return '&' + names[ref]
        return ''
