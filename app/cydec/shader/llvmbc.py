"""LLVM bitcode reader for DXIL (LLVM 3.7 encoding), written from the LLVM bitcode format docs.

Two layers:
- `Bitstream`: abbreviations, blocks, records, BLOCKINFO, VBR/fixed/char6/array/blob.
- `parse_module`: the module block decoded into types, global values, constants, metadata
  and functions made of basic blocks of `Inst` objects, with relative operand ids resolved
  to absolute value ids and a result type computed for every value.
"""
import struct

from cytools_core import CyToolError

# Block ids
BLOCKINFO, MODULE, PARAMATTR, PARAMATTR_GROUP, CONSTANTS, FUNCTION = 0, 8, 9, 10, 11, 12
VALUE_SYMTAB, METADATA, METADATA_ATTACHMENT, TYPE_NEW, USELIST = 14, 15, 16, 17, 18

BINOPS = ['add', 'sub', 'mul', 'udiv', 'sdiv', 'urem', 'srem', 'shl', 'lshr', 'ashr', 'and', 'or', 'xor']
CASTS = ['trunc', 'zext', 'sext', 'fptoui', 'fptosi', 'uitofp', 'sitofp', 'fptrunc', 'fpext', 'ptrtoint',
         'inttoptr', 'bitcast', 'addrspacecast']
PREDICATES = {0: 'false', 1: 'oeq', 2: 'ogt', 3: 'oge', 4: 'olt', 5: 'ole', 6: 'one', 7: 'ord', 8: 'uno',
              9: 'ueq', 10: 'ugt', 11: 'uge', 12: 'ult', 13: 'ule', 14: 'une', 15: 'true',
              32: 'eq', 33: 'ne', 34: 'ugt', 35: 'uge', 36: 'ult', 37: 'ule', 38: 'sgt', 39: 'sge',
              40: 'slt', 41: 'sle'}


class BitcodeError(Exception):
    pass


# ---------------------------------------------------------------------- bitstream

class Abbrev:
    __slots__ = ('ops',)

    def __init__(self, ops):
        self.ops = ops  # list of (kind, value): ('lit', v) ('fixed', w) ('vbr', w) ('array', None) ('char6', None) ('blob', None)


class Block:
    __slots__ = ('id', 'items')

    def __init__(self, block_id):
        self.id = block_id
        self.items = []   # ('record', code, ops, blob) or ('block', Block)

    def records(self):
        return [item for item in self.items if item[0] == 'record']

    def blocks(self, block_id=None):
        return [item[1] for item in self.items if item[0] == 'block' and (block_id is None or item[1].id == block_id)]


class Bitstream:
    def __init__(self, data):
        self.data = data + b'\0' * 8
        self.size_bits = len(data) * 8
        self.pos = 0
        self.blockinfo = {}

    def read(self, width):
        if width == 0:
            return 0
        if self.pos + width > self.size_bits:
            raise BitcodeError('read past end of bitcode')
        byte = self.pos >> 3
        chunk = int.from_bytes(self.data[byte:byte + 9], 'little') >> (self.pos & 7)
        self.pos += width
        return chunk & ((1 << width) - 1)

    def vbr(self, width):
        result = 0
        shift = 0
        high = 1 << (width - 1)
        while True:
            piece = self.read(width)
            result |= (piece & (high - 1)) << shift
            if not piece & high:
                return result
            shift += width - 1
            if shift > 128:
                raise BitcodeError('VBR too long')

    def align32(self):
        self.pos = (self.pos + 31) & ~31

    def read_abbrev_op(self, kind, value):
        if kind == 'lit':
            return value
        if kind == 'fixed':
            return self.read(value)
        if kind == 'vbr':
            return self.vbr(value)
        if kind == 'char6':
            v = self.read(6)
            return ord('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._'[v])
        raise BitcodeError('bad abbrev op %s' % kind)

    def read_abbrev_record(self, abbrev):
        values = []
        blob = None
        ops = abbrev.ops
        index = 0
        while index < len(ops):
            kind, value = ops[index]
            if kind == 'array':
                length = self.vbr(6)
                element = ops[index + 1]
                for _ in range(length):
                    values.append(self.read_abbrev_op(*element))
                index += 2
                continue
            if kind == 'blob':
                length = self.vbr(6)
                self.align32()
                start = self.pos >> 3
                blob = bytes(self.data[start:start + length])
                self.pos += length * 8
                self.align32()
                index += 1
                continue
            values.append(self.read_abbrev_op(kind, value))
            index += 1
        return values[0], values[1:], blob

    def define_abbrev(self):
        count = self.vbr(5)
        ops = []
        index = 0
        while index < count:
            if self.read(1):
                ops.append(('lit', self.vbr(8)))
            else:
                encoding = self.read(3)
                if encoding == 1:
                    ops.append(('fixed', self.vbr(5)))
                elif encoding == 2:
                    ops.append(('vbr', self.vbr(5)))
                elif encoding == 3:
                    ops.append(('array', None))
                elif encoding == 4:
                    ops.append(('char6', None))
                elif encoding == 5:
                    ops.append(('blob', None))
                else:
                    raise BitcodeError('unknown abbrev encoding %d' % encoding)
            index += 1
        return Abbrev(ops)

    def read_block(self, block_id, abbrev_width):
        block = Block(block_id)
        abbrevs = list(self.blockinfo.get(block_id, []))
        current_info = None
        while True:
            if self.pos >= self.size_bits:
                return block
            code = self.read(abbrev_width)
            if code == 0:  # END_BLOCK
                self.align32()
                return block
            if code == 1:  # ENTER_SUBBLOCK
                sub_id = self.vbr(8)
                width = self.vbr(4)
                self.align32()
                length_words = self.read(32)
                end = self.pos + length_words * 32
                if sub_id == BLOCKINFO:
                    self.read_blockinfo(width)
                else:
                    child = self.read_block(sub_id, width)
                    block.items.append(('block', child))
                self.pos = end
                continue
            if code == 2:  # DEFINE_ABBREV
                abbrevs.append(self.define_abbrev())
                continue
            if code == 3:  # UNABBREV_RECORD
                record_code = self.vbr(6)
                count = self.vbr(6)
                ops = [self.vbr(6) for _ in range(count)]
                block.items.append(('record', record_code, ops, None))
                continue
            index = code - 4
            if index >= len(abbrevs):
                raise BitcodeError('undefined abbreviation %d in block %d' % (code, block_id))
            record_code, ops, blob = self.read_abbrev_record(abbrevs[index])
            block.items.append(('record', record_code, ops, blob))

    def read_blockinfo(self, width):
        current = None
        abbrevs = []
        while True:
            code = self.read(width)
            if code == 0:
                self.align32()
                return
            if code == 1:
                raise BitcodeError('nested block in BLOCKINFO')
            if code == 2:
                if current is None:
                    raise BitcodeError('abbrev before SETBID')
                self.blockinfo.setdefault(current, []).append(self.define_abbrev())
                continue
            if code == 3:
                record_code = self.vbr(6)
                count = self.vbr(6)
                ops = [self.vbr(6) for _ in range(count)]
                if record_code == 1:
                    current = ops[0]
                continue
            raise BitcodeError('abbreviated record in BLOCKINFO')


def read_top_level(data):
    if data[:4] == b'\xde\xc0\x17\x0b':  # wrapper header
        offset, size = struct.unpack_from('<II', data, 8)
        data = data[offset:offset + size]
    if data[:4] != b'BC\xc0\xde':
        raise BitcodeError('not LLVM bitcode')
    stream = Bitstream(data[4:])
    blocks = []
    while stream.pos + 4 <= stream.size_bits:
        code = stream.read(2)
        if code != 1:
            break
        block_id = stream.vbr(8)
        width = stream.vbr(4)
        stream.align32()
        length = stream.read(32)
        end = stream.pos + length * 32
        if block_id == BLOCKINFO:
            stream.read_blockinfo(width)
        else:
            blocks.append(stream.read_block(block_id, width))
        stream.pos = end
    return blocks


# ---------------------------------------------------------------------- types

class Type:
    __slots__ = ('kind', 'width', 'elements', 'count', 'pointee', 'ret', 'params', 'name', 'vararg', 'index')

    def __init__(self, kind, **fields):
        self.kind = kind
        self.width = fields.get('width', 0)
        self.elements = fields.get('elements', [])
        self.count = fields.get('count', 0)
        self.pointee = fields.get('pointee')
        self.ret = fields.get('ret')
        self.params = fields.get('params', [])
        self.name = fields.get('name', '')
        self.vararg = fields.get('vararg', False)
        self.index = -1

    def __repr__(self):
        if self.kind == 'int':
            return 'i%d' % self.width
        if self.kind in ('float', 'half', 'double', 'void', 'label', 'metadata'):
            return self.kind
        if self.kind == 'pointer':
            return '%r*' % (self.pointee,)
        if self.kind == 'array':
            return '[%d x %r]' % (self.count, self.elements[0])
        if self.kind == 'vector':
            return '<%d x %r>' % (self.count, self.elements[0])
        if self.kind == 'struct':
            return '%' + (self.name or 'anon')
        if self.kind == 'function':
            return '%r(%s)' % (self.ret, ', '.join(map(repr, self.params)))
        return self.kind

    @property
    def is_float(self):
        return self.kind in ('float', 'half', 'double')


def parse_types(block):
    types = []
    pending_name = ''
    for _, code, ops, blob in block.records():
        if code == 1:  # NUMENTRY
            continue
        t = None
        if code == 2:
            t = Type('void')
        elif code == 3:
            t = Type('float')
        elif code == 4:
            t = Type('double')
        elif code == 5:
            t = Type('label')
        elif code == 6:
            t = Type('struct', name=pending_name)
            pending_name = ''
        elif code == 7:
            t = Type('int', width=ops[0])
        elif code == 8:
            t = Type('pointer', pointee=ops[0])
        elif code == 10:
            t = Type('half')
        elif code == 11:
            t = Type('array', count=ops[0], elements=[ops[1]])
        elif code == 12:
            t = Type('vector', count=ops[0], elements=[ops[1]])
        elif code in (13, 14, 15, 17):
            t = Type('other')
        elif code == 16:
            t = Type('metadata')
        elif code == 18:
            t = Type('struct', elements=list(ops[1:]))
        elif code == 19:
            pending_name = ''.join(chr(c) for c in ops)
            continue
        elif code == 20:
            t = Type('struct', elements=list(ops[1:]), name=pending_name)
            pending_name = ''
        elif code == 21:
            t = Type('function', vararg=bool(ops[0]), ret=ops[1], params=list(ops[2:]))
        elif code == 9:
            t = Type('function', vararg=bool(ops[0]), ret=ops[2], params=list(ops[3:]))
        else:
            t = Type('other')
        t.index = len(types)
        types.append(t)
    # Resolve indices to Type objects.
    for t in types:
        if t.pointee is not None and isinstance(t.pointee, int):
            t.pointee = types[t.pointee]
        if t.ret is not None and isinstance(t.ret, int):
            t.ret = types[t.ret]
        t.params = [types[p] for p in t.params]
        t.elements = [types[e] for e in t.elements]
    return types


# ---------------------------------------------------------------------- values

class Value:
    __slots__ = ('id', 'kind', 'type', 'name', 'data')

    def __init__(self, value_id, kind, value_type, data=None, name=''):
        self.id = value_id
        self.kind = kind          # 'global', 'function', 'const', 'arg', 'inst'
        self.type = value_type
        self.name = name
        self.data = data          # const payload, Function, or Inst

    def __repr__(self):
        return '<%s %s %r>' % (self.kind, self.id, self.data if self.kind == 'const' else self.name)


class Const:
    __slots__ = ('kind', 'value', 'items')

    def __init__(self, kind, value=None, items=None):
        self.kind = kind          # 'int', 'float', 'null', 'undef', 'aggregate', 'data', 'string', 'expr'
        self.value = value
        self.items = items or []

    def __repr__(self):
        return '%s:%r' % (self.kind, self.value if self.kind != 'aggregate' else self.items)


class Inst:
    __slots__ = ('op', 'type', 'args', 'extra', 'value_id', 'block')

    def __init__(self, op, inst_type, args, extra=None, value_id=None):
        self.op = op              # e.g. 'binop', 'cast', 'cmp', 'call', 'br', 'phi', ...
        self.type = inst_type     # result Type (void for no value)
        self.args = args          # absolute value ids (or block indices for branches)
        self.extra = extra or {}
        self.value_id = value_id
        self.block = None

    def __repr__(self):
        return '%s%s %s %s' % ('%%%s = ' % self.value_id if self.value_id is not None else '', self.op, self.args, self.extra)


class Function:
    def __init__(self, value, fn_type, is_proto):
        self.value = value
        self.type = fn_type
        self.is_proto = is_proto
        self.args = []
        self.blocks = []          # list of lists of Inst
        self.names = {}
        self.block_names = {}

    @property
    def name(self):
        return self.value.name


class Module:
    def __init__(self):
        self.types = []
        self.values = []
        self.functions = []
        self.metadata = {}        # id -> ('string', s) | ('value', value_id) | ('node', [ids or None])
        self.named_metadata = {}  # name -> [md ids]
        self.triple = ''

    def value(self, value_id):
        return self.values[value_id] if 0 <= value_id < len(self.values) else None


def decode_signed(v):
    return -(v >> 1) if v & 1 else v >> 1


def float_from_bits(bits, value_type):
    if value_type.kind == 'float':
        return struct.unpack('<f', struct.pack('<I', bits & 0xffffffff))[0]
    if value_type.kind == 'double':
        return struct.unpack('<d', struct.pack('<Q', bits & 0xffffffffffffffff))[0]
    if value_type.kind == 'half':
        return struct.unpack('<e', struct.pack('<H', bits & 0xffff))[0]
    return float(bits)


def parse_constants(block, module, values):
    current = None
    for _, code, ops, blob in block.records():
        if code == 1:
            current = module.types[ops[0]]
            continue
        const = None
        if code == 2:
            const = Const('null')
        elif code == 3:
            const = Const('undef')
        elif code == 4:
            const = Const('int', decode_signed(ops[0]))
        elif code == 5:
            const = Const('int', decode_signed(ops[0]))
        elif code == 6:
            const = Const('float', float_from_bits(ops[0], current))
        elif code == 7:
            const = Const('aggregate', items=list(ops))
        elif code in (8, 9):
            const = Const('string', bytes(ops).decode('latin-1'))
        elif code == 22:
            if current.kind in ('array', 'vector') and current.elements[0].is_float:
                const = Const('aggregate_values', items=[float_from_bits(o, current.elements[0]) for o in ops])
            else:
                const = Const('aggregate_values', items=list(ops))
        elif code in (12, 20):  # CE_GEP / CE_INBOUNDS_GEP: [n x (ty, val)] possibly with leading pointee type
            items = list(ops)
            if len(items) % 2 == 1:
                items = items[1:]
            const = Const('gep', items=[items[i + 1] for i in range(0, len(items), 2)])
        elif code == 11:  # CE_CAST [opc, opty, opval]
            const = Const('cast', value=CASTS[ops[0]] if ops[0] < len(CASTS) else 'cast', items=[ops[2]])
        else:
            const = Const('expr', value=code, items=list(ops))
        value = Value(len(values), 'const', current, const)
        values.append(value)


def parse_metadata(block, module):
    next_id = len(module.metadata)
    pending_name = None
    for _, code, ops, blob in block.records():
        if code == 1:  # STRING
            module.metadata[next_id] = ('string', bytes(ops).decode('utf-8', 'replace'))
            next_id += 1
        elif code == 2:  # VALUE [ty, val]
            module.metadata[next_id] = ('value', ops[1])
            next_id += 1
        elif code in (3, 5, 8):  # NODE, DISTINCT_NODE, OLD_NODE
            if code == 8:
                items = [ops[i + 1] if module.types[ops[i]].kind != 'metadata' else ops[i + 1]
                         for i in range(0, len(ops), 2)]
                module.metadata[next_id] = ('node', items)
            else:
                module.metadata[next_id] = ('node', [o - 1 if o else None for o in ops])
            next_id += 1
        elif code == 4:  # NAME
            pending_name = ''.join(chr(c) for c in ops)
        elif code == 10:  # NAMED_NODE
            if pending_name is not None:
                module.named_metadata[pending_name] = list(ops)
            pending_name = None
        elif code == 6:  # KIND
            continue
        elif code == 35:  # STRINGS (bulk), newer LLVM
            count, offset = ops[0], ops[1]
            next_id = _bulk_strings(module, blob, count, offset, next_id)
        elif code in (7, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 36, 37):
            module.metadata[next_id] = ('other', code)
            next_id += 1


def _bulk_strings(module, blob, count, offset, next_id):
    stream = Bitstream(blob[:offset])
    lengths = [stream.vbr(6) for _ in range(count)]
    position = offset
    for length in lengths:
        module.metadata[next_id] = ('string', blob[position:position + length].decode('utf-8', 'replace'))
        position += length
        next_id += 1
    return next_id


def parse_symtab(block, names, block_names=None):
    for _, code, ops, blob in block.records():
        if code == 1:
            names[ops[0]] = ''.join(chr(c) for c in ops[1:])
        elif code == 2 and block_names is not None:
            block_names[ops[0]] = ''.join(chr(c) for c in ops[1:])
        elif code == 3:
            names[ops[0]] = ''.join(chr(c) for c in ops[2:])


def parse_module(data):
    blocks = read_top_level(data)
    top = next((b for b in blocks if b.id == MODULE), None)
    if top is None:
        raise BitcodeError('no module block')
    module = Module()
    values = module.values
    function_bodies = []
    for item in top.items:
        if item[0] == 'block':
            block = item[1]
            if block.id == TYPE_NEW:
                module.types = parse_types(block)
            elif block.id == CONSTANTS:
                parse_constants(block, module, values)
            elif block.id == METADATA:
                parse_metadata(block, module)
            elif block.id == VALUE_SYMTAB:
                names = {}
                parse_symtab(block, names)
                for value_id, name in names.items():
                    if value_id < len(values):
                        values[value_id].name = name
            elif block.id == FUNCTION:
                function_bodies.append(block)
            continue
        _, code, ops, blob = item
        if code == 2:
            module.triple = ''.join(chr(c) for c in ops)
        elif code == 7:  # GLOBALVAR [pointer type, isconst, initid, linkage, alignment, section, ...]
            explicit = len(ops) > 1 and ops[1] & 2
            value_type = module.types[ops[0]]
            if explicit:
                value_type = Type('pointer', pointee=value_type)
            values.append(Value(len(values), 'global', value_type, {'init': ops[2] - 1 if ops[2] else None}))
        elif code == 8:  # FUNCTION [type, cc, isproto, linkage, ...]
            fn_type = module.types[ops[0]]
            if fn_type.kind == 'pointer':
                fn_type = fn_type.pointee
            value = Value(len(values), 'function', Type('pointer', pointee=fn_type))
            function = Function(value, fn_type, bool(ops[2]))
            value.data = function
            values.append(value)
            module.functions.append(function)
        elif code == 14:  # ALIAS
            values.append(Value(len(values), 'global', module.types[ops[0]]))
    # Function bodies appear in the same order as the non-prototype FUNCTION records.
    bodies = iter(function_bodies)
    for function in module.functions:
        if not function.is_proto:
            body = next(bodies, None)
            if body is not None:
                parse_function(body, module, function)
    return module


def parse_function(block, module, function):
    values = list(module.values)  # module-level values stay at their ids
    base_count = len(values)
    for param_type in function.type.params:
        value = Value(len(values), 'arg', param_type)
        values.append(value)
        function.args.append(value)
    blocks = []
    current = []
    names = {}
    block_names = {}

    def new_block():
        nonlocal current
        current = []
        blocks.append(current)

    def value_type(value_id):
        if 0 <= value_id < len(values):
            return values[value_id].type
        return None

    for item in block.items:
        if item[0] == 'block':
            sub = item[1]
            if sub.id == CONSTANTS:
                parse_constants(sub, module, values)
            elif sub.id == VALUE_SYMTAB:
                parse_symtab(sub, names, block_names)
            elif sub.id == METADATA:
                parse_metadata(sub, module)
            continue
        _, code, ops, blob = item
        if code == 1:  # DECLAREBLOCKS
            blocks.clear()
            for _ in range(ops[0]):
                blocks.append([])
            block_index = 0
            current = blocks[0]
            continue
        if code in (33, 35):  # debug locations
            continue
        next_id = len(values)
        position = [0]

        def take():
            value = ops[position[0]]
            position[0] += 1
            return value

        def rel():
            return next_id - take()

        def rel_typed():
            vid = next_id - take()
            if vid >= next_id:  # forward reference carries its type
                forward_type = module.types[take()]
                while len(values) <= vid:
                    values.append(Value(len(values), 'forward', None))
                values[vid].type = forward_type
            return vid

        inst = None
        if code == 2:  # BINOP
            a = rel_typed()
            b = rel()
            opcode = take()
            flags = ops[position[0]] if position[0] < len(ops) else 0
            t = value_type(a)
            inst = Inst('binop', t, [a, b], {'op': BINOPS[opcode] if opcode < len(BINOPS) else str(opcode),
                                              'float': bool(t and (t.is_float or (t.kind == 'vector' and t.elements[0].is_float))),
                                              'flags': flags})
        elif code == 3:  # CAST
            a = rel_typed()
            dest = module.types[take()]
            opcode = take()
            inst = Inst('cast', dest, [a], {'op': CASTS[opcode] if opcode < len(CASTS) else str(opcode)})
        elif code in (5, 29):  # SELECT / VSELECT
            t = rel_typed()
            f = rel()
            c = rel_typed() if code == 29 else rel()
            inst = Inst('select', value_type(t), [c, t, f])
        elif code == 6:  # EXTRACTELT
            vec = rel_typed()
            index = rel_typed()
            vt = value_type(vec)
            inst = Inst('extractelement', vt.elements[0] if vt and vt.elements else None, [vec, index])
        elif code == 7:  # INSERTELT
            vec = rel_typed()
            elt = rel()
            index = rel_typed()
            inst = Inst('insertelement', value_type(vec), [vec, elt, index])
        elif code == 8:  # SHUFFLEVEC
            a = rel_typed()
            b = rel()
            mask = rel_typed()
            inst = Inst('shufflevector', value_type(a), [a, b, mask])
        elif code in (9, 28):  # CMP / CMP2
            a = rel_typed()
            b = rel()
            predicate = take()
            inst = Inst('cmp', Type('int', width=1), [a, b], {'pred': PREDICATES.get(predicate, str(predicate)),
                                                              'float': predicate < 32})
        elif code == 10:  # RET
            args = [rel_typed()] if ops else []
            inst = Inst('ret', Type('void'), args)
        elif code == 11:  # BR
            if len(ops) == 1:
                inst = Inst('br', Type('void'), [], {'targets': [ops[0]]})
            else:
                cond = next_id - ops[2]
                inst = Inst('br', Type('void'), [cond], {'targets': [ops[0], ops[1]]})
        elif code == 12:  # SWITCH [opty, cond, default, (value id, bb)...]
            cond = next_id - ops[1]
            default = ops[2]
            cases = []
            for i in range(3, len(ops) - 1, 2):
                cases.append((ops[i], ops[i + 1]))
            inst = Inst('switch', Type('void'), [cond], {'default': default, 'cases': cases})
        elif code == 15:
            inst = Inst('unreachable', Type('void'), [])
        elif code == 16:  # PHI [ty, (signed rel val, bb)...]
            t = module.types[ops[0]]
            incoming = []
            for i in range(1, len(ops) - 1, 2):
                vid = next_id - decode_signed(ops[i])
                incoming.append((vid, ops[i + 1]))
            inst = Inst('phi', t, [v for v, _ in incoming], {'incoming': incoming})
        elif code == 19:  # ALLOCA [instty, opty, op, align]
            t = module.types[ops[0]]
            inst = Inst('alloca', Type('pointer', pointee=t), [], {'allocated': t, 'size': ops[2]})
        elif code == 20:  # LOAD [op, (ty), align, vol]
            ptr = rel_typed()
            remaining = len(ops) - position[0]
            if remaining >= 3:
                t = module.types[take()]
            else:
                pt = value_type(ptr)
                t = pt.pointee if pt is not None and pt.kind == 'pointer' else None
            inst = Inst('load', t, [ptr])
        elif code in (24, 44):  # STORE_OLD / STORE [ptr(ty), val(ty), align, vol]
            ptr = rel_typed()
            val = rel_typed() if code == 44 else rel()
            inst = Inst('store', Type('void'), [ptr, val])
        elif code == 26:  # EXTRACTVAL
            agg = rel_typed()
            indices = list(ops[position[0]:])
            t = value_type(agg)
            for index in indices:
                if t is None:
                    break
                t = t.elements[index] if t.kind == 'struct' else (t.elements[0] if t.elements else None)
            inst = Inst('extractvalue', t, [agg], {'indices': indices})
        elif code == 27:  # INSERTVAL
            agg = rel_typed()
            val = rel_typed()
            inst = Inst('insertvalue', value_type(agg), [agg, val], {'indices': list(ops[position[0]:])})
        elif code in (4, 30, 43):  # GEP
            inbounds = True
            source_type = None
            if code == 43:
                inbounds = bool(take())
                source_type = module.types[take()]
            operands = []
            while position[0] < len(ops):
                operands.append(rel_typed())
            pt = value_type(operands[0])
            t = source_type or (pt.pointee if pt is not None and pt.kind == 'pointer' else None)
            for index_id in operands[2:]:
                if t is None:
                    break
                if t.kind == 'struct':
                    index_value = values[index_id].data.value if values[index_id].kind == 'const' else 0
                    t = t.elements[index_value] if isinstance(index_value, int) and index_value < len(t.elements) else None
                elif t.elements:
                    t = t.elements[0]
            inst = Inst('gep', Type('pointer', pointee=t), operands, {'inbounds': inbounds})
        elif code == 34:  # CALL [paramattrs, cc, (fmf), (fnty), fnid, args...]
            take()
            cc = take()
            if cc & (1 << 17):
                take()  # fast math flags
            explicit = None
            if cc & (1 << 15):
                explicit = module.types[take()]
            callee = rel_typed()
            ct = value_type(callee)
            fn_type = explicit or (ct.pointee if ct is not None and ct.kind == 'pointer' else ct)
            args = []
            for param in (fn_type.params if fn_type else []):
                if param.kind == 'label':
                    args.append(('label', take()))
                else:
                    args.append(rel())
            while position[0] < len(ops):
                args.append(rel_typed())
            inst = Inst('call', fn_type.ret if fn_type else Type('void'), [callee] + [a for a in args if not isinstance(a, tuple)],
                        {'callee': callee})
        elif code == 36:
            inst = Inst('fence', Type('void'), [])
        elif code in (38, 46, 37):
            ptr = rel_typed()
            inst = Inst('atomic', value_type(rel_typed()) if code == 38 else None, [ptr], {'code': code})
        else:
            inst = Inst('unknown%d' % code, Type('void'), [])
        produces = inst.type is not None and inst.type.kind != 'void' and inst.op not in ('store', 'br', 'switch', 'ret', 'unreachable', 'fence')
        if produces:
            inst.value_id = next_id
            if next_id < len(values) and values[next_id].kind == 'forward':
                values[next_id].kind = 'inst'
                values[next_id].type = inst.type
                values[next_id].data = inst
            else:
                values.append(Value(next_id, 'inst', inst.type, inst))
        inst.block = len([b for b in blocks if b is not current]) if False else None
        current.append(inst)
        if inst.op in ('br', 'switch', 'ret', 'unreachable'):
            # Move on to the next declared block.
            index = blocks.index(current)
            if index + 1 < len(blocks):
                current = blocks[index + 1]
    for value_id, name in names.items():
        if value_id < len(values):
            values[value_id].name = name
    for index, block_insts in enumerate(blocks):
        for inst in block_insts:
            inst.block = index
    function.blocks = blocks
    function.values = values
    function.block_names = block_names
    return function


# ---------------------------------------------------------------------- metadata helpers

def md_node(module, md_id):
    entry = module.metadata.get(md_id)
    return entry[1] if entry and entry[0] == 'node' else None


def md_string(module, md_id):
    entry = module.metadata.get(md_id)
    return entry[1] if entry and entry[0] == 'string' else None


def md_value(module, md_id):
    """Module-level value of a VALUE metadata: (Value) or None."""
    entry = module.metadata.get(md_id)
    if entry and entry[0] == 'value':
        return module.value(entry[1])
    return None


def md_int(module, md_id):
    value = md_value(module, md_id)
    if value is not None and value.kind == 'const' and value.data.kind == 'int':
        return value.data.value
    if value is not None and value.kind == 'const' and value.data.kind == 'null':
        return 0
    return None
