"""Intermediate representation of the C decompiler: expressions, statements, simplification.

Sizes are in bytes. Constants are stored unsigned (masked to their size) and printed signed
or unsigned by the generator depending on context. Expressions are immutable; `subst`
returns a new tree with variables replaced.
"""

MASKS = {1: 0xff, 2: 0xffff, 4: 0xffffffff, 8: 0xffffffffffffffff, 16: (1 << 128) - 1}


def mask(size):
    return MASKS.get(size, (1 << (8 * size)) - 1)


def signed(value, size):
    value &= mask(size)
    return value - (1 << (8 * size)) if value >> (8 * size - 1) else value


class Expr:
    __slots__ = ()
    size = 0

    def kids(self):
        return ()

    def rebuild(self, kids):
        return self

    def vars(self):
        result = set()
        stack = [self]
        while stack:
            e = stack.pop()
            if isinstance(e, Var):
                result.add(e.name)
            stack.extend(e.kids())
        return result

    def has_load(self):
        stack = [self]
        while stack:
            e = stack.pop()
            if isinstance(e, (Load, Call)):
                return True
            stack.extend(e.kids())
        return False

    def has_call(self):
        stack = [self]
        while stack:
            e = stack.pop()
            if isinstance(e, Call):
                return True
            stack.extend(e.kids())
        return False

    def subst(self, mapping):
        if isinstance(self, Var):
            return mapping.get(self.name, self)
        kids = self.kids()
        if not kids:
            return self
        new = [k.subst(mapping) for k in kids]
        if all(a is b for a, b in zip(new, kids)):
            return self
        return self.rebuild(new)

    def walk(self):
        stack = [self]
        while stack:
            e = stack.pop()
            yield e
            stack.extend(e.kids())

    def __eq__(self, other):
        return type(self) is type(other) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def key(self):
        return (type(self).__name__,)


class Const(Expr):
    __slots__ = ('value', 'size')

    def __init__(self, value, size):
        self.size = size
        self.value = value & mask(size) if isinstance(value, int) else value

    def key(self):
        return ('C', self.value, self.size)

    def __repr__(self):
        return '%#x' % self.value if isinstance(self.value, int) else repr(self.value)


class FConst(Expr):
    __slots__ = ('value', 'size')

    def __init__(self, value, size):
        self.value, self.size = value, size

    def key(self):
        return ('F', self.value, self.size)


class Var(Expr):
    __slots__ = ('name', 'size')

    def __init__(self, name, size):
        self.name, self.size = name, size

    def key(self):
        return ('V', self.name)

    def __repr__(self):
        return self.name


class Addr(Expr):
    """Address of a stack variable (&local_10) or a global (&DAT_...)."""
    __slots__ = ('name', 'size')

    def __init__(self, name, size=8):
        self.name, self.size = name, size

    def key(self):
        return ('A', self.name)


class Sym(Expr):
    """A named constant address: function, import, string, global."""
    __slots__ = ('name', 'address', 'size', 'kind')

    def __init__(self, name, address, size, kind='code'):
        self.name, self.address, self.size, self.kind = name, address, size, kind

    def key(self):
        return ('S', self.address, self.name)


class Load(Expr):
    __slots__ = ('addr', 'size', 'float')

    def __init__(self, addr, size, is_float=False):
        self.addr, self.size, self.float = addr, size, is_float

    def kids(self):
        return (self.addr,)

    def rebuild(self, kids):
        return Load(kids[0], self.size, self.float)

    def key(self):
        return ('L', self.addr.key(), self.size, self.float)


class Bin(Expr):
    __slots__ = ('op', 'a', 'b', 'size')

    def __init__(self, op, a, b, size):
        self.op, self.a, self.b, self.size = op, a, b, size

    def kids(self):
        return (self.a, self.b)

    def rebuild(self, kids):
        return Bin(self.op, kids[0], kids[1], self.size)

    def key(self):
        return ('B', self.op, self.a.key(), self.b.key(), self.size)


class Un(Expr):
    __slots__ = ('op', 'a', 'size')

    def __init__(self, op, a, size):
        self.op, self.a, self.size = op, a, size

    def kids(self):
        return (self.a,)

    def rebuild(self, kids):
        return Un(self.op, kids[0], self.size)

    def key(self):
        return ('U', self.op, self.a.key(), self.size)


class Cast(Expr):
    """kind: zext, sext, trunc, i2f (signed int -> float), u2f, f2i (truncating), f2f."""
    __slots__ = ('kind', 'a', 'size')

    def __init__(self, kind, a, size):
        self.kind, self.a, self.size = kind, a, size

    def kids(self):
        return (self.a,)

    def rebuild(self, kids):
        return Cast(self.kind, kids[0], self.size)

    def key(self):
        return ('K', self.kind, self.a.key(), self.size)


class Cmp(Expr):
    """op: == != <s <=s >s >=s <u <=u >u >=u <f <=f >f >=f ==f !=f; size = operand size."""
    __slots__ = ('op', 'a', 'b', 'operand_size', 'size')

    def __init__(self, op, a, b, operand_size):
        self.op, self.a, self.b, self.operand_size, self.size = op, a, b, operand_size, 1

    def kids(self):
        return (self.a, self.b)

    def rebuild(self, kids):
        return Cmp(self.op, kids[0], kids[1], self.operand_size)

    def key(self):
        return ('P', self.op, self.a.key(), self.b.key())


class Logic(Expr):
    """Short-circuit && / || of conditions, and ! (op 'not', b None)."""
    __slots__ = ('op', 'a', 'b', 'size')

    def __init__(self, op, a, b=None):
        self.op, self.a, self.b, self.size = op, a, b, 1

    def kids(self):
        return (self.a,) if self.b is None else (self.a, self.b)

    def rebuild(self, kids):
        return Logic(self.op, kids[0], kids[1] if len(kids) > 1 else None)

    def key(self):
        return ('G', self.op, self.a.key(), self.b.key() if self.b is not None else None)


class Flags(Expr):
    """Flags produced by an instruction. kind: cmp, test, res (result-based), add, fcmp, bt."""
    __slots__ = ('kind', 'a', 'b', 'size')

    def __init__(self, kind, a, b, size):
        self.kind, self.a, self.b, self.size = kind, a, b, size

    def kids(self):
        return (self.a, self.b)

    def rebuild(self, kids):
        return Flags(self.kind, kids[0], kids[1], self.size)

    def key(self):
        return ('Fl', self.kind, self.a.key(), self.b.key(), self.size)


class Cond(Expr):
    """A condition code applied to a flags value (resolved into Cmp by `resolve_cond`)."""
    __slots__ = ('cc', 'flags', 'size')

    def __init__(self, cc, flags):
        self.cc, self.flags, self.size = cc, flags, 1

    def kids(self):
        return (self.flags,)

    def rebuild(self, kids):
        return Cond(self.cc, kids[0])

    def key(self):
        return ('Q', self.cc, self.flags.key())


class Tern(Expr):
    __slots__ = ('c', 'a', 'b', 'size')

    def __init__(self, c, a, b, size):
        self.c, self.a, self.b, self.size = c, a, b, size

    def kids(self):
        return (self.c, self.a, self.b)

    def rebuild(self, kids):
        return Tern(kids[0], kids[1], kids[2], self.size)

    def key(self):
        return ('T', self.c.key(), self.a.key(), self.b.key())


class Call(Expr):
    __slots__ = ('target', 'args', 'size', 'id', 'returns', 'float', 'hints')
    counter = [0]

    def __init__(self, target, args, size, call_id=None, returns=None, float_size=0):
        # returns: True / False from the callee's own analysis, None when unknown.
        # float_size: 4 / 8 when the callee returns a float / double (xmm0 or st0).
        self.target, self.args, self.size, self.returns = target, list(args), size, returns
        self.float = float_size
        self.hints = ()       # per argument: True when the callee's parameter is floating point
        if call_id is None:
            Call.counter[0] += 1
            call_id = Call.counter[0]
        self.id = call_id

    def kids(self):
        return (self.target,) + tuple(self.args)

    def rebuild(self, kids):
        call = Call(kids[0], kids[1:], self.size, self.id, self.returns, self.float)
        call.hints = self.hints
        return call

    def key(self):
        return ('Call', self.id)


class Intrinsic(Expr):
    """Operation with no C operator: rotl, rotr, bswap, memcpy-like... printed as name(args)."""
    __slots__ = ('name', 'args', 'size')

    def __init__(self, name, args, size):
        self.name, self.args, self.size = name, list(args), size

    def kids(self):
        return tuple(self.args)

    def rebuild(self, kids):
        return Intrinsic(self.name, kids, self.size)

    def key(self):
        return ('I', self.name, tuple(a.key() for a in self.args), self.size)


# ---------------------------------------------------------------------- statements

class Stmt:
    __slots__ = ()

    def uses(self):
        return set()

    def exprs(self):
        return ()

    def map_exprs(self, function):
        return self


class Assign(Stmt):
    __slots__ = ('dst', 'src', 'address')

    def __init__(self, dst, src, address=0):
        self.dst, self.src, self.address = dst, src, address

    def exprs(self):
        return (self.src,)

    def map_exprs(self, function):
        return Assign(self.dst, function(self.src), self.address)

    def __repr__(self):
        return '%s = %r' % (self.dst.name, self.src)


class Store(Stmt):
    __slots__ = ('addr', 'value', 'size', 'float', 'address')

    def __init__(self, addr, value, size, is_float=False, address=0):
        self.addr, self.value, self.size, self.float, self.address = addr, value, size, is_float, address

    def exprs(self):
        return (self.addr, self.value)

    def map_exprs(self, function):
        return Store(function(self.addr), function(self.value), self.size, self.float, self.address)


class ExprStmt(Stmt):
    __slots__ = ('expr', 'address')

    def __init__(self, expr, address=0):
        self.expr, self.address = expr, address

    def exprs(self):
        return (self.expr,)

    def map_exprs(self, function):
        return ExprStmt(function(self.expr), self.address)


class Clobber(Stmt):
    """Registers whose value becomes unknown (call-clobbered, unsupported instruction)."""
    __slots__ = ('names', 'address')

    def __init__(self, names, address=0):
        self.names, self.address = list(names), address


class Branch(Stmt):
    __slots__ = ('cond', 'true', 'false', 'address')

    def __init__(self, cond, true, false, address=0):
        self.cond, self.true, self.false, self.address = cond, true, false, address

    def exprs(self):
        return (self.cond,)

    def map_exprs(self, function):
        return Branch(function(self.cond), self.true, self.false, self.address)


class Jump(Stmt):
    __slots__ = ('target', 'address')

    def __init__(self, target, address=0):
        self.target, self.address = target, address


class Switch(Stmt):
    __slots__ = ('expr', 'cases', 'default', 'address')

    def __init__(self, expr, cases, default, address=0):
        self.expr, self.cases, self.default, self.address = expr, cases, default, address

    def exprs(self):
        return (self.expr,)

    def map_exprs(self, function):
        return Switch(function(self.expr), self.cases, self.default, self.address)


class IndirectJump(Stmt):
    __slots__ = ('expr', 'address')

    def __init__(self, expr, address=0):
        self.expr, self.address = expr, address

    def exprs(self):
        return (self.expr,)

    def map_exprs(self, function):
        return IndirectJump(function(self.expr), self.address)


class Ret(Stmt):
    """Return. fvalue: the floating-point return candidate (xmm0 / st0) until the data-flow pass
    decides between an integer, a floating-point or no return value."""
    __slots__ = ('value', 'address', 'fvalue')

    def __init__(self, value, address=0, fvalue=None):
        self.value, self.address, self.fvalue = value, address, fvalue

    def exprs(self):
        return tuple(e for e in (self.value, self.fvalue) if e is not None)

    def map_exprs(self, function):
        return Ret(function(self.value) if self.value is not None else None, self.address,
                   function(self.fvalue) if self.fvalue is not None else None)


class Comment(Stmt):
    __slots__ = ('text', 'address')

    def __init__(self, text, address=0):
        self.text, self.address = text, address


TERMINATORS = (Branch, Jump, Switch, IndirectJump, Ret)


# ---------------------------------------------------------------------- simplification

INVERT = {'==': '!=', '!=': '==', '<s': '>=s', '>=s': '<s', '<=s': '>s', '>s': '<=s',
          '<u': '>=u', '>=u': '<u', '<=u': '>u', '>u': '<=u',
          '==f': '!=f', '!=f': '==f'}
SWAP = {'==': '==', '!=': '!=', '<s': '>s', '>s': '<s', '<=s': '>=s', '>=s': '<=s',
        '<u': '>u', '>u': '<u', '<=u': '>=u', '>=u': '<=u', '<f': '>f', '>f': '<f', '<=f': '>=f', '>=f': '<=f',
        '==f': '==f', '!=f': '!=f'}


def is_const(e, value=None):
    return isinstance(e, Const) and isinstance(e.value, int) and (value is None or e.value == value & mask(e.size))


def is_condition(e):
    return isinstance(e, (Cmp, Logic, Cond)) or (isinstance(e, Const) and e.size == 1 and e.value in (0, 1))


def negate(c):
    c = simplify(c)
    if isinstance(c, Cmp) and c.op in INVERT:
        return Cmp(INVERT[c.op], c.a, c.b, c.operand_size)
    if isinstance(c, Logic) and c.op == 'not':
        return c.a
    if isinstance(c, Logic) and c.op in ('&&', '||'):
        return Logic('||' if c.op == '&&' else '&&', negate(c.a), negate(c.b))
    if isinstance(c, Const):
        return Const(0 if c.value else 1, 1)
    return Logic('not', c)


# Functions (math.h and the cy_* helpers) whose result is a float / double of the call's size.
FLOAT_FUNCTIONS = {name + suffix for name in ('sqrt', 'fabs', 'fma', 'fmin', 'fmax', 'trunc', 'floor', 'ceil',
                                              'round', 'nearbyint', 'rint', 'sin', 'cos')
                   for suffix in ('', 'f')} | {'cy_float32', 'cy_float64', 'cy_u2f32', 'cy_u2f64', 'cy_faddp_pd',
                                               'cy_faddp_ps'}

ARM_INTEGER_CC = {'eq': 'e', 'ne': 'ne', 'hs': 'ae', 'lo': 'b', 'hi': 'a', 'ls': 'be', 'ge': 'ge', 'lt': 'l',
                  'gt': 'g', 'le': 'le', 'mi': 's', 'pl': 'ns'}
ARM_NZCV = {'eq': lambda n, z, c, v: z, 'ne': lambda n, z, c, v: not z, 'hs': lambda n, z, c, v: c,
            'lo': lambda n, z, c, v: not c, 'mi': lambda n, z, c, v: n, 'pl': lambda n, z, c, v: not n,
            'vs': lambda n, z, c, v: v, 'vc': lambda n, z, c, v: not v, 'hi': lambda n, z, c, v: c and not z,
            'ls': lambda n, z, c, v: not c or z, 'ge': lambda n, z, c, v: n == v, 'lt': lambda n, z, c, v: n != v,
            'gt': lambda n, z, c, v: not z and n == v, 'le': lambda n, z, c, v: z or n != v,
            'al': lambda n, z, c, v: True}


def resolve_arm(cc, f):
    """AArch64 condition (cc without its 'a.' prefix) against a flag source."""
    a, b, size = f.a, f.b, f.size
    if cc == 'al':
        return Const(1, 1)
    if f.kind == 'ccmp':
        # ccmp: when the earlier condition holds, the comparison's flags; else the immediate NZCV.
        taken = resolve_arm(cc, b)
        if taken is None:
            return None
        nzcv = size
        fallback = ARM_NZCV[cc](bool(nzcv & 8), bool(nzcv & 4), bool(nzcv & 2), bool(nzcv & 1))
        return Logic('||', negate(a), taken) if fallback else Logic('&&', a, taken)
    if f.kind == 'afcmp':
        unordered = Logic('||', Cmp('!=f', a, a, size), Cmp('!=f', b, b, size))
        table = {'eq': Cmp('==f', a, b, size), 'ne': negate(Cmp('==f', a, b, size)),
                 'mi': Cmp('<f', a, b, size), 'lo': Cmp('<f', a, b, size), 'ls': Cmp('<=f', a, b, size),
                 'gt': Cmp('>f', a, b, size), 'ge': Cmp('>=f', a, b, size),
                 'pl': negate(Cmp('<f', a, b, size)), 'hs': negate(Cmp('<f', a, b, size)),
                 'hi': negate(Cmp('<=f', a, b, size)), 'lt': negate(Cmp('>=f', a, b, size)),
                 'le': negate(Cmp('>f', a, b, size)), 'vs': unordered, 'vc': negate(unordered)}
        return table.get(cc)
    if f.kind == 'test':
        constants = {'hs': 0, 'lo': 1, 'hi': 0, 'ls': 1, 'vs': 0, 'vc': 1}
        if cc in constants:
            return Const(constants[cc], 1)
        if cc == 'gt':
            return Cmp('>s', Bin('&', a, b, size), Const(0, size), size)
        if cc == 'le':
            return Cmp('<=s', Bin('&', a, b, size), Const(0, size), size)
        if cc == 'ge':
            return Cmp('>=s', Bin('&', a, b, size), Const(0, size), size)
        if cc == 'lt':
            return Cmp('<s', Bin('&', a, b, size), Const(0, size), size)
        return resolve_cond(ARM_INTEGER_CC.get(cc, '?'), f)
    if f.kind == 'add':
        total = Bin('+', a, b, size)
        carry = Cmp('<u', total, a, size)
        if cc == 'hs':
            return carry
        if cc == 'lo':
            return negate(carry)
        if cc == 'hi':
            return Logic('&&', carry, Cmp('!=', total, Const(0, size), size))
        if cc == 'ls':
            return Logic('||', negate(carry), Cmp('==', total, Const(0, size), size))
        if cc in ('ge', 'lt', 'gt', 'le'):
            neg = Un('neg', b, size)
            return Cmp({'ge': '>=s', 'lt': '<s', 'gt': '>s', 'le': '<=s'}[cc], a, neg, size)
        return resolve_cond(ARM_INTEGER_CC.get(cc, '?'), f)
    if f.kind == 'cmp':
        if cc in ('vs', 'vc'):
            diff = Bin('-', a, b, size)
            overflow = Cmp('<s', Bin('&', Bin('^', a, b, size), Bin('^', a, diff, size), size), Const(0, size), size)
            return overflow if cc == 'vs' else negate(overflow)
        return resolve_cond(ARM_INTEGER_CC.get(cc, '?'), f)
    return None


def resolve_cond(cc, f):
    """Turn condition code + flag source into a comparison expression."""
    if not isinstance(f, Flags):
        return None
    if cc.startswith('a.'):
        return resolve_arm(cc[2:], f)
    a, b, size = f.a, f.b, f.size
    zero = Const(0, size)
    if f.kind in ('cmp', 'sub'):
        table = {'e': '==', 'z': '==', 'ne': '!=', 'nz': '!=', 'l': '<s', 'nge': '<s', 'le': '<=s', 'ng': '<=s',
                 'g': '>s', 'nle': '>s', 'ge': '>=s', 'nl': '>=s', 'b': '<u', 'c': '<u', 'nae': '<u',
                 'be': '<=u', 'na': '<=u', 'a': '>u', 'nbe': '>u', 'ae': '>=u', 'nb': '>=u', 'nc': '>=u'}
        if cc in table:
            return Cmp(table[cc], a, b, size)
        if cc in ('s', 'ns'):
            return Cmp('<s' if cc == 's' else '>=s', Bin('-', a, b, size), zero, size)
        return None
    if f.kind in ('test', 'res', 'add'):
        value = Bin('&', a, b, size) if f.kind == 'test' else (Bin('+', a, b, size) if f.kind == 'add' else a)
        if f.kind == 'test' and a == b:
            value = a
        table = {'e': '==', 'z': '==', 'ne': '!=', 'nz': '!=', 's': '<s', 'l': '<s', 'ns': '>=s', 'ge': '>=s',
                 'le': '<=s', 'g': '>s', 'a': '!=', 'be': '=='}
        if f.kind == 'add' and cc in ('b', 'c', 'ae', 'nc', 'nb'):
            op = '<u' if cc in ('b', 'c') else '>=u'
            return Cmp(op, Bin('+', a, b, size), a, size)
        if cc in ('b', 'c') and f.kind != 'add':
            return Const(0, 1)
        if cc in ('ae', 'nc', 'nb') and f.kind != 'add':
            return Const(1, 1)
        if cc in table:
            return Cmp(table[cc], value, zero, size)
        return None
    if f.kind == 'fcmp':
        table = {'b': '<f', 'c': '<f', 'be': '<=f', 'a': '>f', 'ae': '>=f', 'nc': '>=f', 'e': '==f', 'z': '==f',
                 'ne': '!=f', 'nz': '!=f'}
        if cc in table:
            return Cmp(table[cc], a, b, size)
        if cc in ('p', 'np'):
            nan = Logic('||', Cmp('!=f', a, a, size), Cmp('!=f', b, b, size))
            return nan if cc == 'p' else negate(nan)
        return None
    if f.kind == 'fbits':
        # x87 status bits tested after fnstsw: a = ZF condition, b = PF condition.
        if cc in ('e', 'z'):
            return a
        if cc in ('ne', 'nz'):
            return negate(a)
        if cc in ('p', 'pe'):
            return b
        if cc in ('np', 'po'):
            return negate(b)
        return None
    if f.kind == 'bt':
        bit = Bin('&', Bin('>>u', a, b, size), Const(1, size), size)
        if cc in ('b', 'c'):
            return Cmp('!=', bit, Const(0, size), size)
        if cc in ('ae', 'nc', 'nb'):
            return Cmp('==', bit, Const(0, size), size)
    return None


def fold(op, x, y, size):
    m = mask(size)
    bits = 8 * size
    if op == '+':
        return (x + y) & m
    if op == '-':
        return (x - y) & m
    if op == '*':
        return (x * y) & m
    if op == '&':
        return x & y
    if op == '|':
        return x | y
    if op == '^':
        return x ^ y
    if op == '<<':
        return (x << (y % bits)) & m
    if op == '>>u':
        return x >> (y % bits)
    if op == '>>s':
        return (signed(x, size) >> (y % bits)) & m
    if op in ('/u', '%u') and y:
        return (x // y if op == '/u' else x % y) & m
    if op in ('/s', '%s') and y:
        a, b = signed(x, size), signed(y, size)
        q = abs(a) // abs(b) * (1 if (a < 0) == (b < 0) else -1)
        return (q if op == '/s' else a - q * b) & m
    return None


def simplify(e):
    """Bottom-up algebraic simplification (constant folding and common idioms)."""
    kids = e.kids()
    if kids:
        new = [simplify(k) for k in kids]
        if any(a is not b for a, b in zip(new, kids)):
            e = e.rebuild(new)
    if isinstance(e, Bin):
        a, b, op, size = e.a, e.b, e.op, e.size
        if is_const(a) and is_const(b):
            value = fold(op, a.value, b.value, size)
            if value is not None:
                return Const(value, size)
        if op in ('+', '|', '^', '*', '&') and is_const(a) and not is_const(b):
            a, b = b, a
            e = Bin(op, a, b, size)
        if op in ('+', '-', '|', '^', '<<', '>>u', '>>s') and is_const(b, 0):
            return a
        if op == '*' and is_const(b, 1):
            return a
        if op in ('*', '&') and is_const(b, 0):
            return Const(0, size)
        if op == '|' and is_const(b) and b.value == mask(size) and not a.has_call():
            return Const(mask(size), size)
        if op == '&' and is_const(b) and b.value == mask(size):
            return a
        if op in ('^', '-') and a == b and not a.has_call():
            return Const(0, size)
        if op == '&' and a == b:
            return a
        if op == '+' and is_const(b) and isinstance(a, Bin) and a.op in ('+', '-') and is_const(a.b):
            inner = a.b.value if a.op == '+' else (-a.b.value) & mask(size)
            return simplify(Bin('+', a.a, Const(inner + b.value, size), size))
        if op == '-' and is_const(b) and isinstance(a, Bin) and a.op in ('+', '-') and is_const(a.b):
            inner = a.b.value if a.op == '+' else (-a.b.value) & mask(size)
            return simplify(Bin('+', a.a, Const(inner - b.value, size), size))
        if op == '+' and is_const(b) and signed(b.value, size) < 0:
            return Bin('-', a, Const(-signed(b.value, size), size), size)
        if op == '-' and is_const(b) and signed(b.value, size) < 0 and size >= 4:
            return Bin('+', a, Const(-signed(b.value, size), size), size)
        if op == '+' and isinstance(b, Un) and b.op == 'neg':
            return Bin('-', a, b.a, size)
        if op == '*' and is_const(b) and b.value == mask(size):
            return Un('neg', a, size)
        if op == '<<' and is_const(b) and isinstance(a, Bin) and a.op == '<<' and is_const(a.b):
            return simplify(Bin('<<', a.a, Const(a.b.value + b.value, size), size))
        return e
    if isinstance(e, Un):
        if e.op == 'neg' and isinstance(e.a, Un) and e.a.op == 'neg':
            return e.a.a
        if e.op == 'not' and isinstance(e.a, Un) and e.a.op == 'not':
            return e.a.a
        if e.op in ('neg', 'not') and is_const(e.a):
            return Const((-e.a.value if e.op == 'neg' else ~e.a.value) & mask(e.size), e.size)
        return e
    if isinstance(e, Cast):
        a = e.a
        if e.kind in ('zext', 'sext', 'trunc') and a.size == e.size:
            return a
        if e.kind in ('zext', 'trunc') and is_const(a):
            return Const(a.value, e.size)
        if e.kind == 'sext' and is_const(a):
            return Const(signed(a.value, a.size), e.size)
        if e.kind == 'trunc' and isinstance(a, Cast) and a.kind in ('zext', 'sext'):
            if a.a.size == e.size:
                return a.a
            if a.a.size > e.size:
                return simplify(Cast('trunc', a.a, e.size))
        if e.kind == 'trunc' and isinstance(a, Cast) and a.kind == 'trunc':
            return simplify(Cast('trunc', a.a, e.size))
        if e.kind in ('zext', 'sext') and isinstance(a, Cast) and a.kind == e.kind:
            return simplify(Cast(e.kind, a.a, e.size))
        if e.kind == 'zext' and is_condition(a) and e.size >= 1:
            return Cast('zext', a, e.size) if not isinstance(a, Const) else Const(a.value, e.size)
        if e.kind == 'trunc' and isinstance(a, Bin) and a.op in ('+', '-', '*', '&', '|', '^') and \
                isinstance(a.a, Cast) and a.a.kind in ('zext', 'sext') and a.a.a.size == e.size and is_const(a.b):
            return simplify(Bin(a.op, a.a.a, Const(a.b.value, e.size), e.size))
        return e
    if isinstance(e, Cond):
        resolved = resolve_cond(e.cc, e.flags)
        return simplify(resolved) if resolved is not None else e
    if isinstance(e, Cmp):
        a, b = e.a, e.b
        if is_const(a) and not is_const(b):
            return simplify(Cmp(SWAP[e.op], b, a, e.operand_size))
        # (x - y) == 0  ->  x == y
        if e.op in ('==', '!=') and is_const(b, 0) and isinstance(a, Bin) and a.op == '-':
            return Cmp(e.op, a.a, a.b, e.operand_size)
        # (cond) != 0  ->  cond ; (cond) == 0 -> !cond  (bool produced by setcc / zext)
        inner = a.a if isinstance(a, Cast) and a.kind in ('zext', 'trunc') else a
        if e.op in ('==', '!=') and is_const(b, 0) and is_condition(inner):
            return inner if e.op == '!=' else negate(inner)
        if is_const(a) and is_const(b):
            x, y = a.value, b.value
            if e.op.endswith('s'):
                x, y = signed(x, e.operand_size), signed(y, e.operand_size)
            op = e.op.rstrip('su')
            value = {'==': x == y, '!=': x != y, '<': x < y, '<=': x <= y, '>': x > y, '>=': x >= y}.get(op)
            if value is not None and not e.op.endswith('f'):
                return Const(int(value), 1)
        # x <u 1  -> x == 0 ; x >=u 1 -> x != 0
        if e.op == '<u' and is_const(b, 1):
            return Cmp('==', a, Const(0, e.operand_size), e.operand_size)
        if e.op == '>=u' and is_const(b, 1):
            return Cmp('!=', a, Const(0, e.operand_size), e.operand_size)
        if e.op == '>u' and is_const(b, 0):
            return Cmp('!=', a, b, e.operand_size)
        if e.op == '<=u' and is_const(b, 0):
            return Cmp('==', a, b, e.operand_size)
        return e
    if isinstance(e, Logic) and e.op == 'not':
        return negate(e.a) if not isinstance(e.a, Logic) or e.a.op != 'not' else e.a.a
    if isinstance(e, Tern):
        if is_const(e.c):
            return e.a if e.c.value else e.b
        if e.a == e.b:
            return e.a
    return e
