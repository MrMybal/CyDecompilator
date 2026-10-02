"""AArch64 (ARM64) to IR, for the same data-flow / structuring / C back end as x86.

Conventions: AAPCS64 (Linux, Android, macOS) and Windows ARM64 share the register usage that
matters here: integer arguments x0-x7, floating-point / SIMD arguments v0-v7, results in x0 / v0.
Registers are tracked by family (w5 -> x5, s3/d3/q3 -> v3); 32-bit writes zero-extend.

Flags (NZCV) are lazy like on x86: subs/adds/ands/fcmp/ccmp assign a Flags source and the
conditions (Cond 'a.<cc>') are resolved per flag kind by ir.resolve_cond.

NEON operations are expressed with SSE intrinsics (and a few cy_* helpers from the C header)
so the C output compiles and runs on x64 as well.
"""
import re
import struct

from cytools_core import CyToolError

from .ir import (Addr, Assign, Bin, Branch, Call, Cast, Clobber, Cmp, Comment, Cond, Const, ExprStmt, FConst,
                 Flags, IndirectJump, Intrinsic, Jump, Load, Logic, Ret, Store, Switch, Sym, Tern, Un, Var, mask)
from .lifter import CONVENTIONS, MAX_INSTRUCTIONS, NORETURN, Lifter, callee_signature, read_c_string

CC_NAMES = {1: 'eq', 2: 'ne', 3: 'hs', 4: 'lo', 5: 'mi', 6: 'pl', 7: 'vs', 8: 'vc', 9: 'hi', 10: 'ls',
            11: 'ge', 12: 'lt', 13: 'gt', 14: 'le', 15: 'al', 16: 'nv'}
CC_BY_TEXT = {v: k for k, v in CC_NAMES.items()}
CC_BY_TEXT.update({'cs': 3, 'cc': 4})
INVERT_CC = {'eq': 'ne', 'ne': 'eq', 'hs': 'lo', 'lo': 'hs', 'mi': 'pl', 'pl': 'mi', 'vs': 'vc', 'vc': 'vs',
             'hi': 'ls', 'ls': 'hi', 'ge': 'lt', 'lt': 'ge', 'gt': 'le', 'le': 'gt'}

SFT_LSL, SFT_MSL, SFT_LSR, SFT_ASR, SFT_ROR = 1, 2, 3, 4, 5
EXT = {1: ('zext', 1), 2: ('zext', 2), 3: ('zext', 4), 4: ('zext', 8),
       5: ('sext', 1), 6: ('sext', 2), 7: ('sext', 4), 8: ('sext', 8)}

# NEON element arrangement -> (lane bits, SSE integer suffix, float flavour)
ARRANGEMENTS = {'16b': (8, 'epi8', None), '8b': (8, 'epi8', None), '8h': (16, 'epi16', None),
                '4h': (16, 'epi16', None), '4s': (32, 'epi32', 'ps'), '2s': (32, 'epi32', 'ps'),
                '2d': (64, 'epi64', 'pd'), '1d': (64, 'epi64', 'pd')}

FP_SIZE = {'s': 4, 'd': 8, 'h': 2, 'q': 16, 'b': 1}


class Arm64Family:
    sp = 'sp'
    bp = 'x29'
    ax = 'x0'
    map = {}


def family(name):
    """(family, size, kind) of a register name: kind 'x' (general), 'v' (fp/simd), 'sp', 'zr'."""
    if name in ('sp', 'wsp'):
        return 'sp', 8 if name == 'sp' else 4, 'sp'
    if name in ('xzr', 'wzr'):
        return 'zr', 8 if name == 'xzr' else 4, 'zr'
    if name == 'lr':
        return 'x30', 8, 'x'
    if name == 'fp':
        return 'x29', 8, 'x'
    if name.startswith(('ip0', 'ip1')):
        return 'x%d' % (16 + int(name[2])), 8, 'x'
    if name[0] in 'xw' and name[1:].isdigit():
        return 'x' + name[1:], 8 if name[0] == 'x' else 4, 'x'
    if name[0] in 'bhsdqv' and name[1:].isdigit():
        return 'v' + name[1:], 16 if name[0] in 'qv' else FP_SIZE[name[0]], 'v'
    return name, 8, 'x'


def is_vreg(name):
    return len(name) > 1 and name[0] == 'v' and name[1:].isdigit()


# ---------------------------------------------------------------------- decoding / CFG

def branch_target(insn):
    from capstone import arm64
    for operand in reversed(insn.operands):
        if operand.type == arm64.ARM64_OP_IMM:
            return operand.imm
    return None


def decode_function(image, start, md):
    instructions = {}
    leaders = {start}
    pending = [start]
    tables = {}
    while pending and len(instructions) < MAX_INSTRUCTIONS:
        address = pending.pop()
        if address in instructions or not image.executable(address):
            continue
        while address not in instructions and image.executable(address):
            insn = next(md.disasm(image.read(address, 4), address), None)
            if insn is None:
                break
            instructions[address] = insn
            m = insn.mnemonic
            following = address + 4
            if m in ('ret', 'retaa', 'retab', 'brk', 'udf', 'hlt', 'eret'):
                break
            if m == 'b':
                target = branch_target(insn)
                if target is not None and not (target in image.function_starts and target != start):
                    leaders.add(target)
                    pending.append(target)
                break
            if m.startswith('b.') or m in ('cbz', 'cbnz', 'tbz', 'tbnz'):
                target = branch_target(insn)
                if target is not None:
                    leaders.add(target)
                    pending.append(target)
                leaders.add(following)
                address = following
                continue
            if m in ('br', 'braa', 'brab', 'braaz', 'brabz'):
                table = resolve_jump_table(image, instructions, insn)
                if table:
                    tables[address] = table
                    for case_target in set(table['targets']):
                        leaders.add(case_target)
                        pending.append(case_target)
                break
            if m == 'bl':
                target = branch_target(insn)
                name = image.names.get(target, '') if target is not None else ''
                if name.split('!')[-1].split('::')[-1].lstrip('_') in {n.lstrip('_') for n in NORETURN}:
                    break
            address = following
    return instructions, leaders, tables


def resolve_jump_table(image, instructions, br):
    """Tables of clang / GCC / MSVC: br xT with xT = base + (entry << k), entry loaded from
    table[index], or an absolute address loaded from table[index]."""
    from capstone import arm64
    previous = [instructions[a] for a in sorted(a for a in instructions if br.address - 64 <= a < br.address)]
    values = {}

    def reg(insn, operand):
        return family(insn.reg_name(operand.reg))[0]
    for insn in previous:
        ops = insn.operands
        m = insn.mnemonic
        dst = reg(insn, ops[0]) if ops and ops[0].type == arm64.ARM64_OP_REG else None
        value = None
        try:
            if m in ('adrp', 'adr') and ops[1].type == arm64.ARM64_OP_IMM:
                value = ('c', ops[1].imm)
            elif m == 'add' and len(ops) == 3:
                left = values.get(reg(insn, ops[1]))
                if ops[2].type == arm64.ARM64_OP_IMM and left and left[0] == 'c':
                    value = ('c', left[1] + (ops[2].imm << (ops[2].shift.value if ops[2].shift.type else 0)))
                elif ops[2].type == arm64.ARM64_OP_REG:
                    right = values.get(reg(insn, ops[2]))
                    shift = ops[2].shift.value if ops[2].shift.type == SFT_LSL else 0
                    if left and right and left[0] == 'c' and right[0] == 'ld':
                        value = ('sum', left[1], right, shift)
                    elif left and right and right[0] == 'c' and left[0] == 'ld' and not shift:
                        value = ('sum', right[1], left, 0)
            elif m in ('ldr', 'ldrsw', 'ldrh', 'ldrsh', 'ldrb', 'ldrsb') and ops[1].type == arm64.ARM64_OP_MEM \
                    and ops[1].mem.index:
                base = values.get(family(insn.reg_name(ops[1].mem.base))[0])
                if base and base[0] == 'c':
                    width = {'ldrsw': 4, 'ldrh': 2, 'ldrsh': 2, 'ldrb': 1, 'ldrsb': 1}.get(m)
                    if width is None:
                        width = 8 if insn.reg_name(ops[0].reg).startswith('x') else 4
                    value = ('ld', base[1] + ops[1].mem.disp, width, m in ('ldrsw', 'ldrsh', 'ldrsb'),
                             insn.reg_name(ops[1].mem.index), insn.address)
            elif m == 'mov' and len(ops) == 2 and ops[1].type == arm64.ARM64_OP_REG:
                value = values.get(reg(insn, ops[1]))
        except (IndexError, AttributeError):
            value = None
        if dst is not None:
            if value is None:
                values.pop(dst, None)
            else:
                values[dst] = value
    target = values.get(reg(br, br.operands[0])) if br.operands else None
    if not target:
        return None
    if target[0] == 'sum':
        base, load, shift = target[1], target[2], target[3]
    elif target[0] == 'ld' and target[2] == 8:
        base, load, shift = None, target, 0
    else:
        return None
    _, table, width, signed_entries, index_name, load_address = load
    count = None
    for insn in reversed(previous):
        if insn.mnemonic in ('cmp', 'subs') and insn.operands[-1].type == arm64.ARM64_OP_IMM:
            count = insn.operands[-1].imm + 1
            break
    limit = count if count and 0 < count <= 4096 else 512
    targets = []
    for index in range(limit):
        raw = image.read(table + index * width, width)
        if len(raw) != width:
            break
        entry = int.from_bytes(raw, 'little', signed=signed_entries)
        address = (entry if base is None else base + (entry << shift)) & mask(8)
        if not image.executable(address):
            if count is None:
                break
            return None
        targets.append(address)
    if not targets:
        return None
    return {'targets': targets, 'index': index_name, 'count': len(targets), 'load_address': load_address}


# ---------------------------------------------------------------------- lifter

class Arm64Lifter(Lifter):
    def __init__(self, image, convention='aapcs64'):
        import capstone
        self.image = image
        self.fam = Arm64Family()
        self.cc = CONVENTIONS['aapcs64']
        self.convention = 'aapcs64'
        self.md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        self.md.detail = True
        self.word = 8
        self.float_call = None
        self.current = None

    def decode(self, start):
        return decode_function(self.image, start, self.md)

    # ------------------------------------------------------------------ registers

    def reg(self, name):
        fam, size, _ = family(name)
        return fam, size, 0

    def read_reg(self, name):
        fam, size, kind = family(name)
        if kind == 'zr':
            return Const(0, size)
        if kind == 'sp':
            value = self.sp_expr()
            return value if size == 8 else Cast('trunc', value, 4)
        if kind == 'v':
            if fam == 'v0' and self.float_call is not None:
                self.take_float_call()
            return Var(fam, 16)
        if fam == 'x29' and self.state.get('fp') is not None:
            return self.stack_address(self.state['fp'])
        held = self.state.get('stackregs', {}).get(fam)
        if held is not None and size == 8:
            return self.stack_address(held)
        var = Var(fam, 8)
        return var if size == 8 else Cast('trunc', var, 4)

    def write_reg(self, name, value, address):
        fam, size, kind = family(name)
        if kind == 'zr':
            return
        if kind == 'sp':
            offset = self.stack_offset(value)
            if offset is not None:
                self.state['sp'] = offset
            return
        if kind == 'v':
            if fam == 'v0':
                self.float_call = None
            self.emit(Assign(Var(fam, 16), value, address))
            return
        consts = self.state.get('consts', {})
        if fam in consts:
            consts = dict(consts)
            consts.pop(fam)
            self.state['consts'] = consts
        if fam == 'x29':
            self.state['fp'] = self.stack_offset(value) if size == 8 else None
            if self.state['fp'] is not None:
                return
        held = dict(self.state.get('stackregs', {}))
        held.pop(fam, None)
        stack = self.stack_offset(value) if size == 8 else None
        if stack is not None:
            held[fam] = stack
        self.state['stackregs'] = held
        self.emit(Assign(Var(fam, 8), value if size == 8 else Cast('zext', value, 8), address))

    def set_const(self, name, value):
        """A register known to hold an address (adrp / adr / add #imm): memory operands based on
        it resolve to the global they point at."""
        consts = dict(self.state.get('consts', {}))
        consts[family(name)[0]] = value & mask(8)
        self.state['consts'] = consts

    def const_of(self, name):
        return self.state.get('consts', {}).get(family(name)[0])

    def written_registers(self, insn):
        try:
            _, writes = insn.regs_access()
        except Exception:
            return []
        return [family(insn.reg_name(r))[0] for r in writes]

    def stack_var_name(self, offset):
        if offset < 0:
            return 'local_%x' % -offset
        return 'param_%d' % (offset // 8 + len(self.cc['args']) + 1)

    # ------------------------------------------------------------------ operands

    def rsize(self, insn, index):
        return family(insn.reg_name(insn.operands[index].reg))[1]

    def value(self, insn, index, size=None):
        """Source operand with its shift / extension applied."""
        from capstone import arm64
        operand = insn.operands[index]
        if operand.type == arm64.ARM64_OP_REG:
            name = insn.reg_name(operand.reg)
            value = self.read_reg(name)
            width = family(name)[1]
            if family(name)[2] == 'v':
                return value
            if operand.ext:
                kind, bits = EXT[operand.ext]
                target = size or width
                inner = value if bits >= value.size else Cast('trunc', value, bits)
                value = Cast(kind, inner, target) if bits < target else inner
                width = target
            if operand.shift.type and operand.shift.value:
                op = {SFT_LSL: '<<', SFT_LSR: '>>u', SFT_ASR: '>>s'}.get(operand.shift.type)
                amount = Const(operand.shift.value, width)
                if op:
                    value = Bin(op, value, amount, width)
                elif operand.shift.type == SFT_ROR:
                    value = rotate_right(value, operand.shift.value, width)
            if size and size != value.size:
                value = Cast('zext', value, size) if size > value.size else Cast('trunc', value, size)
            return value
        if operand.type == arm64.ARM64_OP_IMM:
            imm = operand.imm
            if operand.shift.type == SFT_LSL and operand.shift.value:
                imm <<= operand.shift.value
            return Const(imm, size or 8)
        if operand.type == arm64.ARM64_OP_FP:
            return FConst(operand.fp, size or 8)
        raise CyToolError('Unsupported', 'operand type %d' % operand.type)

    def address_of(self, insn, operand):
        """(address expression, stack offset or None) of a memory operand (no writeback)."""
        from .ir import simplify
        mem = operand.mem
        known = self.const_of(insn.reg_name(mem.base))
        if known is not None and not mem.index:
            return self.global_address((known + mem.disp) & mask(8), 8), None
        # A table base (adrp + add) indexed by a register: the global itself, so the module
        # defines the table instead of using an absolute address.
        expr = self.global_address(known, 8) if known is not None else self.read_reg(insn.reg_name(mem.base))
        if mem.index:
            index = self.read_reg(insn.reg_name(mem.index))
            if operand.ext:
                kind, bits = EXT[operand.ext]
                inner = index if bits >= index.size else Cast('trunc', index, bits)
                index = Cast(kind, inner, 8) if bits < 8 else inner
            elif index.size < 8:
                index = Cast('zext', index, 8)
            if operand.shift.type == SFT_LSL and operand.shift.value:
                index = Bin('<<', index, Const(operand.shift.value, 8), 8)
            expr = Bin('+', expr, index, 8)
        if mem.disp:
            expr = Bin('+', expr, Const(mem.disp, 8), 8)
        expr = simplify(expr)
        if isinstance(expr, Const):
            return self.global_address(expr.value, 8), None
        if isinstance(expr, Bin) and expr.op == '+' and isinstance(expr.b, Const) and isinstance(expr.a, Const):
            return self.global_address((expr.a.value + expr.b.value) & mask(8), 8), None
        return expr, self.stack_offset(expr)

    def mem_load(self, addr, offset, size, is_float=False):
        if isinstance(addr, Sym) and addr.kind == 'iat':
            return Sym(addr.name[1:], addr.address, size, 'import')
        if size == 16:
            if offset is not None:
                self.memory_slots.add(offset)
                addr = self.stack_address(offset)
            constant = self.rodata_value(addr, 16, vector='epi32')
            return constant if constant is not None else Intrinsic('_mm_loadu_si128', [addr], 16)
        if offset is not None and self.region_of(offset) is None:
            name = self.stack_var_name(offset)
            self.stack_vars[name] = max(self.stack_vars.get(name, 0), size)
            var = Var(name, self.stack_vars[name])
            return var if size == var.size else Cast('trunc', var, size)
        if offset is not None:
            addr = self.stack_address(offset)
        constant = self.rodata_value(addr, size, is_float)
        if constant is not None:
            return constant
        return Load(addr, size, is_float)

    def mem_store(self, addr, offset, value, size, address, is_float=False):
        if size == 16:
            if offset is not None:
                self.memory_slots.add(offset)
                addr = self.stack_address(offset)
            self.emit(ExprStmt(Intrinsic('_mm_storeu_si128', [addr, value], 16), address))
            return
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

    # ------------------------------------------------------------------ calls

    def call(self, insn, address, target=None, callee=None):
        if callee is None:
            if insn.mnemonic.startswith('blr'):
                callee = self.read_reg(insn.reg_name(insn.operands[0].reg))
                if isinstance(callee, Const) and self.image.executable(callee.value):
                    target = callee.value
                    callee = None
            else:
                target = branch_target(insn)
            if callee is None:
                callee = self.code_symbol(target)
                if callee.kind == 'code':
                    target = callee.address
        signature = callee_signature(self.image, target, self.convention) \
            if target is not None and self.image.executable(target) else None
        args = []
        defined = self.defined_since_call
        if signature is not None and len(signature) > 6:
            hints = signature[6]
            ints = sum(1 for h in hints if not h)
            floats = len(hints) - ints
            args = [Var('x%d' % i, 8) for i in range(min(ints, 8))] + [Var('v%d' % i, 16) for i in range(min(floats, 8))]
        else:
            count = 0
            for position in range(8):
                if 'x%d' % position in defined:
                    count = position + 1
            fcount = 0
            for position in range(8):
                if 'v%d' % position in defined:
                    fcount = position + 1
            args = [Var('x%d' % i, 8) for i in range(count)] + [Var('v%d' % i, 16) for i in range(fcount)]
        float_size = signature[4] if signature is not None and len(signature) > 4 else 0
        call = Call(callee, args, 8, returns=None if signature is None else signature[2], float_size=float_size)
        if signature is not None and len(signature) > 6:
            call.hints = signature[6]
        self.float_call = None
        self.calls.append(call)
        volatile = list(self.cc['volatile'])
        self.state['stackregs'] = {k: v for k, v in self.state.get('stackregs', {}).items() if k not in volatile}
        self.state['consts'] = {k: v for k, v in self.state.get('consts', {}).items() if k not in volatile}
        if float_size:
            call.size = float_size
            self.emit(Assign(Var('v0', 16), call, address))
            self.emit(Clobber([r for r in volatile if r != 'v0'] + ['flags'], address))
        elif signature is not None and not signature[2]:
            self.emit(ExprStmt(call, address))
            self.emit(Clobber(volatile + ['flags'], address))
        else:
            self.emit(Assign(Var('x0', 8), call, address))
            self.emit(Clobber([r for r in volatile if r != 'x0'] + ['flags'], address))
            if signature is None:
                self.float_call = (len(self.out) - 2, len(self.out) - 1, call)
        self.defined_since_call = set()
        self.pending_stack = {}

    def exported_by_name(self):
        cached = getattr(self.image, 'exports_by_name', None)
        if cached is None:
            cached = {name: address for address, name in self.image.native.exports.items()}
            self.image.exports_by_name = cached
        return cached

    def take_float_call(self):
        first, clobber, call = self.float_call
        self.float_call = None
        call.float = call.size = 8
        address = self.out[first].address
        self.out[first] = Assign(Var('v0', 16), call, address)
        self.out[clobber] = Clobber([n for n in self.out[clobber].names if n != 'v0'] + ['x0'], address)

    def code_symbol(self, target):
        imported = self.image.native.plt.get(target) if hasattr(self.image.native, 'plt') else None
        if imported:
            name = imported.split('!')[-1].split('@')[0]
            local = self.exported_by_name().get(name)
            if local is not None:
                # A PLT call to a function this library defines (default visibility).
                return Sym(self.image.names.get(local) or name, local, 8, 'code')
            return Sym(name, target, 8, 'import')
        return Sym(self.image.names.get(target) or 'FUN_%x' % target, target, 8, 'code')

    def make_ret(self, address):
        return Ret(Var('x0', 8), address, Var('v0', 16))

    def return_value(self):
        return Var('x0', 8)

    # ------------------------------------------------------------------ instructions

    def cond(self, code):
        return Cond('a.' + CC_NAMES.get(code, 'al'), Var('flags', 1))

    def cond_text(self, text):
        return Cond('a.' + text, Var('flags', 1))

    def lift(self, insn, following, table):
        from capstone import arm64
        m = insn.mnemonic
        a = insn.address
        ops = insn.operands
        REG, IMM, MEM = arm64.ARM64_OP_REG, arm64.ARM64_OP_IMM, arm64.ARM64_OP_MEM
        if m in ('nop', 'hint', 'bti', 'paciasp', 'autiasp', 'pacibsp', 'autibsp', 'dmb', 'dsb', 'isb', 'prfm',
                 'prfum', 'yield', 'xpaclri', 'clrex', 'csdb', 'sb') or m.startswith(('pac', 'aut')):
            return
        if '.' in insn.op_str and not m.startswith(('b.', 'ld', 'st')) and self.neon(insn, m, a):
            return
        # ---- moves and constants
        if m in ('mov', 'movz') and len(ops) == 2:
            dst = insn.reg_name(ops[0].reg)
            if family(dst)[2] == 'v':
                self.fp_move(insn, a)
                return
            size = self.rsize(insn, 0)
            self.write_reg(dst, self.value(insn, 1, size), a)
            return
        if m == 'movn':
            size = self.rsize(insn, 0)
            self.write_reg(insn.reg_name(ops[0].reg), Const(~self.value(insn, 1, size).value, size), a)
            return
        if m == 'movk':
            size = self.rsize(insn, 0)
            shift = ops[1].shift.value if ops[1].shift.type else 0
            old = self.read_reg(insn.reg_name(ops[0].reg))
            keep = mask(size) ^ (0xffff << shift)
            self.write_reg(insn.reg_name(ops[0].reg),
                           Bin('|', Bin('&', old, Const(keep, size), size), Const(ops[1].imm << shift, size), size), a)
            return
        if m in ('adr', 'adrp'):
            self.write_reg(insn.reg_name(ops[0].reg), self.global_address(ops[1].imm, 8), a)
            self.set_const(insn.reg_name(ops[0].reg), ops[1].imm)
            return
        if m in ('add', 'sub') and len(ops) == 3 and ops[2].type == IMM and \
                self.const_of(insn.reg_name(ops[1].reg)) is not None and self.rsize(insn, 0) == 8:
            delta = ops[2].imm << (ops[2].shift.value if ops[2].shift.type == SFT_LSL else 0)
            value = self.const_of(insn.reg_name(ops[1].reg)) + (delta if m == 'add' else -delta)
            self.write_reg(insn.reg_name(ops[0].reg), self.global_address(value & mask(8), 8), a)
            self.set_const(insn.reg_name(ops[0].reg), value)
            return
        # ---- integer arithmetic
        binary = {'add': '+', 'sub': '-', 'and': '&', 'orr': '|', 'eor': '^', 'adds': '+', 'subs': '-',
                  'ands': '&', 'lsl': '<<', 'lsr': '>>u', 'asr': '>>s', 'mul': '*', 'sdiv': '/s', 'udiv': '/u',
                  'lslv': '<<', 'lsrv': '>>u', 'asrv': '>>s', 'bic': '&~', 'bics': '&~', 'orn': '|~', 'eon': '^~'}
        if m in binary and len(ops) == 3:
            size = self.rsize(insn, 0)
            left = self.value(insn, 1, size)
            right = self.value(insn, 2, size)
            op = binary[m]
            if op.endswith('~'):
                op, right = op[0], Un('not', right, size)
            if m in ('lsl', 'lsr', 'asr', 'lslv', 'lsrv', 'asrv') and not isinstance(right, Const):
                right = Bin('&', right, Const(8 * size - 1, size), size)
            if m == 'sdiv' or m == 'udiv':
                # Division by zero gives 0 on AArch64.
                result = Tern(Cmp('==', right, Const(0, size), size), Const(0, size), Bin(op, left, right, size), size)
            else:
                result = Bin(op, left, right, size)
            if m in ('adds', 'subs', 'ands', 'bics'):
                self.set_flags({'adds': 'add', 'subs': 'cmp', 'ands': 'test', 'bics': 'test'}[m], left, right, size, a)
            self.write_reg(insn.reg_name(ops[0].reg), result, a)
            return
        if m in ('cmp', 'cmn', 'tst'):
            size = self.rsize(insn, 0)
            self.set_flags({'cmp': 'cmp', 'cmn': 'add', 'tst': 'test'}[m], self.value(insn, 0, size),
                           self.value(insn, 1, size), size, a)
            return
        if m in ('ccmp', 'ccmn', 'fccmp', 'fccmpe'):
            size = self.rsize(insn, 0) if m.startswith('c') else FP_SIZE[insn.reg_name(ops[0].reg)[0]]
            self.emit(Assign(Var('ccond', 1), self.cond(insn.cc), a))
            if m.startswith('f'):
                inner = Flags('afcmp', self.fp(insn, 0, size), self.fp(insn, 1, size), size)
            else:
                inner = Flags('cmp' if m == 'ccmp' else 'add', self.value(insn, 0, size), self.value(insn, 1, size), size)
            nzcv = ops[2].imm if len(ops) > 2 else 0
            self.emit(Assign(Var('flags', 1), Flags('ccmp', Var('ccond', 1), inner, nzcv), a))
            return
        if m in ('neg', 'negs', 'mvn'):
            size = self.rsize(insn, 0)
            source = self.value(insn, 1, size)
            result = Un('neg' if m != 'mvn' else 'not', source, size)
            if m == 'negs':
                self.set_flags('cmp', Const(0, size), source, size, a)
            self.write_reg(insn.reg_name(ops[0].reg), result, a)
            return
        if m in ('adc', 'sbc', 'adcs', 'sbcs'):
            size = self.rsize(insn, 0)
            carry = Cast('zext', self.cond_text('hs'), size)
            left, right = self.value(insn, 1, size), self.value(insn, 2, size)
            if m.startswith('adc'):
                result = Bin('+', Bin('+', left, right, size), carry, size)
            else:
                result = Bin('-', Bin('-', left, right, size), Bin('^', carry, Const(1, size), size), size)
            self.write_reg(insn.reg_name(ops[0].reg), result, a)
            return
        if m == 'ror' and len(ops) == 3:
            size = self.rsize(insn, 0)
            if ops[2].type == IMM:
                result = rotate_right(self.value(insn, 1, size), ops[2].imm, size)
            else:
                result = Intrinsic('cy_ror%d' % (8 * size), [self.value(insn, 1, size), self.value(insn, 2, size)], size)
            self.write_reg(insn.reg_name(ops[0].reg), result, a)
            return
        if m in ('madd', 'msub', 'mneg', 'smaddl', 'umaddl', 'smsubl', 'umsubl', 'smull', 'umull', 'smnegl',
                 'umnegl'):
            size = self.rsize(insn, 0)
            left, right = self.value(insn, 1), self.value(insn, 2)
            if m.startswith(('sm', 'um')):
                kind = 'sext' if m[0] == 's' else 'zext'
                left, right = Cast(kind, left, 8), Cast(kind, right, 8)
            product = Bin('*', left, right, size)
            if m in ('madd', 'smaddl', 'umaddl'):
                result = Bin('+', self.value(insn, 3, size), product, size)
            elif m in ('msub', 'smsubl', 'umsubl'):
                result = Bin('-', self.value(insn, 3, size), product, size)
            elif m in ('mneg', 'smnegl', 'umnegl'):
                result = Un('neg', product, size)
            else:
                result = product
            self.write_reg(insn.reg_name(ops[0].reg), result, a)
            return
        if m in ('smulh', 'umulh'):
            self.write_reg(insn.reg_name(ops[0].reg), Intrinsic('__mulh' if m == 'smulh' else '__umulh',
                                                                [self.value(insn, 1), self.value(insn, 2)], 8), a)
            return
        if m in ('ubfx', 'sbfx', 'ubfiz', 'sbfiz', 'bfi', 'bfxil', 'bfm', 'ubfm', 'sbfm', 'bfc'):
            self.bitfield(insn, m, a)
            return
        if m in ('uxtb', 'uxth', 'sxtb', 'sxth', 'sxtw', 'uxtw'):
            size = self.rsize(insn, 0)
            bits = {'b': 1, 'h': 2, 'w': 4}[m[-1]]
            source = self.value(insn, 1)
            inner = source if source.size == bits else Cast('trunc', source, bits)
            self.write_reg(insn.reg_name(ops[0].reg), Cast('sext' if m[0] == 's' else 'zext', inner, size), a)
            return
        if m == 'extr':
            size = self.rsize(insn, 0)
            lsb = ops[3].imm
            high, low = self.value(insn, 1, size), self.value(insn, 2, size)
            result = Bin('|', Bin('>>u', low, Const(lsb, size), size),
                         Bin('<<', high, Const(8 * size - lsb, size), size), size) if lsb else low
            self.write_reg(insn.reg_name(ops[0].reg), result, a)
            return
        if m in ('clz', 'rbit', 'rev', 'rev32', 'rev16', 'cls', 'cnt', 'ctz', 'abs'):
            size = self.rsize(insn, 0)
            name = {'clz': 'cy_clz', 'rbit': 'cy_rbit', 'rev': 'cy_bswap', 'cls': 'cy_cls', 'ctz': 'cy_ctz',
                    'cnt': 'cy_popcount', 'rev32': 'cy_rev32_', 'rev16': 'cy_rev16_', 'abs': 'cy_abs'}[m]
            self.write_reg(insn.reg_name(ops[0].reg), Intrinsic('%s%d' % (name, 8 * size), [self.value(insn, 1, size)],
                                                                size), a)
            return
        # ---- conditional select
        if m in ('csel', 'csinc', 'csinv', 'csneg', 'cset', 'csetm', 'cinc', 'cinv', 'cneg', 'fcsel'):
            self.select(insn, m, a)
            return
        # ---- branches and calls
        if m == 'b':
            target = branch_target(insn)
            if target in self.image.function_starts and target != self.function_start:
                self.call(insn, a, target)
                self.emit(self.make_ret(a))
                return
            self.emit(Jump(target, a))
            return
        if m.startswith('b.'):
            self.emit(Branch(self.cond(insn.cc), branch_target(insn), a + 4, a))
            return
        if m in ('cbz', 'cbnz'):
            size = self.rsize(insn, 0)
            test = Cmp('==' if m == 'cbz' else '!=', self.value(insn, 0, size), Const(0, size), size)
            self.emit(Branch(test, branch_target(insn), a + 4, a))
            return
        if m in ('tbz', 'tbnz'):
            size = self.rsize(insn, 0)
            bit = Bin('&', self.value(insn, 0, size), Const(1 << ops[1].imm, size), size)
            test = Cmp('==' if m == 'tbz' else '!=', bit, Const(0, size), size)
            self.emit(Branch(test, branch_target(insn), a + 4, a))
            return
        if m in ('bl', 'blr', 'blraa', 'blrab', 'blraaz', 'blrabz'):
            self.call(insn, a)
            return
        if m in ('ret', 'retaa', 'retab'):
            self.emit(self.make_ret(a))
            return
        if m in ('br', 'braa', 'brab', 'braaz', 'brabz'):
            if table is not None:
                index = self.switch_index if self.switch_index is not None else self.read_reg(table['index'])
                cases = {}
                for value, case_target in enumerate(table['targets']):
                    cases.setdefault(case_target, []).append(value)
                self.emit(Switch(index, cases, None, a))
                return
            target_expr = self.read_reg(insn.reg_name(ops[0].reg))
            if isinstance(target_expr, Sym) and target_expr.kind in ('import', 'code'):
                self.call(insn, a, getattr(target_expr, 'address', None), target_expr)
                self.emit(self.make_ret(a))
                return
            self.emit(IndirectJump(target_expr, a))
            return
        if m in ('brk', 'udf', 'hlt'):
            self.emit(ExprStmt(Intrinsic('__debugbreak', [], 4), a))
            self.emit(self.make_ret(a))
            return
        if m == 'dc' and insn.op_str.startswith('zva'):
            # Zero a cache block (64 bytes on every current core).
            self.emit(ExprStmt(Intrinsic('memset', [self.read_reg(insn.reg_name(ops[-1].reg)), Const(0, 4),
                                                    Const(64, 8)], 8), a))
            return
        if m in ('dc', 'ic', 'tlbi', 'sys', 'msr', 'mrs') and m != 'mrs':
            return
        if m == 'mrs':
            self.write_reg(insn.reg_name(ops[0].reg), Intrinsic('cy_system_register', [], 8), a)
            return
        if m in ('svc', 'hvc', 'smc'):
            self.emit(Assign(Var('x0', 8), Intrinsic('cy_syscall', [Var('x8', 8), Var('x0', 8), Var('x1', 8),
                                                                     Var('x2', 8)], 8), a))
            return
        # ---- memory
        if m in ('ld1', 'st1', 'ld2', 'st2', 'ld3', 'st3', 'ld4', 'st4', 'ld1r') and self.vector_memory(insn, m, a):
            return
        if m.startswith(('ldr', 'ldur', 'str', 'stur', 'ldp', 'stp', 'ldnp', 'stnp', 'ldar', 'stlr', 'ldxr',
                         'ldaxr', 'stxr', 'stlxr', 'ldapr', 'ldxp', 'ldaxp', 'stxp', 'stlxp')):
            self.memory(insn, m, a)
            return
        # ---- floating point
        if self.floating(insn, m, a):
            return
        raise ValueError('no model')

    # ------------------------------------------------------------------ helpers

    def bitfield(self, insn, m, a):
        ops = insn.operands
        size = self.rsize(insn, 0)
        bits = 8 * size
        dst = insn.reg_name(ops[0].reg)
        if m == 'bfc':
            lsb, width = ops[1].imm, ops[2].imm
            old = self.read_reg(dst)
            self.write_reg(dst, Bin('&', old, Const(mask(size) ^ (((1 << width) - 1) << lsb), size), size), a)
            return
        source = self.value(insn, 1, size)
        lsb, width = ops[2].imm, ops[3].imm
        field = (1 << width) - 1
        if m == 'ubfx':
            result = Bin('&', Bin('>>u', source, Const(lsb, size), size), Const(field, size), size)
        elif m == 'sbfx':
            result = Bin('>>s', Bin('<<', source, Const(bits - lsb - width, size), size), Const(bits - width, size), size)
        elif m == 'ubfiz':
            result = Bin('<<', Bin('&', source, Const(field, size), size), Const(lsb, size), size)
        elif m == 'sbfiz':
            result = Bin('<<', Bin('>>s', Bin('<<', source, Const(bits - width, size), size), Const(bits - width, size),
                                   size), Const(lsb, size), size)
        elif m == 'bfi':
            old = self.read_reg(dst)
            result = Bin('|', Bin('&', old, Const(mask(size) ^ (field << lsb), size), size),
                         Bin('<<', Bin('&', source, Const(field, size), size), Const(lsb, size), size), size)
        elif m == 'bfxil':
            old = self.read_reg(dst)
            result = Bin('|', Bin('&', old, Const(mask(size) ^ field, size), size),
                         Bin('&', Bin('>>u', source, Const(lsb, size), size), Const(field, size), size), size)
        else:
            # Raw ubfm/sbfm/bfm (immr, imms) - aliases cover the usual cases.
            immr, imms = lsb, width
            if m == 'ubfm':
                if imms >= immr:
                    result = Bin('&', Bin('>>u', source, Const(immr, size), size), Const((1 << (imms - immr + 1)) - 1, size),
                                 size)
                else:
                    result = Bin('<<', Bin('&', source, Const((1 << (imms + 1)) - 1, size), size),
                                 Const(bits - immr, size), size)
            else:
                raise ValueError('bitfield form')
        self.write_reg(dst, result, a)

    def select(self, insn, m, a):
        ops = insn.operands
        dst = insn.reg_name(ops[0].reg)
        if m == 'fcsel':
            size = FP_SIZE[dst[0]]
            self.write_reg(dst, Tern(self.cond(insn.cc), self.fp(insn, 1, size), self.fp(insn, 2, size), size), a)
            return
        size = self.rsize(insn, 0)
        cond = self.cond(insn.cc)
        if m in ('cset', 'csetm'):
            # The alias carries the condition as written (cset w0, gt).
            one = Const(1, size) if m == 'cset' else Const(mask(size), size)
            self.write_reg(dst, Tern(cond, one, Const(0, size), size), a)
            return
        if m in ('cinc', 'cinv', 'cneg'):
            source = self.value(insn, 1, size)
            changed = {'cinc': Bin('+', source, Const(1, size), size), 'cinv': Un('not', source, size),
                       'cneg': Un('neg', source, size)}[m]
            self.write_reg(dst, Tern(cond, changed, source, size), a)
            return
        first, second = self.value(insn, 1, size), self.value(insn, 2, size)
        if m == 'csinc':
            second = Bin('+', second, Const(1, size), size)
        elif m == 'csinv':
            second = Un('not', second, size)
        elif m == 'csneg':
            second = Un('neg', second, size)
        self.write_reg(dst, Tern(cond, first, second, size), a)

    def memory(self, insn, m, a):
        from capstone import arm64
        ops = insn.operands
        if not any(o.type == arm64.ARM64_OP_MEM for o in ops):
            # ldr / ldrsw from a PC-relative literal: ldr w9, #0x140047fc0
            name = insn.reg_name(ops[0].reg)
            fam, rsize, kind = family(name)
            size = 4 if m == 'ldrsw' else rsize
            value = self.mem_load(self.global_address(ops[1].imm, 8), None, size, kind == 'v')
            if m == 'ldrsw':
                value = Cast('sext', value, 8)
            self.write_reg(name, value, a)
            return
        mem_index = next(i for i, o in enumerate(ops) if o.type == arm64.ARM64_OP_MEM)
        operand = ops[mem_index]
        post = None
        if mem_index + 1 < len(ops) and ops[mem_index + 1].type == arm64.ARM64_OP_IMM:
            post = ops[mem_index + 1].imm
        base_name = insn.reg_name(operand.mem.base)
        if post is not None:
            # Post-index: access [base], then base += imm.
            addr, offset = self.address_of_plain(insn, operand)
        else:
            addr, offset = self.address_of(insn, operand)
        registers = [insn.reg_name(o.reg) for o in ops[:mem_index]]
        load = m.startswith('ld')
        suffix = m
        width = None
        if suffix in ('ldrb', 'strb', 'ldurb', 'sturb', 'ldrsb', 'ldursb', 'ldarb', 'stlrb', 'ldxrb', 'stxrb',
                      'ldaxrb', 'stlxrb', 'ldaprb'):
            width = 1
        elif suffix in ('ldrh', 'strh', 'ldurh', 'sturh', 'ldrsh', 'ldursh', 'ldarh', 'stlrh', 'ldxrh', 'stxrh',
                        'ldaxrh', 'stlxrh', 'ldaprh'):
            width = 2
        elif suffix in ('ldrsw', 'ldursw', 'ldpsw'):
            width = 4
        signed = suffix.startswith(('ldrs', 'ldurs', 'ldps'))
        if m.startswith(('stxr', 'stlxr', 'stxp', 'stlxp')):
            # Exclusive store: status register first; the store always succeeds here.
            status, registers = registers[0], registers[1:]
            self.write_reg(status, Const(0, 4), a)
        step = 0
        for position, name in enumerate(registers):
            fam, rsize, kind = family(name)
            size = width or rsize
            here = addr if not step else simplify_add(addr, step)
            here_offset = None if offset is None else offset + step
            if load:
                if kind == 'v':
                    value = self.mem_load(here, here_offset, rsize, True)
                    self.write_reg(name, value, a)
                else:
                    value = self.mem_load(here, here_offset, size)
                    if size < rsize:
                        value = Cast('sext' if signed else 'zext', value, rsize)
                    self.write_reg(name, value, a)
            else:
                value = self.read_reg(name) if kind != 'v' else self.fp_value_of(name)
                if kind != 'v' and size < value.size:
                    value = Cast('trunc', value, size)
                self.mem_store(here, here_offset, value, size, a, kind == 'v')
            step += size
        if post is not None or insn.writeback:
            base_value = self.read_reg(base_name)
            delta = post if post is not None else operand.mem.disp
            self.write_reg(base_name, simplify_add(base_value, delta), a)

    def vector_memory(self, insn, m, a):
        """NEON ld1/st1 of whole registers, ldN/stN of one lane, ld1r; post-increment by
        immediate or register. (De-interleaving ld2/ld3/ld4 of whole registers is not modelled.)"""
        from capstone import arm64
        ops = insn.operands
        mem_index = next(i for i, o in enumerate(ops) if o.type == arm64.ARM64_OP_MEM)
        operand = ops[mem_index]
        text = insn.op_str
        names = [insn.reg_name(o.reg) for o in ops[:mem_index]]
        lane_match = re.search(r'\}\[(\d+)\]', text)
        element = re.search(r'\.(\d*)([bhsd])\b', text)
        if not element:
            return False
        count, esize = element.group(1), {'b': 1, 'h': 2, 's': 4, 'd': 8}[element.group(2)]
        addr, offset = self.address_of_plain(insn, operand)
        if operand.mem.disp:
            addr = simplify_add(addr, operand.mem.disp)
            offset = None if offset is None else offset + operand.mem.disp
        load = m.startswith('ld')
        step = 0
        if m == 'ld1r':
            value = self.mem_load(addr, offset, esize)
            setter = {1: '_mm_set1_epi8', 2: '_mm_set1_epi16', 4: '_mm_set1_epi32', 8: '_mm_set1_epi64x'}[esize]
            self.write_reg(names[0], Intrinsic(setter, [value], 16), a)
            step = esize
        elif lane_match:
            lane = int(lane_match.group(1))
            bits = 8 * esize
            for name in names:
                here = simplify_add(addr, step)
                here_offset = None if offset is None else offset + step
                if load:
                    value = self.mem_load(here, here_offset, esize)
                    inserted = Intrinsic('_mm_insert_epi%d' % bits, [self.read_reg(name), value, Const(lane, 4)], 16)
                    self.write_reg(name, inserted, a)
                else:
                    value = Intrinsic('_mm_extract_epi%d' % bits, [self.read_reg(name), Const(lane, 4)],
                                      max(esize, 4) if bits < 64 else 8)
                    if value.size != esize:
                        value = Cast('trunc', value, esize)
                    self.mem_store(here, here_offset, value, esize, a)
                step += esize
        elif m in ('ld1', 'st1'):
            width = 16 if count and int(count) * esize == 16 else 8
            for name in names:
                here = simplify_add(addr, step)
                here_offset = None if offset is None else offset + step
                if width == 16:
                    if load:
                        self.write_reg(name, self.mem_load(here, here_offset, 16), a)
                    else:
                        self.mem_store(here, here_offset, self.read_reg(name), 16, a)
                else:
                    if here_offset is not None:
                        self.memory_slots.add(here_offset)
                        here = self.stack_address(here_offset)
                    if load:
                        self.write_reg(name, Intrinsic('_mm_loadl_epi64', [here], 16), a)
                    else:
                        self.emit(ExprStmt(Intrinsic('_mm_storel_epi64', [here, self.read_reg(name)], 16), a))
                step += width
        else:
            return False
        if mem_index + 1 < len(ops):
            following = ops[mem_index + 1]
            base_name = insn.reg_name(operand.mem.base)
            base_value = self.read_reg(base_name)
            if following.type == arm64.ARM64_OP_IMM:
                self.write_reg(base_name, simplify_add(base_value, following.imm), a)
            elif following.type == arm64.ARM64_OP_REG:
                self.write_reg(base_name, Bin('+', base_value, self.read_reg(insn.reg_name(following.reg)), 8), a)
        return True

    def address_of_plain(self, insn, operand):
        from .ir import simplify
        known = self.const_of(insn.reg_name(operand.mem.base))
        expr = Const(known, 8) if known is not None else simplify(self.read_reg(insn.reg_name(operand.mem.base)))
        if isinstance(expr, Const):
            return self.global_address(expr.value, 8), None
        return expr, self.stack_offset(expr)

    def fp_value_of(self, name):
        """A stored fp/simd register: the scalar for s/d, the vector for q."""
        fam, size, _ = family(name)
        var = Var(fam, 16)
        if size == 16:
            return var
        return var

    def fp(self, insn, index, size):
        from capstone import arm64
        operand = insn.operands[index]
        if operand.type == arm64.ARM64_OP_FP:
            return FConst(operand.fp, size)
        if operand.type == arm64.ARM64_OP_IMM:
            return FConst(float(operand.imm), size)
        return self.read_reg(insn.reg_name(operand.reg))

    def fp_move(self, insn, a):
        ops = insn.operands
        self.write_reg(insn.reg_name(ops[0].reg), self.read_reg(insn.reg_name(ops[1].reg)), a)

    def floating(self, insn, m, a):
        from capstone import arm64
        ops = insn.operands
        if not ops:
            return False
        dst = insn.reg_name(ops[0].reg) if ops[0].type == arm64.ARM64_OP_REG else ''
        dkind = family(dst)[2] if dst else ''
        size = FP_SIZE.get(dst[:1], 8) if dkind == 'v' else self.rsize(insn, 0) if dst else 8
        arith = {'fadd': '+f', 'fsub': '-f', 'fmul': '*f', 'fdiv': '/f'}
        if m in arith:
            self.write_reg(dst, Bin(arith[m], self.fp(insn, 1, size), self.fp(insn, 2, size), size), a)
            return True
        if m == 'fnmul':
            self.write_reg(dst, Bin('-f', FConst(-0.0, size), Bin('*f', self.fp(insn, 1, size), self.fp(insn, 2, size),
                                                                   size), size), a)
            return True
        if m in ('fmadd', 'fmsub', 'fnmadd', 'fnmsub'):
            x, y, z = self.fp(insn, 1, size), self.fp(insn, 2, size), self.fp(insn, 3, size)
            fma = 'fmaf' if size == 4 else 'fma'
            negate = lambda e: Bin('-f', FConst(-0.0, size), e, size)  # noqa: E731
            if m == 'fmadd':
                result = Intrinsic(fma, [x, y, z], size)
            elif m == 'fmsub':
                result = Intrinsic(fma, [negate(x), y, z], size)
            elif m == 'fnmadd':
                result = Intrinsic(fma, [negate(x), y, negate(z)], size)
            else:
                result = Intrinsic(fma, [x, y, negate(z)], size)
            self.write_reg(dst, result, a)
            return True
        if m in ('fneg', 'fabs', 'fsqrt', 'frintz', 'frintm', 'frintp', 'frintn', 'frinta', 'frinti', 'frintx'):
            source = self.fp(insn, 1, size)
            if m == 'fneg':
                result = Bin('-f', FConst(-0.0, size), source, size)
            else:
                base = {'fabs': 'fabs', 'fsqrt': 'sqrt', 'frintz': 'trunc', 'frintm': 'floor', 'frintp': 'ceil',
                        'frintn': 'nearbyint', 'frinta': 'round', 'frinti': 'nearbyint', 'frintx': 'rint'}[m]
                result = Intrinsic(base + ('f' if size == 4 else ''), [source], size)
            self.write_reg(dst, result, a)
            return True
        if m in ('fmax', 'fmin', 'fmaxnm', 'fminnm'):
            left, right = self.fp(insn, 1, size), self.fp(insn, 2, size)
            name = ('fmax' if 'max' in m else 'fmin') + ('f' if size == 4 else '')
            self.write_reg(dst, Intrinsic(name, [left, right], size), a)
            return True
        if m in ('fcmp', 'fcmpe'):
            size = FP_SIZE[dst[0]]
            self.set_flags('afcmp', self.fp(insn, 0, size), self.fp(insn, 1, size), size, a)
            return True
        if m == 'fmov':
            source_name = insn.reg_name(ops[1].reg) if ops[1].type == arm64.ARM64_OP_REG else ''
            if source_name and family(source_name)[2] == 'v' and dkind != 'v':
                # fp bits -> integer register
                ssize = FP_SIZE[source_name[0]]
                self.write_reg(dst, Intrinsic('cy_bits%d' % (8 * ssize), [self.read_reg(source_name)], ssize), a)
            elif source_name and family(source_name)[2] != 'v' and dkind == 'v':
                self.write_reg(dst, Intrinsic('cy_float%d' % (8 * size), [self.read_reg(source_name)], size), a)
            else:
                self.write_reg(dst, self.fp(insn, 1, size), a)
            return True
        if m in ('scvtf', 'ucvtf') and dkind == 'v':
            source = self.value(insn, 1)
            if m == 'ucvtf':
                source = Intrinsic('cy_u2f%d' % (8 * source.size), [source], 8)
                result = source if size == 8 else Cast('f2f', source, 4)
            else:
                result = Cast('i2f', source, size)
            if len(ops) > 2 and ops[2].type == arm64.ARM64_OP_IMM and ops[2].imm:
                # Fixed-point source: value / 2^fbits.
                result = Bin('/f', result, FConst(float(1 << ops[2].imm), size), size)
            self.write_reg(dst, result, a)
            return True
        if m.startswith(('fcvtzs', 'fcvtzu', 'fcvtas', 'fcvtms', 'fcvtps', 'fcvtns', 'fcvtau', 'fcvtmu', 'fcvtpu',
                         'fcvtnu')) and dkind != 'v':
            source_name = insn.reg_name(ops[1].reg)
            ssize = FP_SIZE[source_name[0]]
            source = self.read_reg(source_name)
            if len(ops) > 2 and ops[2].type == arm64.ARM64_OP_IMM and ops[2].imm:
                # Fixed-point result: value * 2^fbits before the conversion.
                source = Bin('*f', source, FConst(float(1 << ops[2].imm), ssize), ssize)
            rounding = {'z': None, 'a': 'round', 'm': 'floor', 'p': 'ceil', 'n': 'nearbyint'}[m[4]]
            if rounding:
                source = Intrinsic(rounding + ('f' if ssize == 4 else ''), [source], ssize)
            unsigned = m.endswith('u')
            name = 'cy_f2%s%d' % ('u' if unsigned else 's', 8 * size)
            # Saturating conversion (out-of-range values clamp, NaN gives 0) like the hardware.
            self.write_reg(dst, Intrinsic(name, [Cast('f2f', source, 8) if ssize == 4 else source], size), a)
            return True
        if m == 'fcvt':
            source_name = insn.reg_name(ops[1].reg)
            self.write_reg(dst, Cast('f2f', self.read_reg(source_name), size), a)
            return True
        if m == 'movi' and len(ops) == 2 and ops[1].type == arm64.ARM64_OP_IMM and ops[1].imm == 0:
            self.write_reg(dst, FConst(0.0, 8) if dst[0] == 'd' else Intrinsic('_mm_setzero_si128', [], 16), a)
            return True
        if m == 'movi' and len(ops) == 2 and ops[1].type == arm64.ARM64_OP_IMM and dst[0] == 'd':
            self.write_reg(dst, Intrinsic('_mm_cvtsi64_si128', [Const(ops[1].imm & mask(8), 8)], 16), a)
            return True
        return False

    # ------------------------------------------------------------------ NEON

    def neon(self, insn, m, a):
        """Common NEON vector operations as SSE intrinsics."""
        from capstone import arm64
        text = insn.op_str
        arrangement = re.findall(r'\.(\d+[bhsd])\b', text)
        lanes = re.search(r'\.([bhsd])\[((?:0x)?[0-9a-f]+)\]', text)
        ops = insn.operands
        if not arrangement and not lanes:
            return False
        kind = ARRANGEMENTS.get(arrangement[0]) if arrangement else None
        dst = insn.reg_name(ops[0].reg)

        def vec(index):
            return self.read_reg(insn.reg_name(ops[index].reg))
        if kind is None and lanes is None:
            return False
        if kind:
            bits, isuffix, fflavour = kind
        integer_ops = {'add': 'add', 'sub': 'sub', 'mul': 'mullo', 'cmeq': 'cmpeq', 'cmgt': 'cmpgt'}
        logic = {'and': '_mm_and_si128', 'orr': '_mm_or_si128', 'eor': '_mm_xor_si128'}
        float_ops = {'fadd': 'add', 'fsub': 'sub', 'fmul': 'mul', 'fdiv': 'div', 'fmax': 'max', 'fmin': 'min'}
        if kind and m in integer_ops and len(ops) == 3 and ops[2].type == arm64.ARM64_OP_REG:
            name = '_mm_%s_%s' % (integer_ops[m], isuffix)
            if m == 'mul' and bits == 8:
                return False
            self.write_reg(dst, Intrinsic(name, [vec(1), vec(2)], 16), a)
            return True
        minmax = {('smax', 32): 'max_epi32', ('smin', 32): 'min_epi32', ('umax', 32): 'max_epu32',
                  ('umin', 32): 'min_epu32', ('smax', 16): 'max_epi16', ('smin', 16): 'min_epi16',
                  ('umax', 16): 'max_epu16', ('umin', 16): 'min_epu16', ('smax', 8): 'max_epi8',
                  ('smin', 8): 'min_epi8', ('umax', 8): 'max_epu8', ('umin', 8): 'min_epu8'}
        if kind and (m, bits) in minmax and len(ops) == 3:
            self.write_reg(dst, Intrinsic('_mm_' + minmax[(m, bits)], [vec(1), vec(2)], 16), a)
            return True
        if kind and m in ('cmge', 'cmhs', 'cmhi', 'cmle', 'cmlt') and len(ops) == 3 and \
                ops[2].type == arm64.ARM64_OP_REG and bits in (8, 16, 32):
            left, right = vec(1), vec(2)
            if m in ('cmle', 'cmlt'):
                left, right = right, left

            def eq(x, y):
                return Intrinsic('_mm_cmpeq_%s' % isuffix, [x, y], 16)
            if m in ('cmge', 'cmle'):
                result = Intrinsic('_mm_or_si128', [Intrinsic('_mm_cmpgt_%s' % isuffix, [left, right], 16),
                                                    eq(left, right)], 16)
            elif m == 'cmlt':
                result = Intrinsic('_mm_cmpgt_%s' % isuffix, [left, right], 16)
            else:
                maximum = Intrinsic('_mm_max_epu%d' % bits, [left, right], 16)
                result = eq(maximum, left)
                if m == 'cmhi':
                    result = Intrinsic('_mm_andnot_si128', [eq(left, right), result], 16)
            self.write_reg(dst, result, a)
            return True
        if kind and m in ('cmeq', 'cmgt', 'cmge', 'cmle', 'cmlt') and len(ops) == 3 and \
                ops[2].type == arm64.ARM64_OP_IMM and ops[2].imm == 0 and bits in (8, 16, 32):
            zero = Intrinsic('_mm_setzero_si128', [], 16)
            source = vec(1)
            if m == 'cmeq':
                result = Intrinsic('_mm_cmpeq_%s' % isuffix, [source, zero], 16)
            elif m == 'cmgt':
                result = Intrinsic('_mm_cmpgt_%s' % isuffix, [source, zero], 16)
            elif m == 'cmlt':
                result = Intrinsic('_mm_cmpgt_%s' % isuffix, [zero, source], 16)
            elif m == 'cmge':
                result = Intrinsic('_mm_or_si128', [Intrinsic('_mm_cmpgt_%s' % isuffix, [source, zero], 16),
                                                    Intrinsic('_mm_cmpeq_%s' % isuffix, [source, zero], 16)], 16)
            else:
                result = Intrinsic('_mm_or_si128', [Intrinsic('_mm_cmpgt_%s' % isuffix, [zero, source], 16),
                                                    Intrinsic('_mm_cmpeq_%s' % isuffix, [source, zero], 16)], 16)
            self.write_reg(dst, result, a)
            return True
        if kind and m in ('addp', 'umaxp', 'uminp', 'smaxp', 'sminp') and len(ops) == 3:
            # Pairwise operations: helpers over the lanes of both sources.
            helper = 'cy_%s_%d_%d' % (m, bits, 16 if arrangement[0] in ('16b', '8h', '4s', '2d') else 8)
            self.write_reg(dst, Intrinsic(helper, [vec(1), vec(2)], 16), a)
            return True
        if kind and m in ('shrn', 'xtn', 'rshrn') and len(ops) >= 2:
            source_bits = bits * 2
            amount = ops[2].imm if len(ops) > 2 and ops[2].type == arm64.ARM64_OP_IMM else 0
            helper = 'cy_%s_%d' % ('rshrn' if m == 'rshrn' else 'shrn', source_bits)
            self.write_reg(dst, Intrinsic(helper, [vec(1), Const(amount, 4)], 16), a)
            return True
        if kind and m in ('bsl', 'bit', 'bif') and len(ops) == 3:
            d, n, mm = self.read_reg(dst), vec(1), vec(2)
            selector, chosen, other = {'bsl': (d, n, mm), 'bit': (mm, n, d), 'bif': (mm, d, n)}[m]
            self.write_reg(dst, Intrinsic('_mm_or_si128', [Intrinsic('_mm_and_si128', [selector, chosen], 16),
                                                           Intrinsic('_mm_andnot_si128', [selector, other], 16)],
                                          16), a)
            return True
        if kind and m in ('neg', 'abs', 'mvn', 'not') and len(ops) == 2:
            source = vec(1)
            if m in ('mvn', 'not'):
                result = Intrinsic('_mm_xor_si128', [source, Intrinsic('_mm_set1_epi32', [Const(mask(4), 4)], 16)], 16)
            elif m == 'neg':
                result = Intrinsic('_mm_sub_%s' % isuffix, [Intrinsic('_mm_setzero_si128', [], 16), source], 16)
            elif bits in (8, 16, 32):
                result = Intrinsic('_mm_abs_%s' % isuffix, [source], 16)
            else:
                return False
            self.write_reg(dst, result, a)
            return True
        if kind and fflavour and m in ('fneg', 'fabs') and len(ops) == 2:
            sign = Intrinsic('_mm_set1_%s' % fflavour, [FConst(-0.0, bits // 8)], 16)
            op = '_mm_xor_%s' % fflavour if m == 'fneg' else '_mm_andnot_%s' % fflavour
            args = [vec(1), sign] if m == 'fneg' else [sign, vec(1)]
            self.write_reg(dst, Intrinsic(op, args, 16), a)
            return True
        if kind and m == 'cnt' and bits == 8:
            self.write_reg(dst, Intrinsic('cy_cnt_epi8', [vec(1)], 16), a)
            return True
        if kind and m in ('uaddlv', 'addv') and bits == 8:
            lanes8 = 16 if arrangement[0] == '16b' else 8
            self.write_reg(dst, Intrinsic('_mm_cvtsi32_si128', [Intrinsic('cy_addv_epu8_%d' % lanes8, [vec(1)], 4)],
                                          16), a)
            return True
        if kind and m in logic and len(ops) == 3 and ops[2].type == arm64.ARM64_OP_REG:
            self.write_reg(dst, Intrinsic(logic[m], [vec(1), vec(2)], 16), a)
            return True
        if kind and m == 'bic' and len(ops) == 3 and ops[2].type == arm64.ARM64_OP_REG:
            self.write_reg(dst, Intrinsic('_mm_andnot_si128', [vec(2), vec(1)], 16), a)
            return True
        if kind and fflavour and m in float_ops:
            self.write_reg(dst, Intrinsic('_mm_%s_%s' % (float_ops[m], fflavour), [vec(1), vec(2)], 16), a)
            return True
        if kind and m == 'movi':
            imm = ops[1].imm << (ops[1].shift.value if ops[1].shift.type == SFT_LSL else 0)
            if imm == 0:
                self.write_reg(dst, Intrinsic('_mm_setzero_si128', [], 16), a)
            elif bits == 64:
                self.write_reg(dst, Intrinsic('_mm_set1_epi64x', [Const(imm, 8)], 16), a)
            else:
                self.write_reg(dst, Intrinsic('_mm_set1_%s' % isuffix, [Const(imm, bits // 8)], 16), a)
            return True
        if kind and m in ('mvni',):
            imm = ops[1].imm << (ops[1].shift.value if ops[1].shift.type == SFT_LSL else 0)
            self.write_reg(dst, Intrinsic('_mm_set1_%s' % isuffix, [Const(~imm & mask(bits // 8), bits // 8)], 16), a)
            return True
        if kind and m == 'dup':
            source = insn.reg_name(ops[1].reg)
            if family(source)[2] == 'v':
                return False
            value = self.read_reg(source)
            setter = '_mm_set1_epi64x' if bits == 64 else '_mm_set1_%s' % isuffix
            self.write_reg(dst, Intrinsic(setter, [value if bits == 64 else Cast('trunc', value, bits // 8)
                                                   if value.size > bits // 8 else value], 16), a)
            return True
        if kind and m in ('shl', 'ushr', 'sshr') and ops[2].type == arm64.ARM64_OP_IMM and bits in (16, 32, 64):
            name = {'shl': 'slli', 'ushr': 'srli', 'sshr': 'srai'}[m]
            if name == 'srai' and bits == 64:
                return False
            self.write_reg(dst, Intrinsic('_mm_%s_%s' % (name, isuffix), [vec(1), Const(ops[2].imm, 4)], 16), a)
            return True
        if kind and m in ('scvtf', 'fcvtzs') and bits == 32:
            name = '_mm_cvtepi32_ps' if m == 'scvtf' else '_mm_cvttps_epi32'
            self.write_reg(dst, Intrinsic(name, [vec(1)], 16), a)
            return True
        if m in ('addv', 'smaxv', 'sminv', 'umaxv', 'uminv') and kind and bits == 32:
            helper = {'addv': 'cy_addv_epi32', 'smaxv': 'cy_maxv_epi32', 'sminv': 'cy_minv_epi32',
                      'umaxv': 'cy_maxv_epu32', 'uminv': 'cy_minv_epu32'}[m]
            self.write_reg(dst, Intrinsic('_mm_cvtsi32_si128', [Intrinsic(helper, [vec(1)], 4)], 16), a)
            return True
        if m in ('addv', 'smaxv', 'sminv', 'umaxv', 'uminv') and kind and bits in (8, 16):
            count = 16 if arrangement[0] in ('16b', '8h') else 8
            helper = 'cy_%s_%d_%d' % (m, bits, count)
            self.write_reg(dst, Intrinsic('_mm_cvtsi32_si128', [Intrinsic(helper, [vec(1)], 4)], 16), a)
            return True
        if m in ('rev64', 'rev32', 'rev16') and kind and len(ops) == 2:
            self.write_reg(dst, Intrinsic('cy_%s_%d' % (m, bits), [vec(1)], 16), a)
            return True
        if m == 'addp' and kind is None and lanes is None:
            return False
        if m == 'addp' and kind and bits == 64 and len(ops) == 2:
            self.write_reg(dst, Intrinsic('_mm_cvtsi64_si128', [Intrinsic('cy_addv_epi64', [vec(1)], 8)], 16), a)
            return True
        if m == 'faddp' and kind and len(ops) == 2:
            helper = 'cy_faddp_pd' if bits == 64 else 'cy_faddp_ps'
            setter = '_mm_set_sd' if bits == 64 else '_mm_set_ss'
            self.write_reg(dst, Intrinsic(setter, [Intrinsic(helper, [vec(1)], bits // 8)], 16), a)
            return True
        if lanes and m in ('mov', 'umov', 'smov', 'ins', 'dup') and len(ops) == 2:
            lane_kind, lane = lanes.group(1), int(lanes.group(2), 0)
            lane_bits = {'b': 8, 'h': 16, 's': 32, 'd': 64}[lane_kind]
            dst_is_vec = family(dst)[2] == 'v'
            source = insn.reg_name(ops[1].reg)
            if not dst_is_vec:
                # umov / mov w0, v1.s[2]
                name = {8: '_mm_extract_epi8', 16: '_mm_extract_epi16', 32: '_mm_extract_epi32',
                        64: '_mm_extract_epi64'}[lane_bits]
                value = Intrinsic(name, [self.read_reg(source), Const(lane, 4)], lane_bits // 8 if lane_bits > 16 else 4)
                if m == 'smov' and lane_bits < 32:
                    value = Cast('sext', Cast('trunc', value, lane_bits // 8), self.rsize(insn, 0))
                self.write_reg(dst, value, a)
                return True
            if family(source)[2] != 'v' and m in ('mov', 'ins'):
                name = {8: '_mm_insert_epi8', 16: '_mm_insert_epi16', 32: '_mm_insert_epi32',
                        64: '_mm_insert_epi64'}[lane_bits]
                self.write_reg(dst, Intrinsic(name, [self.read_reg(dst), self.read_reg(source), Const(lane, 4)], 16), a)
                return True
            if m in ('mov', 'dup') and family(source)[2] == 'v' and len(re.findall(r'\[', text)) == 1 and \
                    family(dst)[1] < 16:
                # mov d3, v1.d[1] / dup s0, v1.s[2]: that lane becomes the scalar (low lane).
                value = self.read_reg(source)
                if lane:
                    value = Intrinsic('_mm_srli_si128', [value, Const(lane * lane_bits // 8, 4)], 16)
                self.write_reg(dst, value, a)
                return True
            return False
        return False


def simplify_add(expr, delta):
    from .ir import simplify
    if not delta:
        return expr
    return simplify(Bin('+', expr, Const(delta, 8), 8))


def rotate_right(value, amount, size):
    bits = 8 * size
    amount %= bits
    if not amount:
        return value
    return Bin('|', Bin('>>u', value, Const(amount, size), size), Bin('<<', value, Const(bits - amount, size), size), size)
