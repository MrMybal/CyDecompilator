"""x86 / x86-64 to IR.

`lift_function(image, start, names, convention)` decodes one function (following branches and
jump tables), splits it into basic blocks and lifts every instruction into IR statements:

- registers are tracked per family (rax/eax/ax/al/ah -> rax); 32-bit writes zero-extend on x64;
- the stack pointer is followed symbolically, so [rsp+X] / [rbp-X] become stack variables
  (local_X, param_N) unless their address is taken, in which case they stay memory;
- flags are lazy: a flag-setting instruction assigns a Flags(...) source to the `flags`
  pseudo-register and conditional jumps/setcc/cmovcc read Cond(cc, flags);
- calls take their arguments from the calling convention (Win64, SysV, x86 stack pushes,
  thiscall/fastcall registers) and clobber the volatile registers.
"""
import struct

from cytools_core import CyToolError

from .ir import (Addr, Assign, Bin, Branch, Call, Cast, Clobber, Comment, Cond, Const, ExprStmt, FConst, Flags,
                 IndirectJump, Intrinsic, Jump, Load, Ret, Store, Switch, Sym, Tern, Un, Var, mask, negate)

MAX_INSTRUCTIONS = 20000

X64_FAMILIES = {
    'rax': ('rax', 'eax', 'ax', 'al', 'ah'), 'rbx': ('rbx', 'ebx', 'bx', 'bl', 'bh'),
    'rcx': ('rcx', 'ecx', 'cx', 'cl', 'ch'), 'rdx': ('rdx', 'edx', 'dx', 'dl', 'dh'),
    'rsi': ('rsi', 'esi', 'si', 'sil'), 'rdi': ('rdi', 'edi', 'di', 'dil'),
    'rbp': ('rbp', 'ebp', 'bp', 'bpl'), 'rsp': ('rsp', 'esp', 'sp', 'spl'),
}
for _n in range(8, 16):
    X64_FAMILIES['r%d' % _n] = ('r%d' % _n, 'r%dd' % _n, 'r%dw' % _n, 'r%db' % _n)

CONVENTIONS = {
    'win64': {'args': ['rcx', 'rdx', 'r8', 'r9'], 'fargs': ['xmm0', 'xmm1', 'xmm2', 'xmm3'], 'ret': 'rax',
              'volatile': ['rax', 'rcx', 'rdx', 'r8', 'r9', 'r10', 'r11', 'xmm0', 'xmm1', 'xmm2', 'xmm3', 'xmm4', 'xmm5'],
              'stack_args': 0x20, 'slot': 8, 'positional': True},
    'sysv': {'args': ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9'], 'fargs': ['xmm%d' % i for i in range(8)], 'ret': 'rax',
             'volatile': ['rax', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11'] + ['xmm%d' % i for i in range(16)],
             'stack_args': 0, 'slot': 8, 'positional': False},
    'x86': {'args': [], 'fargs': [], 'ret': 'eax', 'volatile': ['eax', 'ecx', 'edx'], 'stack_args': 0, 'slot': 4,
            'positional': False},
    # AArch64 (AAPCS64 and Windows ARM64): integer and floating-point arguments use separate
    # register sequences; prototypes list the integer parameters first.
    'aapcs64': {'args': ['x%d' % i for i in range(8)], 'fargs': ['v%d' % i for i in range(8)], 'ret': 'x0',
                'volatile': ['x%d' % i for i in range(19)] + ['v%d' % i for i in range(8)] +
                            ['v%d' % i for i in range(16, 32)],
                'stack_args': 0, 'slot': 8, 'positional': False},
}

CC = {'je': 'e', 'jz': 'e', 'jne': 'ne', 'jnz': 'ne', 'jl': 'l', 'jnge': 'l', 'jle': 'le', 'jng': 'le', 'jg': 'g',
      'jnle': 'g', 'jge': 'ge', 'jnl': 'ge', 'jb': 'b', 'jc': 'b', 'jnae': 'b', 'jbe': 'be', 'jna': 'be',
      'ja': 'a', 'jnbe': 'a', 'jae': 'ae', 'jnb': 'ae', 'jnc': 'ae', 'js': 's', 'jns': 'ns', 'jo': 'o', 'jno': 'no',
      'jp': 'p', 'jpe': 'p', 'jnp': 'np', 'jpo': 'np'}


class Image:
    """What the lifter needs from the loaded binary (see engines/native.py Image)."""

    def __init__(self, native_image, names, function_starts):
        self.native = native_image
        self.names = names                      # va -> display name of functions
        self.function_starts = function_starts  # set of known function entry addresses
        self.bits = native_image.bits
        self.arch = native_image.arch
        self.signatures = {}                    # callee va -> (stack params, extra register params)
        self.signature_depth = 0

    def read(self, va, size):
        return self.native.read(va, size)

    def executable(self, va):
        return self.native.executable(va)


# Registers a 32-bit callee may take as non-standard inputs (MSVC helpers such as _allshr).
X86_REGISTER_ARGS = ('eax', 'ecx', 'edx', 'ebx', 'esi', 'edi')
SIGNATURE_DEPTH = 6
FLAG_REGISTERS = ('rflags', 'eflags', 'flags', 'nzcv')


def callee_signature(image, target, convention):
    """(positional parameter count, extra register parameters, returns a value, return size) of a
    callee, from its own data flow, so calls match the callee's prototype.

    None when unknown (recursion, too deep, or the callee cannot be lifted)."""
    if target in image.signatures:
        return image.signatures[target]
    if image.signature_depth >= SIGNATURE_DEPTH:
        return None
    image.signatures[target] = None
    image.signature_depth += 1
    try:
        from .cgen import Generator
        from .dataflow import Program
        lifted = lift_function(image, target, convention)
        generator = Generator(Program(lifted).run(), 'sig', lifted.word)
        generator.narrow()
        generator.infer()
        generator.assign_names()
        signature = signature_of(generator)
    except Exception:
        signature = None
    finally:
        image.signature_depth -= 1
    image.signatures[target] = signature
    return signature


def signature_of(generator):
    """Prototype facts of a generated function, as callers use them (see callee_signature)."""
    program = generator.p
    return (generator.stack_param_count, tuple(generator.register_params),
            bool(program.returns) and not program.float_return,
            program.return_size if program.returns else 0, program.float_return,
            tuple(generator.param_sizes), tuple(bool(v.float or v.vector) for v in generator.param_list))


class Family:
    def __init__(self, bits):
        self.bits = bits
        self.map = {}
        if bits == 64:
            for family, names in X64_FAMILIES.items():
                for index, name in enumerate(names):
                    self.map[name] = (family, (8, 4, 2, 1, 1)[index], 1 if index == 4 else 0)
            self.word = 8
        else:
            for family, names in X64_FAMILIES.items():
                if family.startswith('r') and family[1:].isdigit():
                    continue
                short = 'e' + family[1:]
                for index, name in enumerate(names[1:]):
                    self.map[name] = (short, (4, 2, 1, 1)[index], 1 if index == 3 else 0)
            self.word = 4
        self.sp = 'rsp' if bits == 64 else 'esp'
        self.bp = 'rbp' if bits == 64 else 'ebp'
        self.ax = 'rax' if bits == 64 else 'eax'
        self.cx = 'rcx' if bits == 64 else 'ecx'
        self.dx = 'rdx' if bits == 64 else 'edx'
        self.si = 'rsi' if bits == 64 else 'esi'
        self.di = 'rdi' if bits == 64 else 'edi'


class LiftedFunction:
    def __init__(self, start):
        self.start = start
        self.blocks = {}       # block address -> list of statements
        self.order = []        # block addresses in address order
        self.succ = {}
        self.instructions = {}
        self.frame_size = 0
        self.stack_vars = {}   # name -> size
        self.memory_slots = set()
        self.calls = []
        self.unsupported = []
        self.convention = ''
        self.word = 8


# ---------------------------------------------------------------------- decoding / CFG

def decode_function(image, start, md):
    """Instructions reachable from `start` inside the function, and block leaders."""
    import capstone
    instructions = {}
    leaders = {start}
    pending = [start]
    jump_tables = {}
    while pending and len(instructions) < MAX_INSTRUCTIONS:
        address = pending.pop()
        if address in instructions or not image.executable(address):
            continue
        while address not in instructions and image.executable(address):
            data = image.read(address, 16)
            insn = next(md.disasm(data, address), None)
            if insn is None:
                break
            instructions[address] = insn
            groups = set(insn.groups)
            following = address + insn.size
            if capstone.CS_GRP_RET in groups or insn.mnemonic in ('hlt', 'ud2', 'int3'):
                break
            if capstone.CS_GRP_JUMP in groups:
                target = imm_target(insn)
                if insn.mnemonic == 'jmp':
                    if target is not None:
                        if target in image.function_starts and target != start:
                            break  # tail call
                        leaders.add(target)
                        pending.append(target)
                    else:
                        table = resolve_jump_table(image, instructions, insn)
                        if table:
                            jump_tables[address] = table
                            for case_target in set(table['targets']):
                                leaders.add(case_target)
                                pending.append(case_target)
                    break
                if target is not None:
                    leaders.add(target)
                    pending.append(target)
                leaders.add(following)
                address = following
                continue
            if capstone.CS_GRP_CALL in groups and is_noreturn_call(image, insn):
                break
            address = following
    return instructions, leaders, jump_tables


NORETURN = {'exit', '_exit', 'abort', 'ExitProcess', 'TerminateProcess', '__fastfail', '_invalid_parameter_noinfo_noreturn',
            '__report_gsfailure', '_CxxThrowException', 'RaiseException', 'FatalExit', 'longjmp', '__stack_chk_fail',
            '_Exit', 'quick_exit', '__assert_fail', 'ExitThread'}


def is_noreturn_call(image, insn):
    target = imm_target(insn)
    name = ''
    if target is not None:
        name = image.names.get(target, '')
    else:
        for ref in memory_targets(insn, image.bits):
            name = image.native.import_slots.get(ref, '')
    return name.split('!')[-1].split('::')[-1] in NORETURN


def imm_target(insn):
    from capstone import x86
    if insn.operands and insn.operands[0].type == x86.X86_OP_IMM:
        return insn.operands[0].imm
    return None


def memory_targets(insn, bits):
    from capstone import x86
    refs = []
    for operand in insn.operands:
        if operand.type == x86.X86_OP_MEM:
            mem = operand.mem
            if mem.base == x86.X86_REG_RIP:
                refs.append(insn.address + insn.size + mem.disp)
            elif mem.base == 0 and mem.index == 0:
                refs.append(mem.disp & mask(bits // 8))
    return refs


def resolve_jump_table(image, instructions, jmp):
    """Recognise MSVC/GCC/Clang jump tables for `jmp reg` / `jmp [table + idx*N]`."""
    from capstone import x86
    previous = [instructions[a] for a in sorted(a for a in instructions if a < jmp.address)][-12:]
    operand = jmp.operands[0]
    entries = []
    base = None
    kind = None
    table = None
    width = 4
    index_reg = None
    if operand.type == x86.X86_OP_MEM and operand.mem.index and operand.mem.base == 0:
        table = operand.mem.disp & mask(image.bits // 8)
        width = operand.mem.scale
        kind = 'absolute'
        index_reg = jmp.reg_name(operand.mem.index)
    elif operand.type == x86.X86_OP_REG:
        load = None
        target_reg = jmp.reg_name(operand.reg)
        # Expected: mov/movsxd r32, [B + idx*4 (+off)] ; add target, B ; lea B, [rip+X]
        load = add = lea = None
        for insn in reversed(previous):
            if insn.mnemonic == 'add' and add is None and insn.op_str.startswith(target_reg):
                add = insn
            elif insn.mnemonic in ('mov', 'movsxd', 'movzx') and load is None and add is not None and \
                    insn.operands[1].type == x86.X86_OP_MEM and insn.operands[1].mem.index:
                load = insn
            elif insn.mnemonic == 'lea' and lea is None and insn.operands[1].type == x86.X86_OP_MEM and \
                    insn.operands[1].mem.base == x86.X86_REG_RIP:
                lea = insn
        if load is None or (lea is None and image.bits != 64):
            return None
        if lea is not None:
            base = lea.address + lea.size + lea.operands[1].mem.disp
        else:
            base = image.native.base
            if image.native.data_segment(base + load.operands[1].mem.disp) is None:
                return None
        mem = load.operands[1].mem
        table = base + mem.disp
        width = 4
        kind = 'relative-signed' if load.mnemonic == 'movsxd' else 'relative'
        index_reg = load.reg_name(mem.index)
    else:
        return None
    count = None
    for insn in reversed(previous):
        if insn.mnemonic == 'cmp' and len(insn.operands) == 2 and insn.operands[1].type == x86.X86_OP_IMM:
            count = insn.operands[1].imm + 1
            break
    limit = count if count and 0 < count <= 4096 else 512
    targets = []
    for index in range(limit):
        raw = image.read(table + index * width, width)
        if len(raw) != width:
            break
        value = int.from_bytes(raw, 'little')
        if kind == 'absolute':
            target = value
        elif kind == 'relative-signed':
            target = (table if base is None else base) + (value - (1 << 32) if value >> 31 else value)
        else:
            target = base + value
        target &= mask(image.bits // 8)
        if not image.executable(target):
            if count is None:
                break
            return None
        targets.append(target)
    if not targets:
        return None
    return {'targets': targets, 'index': index_reg, 'count': len(targets),
            'load_address': load.address if kind != 'absolute' else jmp.address}


# ---------------------------------------------------------------------- lifter

class Lifter:
    def __init__(self, image, convention):
        import capstone
        self.image = image
        self.fam = Family(image.bits)
        self.cc = CONVENTIONS[convention]
        self.convention = convention
        mode = capstone.CS_MODE_64 if image.bits == 64 else capstone.CS_MODE_32
        self.md = capstone.Cs(capstone.CS_ARCH_X86, mode)
        self.md.detail = True
        self.word = image.bits // 8

    # ------------------------------------------------------------------ registers

    def reg(self, name):
        family, size, offset = self.fam.map.get(name, (name, self.word, 0))
        return family, size, offset

    def read_reg(self, name):
        if name.startswith(('xmm', 'ymm')):
            if name[3:] == '0' and self.float_call is not None and not self.zero_idiom():
                self.take_float_call()
            return Var('xmm' + name[3:], 16)
        family, size, offset = self.reg(name)
        if family == self.fam.sp:
            return self.sp_expr()
        held = self.state.get('stackregs', {}).get(family)
        if held is not None and size == self.word and not (family == self.fam.bp and self.state['fp'] is not None):
            return self.stack_address(held)
        if family == self.fam.bp and self.state['fp'] is not None:
            return self.stack_address(self.state['fp'])
        var = Var(family, self.word)
        if offset:
            return Cast('trunc', Bin('>>u', var, Const(8, self.word), self.word), 1)
        if size == self.word:
            return var
        return Cast('trunc', var, size)

    def write_reg(self, name, value, address):
        if name.startswith(('xmm', 'ymm')):
            if name[3:] == '0':
                self.float_call = None
            self.emit(Assign(Var('xmm' + name[3:], 16), value, address))
            return
        family, size, offset = self.reg(name)
        if family == self.fam.sp:
            return  # handled by stack tracking
        if family == self.fam.bp:
            self.state['fp'] = None
        # Remember registers that hold a stack address (mov rax, rsp / lea rbx, [rsp+20h]) so
        # accesses through them stay frame accesses.
        held = dict(self.state.get('stackregs', {}))
        held.pop(family, None)
        stack = self.stack_offset(value) if size == self.word else None
        if stack is not None:
            held[family] = stack
        self.state['stackregs'] = held
        var = Var(family, self.word)
        if size == self.word:
            self.emit(Assign(var, value, address))
        elif size == 4 and self.word == 8:
            self.emit(Assign(var, Cast('zext', value, 8), address))
        else:
            shift = 8 * offset
            keep = mask(self.word) ^ (mask(size) << shift)
            merged = Bin('|', Bin('&', var, Const(keep, self.word), self.word),
                         Bin('<<', Cast('zext', value, self.word), Const(shift, self.word), self.word), self.word)
            self.emit(Assign(var, merged, address))

    # ------------------------------------------------------------------ stack

    def sp_expr(self):
        return self.stack_address(self.state['sp'])

    def stack_address(self, offset):
        return Addr('stack%+d' % offset if offset else 'stack+0', self.word)

    @staticmethod
    def stack_offset(expr):
        """Offset of a stack address expression (Addr('stack-16') + c), or None."""
        if isinstance(expr, Addr) and expr.name.startswith('stack'):
            return int(expr.name[5:])
        if isinstance(expr, Bin) and expr.op in ('+', '-') and isinstance(expr.b, Const):
            base = Lifter.stack_offset(expr.a)
            if base is not None:
                from .ir import signed
                delta = signed(expr.b.value, expr.b.size)
                return base + delta if expr.op == '+' else base - delta
        return None

    def compute_regions(self):
        """Frame layout: a local whose address escapes is a buffer running up to the next escaped
        local (or the top of the frame); every access inside it goes through memory."""
        negatives = sorted(o for o in self.memory_slots if o < 0)
        self.regions = {o: negatives[i + 1] if i + 1 < len(negatives) else 0 for i, o in enumerate(negatives)}
        # Win64 home (shadow) slots belong to this function too.
        homes = sorted(o for o in self.memory_slots if self.home_slot(o))
        self.regions.update({o: homes[i + 1] if i + 1 < len(homes) else 0x28 for i, o in enumerate(homes)})

    def home_slot(self, offset):
        return self.convention == 'win64' and 0 < offset <= 0x20

    def region_of(self, offset):
        for start, end in self.regions.items():
            if start <= offset < end:
                return start
        return None

    def stack_var_name(self, offset):
        if offset < 0:
            return 'local_%x' % -offset
        if self.word == 4:
            return 'param_%d' % ((offset - 4) // 4 + 1) if offset >= 4 else 'retaddr'
        if offset == 0:
            return 'retaddr'
        if offset <= 0x20 and self.convention == 'win64':
            return 'home_%x' % offset
        first = 0x28 if self.convention == 'win64' else 8
        return 'param_%d' % ((offset - first) // 8 + len(self.cc['args']) + 1)

    def memory_expr(self, insn, operand):
        from capstone import x86
        mem = operand.mem
        size = operand.size or self.word
        parts = []
        if mem.base == x86.X86_REG_RIP:
            target = insn.address + insn.size + mem.disp
            return self.global_address(target, size), None
        base = insn.reg_name(mem.base) if mem.base else None
        index = insn.reg_name(mem.index) if mem.index else None
        displacement = mem.disp
        expr = None
        if base:
            expr = self.read_reg(base)
        if index:
            idx = self.read_reg(index)
            if mem.scale != 1:
                idx = Bin('*', idx, Const(mem.scale, self.word), self.word)
            expr = idx if expr is None else Bin('+', expr, idx, self.word)
        if expr is None:
            return self.global_address(displacement & mask(self.word), size), None
        if displacement:
            target = displacement & mask(self.word)
            seg = self.image.native.data_segment(target) if target > 0x10000 else None
            base_value = self.global_address(target, size) if seg is not None and not seg.executable else \
                Const(displacement, self.word)
            expr = Bin('+', expr, base_value, self.word)
        from .ir import simplify
        expr = simplify(expr)
        offset = self.stack_offset(expr)
        return expr, offset

    def global_address(self, address, size):
        name = self.image.names.get(address)
        if name and self.image.executable(address):
            return Sym(name, address, self.word, 'code')
        imported = self.image.native.import_slots.get(address)
        if imported:
            return Sym('&' + imported.split('!')[-1], address, self.word, 'iat')
        seg = self.image.native.data_segment(address)
        if seg is None or seg.executable:
            return Const(address, self.word)
        if seg.writable:
            return Sym(name or 'DAT_%x' % address, address, self.word, 'data')
        text = read_c_string(self.image.native, address) if not name else None
        if text is not None:
            return Sym(text, address, self.word, 'string')
        return Sym(name or 'DAT_%x' % address, address, self.word, 'rodata')

    def rodata_value(self, addr, size, is_float=False, vector=None):
        """Value of a read-only constant at a known address, or None."""
        base, delta = None, 0
        if isinstance(addr, Sym) and addr.kind in ('rodata', 'string'):
            base = addr.address
        elif isinstance(addr, Bin) and addr.op == '+' and isinstance(addr.a, Sym) and addr.a.kind in ('rodata', 'string') \
                and isinstance(addr.b, Const):
            base, delta = addr.a.address, addr.b.value
        elif isinstance(addr, Const):
            seg = self.image.native.data_segment(addr.value)
            if seg is not None and not seg.writable and not seg.executable:
                base = addr.value
        if base is None:
            return None
        raw = self.image.read(base + delta, size)
        if len(raw) != size:
            return None
        if vector:
            import math
            floats = struct.unpack('<4f', raw) if vector == 'ps' else struct.unpack('<2d', raw) if vector == 'pd' else ()
            if not all(math.isfinite(v) for v in floats) or any(v == 0 and math.copysign(1, v) < 0 for v in floats):
                vector = 'epi32'    # masks (NaN, infinities, -0.0): keep the exact bits
            if vector == 'ps':
                return Intrinsic('_mm_setr_ps', [FConst(v, 4) for v in struct.unpack('<4f', raw)], 16)
            if vector == 'pd':
                return Intrinsic('_mm_setr_pd', [FConst(v, 8) for v in struct.unpack('<2d', raw)], 16)
            return Intrinsic('_mm_setr_epi32', [Const(v, 4) for v in struct.unpack('<4I', raw)], 16)
        if is_float and size in (4, 8):
            return FConst(struct.unpack('<f' if size == 4 else '<d', raw)[0], size)
        if size in (1, 2, 4, 8):
            return Const(int.from_bytes(raw, 'little'), size)
        return None

    def operand_value(self, insn, index, size=None):
        from capstone import x86
        operand = insn.operands[index]
        if operand.type == x86.X86_OP_REG:
            return self.read_reg(insn.reg_name(operand.reg))
        if operand.type == x86.X86_OP_IMM:
            return Const(operand.imm, size or operand.size or self.word)
        if operand.type == x86.X86_OP_MEM:
            return self.load(insn, operand)
        raise CyToolError('Unsupported', 'operand type')

    def load(self, insn, operand, is_float=False, size=None):
        addr, offset = self.memory_expr(insn, operand)
        size = size or operand.size or self.word
        if isinstance(addr, Sym) and addr.kind == 'iat':
            return Sym(addr.name[1:], addr.address, size, 'import')
        if offset is not None and self.region_of(offset) is None:
            name = self.stack_var_name(offset)
            self.stack_vars[name] = max(self.stack_vars.get(name, 0), size)
            var = Var(name, max(self.stack_vars[name], size))
            return var if size == var.size else Cast('trunc', var, size)
        if offset is not None:
            addr = self.stack_address(offset)     # canonical: rendered inside its frame buffer
        constant = self.rodata_value(addr, size, is_float)
        if constant is not None:
            return constant
        return Load(addr, size, is_float)

    def store(self, insn, operand, value, address, is_float=False):
        addr, offset = self.memory_expr(insn, operand)
        size = operand.size or self.word
        if offset is not None and self.region_of(offset) is None:
            name = self.stack_var_name(offset)
            self.stack_vars[name] = max(self.stack_vars.get(name, 0), size)
            statement = Assign(Var(name, self.stack_vars[name]), value, address)
            self.emit(statement)
            self.pending_stack[offset] = statement
            return
        if offset is not None:
            addr = self.stack_address(offset)
        self.emit(Store(addr, value, size, is_float, address))

    def write_operand(self, insn, index, value, address, is_float=False):
        from capstone import x86
        operand = insn.operands[index]
        if operand.type == x86.X86_OP_REG:
            self.write_reg(insn.reg_name(operand.reg), value, address)
        elif operand.type == x86.X86_OP_MEM:
            self.store(insn, operand, value, address, is_float)

    def emit(self, statement):
        self.out.append(statement)

    def set_flags(self, kind, a, b, size, address):
        self.emit(Assign(Var('flags', 1), Flags(kind, a, b, size), address))

    # ------------------------------------------------------------------ calls

    def call(self, insn, address):
        target = imm_target(insn)
        if target is not None:
            name = self.image.names.get(target) or 'FUN_%x' % target
            callee = Sym(name, target, self.word, 'code')
        else:
            operand = insn.operands[0]
            from capstone import x86
            if operand.type == x86.X86_OP_MEM:
                value = self.load(insn, operand)
                callee = value if isinstance(value, Sym) else value
            else:
                callee = self.read_reg(insn.reg_name(operand.reg))
            if isinstance(callee, Const) and self.image.executable(callee.value):
                target = callee.value
                callee = Sym(self.image.names.get(target) or 'FUN_%x' % target, target, self.word, 'code')
        args = []
        sp_call = self.state['sp']
        signature = callee_signature(self.image, target, self.convention)             if target is not None and self.image.executable(target) else None
        if self.convention == 'x86':
            if signature is None and self.thiscall_candidate():
                args.append(Var(self.fam.cx, 4))
            k = 0
            if signature is not None and len(signature) > 5:
                # Walk the callee's parameters over the outgoing stack area.
                offset = sp_call
                for size in signature[5]:
                    first = self.pending_stack.pop(offset, None)
                    if size == 8 and first is not None and first.dst.size < 8 and offset + 4 in self.pending_stack:
                        high = self.pending_stack.pop(offset + 4)
                        args.append(Bin('|', Cast('zext', first.dst, 8),
                                        Bin('<<', Cast('zext', high.dst, 8), Const(32, 8), 8), 8))
                    elif first is not None:
                        args.append(first.dst)
                    else:
                        args.append(Const(0, size))
                    offset += size
                k = (offset - sp_call) // 4
            else:
                while sp_call + 4 * k in self.pending_stack and (signature is None or k < signature[0]):
                    statement = self.pending_stack.pop(sp_call + 4 * k)
                    # The slot variable (not the pushed expression) is passed: the data-flow pass
                    # inlines it only when the registers it read are unchanged at the call.
                    args.append(statement.dst)
                    k += 1
                if signature is not None:
                    args.extend(Const(0, 4) for _ in range(signature[0] - k))
            self.pushed_args = k
            if signature is not None:
                args.extend(Var(register, 4) for register in signature[1])
        else:
            defined = self.defined_since_call
            count = 0
            for position, register in enumerate(self.cc['args']):
                freg = self.cc['fargs'][position] if position < len(self.cc['fargs']) else None
                if register in defined or (freg and freg in defined):
                    count = position + 1
            if signature is not None:
                count = min(signature[0], len(self.cc['args']))
            hints = signature[6] if signature is not None and len(signature) > 6 else ()
            for position in range(count):
                register = self.cc['args'][position]
                freg = self.cc['fargs'][position] if position < len(self.cc['fargs']) else None
                if position < len(hints) and self.convention == 'win64':
                    # The callee's own parameter kind decides between rcx.. and xmm0..
                    args.append(Var(freg, 16) if hints[position] else Var(register, 8))
                elif register not in defined and freg in defined:
                    args.append(Var(freg, 16))
                else:
                    args.append(Var(register, 8))
            first = sp_call + self.cc['stack_args']
            k = 0
            stack_count = None if signature is None else max(0, signature[0] - len(self.cc['args']))
            while first + 8 * k in self.pending_stack and (stack_count is None or k < stack_count):
                statement = self.pending_stack.pop(first + 8 * k)
                # The slot variable (not the pushed expression) is passed: the data-flow pass
                # inlines it only when the registers it read are unchanged at the call.
                args.append(statement.dst)
                k += 1
            if stack_count is not None:
                args.extend(Const(0, 8) for _ in range(stack_count - k))
        float_size = signature[4] if signature is not None and len(signature) > 4 else 0
        call = Call(callee, args, self.word, returns=None if signature is None else signature[2],
                    float_size=float_size)
        if signature is not None and len(signature) > 6:
            call.hints = signature[6]
        self.float_call = None
        volatile = {self.reg(r)[0] for r in self.cc['volatile'] if not r.startswith('xmm')}
        self.state['stackregs'] = {k: v for k, v in self.state.get('stackregs', {}).items() if k not in volatile}
        self.calls.append(call)
        clobbered = [r for r in self.cc['volatile'] if r != self.cc['ret']]
        if float_size:
            # Floating-point result: st0 (x86) or xmm0.
            call.size = float_size
            if self.convention == 'x86':
                depth = self.state.get('fpu', 0) + 1
                self.state['fpu'] = depth
                self.emit(Assign(Var('fst%d' % depth, 8), call, address))
                self.emit(Clobber(list(self.cc['volatile']) + ['flags'], address))
            else:
                setter = '_mm_set_sd' if float_size == 8 else '_mm_set_ss'
                self.emit(Assign(Var('xmm0', 16), Intrinsic(setter, [call], 16), address))
                self.emit(Clobber([r for r in self.cc['volatile'] if r != 'xmm0'] + ['flags'], address))
            self.defined_since_call = set()
            self.pending_stack = {}
            return
        if signature is not None and not signature[2]:
            # The callee returns nothing: a plain call statement.
            self.emit(ExprStmt(call, address))
            self.emit(Clobber(list(self.cc['volatile']) + ['flags'], address))
            self.defined_since_call = set()
            self.pending_stack = {}
            return
        if self.convention == 'x86' and signature is not None and signature[3] <= 4:
            call.size = 4
            self.emit(Assign(Var('eax', 4), call, address))
            self.emit(Clobber(clobbered + ['flags'], address))
            self.defined_since_call = set()
            self.pending_stack = {}
            return
        if self.convention == 'x86':
            # 64-bit results come back in edx:eax; dead parts are removed by the data-flow pass.
            # 'callret' marks an unknown callee: its value does not make this function return one.
            call.size = 8
            if signature is not None:
                self.emit(Assign(Var('callval', 8), call, address))
                self.emit(Assign(Var('eax', 4), Cast('trunc', Var('callval', 8), 4), address))
                self.emit(Assign(Var('edx', 4), Cast('trunc', Bin('>>u', Var('callval', 8), Const(32, 8), 8), 4),
                                 address))
                self.emit(Clobber([r for r in clobbered if r != 'edx'] + ['flags'], address))
                self.defined_since_call = set()
                self.pending_stack = {}
                return
            self.emit(Assign(Var('callret', 8), call, address))
            first = len(self.out) - 1
            self.emit(Assign(Var('eax', 4), Cast('trunc', Var('callret', 8), 4), address))
            self.emit(Assign(Var('edx', 4), Cast('trunc', Bin('>>u', Var('callret', 8), Const(32, 8), 8), 4), address))
            clobbered = [r for r in clobbered if r != 'edx']
            self.emit(Clobber(clobbered + ['flags'], address))
            if signature is None:
                self.float_call = (first, len(self.out) - 1, call)
            self.defined_since_call = set()
            self.pending_stack = {}
            return
        self.emit(Assign(Var(self.fam.ax, self.word), call, address))
        self.emit(Clobber(clobbered + ['flags'], address))
        if signature is None:
            self.float_call = (len(self.out) - 2, len(self.out) - 1, call)
        self.defined_since_call = set()
        self.pending_stack = {}

    def take_float_call(self):
        """The last call (unknown callee) is read as returning a double: rewrite its result."""
        first, clobber, call = self.float_call
        self.float_call = None
        call.float = call.size = 8
        address = self.out[first].address
        if self.convention == 'x86':
            self.out[first] = Assign(Var('fst1', 8), call, address)
            self.state['fpu'] = 1
        else:
            self.out[first] = Assign(Var('xmm0', 16), Intrinsic('_mm_set_sd', [call], 16), address)
            names = [n for n in self.out[clobber].names if n != 'xmm0'] + [self.fam.ax]
            self.out[clobber] = Clobber(names, address)

    def zero_idiom(self):
        insn = self.current
        if insn is None or len(insn.operands) < 2 or not insn.mnemonic.lstrip('v').startswith(('xor', 'pxor', 'sub')):
            return False
        return insn.op_str.split(',')[0].strip() == insn.op_str.split(',')[-1].strip()

    def make_ret(self, address):
        """Return statement; the floating-point candidate is st0 (x86) or xmm0."""
        if self.convention == 'x86':
            depth = self.state.get('fpu', 0)
            fvalue = Var('fst%d' % depth, 8) if depth >= 1 else None
        else:
            fvalue = Var('xmm0', 16)
        return Ret(self.return_value(), address, fvalue)

    def return_value(self):
        if self.convention == 'x86':
            return Bin('|', Cast('zext', Var('eax', 4), 8),
                       Bin('<<', Cast('zext', Var('edx', 4), 8), Const(32, 8), 8), 8)
        return Var(self.fam.ax, self.word)

    def thiscall_candidate(self):
        return 'ecx' in self.defined_since_call and self.image.bits == 32

    # ------------------------------------------------------------------ instructions

    def lift_block(self, instructions, state, table=None):
        self.state = dict(state)
        self.out = []
        self.defined_since_call = set()
        self.pending_stack = {}
        self.pushed_args = 0
        self.switch_index = None
        self.float_call = None
        self.current = None
        for position, insn in enumerate(instructions):
            self.current = insn
            following = instructions[position + 1] if position + 1 < len(instructions) else None
            if table is not None and insn.address == table.get('load_address') and table.get('index'):
                value = self.read_reg(table['index'])
                self.switch_index = Var('switch_index', value.size)
                self.emit(Assign(self.switch_index, value, insn.address))
            try:
                self.lift(insn, following, table)
            except CyToolError:
                raise
            except Exception as exc:  # keep going on a single instruction we could not model
                self.out.append(Comment('unsupported: %s %s (%s)' % (insn.mnemonic, insn.op_str, exc), insn.address))
                self.unsupported.append(insn.address)
                reads, writes = insn.regs_access()
                written = [insn.reg_name(r) for r in writes]
                names = {self.reg(name)[0] for name in written if name not in FLAG_REGISTERS}
                flags = ['flags'] if any(name in FLAG_REGISTERS for name in written) else []
                self.out.append(Clobber(sorted(names) + flags, insn.address))
            for name in self.written_registers(insn):
                self.defined_since_call.add(name)
        return self.out, self.state

    def written_registers(self, insn):
        try:
            reads, writes = insn.regs_access()
        except Exception:
            return []
        names = []
        for r in writes:
            name = insn.reg_name(r)
            if name.startswith(('xmm', 'ymm')):
                names.append('xmm' + name[3:])
            elif name in self.fam.map:
                names.append(self.reg(name)[0])
        return names

    def lift(self, insn, following, table):
        from capstone import x86
        m = insn.mnemonic
        if m.startswith('lock '):
            m = m[5:]       # atomicity is not expressed in C; the operation itself is
        a = insn.address
        ops = insn.operands
        size = ops[0].size if ops else self.word
        W = self.word
        if m in ('nop', 'endbr64', 'endbr32', 'pause', 'prefetchnta', 'prefetcht0', 'lfence', 'mfence', 'sfence',
                 'int3') or m.startswith(('nop', 'prefetch')):
            return
        if (m.startswith('f') or m in ('wait', 'sahf') or m == 'test' and insn.op_str.startswith('ah,')) and \
                self.x87(insn, m, a):
            return
        if m == 'mov' or m == 'movabs':
            value = self.operand_value(insn, 1, size)
            self.write_operand(insn, 0, value, a)
            if ops[0].type == x86.X86_OP_REG and insn.reg_name(ops[0].reg) in (self.fam.bp, 'rbp', 'ebp') and \
                    ops[1].type == x86.X86_OP_REG and self.reg(insn.reg_name(ops[1].reg))[0] == self.fam.sp:
                self.state['fp'] = self.state['sp']
            return
        if m in ('movzx', 'movsx', 'movsxd'):
            value = self.operand_value(insn, 1)
            kind = 'zext' if m == 'movzx' else 'sext'
            self.write_operand(insn, 0, Cast(kind, value, size), a)
            return
        if m == 'lea':
            addr, offset = self.memory_expr(insn, ops[1])
            dest = insn.reg_name(ops[0].reg)
            family = self.reg(dest)[0]
            if family == self.fam.sp and offset is not None:
                self.state['sp'] = offset
                return
            if family == self.fam.bp and offset is not None:
                self.state['fp'] = offset
                return
            if offset is not None:
                addr = self.stack_address(offset)
            if isinstance(addr, Sym) and addr.kind == 'iat':
                addr = Sym(addr.name, addr.address, W, 'data')
            self.write_reg(dest, addr if ops[0].size == W else Cast('trunc', addr, ops[0].size), a)
            return
        if m == 'push':
            value = self.operand_value(insn, 0, W)
            self.state['sp'] -= W
            name = self.stack_var_name(self.state['sp'])
            self.stack_vars[name] = W
            statement = Assign(Var(name, W), value, a)
            self.emit(statement)
            self.pending_stack[self.state['sp']] = statement
            return
        if m == 'pop':
            name = self.stack_var_name(self.state['sp'])
            self.stack_vars[name] = W
            value = Var(name, W)
            self.state['sp'] += W
            dest = insn.reg_name(ops[0].reg) if ops[0].type == x86.X86_OP_REG else None
            if dest and self.reg(dest)[0] == self.fam.bp:
                self.state['fp'] = None
            if dest:
                self.write_reg(dest, value, a)
            else:
                self.write_operand(insn, 0, value, a)
            return
        if m == 'leave':
            if self.state['fp'] is not None:
                self.state['sp'] = self.state['fp']
            self.state['fp'] = None
            self.state['sp'] += W
            return
        if m in ('add', 'sub', 'and', 'or', 'xor', 'adc', 'sbb'):
            dest = ops[0]
            if dest.type == x86.X86_OP_REG and self.reg(insn.reg_name(dest.reg))[0] == self.fam.sp:
                if ops[1].type == x86.X86_OP_IMM:
                    delta = ops[1].imm
                    if m == 'add':
                        self.state['sp'] += delta
                    elif m == 'sub':
                        self.state['sp'] -= delta
                        self.frame = max(getattr(self, 'frame', 0), -self.state['sp'])
                    elif m == 'and':
                        self.state['aligned'] = True
                return
            left = self.operand_value(insn, 0)
            right = self.operand_value(insn, 1, size)
            if m == 'xor' and ops[1].type == ops[0].type == x86.X86_OP_REG and ops[0].reg == ops[1].reg:
                self.write_operand(insn, 0, Const(0, size), a)
                self.set_flags('res', Const(0, size), Const(0, size), size, a)
                return
            if m in ('adc', 'sbb'):
                carry = Cast('zext', Cond('b', Var('flags', 1)), size)
                if m == 'sbb' and ops[0].type == ops[1].type == x86.X86_OP_REG and ops[0].reg == ops[1].reg:
                    self.write_operand(insn, 0, Un('neg', carry, size), a)
                    return
                op = '+' if m == 'adc' else '-'
                result = Bin(op, Bin(op, left, right, size), carry, size)
                self.write_operand(insn, 0, result, a)
                self.emit(Clobber(['flags'], a))
                return
            op = {'add': '+', 'sub': '-', 'and': '&', 'or': '|', 'xor': '^'}[m]
            result = Bin(op, left, right, size)
            if m == 'sub':
                self.set_flags('cmp', left, right, size, a)
            elif m == 'add':
                self.set_flags('add', left, right, size, a)
            self.write_operand(insn, 0, result, a)
            if m not in ('sub', 'add'):
                self.set_flags('res', self.operand_value(insn, 0), Const(0, size), size, a)
            return
        if m in ('cmp', 'test'):
            left = self.operand_value(insn, 0)
            right = self.operand_value(insn, 1, size)
            self.set_flags(m, left, right, size, a)
            return
        if m in ('inc', 'dec', 'neg', 'not'):
            value = self.operand_value(insn, 0)
            if m in ('inc', 'dec'):
                result = Bin('+' if m == 'inc' else '-', value, Const(1, size), size)
            else:
                result = Un(m, value, size)
            self.write_operand(insn, 0, result, a)
            if m != 'not':
                self.set_flags('res', self.operand_value(insn, 0), Const(0, size), size, a)
            return
        if m in ('shl', 'sal', 'shr', 'sar', 'rol', 'ror'):
            value = self.operand_value(insn, 0)
            count = self.operand_value(insn, 1, 1) if len(ops) > 1 else Const(1, 1)
            count = Cast('zext', count, size) if count.size != size else count
            if m in ('rol', 'ror'):
                result = Intrinsic('_rotl' if m == 'rol' else '_rotr', [value, count], size)
            else:
                result = Bin({'shl': '<<', 'sal': '<<', 'shr': '>>u', 'sar': '>>s'}[m], value, count, size)
            self.write_operand(insn, 0, result, a)
            self.set_flags('res', self.operand_value(insn, 0), Const(0, size), size, a)
            return
        if m in ('shld', 'shrd'):
            dst = self.operand_value(insn, 0)
            src = self.operand_value(insn, 1)
            count = self.operand_value(insn, 2, 1) if len(ops) > 2 else Cast('trunc', self.read_reg('cl'), 1)
            if size == 8:
                # MSVC x64 intrinsics with exactly the instruction's semantics.
                if m == 'shrd':
                    result = Intrinsic('__shiftright128', [dst, src, Cast('zext', count, 1)], 8)
                else:
                    result = Intrinsic('__shiftleft128', [src, dst, Cast('zext', count, 1)], 8)
            else:
                wide = size * 2
                shift = Bin('&', Cast('zext', count, wide), Const(8 * size - 1, wide), wide)
                if m == 'shrd':
                    pair = Bin('|', Bin('<<', Cast('zext', src, wide), Const(8 * size, wide), wide), Cast('zext', dst, wide), wide)
                    result = Cast('trunc', Bin('>>u', pair, shift, wide), size)
                else:
                    pair = Bin('|', Bin('<<', Cast('zext', dst, wide), Const(8 * size, wide), wide), Cast('zext', src, wide), wide)
                    result = Cast('trunc', Bin('>>u', Bin('<<', pair, shift, wide), Const(8 * size, wide), wide), size)
            self.write_operand(insn, 0, result, a)
            self.emit(Clobber(['flags'], a))
            return
        if m == 'imul':
            if len(ops) == 3:
                result = Bin('*', self.operand_value(insn, 1), self.operand_value(insn, 2, size), size)
                self.write_operand(insn, 0, result, a)
            elif len(ops) == 2:
                result = Bin('*', self.operand_value(insn, 0), self.operand_value(insn, 1, size), size)
                self.write_operand(insn, 0, result, a)
            else:
                self.mul_wide(insn, signed=True)
            self.emit(Clobber(['flags'], a))
            return
        if m == 'mul':
            self.mul_wide(insn, signed=False)
            self.emit(Clobber(['flags'], a))
            return
        if m in ('div', 'idiv'):
            divisor = self.operand_value(insn, 0)
            ax = self.read_reg({1: 'al', 2: 'ax', 4: 'eax', 8: 'rax'}[size])
            dx = self.read_reg({1: 'ah', 2: 'dx', 4: 'edx', 8: 'rdx'}[size])
            suffix = 's' if m == 'idiv' else 'u'
            # The dividend is dx:ax; compilers set dx to the sign/zero extension of ax (cdq/xor edx,edx).
            dividend = ax
            self.emit(Assign(Var('divtmp', size), dividend, a))
            self.emit(Comment('dividend high part: %r' % (dx,), a)) if False else None
            self.write_reg({1: 'al', 2: 'ax', 4: 'eax', 8: 'rax'}[size], Bin('/' + suffix, Var('divtmp', size), divisor, size), a)
            self.write_reg({1: 'ah', 2: 'dx', 4: 'edx', 8: 'rdx'}[size], Bin('%' + suffix, Var('divtmp', size), divisor, size), a)
            self.emit(Clobber(['flags'], a))
            return
        if m in ('cdq', 'cqo', 'cwd'):
            src = {'cdq': 'eax', 'cqo': 'rax', 'cwd': 'ax'}[m]
            dst = {'cdq': 'edx', 'cqo': 'rdx', 'cwd': 'dx'}[m]
            s = {'cdq': 4, 'cqo': 8, 'cwd': 2}[m]
            self.write_reg(dst, Bin('>>s', self.read_reg(src), Const(8 * s - 1, s), s), a)
            return
        if m in ('cdqe', 'cwde', 'cbw'):
            src, dst, s = {'cdqe': ('eax', 'rax', 8), 'cwde': ('ax', 'eax', 4), 'cbw': ('al', 'ax', 2)}[m]
            self.write_reg(dst, Cast('sext', self.read_reg(src), s), a)
            return
        if m == 'xchg':
            left = self.operand_value(insn, 0)
            right = self.operand_value(insn, 1)
            self.emit(Assign(Var('xchgtmp', size), left, a))
            self.write_operand(insn, 0, right, a)
            self.write_operand(insn, 1, Var('xchgtmp', size), a)
            return
        if m.startswith('set'):
            cond = Cond(m[3:], Var('flags', 1))
            self.write_operand(insn, 0, Cast('zext', cond, 1), a)
            return
        if m.startswith('cmov'):
            cond = Cond(m[4:], Var('flags', 1))
            value = Tern(cond, self.operand_value(insn, 1), self.operand_value(insn, 0), size)
            self.write_operand(insn, 0, value, a)
            return
        if m == 'bt':
            self.set_flags('bt', self.operand_value(insn, 0), self.operand_value(insn, 1, size), size, a)
            return
        if m in ('bts', 'btr', 'btc'):
            value = self.operand_value(insn, 0)
            bit = Bin('<<', Const(1, size), Bin('&', self.operand_value(insn, 1, size), Const(8 * size - 1, size), size),
                      size)
            self.emit(Assign(Var('bttmp', size), value, a))
            self.set_flags('bt', Var('bttmp', size), self.operand_value(insn, 1, size), size, a)
            if m == 'bts':
                result = Bin('|', Var('bttmp', size), bit, size)
            elif m == 'btr':
                result = Bin('&', Var('bttmp', size), Un('not', bit, size), size)
            else:
                result = Bin('^', Var('bttmp', size), bit, size)
            self.write_operand(insn, 0, result, a)
            return
        if m == 'xadd':
            self.emit(Assign(Var('xaddtmp', size), self.operand_value(insn, 0), a))
            source = self.operand_value(insn, 1)
            self.set_flags('add', Var('xaddtmp', size), source, size, a)
            self.write_operand(insn, 0, Bin('+', Var('xaddtmp', size), source, size), a)
            self.write_operand(insn, 1, Var('xaddtmp', size), a)
            return
        if m == 'cmpxchg':
            accumulator = {1: 'al', 2: 'ax', 4: 'eax', 8: 'rax'}[size]
            self.emit(Assign(Var('cmpxtmp', size), self.operand_value(insn, 0), a))
            self.set_flags('cmp', self.read_reg(accumulator), Var('cmpxtmp', size), size, a)
            self.write_operand(insn, 0, Tern(Cond('e', Var('flags', 1)), self.operand_value(insn, 1),
                                             Var('cmpxtmp', size), size), a)
            self.write_reg(accumulator, Var('cmpxtmp', size), a)
            return
        if m in ('bsf', 'bsr', 'tzcnt', 'lzcnt', 'popcnt', 'bswap'):
            source = self.operand_value(insn, 1 if len(ops) > 1 else 0)
            name = {'bsf': '__bsf', 'bsr': '__bsr', 'tzcnt': '__tzcnt', 'lzcnt': '__lzcnt', 'popcnt': '__popcnt',
                    'bswap': '__bswap'}[m]
            self.write_operand(insn, 0, Intrinsic(name, [source], size), a)
            self.emit(Clobber(['flags'], a))
            return
        if m == 'call':
            self.call(insn, a)
            self.state['sp'] += 0  # the return address push/pop cancels out
            if following is not None and following.mnemonic == 'add' and following.op_str.startswith(('esp', 'rsp')):
                pass  # cdecl: the caller's add esp, N follows and is tracked normally
            elif self.convention == 'x86' and self.pushed_args:
                self.state['sp'] += 4 * self.pushed_args  # stdcall: the callee popped its arguments
            return
        if m in ('ret', 'retn'):
            self.emit(self.make_ret(a))
            return
        if m == 'jmp':
            target = imm_target(insn)
            if target is not None:
                if target in self.image.function_starts and target != self.function_start:
                    # Tail call.
                    self.call(insn, a)
                    self.emit(self.make_ret(a))
                    return
                self.emit(Jump(target, a))
                return
            if table is not None:
                index = self.switch_index if self.switch_index is not None else                     (self.read_reg(table['index']) if table.get('index') else Const(0, 4))
                cases = {}
                for value, case_target in enumerate(table['targets']):
                    cases.setdefault(case_target, []).append(value)
                self.emit(Switch(index, cases, None, a))
                return
            operand = ops[0]
            target_expr = self.operand_value(insn, 0)
            if isinstance(target_expr, Sym) and target_expr.kind == 'import':
                self.call(insn, a)
                self.emit(self.make_ret(a))
                return
            self.emit(IndirectJump(target_expr, a))
            return
        if m in CC:
            target = imm_target(insn)
            self.emit(Branch(Cond(CC[m], Var('flags', 1)), target, a + insn.size, a))
            return
        if m in ('jecxz', 'jrcxz', 'jcxz'):
            target = imm_target(insn)
            register = {'jecxz': 'ecx', 'jrcxz': 'rcx', 'jcxz': 'cx'}[m]
            from .ir import Cmp
            self.emit(Branch(Cmp('==', self.read_reg(register), Const(0, 4), 4), target, a + insn.size, a))
            return
        if m.startswith(('rep', 'movs', 'stos', 'lods', 'scas', 'cmps')) and self.string_op(insn, a):
            return
        if self.sse(insn, a):
            return
        raise ValueError('no model')

    # ------------------------------------------------------------------ x87

    def st(self, index):
        """st(index) as a variable named by absolute stack slot (fst1 = first pushed value)."""
        depth = self.state.get('fpu', 0)
        if depth == 0 and index == 0 and self.float_call is not None:
            self.take_float_call()
            depth = 1
        return Var('fst%d' % (depth - index), 8)

    def fpush(self, value, address):
        depth = self.state.get('fpu', 0) + 1
        self.state['fpu'] = depth
        self.float_call = None
        self.emit(Assign(Var('fst%d' % depth, 8), value, address))

    def fpop(self, count=1):
        self.state['fpu'] = self.state.get('fpu', 0) - count

    def fset(self, index, value, address):
        depth = self.state.get('fpu', 0)
        self.emit(Assign(Var('fst%d' % (depth - index), 8), value, address))

    def fmem(self, insn, operand, integer=False):
        """A memory operand as a double (float/double/extended, or a signed integer for fi*)."""
        size = operand.size or 8
        if integer:
            return Cast('i2f', self.load(insn, operand), 8)
        if size == 10:
            from capstone import x86
            addr, _ = self.memory_expr(insn, operand)
            return Load(addr, 8, True)      # 80-bit extended: read as a double (approximation)
        value = self.load(insn, operand, True)
        return value if size == 8 else Cast('f2f', value, 8)

    def st_index(self, insn, operand):
        name = insn.reg_name(operand.reg)       # 'st(3)'
        return int(name[3:-1]) if name.startswith('st(') else 0

    def x87(self, insn, m, a):
        from capstone import x86
        ops = insn.operands
        is_mem = bool(ops) and ops[-1].type == x86.X86_OP_MEM
        if m in ('wait', 'fwait', 'fnclex', 'fclex', 'fninit', 'finit', 'fldcw', 'ffree', 'fnop', 'fincstp',
                 'fdecstp', 'femms'):
            return True
        if m in ('fnstcw', 'fstcw'):
            self.store(insn, ops[0], Const(0x27f, 2), a)
            return True
        if m in ('fld', 'fild'):
            if is_mem:
                self.fpush(self.fmem(insn, ops[0], m == 'fild'), a)
            else:
                self.fpush(self.st(self.st_index(insn, ops[0])), a)
            return True
        constants = {'fldz': 0.0, 'fld1': 1.0, 'fldpi': 3.141592653589793, 'fldl2e': 1.4426950408889634,
                     'fldln2': 0.6931471805599453, 'fldlg2': 0.3010299956639812, 'fldl2t': 3.321928094887362}
        if m in constants:
            self.fpush(FConst(constants[m], 8), a)
            return True
        if m in ('fst', 'fstp'):
            value = self.st(0)
            if is_mem:
                size = ops[0].size or 8
                self.store(insn, ops[0], value if size >= 8 else Cast('f2f', value, size), a, is_float=True)
            else:
                self.fset(self.st_index(insn, ops[0]), value, a)
            if m == 'fstp':
                self.fpop()
            return True
        if m in ('fist', 'fistp', 'fisttp'):
            self.store(insn, ops[0], Cast('f2i', self.st(0), ops[0].size or 4), a)
            if m != 'fist':
                self.fpop()
            return True
        arithmetic = {'fadd': '+f', 'fsub': '-f', 'fsubr': '-f', 'fmul': '*f', 'fdiv': '/f', 'fdivr': '/f'}
        base = m[:-1] if m.endswith('p') and m[:-1] in arithmetic else m
        integer = base.startswith('fi') and ('f' + base[2:]) in arithmetic
        if integer:
            base = 'f' + base[2:]
        if base in arithmetic:
            op = arithmetic[base]
            reverse = base.endswith('r')
            pop = m.endswith('p') and not integer
            if is_mem:
                dst, left, right = 0, self.st(0), self.fmem(insn, ops[0], integer)
            elif len(ops) == 2:
                i, j = self.st_index(insn, ops[0]), self.st_index(insn, ops[1])
                dst, left, right = i, self.st(i), self.st(j)
            elif len(ops) == 1:
                i = self.st_index(insn, ops[0])
                dst, left, right = (i, self.st(i), self.st(0)) if pop else (0, self.st(0), self.st(i))
            else:
                dst, left, right = 1, self.st(1), self.st(0)
            if reverse:
                left, right = right, left
            self.fset(dst, Bin(op, left, right, 8), a)
            if pop:
                self.fpop()
            return True
        if m == 'fchs':
            self.fset(0, Bin('-f', FConst(-0.0, 8), self.st(0), 8), a)
            return True
        functions = {'fabs': 'fabs', 'fsqrt': 'sqrt', 'fsin': 'sin', 'fcos': 'cos', 'frndint': 'nearbyint'}
        if m in functions:
            self.fset(0, Intrinsic(functions[m], [self.st(0)], 8), a)
            return True
        if m == 'fxch':
            i = self.st_index(insn, ops[0]) if ops else 1
            self.emit(Assign(Var('fxtmp', 8), self.st(0), a))
            self.fset(0, self.st(i), a)
            self.fset(i, Var('fxtmp', 8), a)
            return True
        if m in ('fcomi', 'fcomip', 'fucomi', 'fucomip'):
            i = self.st_index(insn, ops[-1]) if ops else 1
            self.set_flags('fcmp', self.st(0), self.st(i), 8, a)
            if m.endswith('p'):
                self.fpop()
            return True
        if m in ('fcom', 'fcomp', 'fcompp', 'fucom', 'fucomp', 'fucompp', 'ficom', 'ficomp', 'ftst'):
            if m == 'ftst':
                right = FConst(0.0, 8)
            elif is_mem:
                right = self.fmem(insn, ops[0], m.startswith('fi'))
            else:
                right = self.st(self.st_index(insn, ops[0]) if ops else 1)
            self.emit(Assign(Var('fcmpa', 8), self.st(0), a))
            self.emit(Assign(Var('fcmpb', 8), right, a))
            self.state['fpsw'] = True
            self.fpop(2 if m.endswith('pp') else 1 if m.endswith('p') else 0)
            return True
        if m in ('fnstsw', 'fstsw'):
            if ops and ops[0].type == x86.X86_OP_REG and self.state.get('fpsw'):
                self.emit(Clobber([self.fam.ax], a))
                return True
            return False
        if m == 'sahf' and self.state.get('fpsw'):
            self.set_flags('fcmp', Var('fcmpa', 8), Var('fcmpb', 8), 8, a)
            return True
        if m == 'test' and self.state.get('fpsw') and len(ops) == 2 and ops[1].type == x86.X86_OP_IMM:
            # Condition bits after fcom: C0 (0x01) = less or unordered, C2 (0x04) = unordered,
            # C3 (0x40) = equal or unordered. ZF: none of the tested bits; PF: even number of them.
            from .ir import Cmp, Logic
            fa, fb = Var('fcmpa', 8), Var('fcmpb', 8)
            unordered = Logic('||', Cmp('!=f', fa, fa, 8), Cmp('!=f', fb, fb, 8))
            bits = {0x01: Logic('||', Cmp('<f', fa, fb, 8), unordered), 0x04: unordered,
                    0x40: Logic('||', Cmp('==f', fa, fb, 8), unordered)}
            chosen = [bits[b] for b in (0x01, 0x04, 0x40) if ops[1].imm & b]
            if not chosen:
                return False
            any_set = chosen[0]
            for bit in chosen[1:]:
                any_set = Logic('||', any_set, bit)
            odd = chosen[0]
            for bit in chosen[1:]:
                odd = Logic('||', Logic('&&', odd, negate(bit)), Logic('&&', negate(odd), bit))
            self.emit(Assign(Var('flags', 1), Flags('fbits', negate(any_set), negate(odd), 1), a))
            return True
        return False

    def mul_wide(self, insn, signed):
        size = insn.operands[0].size
        a = insn.address
        ax_name = {1: 'al', 2: 'ax', 4: 'eax', 8: 'rax'}[size]
        dx_name = {1: 'ah', 2: 'dx', 4: 'edx', 8: 'rdx'}[size]
        left = self.read_reg(ax_name)
        right = self.operand_value(insn, 0)
        if size == 8:
            self.emit(Assign(Var('mula', 8), left, a))
            self.emit(Assign(Var('mulb', 8), right, a))
            self.write_reg('rax', Bin('*', Var('mula', 8), Var('mulb', 8), 8), a)
            self.write_reg('rdx', Intrinsic('__mulh' if signed else '__umulh', [Var('mula', 8), Var('mulb', 8)], 8), a)
            return
        wide = size * 2
        kind = 'sext' if signed else 'zext'
        product = Bin('*', Cast(kind, left, wide), Cast(kind, right, wide), wide)
        self.emit(Assign(Var('multmp', wide), product, a))
        self.write_reg(ax_name, Cast('trunc', Var('multmp', wide), size), a)
        self.write_reg(dx_name, Cast('trunc', Bin('>>u', Var('multmp', wide), Const(8 * size, wide), wide), size), a)

    def string_op(self, insn, a):
        m = insn.mnemonic
        prefix = ''
        if ' ' in m:
            prefix, m = m.split(' ', 1)
        width = {'b': 1, 'w': 2, 'd': 4, 'q': 8}.get(m[-1], 1)
        W = self.word
        di, si, cx = self.read_reg(self.fam.di), self.read_reg(self.fam.si), self.read_reg(self.fam.cx)
        if m.startswith('stos') and prefix in ('rep',):
            value = self.read_reg({1: 'al', 2: 'ax', 4: 'eax', 8: 'rax'}[width])
            fn = 'memset' if width == 1 else 'memset%d' % (8 * width)
            self.emit(ExprStmt(Intrinsic(fn, [di, value, cx], W), a))
            self.emit(Clobber([self.fam.di, self.fam.cx], a))
            return True
        if m.startswith('movs') and prefix in ('rep',):
            count = cx if width == 1 else Bin('*', cx, Const(width, W), W)
            self.emit(ExprStmt(Intrinsic('memcpy', [di, si, count], W), a))
            self.emit(Clobber([self.fam.di, self.fam.si, self.fam.cx], a))
            return True
        if m.startswith('stos') and not prefix:
            value = self.read_reg({1: 'al', 2: 'ax', 4: 'eax', 8: 'rax'}[width])
            self.emit(Store(di, value, width, False, a))
            self.write_reg(self.fam.di, Bin('+', di, Const(width, W), W), a)
            return True
        if m.startswith('movs') and not prefix and len(insn.operands) < 2 or m.startswith('movs') and not prefix and \
                insn.operands and insn.operands[0].type == 3 and insn.operands[1].type == 3:
            self.emit(Store(di, Load(si, width), width, False, a))
            self.write_reg(self.fam.di, Bin('+', di, Const(width, W), W), a)
            self.write_reg(self.fam.si, Bin('+', si, Const(width, W), W), a)
            return True
        return False

    def sse(self, insn, a):
        from capstone import x86
        m = insn.mnemonic
        ops = insn.operands
        if m.startswith('v') and m[1:] in SSE_SCALAR:
            m = m[1:]
            if len(ops) == 3:  # AVX three-operand form: dst = src1 op src2
                kind, op = SSE_SCALAR[m]
                size = 4 if kind == 'ss' else 8
                self.write_operand(insn, 0, Bin(op, self.fvalue(insn, 1, size), self.fvalue(insn, 2, size), size), a)
                return True
        if m in ('movss', 'movsd', 'vmovss', 'vmovsd') and len(ops) == 2:
            size = 4 if m.endswith('ss') else 8
            value = self.fvalue(insn, 1, size)
            self.write_operand(insn, 0, value, a, is_float=True)
            return True
        if m in VECTOR_MOVES and len(ops) == 2:
            flavour = VECTOR_MOVES[m]
            if ops[0].type == x86.X86_OP_REG and ops[1].type == x86.X86_OP_REG:
                self.write_operand(insn, 0, self.read_reg(insn.reg_name(ops[1].reg)), a)
                return True
            if (ops[1].size or 16) != 16 or (ops[0].size or 16) != 16:
                return False
            if ops[1].type == x86.X86_OP_MEM:
                addr, offset = self.memory_expr(insn, ops[1])
                if offset is not None:
                    self.memory_slots.add(offset)
                constant = self.rodata_value(addr, 16, vector=flavour)
                self.write_operand(insn, 0, constant if constant is not None else
                                   Intrinsic('_mm_loadu_%s' % flavour, [addr], 16), a)
                return True
            value = self.read_reg(insn.reg_name(ops[1].reg))
            addr, offset = self.memory_expr(insn, ops[0])
            if offset is not None:
                self.memory_slots.add(offset)
            self.emit(ExprStmt(Intrinsic('_mm_storeu_%s' % flavour, [addr, value], 16), a))
            return True
        if m in SSE_SCALAR:
            kind, op = SSE_SCALAR[m]
            size = 4 if kind == 'ss' else 8
            left = self.fvalue(insn, 0, size)
            right = self.fvalue(insn, 1, size)
            if op in ('min', 'max'):
                # Exact SSE semantics: the second operand when unordered or equal.
                from .ir import Cmp
                result = Tern(Cmp('<f' if op == 'min' else '>f', left, right, size), left, right, size)
            elif op == 'sqrt':
                result = Intrinsic('sqrtf' if size == 4 else 'sqrt', [right], size)
            else:
                result = Bin(op, left, right, size)
            self.write_operand(insn, 0, result, a, is_float=True)
            return True
        if m in ('xorps', 'xorpd', 'pxor', 'vxorps', 'vxorpd', 'vpxor') and \
                all(o.type == x86.X86_OP_REG for o in ops) and ops[-1].reg == ops[-2].reg:
            self.write_operand(insn, 0, FConst(0.0, 8), a)
            return True
        if m in ('cvtsi2sd', 'cvtsi2ss', 'vcvtsi2sd', 'vcvtsi2ss'):
            size = 8 if m.endswith('sd') else 4
            source = self.operand_value(insn, len(ops) - 1)
            self.write_operand(insn, 0, Cast('i2f', source, size), a)
            return True
        if m in ('cvttsd2si', 'cvttss2si', 'cvtsd2si', 'cvtss2si', 'vcvttsd2si', 'vcvttss2si'):
            source = self.fvalue(insn, 1, 8 if 'sd' in m else 4)
            self.write_operand(insn, 0, Cast('f2i', source, ops[0].size), a)
            return True
        if m in ('cvtss2sd', 'cvtsd2ss', 'vcvtss2sd', 'vcvtsd2ss'):
            size = 8 if m.endswith('sd') else 4
            source = self.fvalue(insn, len(ops) - 1, 4 if size == 8 else 8)
            self.write_operand(insn, 0, Cast('f2f', source, size), a)
            return True
        if m in ('comiss', 'comisd', 'ucomiss', 'ucomisd', 'vcomiss', 'vcomisd', 'vucomiss', 'vucomisd'):
            size = 4 if m.endswith('ss') else 8
            self.set_flags('fcmp', self.fvalue(insn, 0, size), self.fvalue(insn, 1, size), size, a)
            return True
        if m in ('movd', 'movq', 'vmovd', 'vmovq'):
            def is_xmm(index):
                return ops[index].type == x86.X86_OP_REG and insn.reg_name(ops[index].reg).startswith('xmm')
            if is_xmm(0) and is_xmm(1):
                self.write_operand(insn, 0, Intrinsic('_mm_move_epi64', [self.read_reg(insn.reg_name(ops[1].reg))], 16), a)
            elif is_xmm(0):
                wide = (ops[1].size or 4) == 8
                if ops[1].type == x86.X86_OP_MEM and wide:
                    addr, _ = self.memory_expr(insn, ops[1])
                    self.write_operand(insn, 0, Intrinsic('_mm_loadl_epi64', [addr], 16), a)
                else:
                    source = self.operand_value(insn, 1)
                    self.write_operand(insn, 0, Intrinsic('_mm_cvtsi64_si128' if wide else '_mm_cvtsi32_si128', [source], 16), a)
            else:
                wide = (ops[0].size or 4) == 8
                vector = self.read_reg(insn.reg_name(ops[1].reg))
                if ops[0].type == x86.X86_OP_MEM and wide:
                    addr, _ = self.memory_expr(insn, ops[0])
                    self.emit(ExprStmt(Intrinsic('_mm_storel_epi64', [addr, vector], 16), a))
                else:
                    value = Intrinsic('_mm_cvtsi128_si64' if wide else '_mm_cvtsi128_si32', [vector], 8 if wide else 4)
                    self.write_operand(insn, 0, value, a)
            return True
        if self.packed(insn, a):
            return True
        return False

    def packed(self, insn, a):
        """Packed SSE/AVX instructions as exact _mm_* intrinsics."""
        from capstone import x86
        m = insn.mnemonic
        ops = insn.operands
        avx = m.startswith('v') and m[1:] in PACKED and len(ops) == len(PACKED[m[1:]][1]) + 1
        name = m[1:] if avx else m
        if name not in PACKED:
            return False
        intrinsic, shape = PACKED[name]
        values = []
        sources = list(range(1, len(ops))) if avx else ([0] + list(range(1, len(ops))))
        if not avx and shape in ('v', 'vi'):
            sources = list(range(1, len(ops)))  # result depends only on the source (pshufd, cvtdq2ps...)
        elif not avx and shape == 'si':
            sources = [0, 1]  # shift the destination in place by an immediate
        for index in sources:
            operand = ops[index]
            if operand.type == x86.X86_OP_IMM:
                values.append(Const(operand.imm, 4))
            elif operand.type == x86.X86_OP_REG:
                values.append(self.read_reg(insn.reg_name(operand.reg)))
            else:
                addr, offset = self.memory_expr(insn, operand)
                if offset is not None:
                    self.memory_slots.add(offset)
                flavour = 'ps' if intrinsic.endswith('_ps') else 'pd' if intrinsic.endswith('_pd') else 'si128'
                constant = self.rodata_value(addr, 16, vector=flavour)
                values.append(constant if constant is not None else Intrinsic('_mm_loadu_%s' % flavour, [addr], 16))
        scalar = intrinsic in SCALAR_RESULT
        result = Intrinsic(intrinsic, values, SCALAR_RESULT.get(intrinsic, 16))
        self.write_operand(insn, 0, result, a)
        return True

    def fvalue(self, insn, index, size):
        from capstone import x86
        operand = insn.operands[index]
        if operand.type == x86.X86_OP_REG:
            return self.read_reg(insn.reg_name(operand.reg))
        if operand.type == x86.X86_OP_MEM:
            addr, offset = self.memory_expr(insn, operand)
            constant = self.rodata_value(addr, size, is_float=True)
            if constant is not None:
                return constant
            # Scalar SSE operands may be described as xmmword: only `size` bytes are read.
            return self.load(insn, operand, is_float=True, size=size)
        return self.operand_value(insn, index, size)


def read_c_string(native, address, limit=256):
    """A printable NUL-terminated ASCII string at address (at least 2 characters), else None."""
    raw = native.read(address, limit)
    end = raw.find(b'\0')
    if end < 2:
        return None
    text = raw[:end]
    if all(32 <= c < 127 or c in (9, 10, 13) for c in text):
        return text.decode('ascii')
    return None


SSE_SCALAR = {'addss': ('ss', '+f'), 'addsd': ('sd', '+f'), 'subss': ('ss', '-f'), 'subsd': ('sd', '-f'),
              'mulss': ('ss', '*f'), 'mulsd': ('sd', '*f'), 'divss': ('ss', '/f'), 'divsd': ('sd', '/f'),
              'minss': ('ss', 'min'), 'minsd': ('sd', 'min'), 'maxss': ('ss', 'max'), 'maxsd': ('sd', 'max'),
              'sqrtss': ('ss', 'sqrt'), 'sqrtsd': ('sd', 'sqrt')}


VECTOR_MOVES = {'movdqu': 'si128', 'movdqa': 'si128', 'lddqu': 'si128', 'vmovdqu': 'si128', 'vmovdqa': 'si128',
                'movups': 'ps', 'movaps': 'ps', 'vmovups': 'ps', 'vmovaps': 'ps',
                'movupd': 'pd', 'movapd': 'pd', 'vmovupd': 'pd', 'vmovapd': 'pd'}

# mnemonic -> (intrinsic, argument shape). Shapes: vv (dst op src), vvi (+imm), v (from src),
# vi (from src + imm), si (shift dst by imm). AVX three-operand forms use src1, src2.
PACKED = {}
for _suffix, _bits in (('b', 8), ('w', 16), ('d', 32), ('q', 64)):
    PACKED['padd' + _suffix] = ('_mm_add_epi%d' % _bits, 'vv')
    PACKED['psub' + _suffix] = ('_mm_sub_epi%d' % _bits, 'vv')
for _suffix, _bits in (('b', 8), ('w', 16), ('d', 32)):
    PACKED['pcmpeq' + _suffix] = ('_mm_cmpeq_epi%d' % _bits, 'vv')
    PACKED['pcmpgt' + _suffix] = ('_mm_cmpgt_epi%d' % _bits, 'vv')
for _mnemonic, _intrinsic in (('punpcklbw', 'unpacklo_epi8'), ('punpcklwd', 'unpacklo_epi16'),
                              ('punpckldq', 'unpacklo_epi32'), ('punpcklqdq', 'unpacklo_epi64'),
                              ('punpckhbw', 'unpackhi_epi8'), ('punpckhwd', 'unpackhi_epi16'),
                              ('punpckhdq', 'unpackhi_epi32'), ('punpckhqdq', 'unpackhi_epi64'),
                              ('pand', 'and_si128'), ('pandn', 'andnot_si128'), ('por', 'or_si128'),
                              ('pxor', 'xor_si128'), ('pmullw', 'mullo_epi16'), ('pmulld', 'mullo_epi32'),
                              ('pmuludq', 'mul_epu32'), ('pmulhw', 'mulhi_epi16'), ('pmaddwd', 'madd_epi16'),
                              ('pmaxsd', 'max_epi32'), ('pminsd', 'min_epi32'), ('pmaxud', 'max_epu32'),
                              ('pminud', 'min_epu32'), ('pmaxsw', 'max_epi16'), ('pminsw', 'min_epi16'),
                              ('pmaxub', 'max_epu8'), ('pminub', 'min_epu8'), ('pavgb', 'avg_epu8'),
                              ('packssdw', 'packs_epi32'), ('packsswb', 'packs_epi16'), ('packuswb', 'packus_epi16'),
                              ('packusdw', 'packus_epi32'), ('psadbw', 'sad_epu8'),
                              ('addps', 'add_ps'), ('subps', 'sub_ps'), ('mulps', 'mul_ps'), ('divps', 'div_ps'),
                              ('addpd', 'add_pd'), ('subpd', 'sub_pd'), ('mulpd', 'mul_pd'), ('divpd', 'div_pd'),
                              ('andps', 'and_ps'), ('orps', 'or_ps'), ('xorps', 'xor_ps'), ('andnps', 'andnot_ps'),
                              ('andpd', 'and_pd'), ('orpd', 'or_pd'), ('xorpd', 'xor_pd'), ('andnpd', 'andnot_pd'),
                              ('maxps', 'max_ps'), ('minps', 'min_ps'), ('maxpd', 'max_pd'), ('minpd', 'min_pd'),
                              ('unpcklps', 'unpacklo_ps'), ('unpckhps', 'unpackhi_ps'), ('unpcklpd', 'unpacklo_pd'),
                              ('unpckhpd', 'unpackhi_pd'), ('movlhps', 'movelh_ps'), ('movhlps', 'movehl_ps'),
                              ('haddps', 'hadd_ps'), ('haddpd', 'hadd_pd'), ('cmpeqps', 'cmpeq_ps'),
                              ('cmpltps', 'cmplt_ps'), ('cmpleps', 'cmple_ps')):
    PACKED[_mnemonic] = ('_mm_' + _intrinsic, 'vv')
for _mnemonic, _intrinsic in (('shufps', 'shuffle_ps'), ('shufpd', 'shuffle_pd'), ('palignr', 'alignr_epi8'),
                              ('pblendw', 'blend_epi16'), ('blendps', 'blend_ps'), ('blendpd', 'blend_pd')):
    PACKED[_mnemonic] = ('_mm_' + _intrinsic, 'vvi')
for _mnemonic, _intrinsic in (('cvtdq2ps', 'cvtepi32_ps'), ('cvttps2dq', 'cvttps_epi32'), ('cvtps2dq', 'cvtps_epi32'),
                              ('cvtdq2pd', 'cvtepi32_pd'), ('cvttpd2dq', 'cvttpd_epi32'), ('cvtps2pd', 'cvtps_pd'),
                              ('cvtpd2ps', 'cvtpd_ps'), ('sqrtps', 'sqrt_ps'), ('sqrtpd', 'sqrt_pd'),
                              ('rcpps', 'rcp_ps'), ('rsqrtps', 'rsqrt_ps'), ('pabsd', 'abs_epi32'),
                              ('pmovsxdq', 'cvtepi32_epi64'), ('pmovzxdq', 'cvtepu32_epi64'),
                              ('pmovsxwd', 'cvtepi16_epi32'), ('pmovzxwd', 'cvtepu16_epi32'),
                              ('pmovsxbd', 'cvtepi8_epi32'), ('pmovzxbd', 'cvtepu8_epi32'),
                              ('pmovmskb', 'movemask_epi8'), ('movmskps', 'movemask_ps'), ('movmskpd', 'movemask_pd')):
    PACKED[_mnemonic] = ('_mm_' + _intrinsic, 'v')
for _mnemonic, _intrinsic in (('pshufd', 'shuffle_epi32'), ('pshuflw', 'shufflelo_epi16'),
                              ('pshufhw', 'shufflehi_epi16'), ('pextrd', 'extract_epi32'), ('pextrq', 'extract_epi64'),
                              ('pextrw', 'extract_epi16'), ('pextrb', 'extract_epi8'), ('extractps', 'extract_ps')):
    PACKED[_mnemonic] = ('_mm_' + _intrinsic, 'vi')
for _mnemonic, _intrinsic in (('pinsrd', 'insert_epi32'), ('pinsrq', 'insert_epi64'), ('pinsrw', 'insert_epi16'),
                              ('pinsrb', 'insert_epi8')):
    PACKED[_mnemonic] = ('_mm_' + _intrinsic, 'vvi')
for _mnemonic, _intrinsic in (('psrldq', 'srli_si128'), ('pslldq', 'slli_si128'), ('psrld', 'srli_epi32'),
                              ('pslld', 'slli_epi32'), ('psrad', 'srai_epi32'), ('psrlq', 'srli_epi64'),
                              ('psllq', 'slli_epi64'), ('psrlw', 'srli_epi16'), ('psllw', 'slli_epi16'),
                              ('psraw', 'srai_epi16')):
    PACKED[_mnemonic] = ('_mm_' + _intrinsic, 'si')
SCALAR_RESULT = {'_mm_movemask_epi8': 4, '_mm_movemask_ps': 4, '_mm_movemask_pd': 4, '_mm_extract_epi32': 4,
                 '_mm_extract_epi64': 8, '_mm_extract_epi16': 4, '_mm_extract_epi8': 4, '_mm_extract_ps': 4,
                 '_mm_cvtsi128_si32': 4, '_mm_cvtsi128_si64': 8}


def address_taken(instructions, word, fam):
    """Stack offsets (relative to entry) whose address escapes: lea reg, [rsp/rbp + X]."""
    return set()


def lift_function(image, start, convention):
    """Decode and lift a function; returns LiftedFunction with IR blocks keyed by address."""
    if convention == 'aapcs64':
        from .lifter_arm64 import Arm64Lifter
        lifter = Arm64Lifter(image)
        lifter.function_start = start
        instructions, leaders, tables = lifter.decode(start)
    else:
        lifter = Lifter(image, convention)
        lifter.function_start = start
        instructions, leaders, tables = decode_function(image, start, lifter.md)
    if not instructions:
        raise CyToolError('EngineFailed', 'No instructions decoded at 0x%x.' % start)
    addresses = sorted(instructions)
    blocks = {}
    current = None
    for address in addresses:
        if address in leaders or current is None or address != blocks[current][-1].address + blocks[current][-1].size:
            current = address
            blocks[current] = []
        blocks[current].append(instructions[address])
    # Pass 1: find stack slots whose address escapes (lea of a stack address used as a pointer).
    lifter.memory_slots = set()
    lifter.stack_vars = {}
    lifter.calls = []
    lifter.unsupported = []
    states = {start: {'sp': 0, 'fp': None, 'aligned': False}}
    order = [start] + [b for b in sorted(blocks) if b != start]
    lifted = {}
    succ = {}
    lifter.regions = {}
    for attempt in range(4):
        lifter.compute_regions()
        slots_before = set(lifter.memory_slots)
        states = {start: {'sp': 0, 'fp': None, 'aligned': False}}
        lifted = {}
        worklist = [start]
        visited = set()
        while worklist:
            block = worklist.pop(0)
            if block in visited or block not in blocks:
                continue
            visited.add(block)
            state = states.get(block, {'sp': 0, 'fp': None, 'aligned': False})
            last = blocks[block][-1]
            statements, end_state = lifter.lift_block(blocks[block], state, tables.get(last.address))
            terminator = statements[-1] if statements else None
            from .ir import TERMINATORS
            if not isinstance(terminator, TERMINATORS):
                following = last.address + last.size
                if following in blocks:
                    statements.append(Jump(following, last.address))
                else:
                    statements.append(lifter.make_ret(last.address))
            terminator = statements[-1]
            targets = []
            if isinstance(terminator, Jump):
                targets = [terminator.target]
            elif isinstance(terminator, Branch):
                targets = [terminator.true, terminator.false]
            elif isinstance(terminator, Switch):
                targets = list(terminator.cases)
            succ[block] = [t for t in targets if t in blocks]
            lifted[block] = statements
            for target in succ[block]:
                if target not in states:
                    states[target] = dict(end_state)
                worklist.append(target)
        if attempt < 3:
            # Addresses taken inside a known buffer do not split it.
            escaped = {o for o in escaping_slots(lifted)
                       if (o < 0 or lifter.home_slot(o)) and lifter.region_of(o) is None}
            if not escaped - slots_before and lifter.memory_slots == slots_before:
                break
            lifter.memory_slots |= escaped
            lifter.stack_vars = {}
            lifter.calls = []
    function = LiftedFunction(start)
    function.blocks = lifted
    function.order = [b for b in sorted(lifted)]
    if start in function.order:
        function.order.remove(start)
        function.order.insert(0, start)
    function.succ = succ
    function.instructions = instructions
    function.stack_vars = lifter.stack_vars
    function.memory_slots = lifter.memory_slots
    function.regions = dict(lifter.regions)
    function.calls = lifter.calls
    function.unsupported = lifter.unsupported
    function.convention = convention
    function.word = lifter.word
    function.ret_reg = lifter.fam.ax
    function.args = lifter.cc['args']
    function.fargs = lifter.cc['fargs']
    return function


def escaping_slots(blocks):
    """Stack variables whose address (Addr('stack...')) appears in an expression."""
    found = set()
    for statements in blocks.values():
        for statement in statements:
            for expr in statement.exprs():
                for node in expr.walk():
                    if isinstance(node, Addr) and node.name.startswith('stack'):
                        found.add(int(node.name[5:]))
    return found
