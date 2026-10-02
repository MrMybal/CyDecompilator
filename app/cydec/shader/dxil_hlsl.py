"""DXIL (Shader Model 6) to HLSL.

Input: a DXBC-style container. The DXIL chunk holds the program bitcode; the STAT chunk
(when present) holds the same module with full reflection metadata, which gives resource
names, cbuffer and structure field names with byte offsets, and signatures.

Pipeline: bitcode (llvmbc) -> resources/signatures/annotations -> per-function CFG
analysis (dominators, post-dominators, natural loops) -> structured emission (if/else,
while, switch, break/continue) -> expressions with single-use inlining, phi variables,
dx.op intrinsics mapped back to HLSL (Sample, Load, cbuffer fields, input/output
semantics, thread ids, atomics, barriers, discard...).

All temporaries are declared at the top of the function, so the result stays valid HLSL
whatever the control-flow nesting.
"""
import re
import struct

from cytools_core import CyToolError

from . import llvmbc
from .dxbc import chunks
from .spirv import format_float

SWIZZLE = 'xyzw'
RESOURCE_CLASSES = ('srv', 'uav', 'cbv', 'sampler')
KINDS = {1: 'Texture1D', 2: 'Texture2D', 3: 'Texture2DMS', 4: 'Texture3D', 5: 'TextureCube', 6: 'Texture1DArray',
         7: 'Texture2DArray', 8: 'Texture2DMSArray', 9: 'TextureCubeArray', 10: 'Buffer', 11: 'ByteAddressBuffer',
         12: 'StructuredBuffer', 13: 'cbuffer', 14: 'SamplerState', 15: 'tbuffer', 16: 'RaytracingAccelerationStructure',
         17: 'FeedbackTexture2D', 18: 'FeedbackTexture2DArray'}
COORDS = {1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 2, 7: 3, 8: 3, 9: 4, 10: 1, 11: 1, 12: 1}
COMP_TYPES = {1: 'bool', 2: 'min16int', 3: 'min16uint', 4: 'int', 5: 'uint', 6: 'int64_t', 7: 'uint64_t',
              8: 'half', 9: 'float', 10: 'double', 11: 'snorm half', 12: 'unorm half', 13: 'snorm float',
              14: 'unorm float', 15: 'snorm double', 16: 'unorm double'}
SEMANTIC_KINDS = {1: 'SV_VertexID', 2: 'SV_InstanceID', 3: 'SV_Position', 4: 'SV_RenderTargetArrayIndex',
                  5: 'SV_ViewportArrayIndex', 6: 'SV_ClipDistance', 7: 'SV_CullDistance',
                  8: 'SV_OutputControlPointID', 9: 'SV_DomainLocation', 10: 'SV_PrimitiveID',
                  11: 'SV_GSInstanceID', 12: 'SV_SampleIndex', 13: 'SV_IsFrontFace', 14: 'SV_Coverage',
                  15: 'SV_InnerCoverage', 16: 'SV_Target', 17: 'SV_Depth', 18: 'SV_DepthLessEqual',
                  19: 'SV_DepthGreaterEqual', 20: 'SV_StencilRef', 21: 'SV_DispatchThreadID', 22: 'SV_GroupID',
                  23: 'SV_GroupIndex', 24: 'SV_GroupThreadID', 25: 'SV_TessFactor', 26: 'SV_InsideTessFactor',
                  27: 'SV_ViewID', 28: 'SV_Barycentrics', 29: 'SV_ShadingRate', 30: 'SV_CullPrimitive'}

UNARY = {6: 'abs', 7: 'saturate', 8: 'isnan', 9: 'isinf', 10: 'isfinite', 11: 'isnormal', 12: 'cos', 13: 'sin',
         14: 'tan', 15: 'acos', 16: 'asin', 17: 'atan', 18: 'cosh', 19: 'sinh', 20: 'tanh', 21: 'exp2', 22: 'frac',
         23: 'log2', 24: 'sqrt', 25: 'rsqrt', 26: 'round', 27: 'floor', 28: 'ceil', 29: 'trunc', 30: 'reversebits',
         31: 'countbits', 32: 'firstbitlow', 33: 'firstbithigh', 34: 'firstbithigh', 83: 'ddx_coarse',
         84: 'ddy_coarse', 85: 'ddx_fine', 86: 'ddy_fine', 130: 'f32tof16', 131: 'f16tof32',
         124: 'asfloat16', 125: 'asint16', 126: 'asfloat', 127: 'asint', 128: 'asdouble', 129: 'asint64'}
BINARY = {35: 'max', 36: 'min', 37: 'max', 38: 'min', 39: 'max', 40: 'min'}
TERTIARY = {46: 'mad', 47: 'fma', 48: 'mad', 49: 'mad', 50: 'msad4', 51: 'ibfe', 52: 'ubfe'}
SYSTEM_VALUES = {93: ('DTid', 'uint3', 'SV_DispatchThreadID'), 94: ('Gid', 'uint3', 'SV_GroupID'),
                 95: ('GTid', 'uint3', 'SV_GroupThreadID'), 96: ('GI', 'uint', 'SV_GroupIndex'),
                 90: ('sampleIndex', 'uint', 'SV_SampleIndex'), 91: ('coverage', 'uint', 'SV_Coverage'),
                 92: ('innerCoverage', 'uint', 'SV_InnerCoverage'), 100: ('gsInstance', 'uint', 'SV_GSInstanceID'),
                 107: ('controlPoint', 'uint', 'SV_OutputControlPointID'), 108: ('primitive', 'uint', 'SV_PrimitiveID'),
                 138: ('viewId', 'uint', 'SV_ViewID')}
WAVE = {110: 'WaveIsFirstLane', 111: 'WaveGetLaneIndex', 112: 'WaveGetLaneCount', 113: 'WaveActiveAnyTrue',
        114: 'WaveActiveAllTrue', 115: 'WaveActiveAllEqual', 116: 'WaveActiveBallot', 117: 'WaveReadLaneAt',
        118: 'WaveReadLaneFirst', 135: 'WaveActiveCountBits', 136: 'WavePrefixCountBits', 122: 'QuadReadLaneAt'}
SIDE_EFFECTS = {5, 67, 69, 70, 78, 79, 80, 82, 97, 98, 99, 106, 140, 141}
ATOMIC_OPS = {0: 'InterlockedAdd', 1: 'InterlockedAnd', 2: 'InterlockedOr', 3: 'InterlockedXor', 4: 'InterlockedMin',
              5: 'InterlockedMax', 6: 'InterlockedMin', 7: 'InterlockedMax', 8: 'InterlockedExchange'}
BIN_TEXT = {'add': ('+', 4), 'sub': ('-', 4), 'mul': ('*', 3), 'udiv': ('/', 3), 'sdiv': ('/', 3), 'urem': ('%', 3),
            'srem': ('%', 3), 'shl': ('<<', 5), 'lshr': ('>>', 5), 'ashr': ('>>', 5), 'and': ('&', 8),
            'or': ('|', 10), 'xor': ('^', 9)}
CMP_TEXT = {'oeq': '==', 'ueq': '==', 'one': '!=', 'une': '!=', 'ogt': '>', 'ugt': '>', 'oge': '>=', 'uge': '>=',
            'olt': '<', 'ult': '<', 'ole': '<=', 'ule': '<=', 'eq': '==', 'ne': '!=', 'sgt': '>', 'sge': '>=',
            'slt': '<', 'sle': '<='}
INVERSE = {'==': '!=', '!=': '==', '<': '>=', '>=': '<', '>': '<=', '<=': '>'}
UNSIGNED = {'udiv', 'urem', 'lshr'}


class E:
    """An expression: text plus precedence (0 atom, 1 unary, 3 mul, 4 add, 5 shift, 6 rel, 7 eq ... 13 ternary)."""
    __slots__ = ('text', 'prec', 'cmp')

    def __init__(self, text, prec=0, cmp=None):
        self.text, self.prec, self.cmp = text, prec, cmp


def wrap(expr, prec, right=False):
    if expr.prec > prec or (right and expr.prec == prec and prec > 2):
        return '(%s)' % expr.text
    return expr.text


# ---------------------------------------------------------------------- container / metadata

def bitcode_of(blob):
    offset, size = struct.unpack_from('<II', blob, 16)
    return blob[8 + offset:8 + offset + size]


class Reflection:
    def __init__(self, module):
        self.module = module
        self.resources = {name: {} for name in RESOURCE_CLASSES}
        self.inputs, self.outputs, self.patch = {}, {}, {}
        self.kind = 'ps'
        self.model = (6, 0)
        self.numthreads = None
        self.entry_name = 'main'
        self.annotations = {}
        self._parse()

    def node(self, md_id):
        return llvmbc.md_node(self.module, md_id) if md_id is not None else None

    def string(self, md_id):
        return llvmbc.md_string(self.module, md_id) if md_id is not None else None

    def int(self, md_id):
        return llvmbc.md_int(self.module, md_id) if md_id is not None else None

    def _parse(self):
        named = self.module.named_metadata
        for md in named.get('dx.shaderModel', []):
            node = self.node(md)
            if node:
                self.kind = self.string(node[0]) or 'ps'
                self.model = (self.int(node[1]) or 6, self.int(node[2]) or 0)
        for md in named.get('dx.typeAnnotations', []):
            node = self.node(md)
            if not node or self.int(node[0]) != 0:
                continue
            for index in range(1, len(node) - 1, 2):
                value = llvmbc.md_value(self.module, node[index])
                annotation = self.node(node[index + 1])
                if value is None or not annotation:
                    continue
                fields = []
                for field_md in annotation[1:]:
                    tags = self.node(field_md) or []
                    field = {}
                    for t in range(0, len(tags) - 1, 2):
                        tag = self.int(tags[t])
                        if tag == 6:
                            field['name'] = self.string(tags[t + 1])
                        elif tag == 3:
                            field['offset'] = self.int(tags[t + 1]) or 0
                        elif tag == 7:
                            field['comp'] = self.int(tags[t + 1])
                        elif tag == 2:
                            matrix = self.node(tags[t + 1]) or []
                            field['matrix'] = (self.int(matrix[0]) if matrix else 4, self.int(matrix[1]) if len(matrix) > 1 else 4)
                            field['orientation'] = self.int(matrix[2]) if len(matrix) > 2 else 2
                    fields.append(field)
                self.annotations[value.type.index] = {'size': self.int(annotation[0]) or 0, 'fields': fields,
                                                     'type': value.type}
        for md in named.get('dx.resources', []):
            self._resources(self.node(md))
        for md in named.get('dx.entryPoints', []):
            entry = self.node(md)
            if not entry:
                continue
            self.entry_name = self.string(entry[1]) or 'main'
            signatures = self.node(entry[2]) if len(entry) > 2 else None
            if signatures:
                for target, md_list in zip((self.inputs, self.outputs, self.patch), signatures):
                    for element_md in self.node(md_list) or []:
                        element = self._element(self.node(element_md))
                        if element:
                            target[element['id']] = element
            if len(entry) > 3 and not any(self.resources.values()):
                self._resources(self.node(entry[3]))
            properties = self.node(entry[4]) if len(entry) > 4 else None
            if properties:
                for index in range(0, len(properties) - 1, 2):
                    if self.int(properties[index]) == 4:
                        values = self.node(properties[index + 1]) or []
                        self.numthreads = tuple(self.int(v) or 1 for v in values[:3])
            break

    def _resources(self, node):
        if not node:
            return
        for class_index, list_md in enumerate(node[:4]):
            for record_md in self.node(list_md) or []:
                record = self.node(record_md)
                if not record:
                    continue
                value = llvmbc.md_value(self.module, record[1])
                resource_type = value.type if value is not None else None
                while resource_type is not None and resource_type.kind in ('pointer', 'array'):
                    resource_type = resource_type.pointee if resource_type.kind == 'pointer' else resource_type.elements[0]
                item = {'class': RESOURCE_CLASSES[class_index], 'id': self.int(record[0]) or 0,
                        'name': self.string(record[2]) or '', 'space': self.int(record[3]) or 0,
                        'lower': self.int(record[4]) or 0, 'range': self.int(record[5]),
                        'type': resource_type}
                if class_index in (0, 1):
                    item['kind'] = self.int(record[6]) or 0
                    extra = self.node(record[-1]) if record[-1] is not None else None
                    if extra:
                        for t in range(0, len(extra) - 1, 2):
                            tag = self.int(extra[t])
                            if tag == 0:
                                item['comp'] = self.int(extra[t + 1])
                            elif tag == 1:
                                item['stride'] = self.int(extra[t + 1])
                    if class_index == 1:
                        item['counter'] = bool(self.int(record[8])) if len(record) > 8 else False
                elif class_index == 2:
                    item['kind'] = 13
                    item['size'] = self.int(record[6]) or 0
                else:
                    item['kind'] = 14
                    item['comparison'] = (self.int(record[6]) or 0) == 1
                self.resources[RESOURCE_CLASSES[class_index]][item['id']] = item

    def _element(self, node):
        if not node:
            return None
        indices = [self.int(i) or 0 for i in (self.node(node[4]) or [])]
        element = {'id': self.int(node[0]) or 0, 'name': self.string(node[1]) or 'ATTR',
                   'comp': self.int(node[2]) or 9, 'kind': self.int(node[3]) or 0, 'indices': indices or [0],
                   'interp': self.int(node[5]) or 0, 'rows': self.int(node[6]) or 1, 'cols': self.int(node[7]) or 1}
        name = element['name']
        if element['kind'] and not name.upper().startswith('SV_'):
            name = SEMANTIC_KINDS.get(element['kind'], name)
        element['semantic'] = name
        index = element['indices'][0]
        element['field'] = name if name.upper().startswith('SV_') and not index else '%s%d' % (name, index)
        return element

    def fields_of(self, struct_type):
        """Annotated fields (name, offset, hlsl type) of an LLVM struct type, or []."""
        if struct_type is None:
            return []
        annotation = self.annotations.get(struct_type.index)
        if annotation is None:
            return []
        result = []
        for index, field in enumerate(annotation['fields']):
            member = struct_type.elements[index] if index < len(struct_type.elements) else None
            result.append({'name': field.get('name') or 'field%d' % index, 'offset': field.get('offset', 0),
                           'type': self.hlsl_field_type(member, field), 'llvm': member,
                           'rowMajor': field.get('orientation') == 1})
        return result

    def hlsl_field_type(self, member, field):
        base = COMP_TYPES.get(field.get('comp'), 'float')
        if 'matrix' in field:
            rows, cols = field['matrix']
            return '%s%dx%d' % (base, rows, cols)
        dims = ''
        t = member
        while t is not None and t.kind == 'array':
            dims += '[%d]' % t.count
            t = t.elements[0]
        if t is not None and t.kind == 'vector':
            return '%s%d%s' % (base, t.count, dims)
        if t is not None and t.kind == 'struct':
            name = t.name.split('.')[-1] if t.name else 'Struct'
            return name + dims
        return base + dims


# ---------------------------------------------------------------------- CFG

def successors(block):
    term = block[-1] if block else None
    if term is None:
        return []
    if term.op == 'br':
        return list(term.extra['targets'])
    if term.op == 'switch':
        return [term.extra['default']] + [bb for _, bb in term.extra['cases']]
    return []


def dominators(count, succ, entry=0):
    preds = [[] for _ in range(count)]
    for b in range(count):
        for s in succ[b]:
            preds[s].append(b)
    order = []
    seen = set()

    def dfs(b):
        stack = [(b, iter(succ[b]))]
        seen.add(b)
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                stack.pop()
                order.append(node)
            elif nxt not in seen:
                seen.add(nxt)
                stack.append((nxt, iter(succ[nxt])))
    dfs(entry)
    rpo = list(reversed(order))
    index = {b: i for i, b in enumerate(rpo)}
    idom = {entry: entry}

    def intersect(a, b):
        while a != b:
            while index[a] > index[b]:
                a = idom[a]
            while index[b] > index[a]:
                b = idom[b]
        return a
    changed = True
    while changed:
        changed = False
        for b in rpo[1:]:
            candidates = [p for p in preds[b] if p in idom]
            if not candidates:
                continue
            new = candidates[0]
            for p in candidates[1:]:
                new = intersect(p, new)
            if idom.get(b) != new:
                idom[b] = new
                changed = True
    return idom, rpo, preds


def dominates(idom, a, b):
    while True:
        if a == b:
            return True
        parent = idom.get(b)
        if parent is None or parent == b:
            return False
        b = parent


class Cfg:
    def __init__(self, blocks):
        self.count = len(blocks)
        self.succ = [successors(b) for b in blocks]
        self.idom, self.rpo, self.preds = dominators(self.count, self.succ)
        exit_node = self.count
        rsucc = [[] for _ in range(self.count + 1)]
        for b in range(self.count):
            if not self.succ[b]:
                rsucc[exit_node].append(b)
            for s in self.succ[b]:
                rsucc[s].append(b)
        reachable_back = set()
        stack = [exit_node]
        while stack:
            node = stack.pop()
            if node in reachable_back:
                continue
            reachable_back.add(node)
            stack.extend(rsucc[node])
        # Blocks that never reach an exit (infinite loops) get an edge to it.
        for b in range(self.count):
            if b not in reachable_back:
                rsucc[exit_node].append(b)
        self.ipdom, _, _ = dominators(self.count + 1, rsucc, exit_node)
        self.exit = exit_node
        self.loops = {}
        for b in range(self.count):
            for s in self.succ[b]:
                if b in self.idom and dominates(self.idom, s, b):
                    loop = self.loops.setdefault(s, {'header': s, 'latches': [], 'body': {s}})
                    loop['latches'].append(b)
        for header, loop in self.loops.items():
            stack = list(loop['latches'])
            while stack:
                node = stack.pop()
                if node in loop['body']:
                    continue
                loop['body'].add(node)
                stack.extend(self.preds[node])
            exits = []
            for node in sorted(loop['body']):
                for s in self.succ[node]:
                    if s not in loop['body'] and s not in exits:
                        exits.append(s)
            merge = self.ipdom.get(header)
            if merge in loop['body'] or merge == self.exit or merge is None:
                merge = exits[0] if exits else None
            elif exits and merge not in exits:
                # Prefer a direct exit when the post-dominator is further away.
                merge = exits[0] if len(exits) == 1 else merge
            loop['merge'] = merge
            loop['exits'] = exits

    def post_dominator(self, b):
        p = self.ipdom.get(b)
        return None if p == self.exit else p


# ---------------------------------------------------------------------- writer

class Writer:
    def __init__(self, data):
        parts = dict(chunks(data))
        if 'DXIL' not in parts:
            raise CyToolError('Unsupported', 'No DXIL program in this container.')
        self.code = llvmbc.parse_module(bitcode_of(parts['DXIL']))
        meta_module = self.code
        if 'STAT' in parts:
            try:
                meta_module = llvmbc.parse_module(bitcode_of(parts['STAT']))
            except (llvmbc.BitcodeError, IndexError, KeyError, struct.error):
                meta_module = self.code
        self.reflection = Reflection(meta_module)
        if not any(self.reflection.resources.values()) and meta_module is not self.code:
            self.reflection = Reflection(self.code)
        self.lines = []
        self.depth = 1
        self.system_values = {}

    # ------------------------------------------------------------------ values

    def literal(self, value):
        const = value.data
        t = value.type
        if const.kind == 'int':
            if t is not None and t.kind == 'int' and t.width == 1:
                return E('true' if const.value else 'false')
            return E(str(const.value), 1 if const.value < 0 else 0)
        if const.kind == 'float':
            text = format_float(const.value)
            if t is not None and t.kind == 'half':
                text += 'h' if False else ''
            return E(text, 1 if text.startswith('-') else 0)
        if const.kind in ('null', 'undef'):
            if t is not None and t.is_float:
                return E('0.0')
            if t is not None and t.kind == 'int' and t.width == 1:
                return E('false')
            return E('0')
        if const.kind == 'aggregate_values':
            return E('{%s}' % ', '.join(format_float(v) if isinstance(v, float) else str(v) for v in const.items))
        if const.kind == 'aggregate':
            return E('{%s}' % ', '.join(self.value(i).text for i in const.items))
        if const.kind == 'gep' and const.items:
            base = self.value(const.items[0])
            indices = const.items[2:]
            return E(base.text + ''.join('[%s]' % self.value(i).text for i in indices))
        return E('/*const*/0')

    def value(self, value_id):
        if value_id in self.exprs:
            return self.exprs[value_id]
        value = self.values[value_id] if value_id < len(self.values) else None
        if value is None:
            return E('_%d' % value_id)
        if value.kind == 'const':
            return self.literal(value)
        if value.kind == 'global':
            return E(self.global_name(value))
        if value.kind == 'function':
            return E(value.name)
        return E(self.temp_name(value_id))

    def temp_name(self, value_id):
        return '_%d' % (value_id - self.first_local)

    def global_name(self, value):
        name = value.name or 'g%d' % value.id
        match = re.match(r'^\x01?\?([A-Za-z_][A-Za-z0-9_]*)@', name)
        if match:
            return match.group(1)
        return re.sub(r'[^A-Za-z0-9_]', '_', name).strip('_') or 'g%d' % value.id

    def hlsl_type(self, t):
        if t is None:
            return 'float'
        if t.kind == 'float':
            return 'float'
        if t.kind == 'half':
            return 'half'
        if t.kind == 'double':
            return 'double'
        if t.kind == 'int':
            return {1: 'bool', 8: 'uint', 16: 'min16int', 32: 'int', 64: 'int64_t'}.get(t.width, 'int')
        if t.kind == 'vector':
            return '%s%d' % (self.hlsl_type(t.elements[0]), t.count)
        if t.kind == 'struct' and t.name == 'dx.types.Handle':
            return 'handle'
        if t.kind == 'struct':
            scalars = [e for e in t.elements if e.kind in ('float', 'int', 'half', 'double')]
            if scalars and t.name.startswith('dx.types.'):
                count = min(4, len([e for e in t.elements if e.kind == scalars[0].kind]))
                base = self.hlsl_type(scalars[0])
                return base if count == 1 else '%s%d' % (base, count)
            return 'float4'
        if t.kind == 'array':
            return self.hlsl_type(t.elements[0])
        return 'float'

    # ------------------------------------------------------------------ resources

    def resource_of(self, handle_id):
        return self.handles.get(handle_id)

    def resource_text(self, handle_id):
        info = self.handles.get(handle_id)
        if info is None:
            return 'resource_%s' % self.value(handle_id).text
        record, index = info
        name = record['name'] or '%s%d' % (record['class'], record['lower'])
        if index is not None:
            return '%s[%s]' % (name, index)
        return name

    def field_at(self, fields, offset):
        best = None
        for field in fields:
            if field['offset'] <= offset and (best is None or field['offset'] >= best['offset']):
                best = field
        return best

    def member_text(self, fields, offset):
        """`name.comp` for a byte offset inside an annotated structure."""
        field = self.field_at(fields, offset)
        if field is None:
            return None
        delta = offset - field['offset']
        t = field['type']
        if re.match(r'^[a-z0-9_ ]+\d+x\d+$', t):
            register, comp = divmod(delta // 4, 4)
            # Column-major (the HLSL default) stores one column per register.
            row, column = (register, comp) if field.get('rowMajor') else (comp, register)
            return '%s._m%d%d' % (field['name'], row, column)
        count = re.search(r'(\d+)$', t)
        if count and not t.endswith(']'):
            comp = delta // 4
            return '%s.%s' % (field['name'], SWIZZLE[comp]) if comp < 4 else field['name']
        if t.endswith(']'):
            return '%s[%d]' % (field['name'], delta // 16 if delta >= 16 else delta // 4)
        return field['name']

    def cbuffer_element(self, handle_id, register, component, width=4):
        info = self.handles.get(handle_id)
        if info is not None:
            record = info[0]
            fields = self.reflection.fields_of(record.get('type'))
            if fields:
                text = self.member_text(fields, register * 16 + component * width)
                if text:
                    return text
            name = record['name']
        else:
            name = 'cb'
        return '%s_regs[%s].%s' % (name, register, SWIZZLE[component % 4])

    def dynamic_cbuffer(self, handle_id, register, component):
        """cbuffer read with a computed register: resolve to an array field (`Weights[i].x`)."""
        info = self.handles.get(handle_id)
        record = info[0] if info else None
        base = 0
        index_text = self.value(register).text
        producer = self.values[register].data if self.values[register].kind == 'inst' else None
        if producer is not None and producer.op == 'binop' and producer.extra['op'] == 'add':
            constant = self.const_int(producer.args[1])
            if constant is not None:
                base = constant
                index_text = self.value(producer.args[0]).text
        fields = self.reflection.fields_of(record.get('type')) if record else []
        for field in fields:
            if field['offset'] == base * 16 and field['type'].endswith(']'):
                element = re.sub(r'\[\d+\]$', '', field['type'])
                count = re.search(r'(\d+)$', element)
                suffix = '.%s' % SWIZZLE[component % 4] if count and int(count.group(1)) > 1 else ''
                return '%s[%s]%s' % (field['name'], index_text, suffix)
        name = record['name'] if record else 'cb'
        return '%s_regs[%s].%s' % (name, self.value(register).text, SWIZZLE[component % 4])

    def structured_fields(self, record):
        t = record.get('type')
        if t is not None and t.kind == 'struct' and len(t.elements) == 1:
            inner = t.elements[0]
            while inner.kind == 'array':
                inner = inner.elements[0]
            if inner.kind == 'struct':
                return self.reflection.fields_of(inner)
        return []

    # ------------------------------------------------------------------ dx.op calls

    def call(self, inst):
        callee = self.values[inst.extra['callee']]
        name = callee.name or ''
        args = inst.args[1:]
        if not name.startswith('dx.op.'):
            return E('%s(%s)' % (re.sub(r'[^A-Za-z0-9_]', '_', name), ', '.join(self.value(a).text for a in args))), False
        opcode_value = self.values[args[0]] if args else None
        opcode = opcode_value.data.value if opcode_value is not None and opcode_value.kind == 'const' and opcode_value.data.kind == 'int' else -1
        a = args[1:]
        v = lambda i: self.value(a[i])  # noqa: E731
        t = lambda i: self.value(a[i]).text  # noqa: E731
        const = lambda i: self.const_int(a[i])  # noqa: E731
        if opcode == 4:  # LoadInput(sigId, row, col, vertex)
            element = self.reflection.inputs.get(const(0))
            return E(self.signature_text('input', element, a[1], const(2))), False
        if opcode == 5:  # StoreOutput(sigId, row, col, value)
            element = self.reflection.outputs.get(const(0))
            return E('%s = %s;' % (self.signature_text('output', element, a[1], const(2)), t(3))), True
        if opcode in UNARY:
            return E('%s(%s)' % (UNARY[opcode], t(0))), False
        if opcode in BINARY:
            return E('%s(%s, %s)' % (BINARY[opcode], t(0), t(1))), False
        if opcode in TERTIARY:
            return E('%s(%s, %s, %s)' % (TERTIARY[opcode], t(0), t(1), t(2))), False
        if opcode == 53:
            return E('bfi(%s, %s, %s, %s)' % (t(0), t(1), t(2), t(3))), False
        if opcode in (54, 55, 56):
            n = opcode - 52
            vec = 'float%d' % n
            first = self.merge([t(i) for i in range(n)])
            second = self.merge([t(n + i) for i in range(n)])
            return E('dot(%s, %s)' % (self.vector(vec, first), self.vector(vec, second))), False
        if opcode in (41, 42, 43):
            op = {41: '*', 42: '*', 43: '/'}[opcode]
            return E('%s %s %s' % (wrap(v(0), 3), op, wrap(v(1), 3, True)), 3), False
        if opcode == 57:
            return E('/*handle*/'), False
        if opcode in (216,):
            return self.value(a[0]), False
        if opcode == 59 or opcode == 58:
            return E('/*cbuffer*/'), False
        if opcode in SYSTEM_VALUES:
            label, kind, semantic = SYSTEM_VALUES[opcode]
            self.system_values[label] = (kind, semantic)
            if kind.endswith('3') and a:
                return E('%s.%s' % (label, SWIZZLE[const(0) or 0])), False
            return E(label), False
        if opcode in (119, 121):  # WaveActiveOp / WavePrefixOp (value, op, sign)
            names = {0: 'Sum', 1: 'Product', 2: 'Min', 3: 'Max'}
            prefix = 'WaveActive' if opcode == 119 else 'WavePrefix'
            return E('%s%s(%s)' % (prefix, names.get(const(1), 'Sum'), t(0))), False
        if opcode == 120:  # WaveActiveBit (value, op)
            return E('WaveActiveBit%s(%s)' % ({0: 'And', 1: 'Or', 2: 'Xor'}.get(const(1), 'Or'), t(0))), False
        if opcode == 123:  # QuadOp (value, op)
            return E('%s(%s)' % ({0: 'QuadReadAcrossX', 1: 'QuadReadAcrossY', 2: 'QuadReadAcrossDiagonal'}.get(const(1), 'QuadReadAcrossX'), t(0))), False
        if opcode in WAVE:
            return E('%s(%s)' % (WAVE[opcode], ', '.join(t(i) for i in range(len(a))))), False
        if opcode in (60, 61, 62, 63, 64, 65, 73, 74, 81):
            return self.sample(opcode, a), False
        if opcode == 66:  # TextureLoad(srv, mip, c0, c1, c2, o0, o1, o2)
            return self.texture_load(a), False
        if opcode == 67:  # TextureStore(uav, c0, c1, c2, v0..v3, mask)
            record = self.resource_of(a[0])
            count = COORDS.get(record[0].get('kind'), 2) if record else 2
            coords = self.vector('uint%d' % count if count > 1 else 'uint', self.merge([t(1 + i) for i in range(count)]))
            mask = const(8) or 15
            values = [t(4 + i) for i in range(4) if mask & (1 << i)]
            target = '%s[%s]' % (self.resource_text(a[0]), coords)
            if mask != 15:
                target += '.' + ''.join(SWIZZLE[i] for i in range(4) if mask & (1 << i))
            kind = 'float%d' % len(values) if len(values) > 1 else 'float'
            return E('%s = %s;' % (target, self.vector(kind, self.merge(values)))), True
        if opcode in (68, 139):  # BufferLoad / RawBufferLoad
            return self.buffer_load(a, raw=opcode == 139), False
        if opcode in (69, 140):  # BufferStore / RawBufferStore
            return self.buffer_store(a, raw=opcode == 140), True
        if opcode == 70:
            return E('%s.%s()' % (self.resource_text(a[0]), 'IncrementCounter' if const(1) == 1 else 'DecrementCounter')), True
        if opcode == 72:
            return E('GetDimensions(%s, %s)' % (self.resource_text(a[0]), t(1))), False
        if opcode == 78:  # AtomicBinOp(handle, op, o0, o1, o2, value)
            target = self.atomic_target(a[0], [a[2], a[3], a[4]])
            function = ATOMIC_OPS.get(const(1), 'InterlockedOp')
            return E('%s(%s, %s' % (function, target, t(5))), True
        if opcode == 79:  # AtomicCompareExchange(handle, o0, o1, o2, compare, value)
            target = self.atomic_target(a[0], [a[1], a[2], a[3]])
            return E('InterlockedCompareExchange(%s, %s, %s' % (target, t(4), t(5))), True
        if opcode == 80:
            flags = const(0) or 0
            if flags & 2:
                barrier = 'AllMemoryBarrier' if flags & 8 else 'DeviceMemoryBarrier'
            else:
                barrier = 'GroupMemoryBarrier'
            return E('%s%s();' % (barrier, 'WithGroupSync' if flags & 1 else '')), True
        if opcode == 82:
            cond = v(0)
            if cond.text == 'true':
                return E('discard;'), True
            return E('if (%s) discard;' % cond.text), True
        if opcode in (87, 88, 89):
            function = {87: 'EvaluateAttributeSnapped', 88: 'EvaluateAttributeAtSample', 89: 'EvaluateAttributeCentroid'}[opcode]
            element = self.reflection.inputs.get(const(0))
            base = self.signature_text('input', element, a[1], const(2))
            extra = ', '.join(t(i) for i in range(3, len(a)))
            return E('%s(%s%s)' % (function, base, (', ' + extra) if extra else '')), False
        if opcode in (97, 98, 99):
            return E({97: 'stream.Append(output);', 98: 'stream.RestartStrip();',
                      99: 'stream.Append(output); stream.RestartStrip();'}[opcode]), True
        if opcode == 101:
            return E('asdouble(%s, %s)' % (t(0), t(1))), False
        operation = name.split('.')[2] if name.count('.') >= 2 else name
        return E('%s(%s)' % (operation, ', '.join(t(i) for i in range(len(a))))), opcode in SIDE_EFFECTS

    def const_int(self, value_id):
        value = self.values[value_id] if value_id < len(self.values) else None
        if value is not None and value.kind == 'const':
            if value.data.kind == 'int':
                return value.data.value
            if value.data.kind in ('null', 'undef'):
                return 0
        return None

    def signature_text(self, root, element, row_id, column):
        if element is None:
            return '%s.attr' % root
        text = '%s.%s' % (root, element['field'])
        if element['rows'] > 1:
            text += '[%s]' % self.value(row_id).text
        if element['cols'] > 1 and column is not None:
            text += '.' + SWIZZLE[column]
        return text

    @staticmethod
    def merge(parts):
        merged = []
        for part in parts:
            match = re.fullmatch(r'(.+)\.([xyzw]+)', part)
            if merged and match:
                previous = re.fullmatch(r'(.+)\.([xyzw]+)', merged[-1])
                if previous and previous.group(1) == match.group(1) and \
                        len(previous.group(2)) + len(match.group(2)) <= 4 and \
                        re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.\[\]]*', match.group(1)):
                    merged[-1] = '%s.%s%s' % (match.group(1), previous.group(2), match.group(2))
                    continue
            merged.append(part)
        return merged

    @staticmethod
    def vector(kind, parts):
        if len(parts) == 1:
            single = parts[0]
            count = re.search(r'(\d)$', kind)
            n = int(count.group(1)) if count else 1
            match = re.fullmatch(r'.+\.([xyzw]+)', single)
            if n == 1 or (match and len(match.group(1)) == n):
                return single
        return '%s(%s)' % (kind, ', '.join(parts))

    def sample(self, opcode, a):
        record = self.resource_of(a[0])
        count = COORDS.get(record[0].get('kind'), 2) if record else 2
        texture = self.resource_text(a[0])
        sampler = self.resource_text(a[1])
        coords = [self.value(a[2 + i]).text for i in range(count)]
        coord = self.vector('float%d' % count if count > 1 else 'float', self.merge(coords))
        offsets = []
        offset_base = 6
        if opcode in (73, 74):
            offset_base = 6
        rest_base = 9
        if opcode in (73, 74):
            rest_base = 8
        for i in range(min(count, 3) if opcode not in (73, 74) else 2):
            value = self.values[a[offset_base + i]] if offset_base + i < len(a) else None
            if value is not None and not (value.kind == 'const' and value.data.kind in ('undef', 'null', 'int') and
                                          (value.data.kind != 'int' or value.data.value == 0)):
                offsets.append(self.value(a[offset_base + i]).text)
        offset = (', int%d(%s)' % (len(offsets), ', '.join(offsets))) if offsets and len(offsets) > 1 else \
                 (', %s' % offsets[0] if offsets else '')
        extra = lambda i: self.value(a[rest_base + i]).text if rest_base + i < len(a) else '0'  # noqa: E731
        if opcode == 60:
            call = '%s.Sample(%s, %s%s)' % (texture, sampler, coord, offset)
        elif opcode == 61:
            call = '%s.SampleBias(%s, %s, %s%s)' % (texture, sampler, coord, extra(0), offset)
        elif opcode == 62:
            call = '%s.SampleLevel(%s, %s, %s%s)' % (texture, sampler, coord, extra(0), offset)
        elif opcode == 63:
            ddx = self.vector('float%d' % count if count > 1 else 'float', self.merge([extra(i) for i in range(count)]))
            ddy = self.vector('float%d' % count if count > 1 else 'float', self.merge([extra(3 + i) for i in range(count)]))
            call = '%s.SampleGrad(%s, %s, %s, %s%s)' % (texture, sampler, coord, ddx, ddy, offset)
        elif opcode == 64:
            call = '%s.SampleCmp(%s, %s, %s%s)' % (texture, sampler, coord, extra(0), offset)
        elif opcode == 65:
            call = '%s.SampleCmpLevelZero(%s, %s, %s%s)' % (texture, sampler, coord, extra(0), offset)
        elif opcode == 73:
            channel = self.const_int(a[8]) if len(a) > 8 else 0
            method = {0: 'GatherRed', 1: 'GatherGreen', 2: 'GatherBlue', 3: 'GatherAlpha'}.get(channel, 'Gather')
            call = '%s.%s(%s, %s%s)' % (texture, method, sampler, coord, offset)
        elif opcode == 74:
            call = '%s.GatherCmp(%s, %s, %s%s)' % (texture, sampler, coord, self.value(a[9]).text if len(a) > 9 else '0', offset)
        else:
            call = '%s.CalculateLevelOfDetail(%s, %s)' % (texture, sampler, coord)
        return E(call)

    def texture_load(self, a):
        record = self.resource_of(a[0])
        kind = record[0].get('kind') if record else 2
        count = COORDS.get(kind, 2)
        coords = [self.value(a[2 + i]).text for i in range(count)]
        if record and record[0]['class'] == 'uav':
            return E('%s[%s]' % (self.resource_text(a[0]), self.vector('uint%d' % count if count > 1 else 'uint', self.merge(coords))))
        if kind in (3, 8):
            return E('%s.Load(%s, %s)' % (self.resource_text(a[0]), self.vector('int%d' % count, self.merge(coords)), self.value(a[1]).text))
        mip = self.value(a[1]).text if self.const_int(a[1]) is None or True else '0'
        return E('%s.Load(%s)' % (self.resource_text(a[0]), 'int%d(%s, %s)' % (count + 1, ', '.join(self.merge(coords)), mip)))

    def buffer_load(self, a, raw):
        record = self.resource_of(a[0])
        name = self.resource_text(a[0])
        index = self.value(a[1]).text
        kind = record[0].get('kind') if record else 10
        if kind == 12:  # structured: (index, byte offset)
            offset = self.const_int(a[2]) if len(a) > 2 else 0
            fields = self.structured_fields(record[0]) if record else []
            if fields and offset is not None:
                return E('%s[%s]' % (name, index), 0, ('struct', fields, offset))
            return E('%s[%s]' % (name, index), 0, ('raw', offset))
        if kind == 11:
            return E('%s.Load4(%s)' % (name, index))
        return E('%s[%s]' % (name, index))

    def buffer_store(self, a, raw):
        """BufferStore / RawBufferStore: (uav, coord0, coord1, v0, v1, v2, v3, mask[, alignment])."""
        record = self.resource_of(a[0])
        name = self.resource_text(a[0])
        index = self.value(a[1]).text
        kind = record[0].get('kind') if record else 10
        mask = self.const_int(a[7]) if len(a) > 7 else 15
        mask = 15 if not mask else mask
        components = [i for i in range(4) if mask & (1 << i)]
        values = [self.value(a[3 + i]).text for i in components]
        first = self.values[a[3 + components[0]]] if components else None
        base = self.hlsl_type(first.type) if first is not None else 'float'
        value = self.vector('%s%d' % (base, len(values)) if len(values) > 1 else base, self.merge(values))
        if kind == 12:
            offset = self.const_int(a[2])
            fields = self.structured_fields(record[0]) if record else []
            member = self.member_text(fields, offset) if fields and offset is not None else None
            if member:
                return E('%s[%s].%s = %s;' % (name, index, member.split('.')[0], value))
            return E('%s[%s] = %s;  // byte offset %s' % (name, index, value, self.value(a[2]).text))
        if kind == 11:
            suffix = str(len(values)) if len(values) > 1 else ''
            if base != 'uint':
                value = 'asuint(%s)' % value
            return E('%s.Store%s(%s, %s);' % (name, suffix, index, value))
        return E('%s[%s] = %s;' % (name, index, value))

    def atomic_target(self, handle, coords):
        record = self.resource_of(handle)
        name = self.resource_text(handle)
        if record is None:
            return name
        kind = record[0].get('kind')
        first = self.value(coords[0]).text
        if kind == 11:
            return '%s /* byte %s */' % (name, first)
        if kind == 12:
            return '%s[%s]' % (name, first)
        count = COORDS.get(kind, 1)
        if count == 1:
            return '%s[%s]' % (name, first)
        return '%s[%s]' % (name, self.vector('uint%d' % count, self.merge([self.value(c).text for c in coords[:count]])))

    # ------------------------------------------------------------------ instructions

    def build(self, inst):
        """(expression, is_statement) for one instruction."""
        op = inst.op
        args = inst.args
        if op == 'binop':
            operator, prec = BIN_TEXT.get(inst.extra['op'], ('?', 4))
            a, b = self.value(args[0]), self.value(args[1])
            t = self.values[args[0]].type if args[0] < len(self.values) else None
            if t is not None and t.kind == 'int' and t.width == 1:
                operator, prec = {'and': ('&&', 11), 'or': ('||', 12), 'xor': ('!=', 7)}.get(inst.extra['op'], (operator, prec))
            if inst.extra.get('float') and inst.extra['op'] in ('urem', 'srem'):
                return E('fmod(%s, %s)' % (a.text, b.text)), False
            if inst.extra['op'] in UNSIGNED:
                return E('(uint)%s %s (uint)%s' % (wrap(a, 1), operator, wrap(b, 1)), prec), False
            return E('%s %s %s' % (wrap(a, prec), operator, wrap(b, prec, True)), prec), False
        if op == 'cmp':
            a, b = self.value(args[0]), self.value(args[1])
            operator = CMP_TEXT.get(inst.extra['pred'], '?')
            prec = 7 if operator in ('==', '!=') else 6
            if inst.extra['pred'] in ('true', 'false'):
                return E(inst.extra['pred']), False
            left = wrap(a, prec)
            right = wrap(b, prec, True)
            if inst.extra['pred'] in ('ugt', 'uge', 'ult', 'ule') and not inst.extra.get('float'):
                left, right = '(uint)' + wrap(a, 1), '(uint)' + wrap(b, 1)
            return E('%s %s %s' % (left, operator, right), prec, (left, operator, right)), False
        if op == 'cast':
            source = self.value(args[0])
            kind = inst.extra['op']
            target = self.hlsl_type(inst.type)
            if kind == 'bitcast':
                function = 'asfloat' if inst.type is not None and inst.type.is_float else 'asint'
                return E('%s(%s)' % (function, source.text)), False
            if kind in ('zext', 'uitofp') and self.values[args[0]].type is not None and \
                    self.values[args[0]].type.kind == 'int' and self.values[args[0]].type.width == 1:
                return E('(%s)%s' % (target, wrap(source, 1)), 1), False
            if kind in ('uitofp', 'zext', 'fptoui'):
                if kind == 'uitofp':
                    return E('(float)(uint)%s' % wrap(source, 1), 1), False
                return E('(%s)%s' % ('uint' if kind != 'uitofp' else target, wrap(source, 1)), 1), False
            return E('(%s)%s' % (target, wrap(source, 1)), 1), False
        if op == 'select':
            c, a, b = self.value(args[0]), self.value(args[1]), self.value(args[2])
            return E('%s ? %s : %s' % (wrap(c, 12), wrap(a, 12), wrap(b, 12)), 13), False
        if op == 'extractvalue':
            source = self.value(args[0])
            index = inst.extra['indices'][0] if inst.extra['indices'] else 0
            producer = self.values[args[0]].data if self.values[args[0]].kind == 'inst' else None
            if producer is not None and producer.op == 'call':
                callee = self.values[producer.extra['callee']].name or ''
                if callee.startswith('dx.op.cbufferLoadLegacy'):
                    width = 8 if callee.endswith(('f64', 'i64')) else 4
                    register = producer.args[3] if len(producer.args) > 3 else None
                    reg_const = self.const_int(register) if register is not None else None
                    if reg_const is None:
                        return E(self.dynamic_cbuffer(producer.args[2], register, index)), False
                    return E(self.cbuffer_element(producer.args[2], reg_const, index, width)), False
            if source.cmp and isinstance(source.cmp, tuple) and source.cmp[0] == 'struct':
                _, fields, offset = source.cmp
                member = self.member_text(fields, offset + index * 4)
                if member:
                    return E('%s.%s' % (source.text, member)), False
            if source.cmp and isinstance(source.cmp, tuple) and source.cmp[0] == 'raw':
                offset = source.cmp[1] if source.cmp[1] is not None else 0
                return E('asfloat(%s.words[%d])' % (source.text, offset // 4 + index)), False
            if index < 4:
                return E('%s.%s' % (wrap(source, 0), SWIZZLE[index])), False
            return E('/*status*/%s' % wrap(source, 0)), False
        if op == 'extractelement':
            return E('%s[%s]' % (wrap(self.value(args[0]), 0), self.value(args[1]).text)), False
        if op == 'gep':
            base = self.value(args[0])
            indices = args[2:] if len(args) > 2 else args[1:]
            text = base.text + ''.join('[%s]' % self.value(i).text for i in indices)
            return E(text), False
        if op == 'load':
            pointer = self.value(args[0])
            return E(pointer.text), False
        if op == 'store':
            return E('%s = %s;' % (self.value(args[0]).text, self.value(args[1]).text)), True
        if op == 'call':
            return self.call(inst)
        if op == 'alloca':
            return E('local%d' % inst.value_id), False
        if op == 'insertvalue':
            return E('/*insertvalue*/%s' % self.value(args[0]).text), False
        return E('/* %s */' % op), True

    # ------------------------------------------------------------------ analysis

    def prepare(self, function):
        self.function = function
        self.values = function.values
        self.first_local = len(self.code.values)
        self.exprs = {}
        self.handles = {}
        self.uses = {}
        self.use_block = {}
        for block_index, block in enumerate(function.blocks):
            for inst in block:
                operands = list(inst.args)
                if inst.op == 'call':
                    operands = inst.args[1:]
                for operand in set(operands):
                    self.uses[operand] = self.uses.get(operand, 0) + 1
                    self.use_block.setdefault(operand, set()).add(block_index)
                if inst.op == 'phi':
                    for value_id, incoming_block in inst.extra['incoming']:
                        self.use_block.setdefault(value_id, set()).add(incoming_block)
        # Resource handles.
        for block in function.blocks:
            for inst in block:
                if inst.op != 'call':
                    continue
                callee = self.values[inst.extra['callee']].name or ''
                if callee == 'dx.op.createHandle':
                    a = inst.args[2:]
                    class_index = self.const_int(a[0]) or 0
                    range_id = self.const_int(a[1]) or 0
                    record = self.reflection.resources[RESOURCE_CLASSES[class_index % 4]].get(range_id)
                    if record is None:
                        record = {'class': RESOURCE_CLASSES[class_index % 4], 'id': range_id,
                                  'name': '%s%d' % ('tucs'[class_index % 4], range_id), 'lower': range_id, 'kind': 2}
                    index_const = self.const_int(a[2])
                    index = None
                    if record.get('range') not in (1, None) or index_const is None:
                        index = self.value(a[2]).text if index_const is None else str(index_const - record.get('lower', 0))
                    self.handles[inst.value_id] = (record, index)
                elif callee.startswith('dx.op.createHandleFromBinding'):
                    binding = self.values[inst.args[2]]
                    if binding.kind == 'const' and binding.data.kind == 'aggregate':
                        fields = [self.const_int(i) or 0 for i in binding.data.items]
                    elif binding.kind == 'const' and binding.data.kind in ('null', 'undef'):
                        fields = [0, 0, 0, 0]  # zeroinitializer: first SRV of space 0
                    else:
                        fields = []
                    if len(fields) >= 4:
                        lower, upper, space, class_index = fields[:4]
                        record = next((r for r in self.reflection.resources[RESOURCE_CLASSES[class_index % 4]].values()
                                       if r['lower'] == lower and r['space'] == space), None)
                        if record is None:
                            record = {'class': RESOURCE_CLASSES[class_index % 4], 'name': 'res%d' % lower, 'lower': lower, 'kind': 2}
                        index_const = self.const_int(inst.args[3])
                        index = None if index_const is not None and record.get('range') in (1, None) else self.value(inst.args[3]).text
                        self.handles[inst.value_id] = (record, index)
                elif callee.startswith('dx.op.annotateHandle'):
                    source = inst.args[2]
                    if source in self.handles:
                        self.handles[inst.value_id] = self.handles[source]
                elif callee.startswith('dx.op.createHandleFromHeap'):
                    self.handles[inst.value_id] = ({'class': 'srv', 'name': 'ResourceDescriptorHeap', 'kind': 2},
                                                   self.value(inst.args[2]).text)

    def pure(self, inst):
        if inst.op in ('binop', 'cmp', 'cast', 'select', 'extractvalue', 'extractelement', 'gep'):
            return True
        if inst.op == 'call':
            callee = self.values[inst.extra['callee']].name or ''
            if not callee.startswith('dx.op.'):
                return False
            opcode = self.const_int(inst.args[1]) if len(inst.args) > 1 else None
            if opcode in SIDE_EFFECTS:
                return False
            if opcode in (66, 68, 139):  # loads: pure only for read-only resources
                info = self.handles.get(inst.args[2])
                return info is not None and info[0]['class'] != 'uav'
            return True
        return False

    def inline_ok(self, inst, block, position):
        vid = inst.value_id
        if self.uses.get(vid, 0) != 1:
            return False
        blocks = self.use_block.get(vid, set())
        if blocks != {inst.block}:
            return False
        if self.pure(inst):
            return True
        if inst.op == 'load' or (inst.op == 'call' and not self.pure(inst)):
            for other in block[position + 1:]:
                if vid in other.args:
                    return True
                if other.op in ('store', 'atomic') or (other.op == 'call' and not self.pure(other)):
                    return False
        return False

    # ------------------------------------------------------------------ emission

    def emit(self, text):
        self.lines.append('    ' * self.depth + text)

    def declare(self, value_id, value_type):
        name = self.temp_name(value_id)
        self.declarations.setdefault(self.hlsl_type(value_type), []).append(name)
        return name

    def block_body(self, index):
        block = self.function.blocks[index]
        for position, inst in enumerate(block[:-1] if block and block[-1].op in ('br', 'switch', 'ret', 'unreachable') else block):
            if inst.op == 'phi':
                continue
            if inst.op == 'call':
                callee = self.values[inst.extra['callee']].name or ''
                if callee in ('dx.op.createHandle', 'dx.op.annotateHandle') or callee.startswith(
                        ('dx.op.createHandleFromBinding', 'dx.op.cbufferLoadLegacy', 'dx.op.annotateHandle')):
                    continue
            expression, statement = self.build(inst)
            if statement or inst.value_id is None:
                if inst.value_id is not None and expression.text.startswith('Interlocked'):
                    name = self.declare(inst.value_id, inst.type)
                    self.emit('%s, %s);' % (expression.text, name))
                    self.exprs[inst.value_id] = E(name)
                elif expression.text.startswith('Interlocked'):
                    self.emit(expression.text + ');')
                else:
                    self.emit(expression.text if expression.text.endswith(';') else expression.text + ';')
                continue
            if expression.cmp and isinstance(expression.cmp, tuple) and expression.cmp[0] in ('struct', 'raw'):
                self.exprs[inst.value_id] = expression  # virtual structured-buffer load
                continue
            if self.inline_ok(inst, block, position):
                self.exprs[inst.value_id] = expression
                continue
            name = self.declare(inst.value_id, inst.type)
            self.emit('%s = %s;' % (name, expression.text))
            self.exprs[inst.value_id] = E(name)

    def phi_copies(self, source, target):
        for inst in self.function.blocks[target]:
            if inst.op != 'phi':
                continue
            for value_id, incoming in inst.extra['incoming']:
                if incoming == source:
                    text = self.value(value_id).text
                    name = self.phi_names[inst.value_id]
                    if text != name:
                        self.emit('%s = %s;' % (name, text))

    def jump(self, source, target, follow, stops):
        self.phi_copies(source, target)
        if target == follow:
            return None
        if self.loops_stack:
            loop = self.loops_stack[-1]
            if target == loop['header']:
                self.emit('continue;')
                return None
            if target == loop['merge'] or target not in loop['body']:
                self.emit('break;')
                return None
        if target in stops:
            return None
        return target

    def sequence(self, start, stops, follow):
        index = start
        guard = 0
        while index is not None and index not in stops and guard < 100000:
            guard += 1
            loop = self.cfg.loops.get(index)
            if loop is not None and loop not in self.loops_stack:
                self.emit('while (true)')
                self.emit('{')
                self.depth += 1
                self.loops_stack.append(loop)
                self.sequence(index, set(), loop['header'])
                self.loops_stack.pop()
                self.trim_continue()
                self.depth -= 1
                self.emit('}')
                index = loop['merge']
                continue
            if index in self.emitted:
                if self.loops_stack and index == self.loops_stack[-1]['header']:
                    return
                self.emit('// control flow re-joins block %d' % index)
                return
            self.emitted.add(index)
            self.block_body(index)
            index = self.terminator(index, stops, follow)

    def trim_continue(self):
        while self.lines and self.lines[-1].strip() == 'continue;':
            self.lines.pop()

    def terminator(self, index, stops, follow):
        block = self.function.blocks[index]
        term = block[-1] if block else None
        if term is None:
            return None
        if term.op == 'ret':
            if term.args:
                self.emit('return %s;' % self.value(term.args[0]).text)
            else:
                self.emit('return;')
            return None
        if term.op == 'unreachable':
            return None
        if term.op == 'br' and len(term.extra['targets']) == 1:
            return self.jump(index, term.extra['targets'][0], follow, stops)
        if term.op == 'br':
            cond = self.value(term.args[0])
            true_target, false_target = term.extra['targets']
            merge = self.cfg.post_dominator(index)
            loop = self.loops_stack[-1] if self.loops_stack else None
            if loop is not None and (merge is None or merge not in loop['body']):
                merge = None
            exits = set()
            if loop is not None:
                exits = {loop['header']} | {t for t in (true_target, false_target) if t not in loop['body']}
            if true_target in exits or false_target in exits:
                inner, outer = (true_target, false_target) if true_target in exits else (false_target, true_target)
                condition = cond.text if inner == true_target else self.negate(cond)
                self.emit('if (%s)' % condition)
                self.emit('{')
                self.depth += 1
                self.jump(index, inner, None, set())
                self.depth -= 1
                self.emit('}')
                if outer in exits:
                    self.jump(index, outer, None, set())
                    return None
                return self.jump(index, outer, follow, stops)
            inner_stops = set(stops) | ({merge} if merge is not None else set())
            if true_target == merge:
                self.emit('if (%s)' % self.negate(cond))
                self.emit('{')
                self.depth += 1
                self.arm(index, false_target, inner_stops, merge)
                self.depth -= 1
                self.emit('}')
                if self.has_phi_from(index, merge):
                    self.emit('else')
                    self.emit('{')
                    self.depth += 1
                    self.phi_copies(index, merge)
                    self.depth -= 1
                    self.emit('}')
            else:
                self.emit('if (%s)' % cond.text)
                self.emit('{')
                self.depth += 1
                self.arm(index, true_target, inner_stops, merge)
                self.depth -= 1
                self.emit('}')
                if false_target != merge or self.has_phi_from(index, merge):
                    start = len(self.lines)
                    self.emit('else')
                    self.emit('{')
                    self.depth += 1
                    self.arm(index, false_target, inner_stops, merge)
                    self.depth -= 1
                    self.emit('}')
                    self.collapse_else(start)
            if merge is None or merge in stops:
                return None
            if merge == follow:
                return None
            return merge
        if term.op == 'switch':
            selector = self.value(term.args[0]).text
            merge = self.cfg.post_dominator(index)
            default = term.extra['default']
            groups = {}
            for value_id, target in term.extra['cases']:
                groups.setdefault(target, []).append(self.const_int(value_id))
            self.emit('switch (%s)' % selector)
            self.emit('{')
            inner_stops = set(stops) | ({merge} if merge is not None else set())
            entries = list(groups.items())
            if default not in groups:
                entries.append((default, None))
            for target, values in entries:
                if values is None:
                    self.emit('default:')
                else:
                    for value in values:
                        self.emit('case %s:' % value)
                    if target == default:
                        self.emit('default:')
                self.emit('{')
                self.depth += 1
                self.loops_stack.append({'header': None, 'merge': merge, 'body': set(range(self.cfg.count)) - {merge}})
                self.arm(index, target, inner_stops, merge)
                self.loops_stack.pop()
                if not self.lines[-1].strip() in ('break;', 'return;', 'continue;', 'discard;'):
                    self.emit('break;')
                self.depth -= 1
                self.emit('}')
            self.emit('}')
            if merge is None or merge in stops:
                return None
            return merge
        return None

    def has_phi_from(self, source, target):
        if target is None:
            return False
        return any(inst.op == 'phi' and any(b == source for _, b in inst.extra['incoming'])
                   for inst in self.function.blocks[target])

    def arm(self, source, target, stops, merge):
        self.phi_copies(source, target)
        if target == merge:
            return
        if self.loops_stack:
            loop = self.loops_stack[-1]
            if loop['header'] is not None and target == loop['header']:
                self.emit('continue;')
                return
            if target == loop['merge']:
                self.emit('break;')
                return
        self.sequence(target, stops, merge)

    def collapse_else(self, start):
        body = self.lines[start + 2:-1]
        if body and body[0].strip().startswith('if (') and self.single_statement(body):
            indent = self.lines[start][:len(self.lines[start]) - len('else')]
            self.lines[start:] = [indent + 'else ' + body[0].strip()] + [
                line[4:] if line.startswith('    ') else line for line in body[1:]]

    @staticmethod
    def single_statement(lines):
        base = len(lines[0]) - len(lines[0].lstrip())
        depth = 0
        for index, line in enumerate(lines):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            if index > 0 and indent == base and depth == 0 and not stripped.startswith(('{', '}', 'else')):
                return False
            if stripped == '{':
                depth += 1
            elif stripped == '}':
                depth -= 1
        return True

    def negate(self, expression):
        if expression.cmp and isinstance(expression.cmp, tuple) and len(expression.cmp) == 3 and expression.cmp[1] in INVERSE:
            left, operator, right = expression.cmp
            return '%s %s %s' % (left, INVERSE[operator], right)
        return '!' + wrap(expression, 1)

    # ------------------------------------------------------------------ module

    def function_text(self, function):
        self.prepare(function)
        self.cfg = Cfg(function.blocks)
        self.emitted = set()
        self.loops_stack = []
        self.declarations = {}
        self.phi_names = {}
        self.lines = []
        self.depth = 1
        for block in function.blocks:
            for inst in block:
                if inst.op == 'phi':
                    name = self.declare(inst.value_id, inst.type)
                    self.phi_names[inst.value_id] = name
                    self.exprs[inst.value_id] = E(name)
        if function.blocks:
            self.sequence(0, set(), None)
        body = self.lines
        while body and body[-1].strip() in ('return;',):
            body.pop()
        return body

    def globals_text(self):
        out = []
        for value in self.code.values:
            if value.kind != 'global' or value.type is None:
                continue
            name = self.global_name(value)
            if not name or name.startswith('dx_'):
                continue
            pointee = value.type.pointee if value.type.kind == 'pointer' else value.type
            dims = ''
            t = pointee
            while t is not None and t.kind == 'array':
                dims += '[%d]' % t.count
                t = t.elements[0]
            init = value.data.get('init') if isinstance(value.data, dict) else None
            initializer = ''
            if init is not None and init < len(self.code.values):
                literal = self.literal(self.code.values[init]) if self.code.values[init].kind == 'const' else None
                if literal is not None and literal.text.startswith('{'):
                    initializer = ' = ' + literal.text
            prefix = 'static const ' if initializer else 'groupshared '
            out.append('%s%s %s%s%s;' % (prefix, self.hlsl_type(t), name, dims, initializer))
        return out

    def resources_text(self):
        out = []
        refl = self.reflection
        for record in sorted(refl.resources['cbv'].values(), key=lambda r: r['lower']):
            fields = refl.fields_of(record.get('type'))
            out.append('cbuffer %s : register(b%d%s)' % (record['name'] or 'cb%d' % record['lower'], record['lower'],
                                                         ', space%d' % record['space'] if record['space'] else ''))
            out.append('{')
            for field in fields:
                ftype = field['type']
                dims = ''
                match = re.match(r'^(.*?)((?:\[\d+\])+)$', ftype)
                if match:
                    ftype, dims = match.group(1), match.group(2)
                if field.get('rowMajor') and re.search(r'\d+x\d+$', ftype):
                    ftype = 'row_major ' + ftype
                out.append('    %-14s %s%s;  // offset %d' % (ftype, field['name'], dims, field['offset']))
            if not fields:
                out.append('    float4 %s_regs[%d];' % (record['name'] or 'cb', max(1, (record.get('size') or 16) // 16)))
            out.append('};')
            out.append('')
        structs = {}
        for cls in ('srv', 'uav'):
            for record in refl.resources[cls].values():
                if record.get('kind') == 12:
                    fields = self.structured_fields(record)
                    inner = record['type'].elements[0] if record.get('type') is not None and record['type'].elements else None
                    while inner is not None and inner.kind == 'array':
                        inner = inner.elements[0]
                    if fields and inner is not None:
                        name = inner.name.split('.')[-1] if inner.name else 'Element'
                        structs[name] = fields
                        record['element'] = name
        for name, fields in structs.items():
            out.append('struct %s' % name)
            out.append('{')
            for field in fields:
                out.append('    %-14s %s;  // offset %d' % (field['type'], field['name'], field['offset']))
            out.append('};')
            out.append('')
        for cls, letter in (('sampler', 's'), ('srv', 't'), ('uav', 'u')):
            for record in sorted(refl.resources[cls].values(), key=lambda r: r['lower']):
                name = record['name'] or '%s%d' % (letter, record['lower'])
                count = record.get('range')
                array = '' if count in (1, None) else ('[]' if count in (-1, 0xffffffff) else '[%d]' % count)
                space = ', space%d' % record['space'] if record['space'] else ''
                if cls == 'sampler':
                    kind = 'SamplerComparisonState' if record.get('comparison') else 'SamplerState'
                    out.append('%s %s%s : register(s%d%s);' % (kind, name, array, record['lower'], space))
                    continue
                kind = KINDS.get(record.get('kind'), 'Texture2D')
                element = COMP_TYPES.get(record.get('comp'), 'float')
                if kind == 'StructuredBuffer':
                    template = '<%s>' % record.get('element', 'uint')
                elif kind == 'ByteAddressBuffer':
                    template = ''
                else:
                    template = '<%s4>' % element if ' ' not in element else '<%s4>' % element
                prefix = 'RW' if cls == 'uav' else ''
                comment = '  // stride %d' % record['stride'] if record.get('stride') else ''
                out.append('%s%s%s %s%s : register(%s%d%s);%s' % (prefix, kind, template, name, array, letter,
                                                                    record['lower'], space, comment))
        return out

    def struct_text(self, name, elements):
        lines = ['struct %s' % name, '{']
        for element in sorted(elements.values(), key=lambda e: e['id']):
            base = COMP_TYPES.get(element['comp'], 'float').split()[-1]
            kind = base if element['cols'] == 1 else '%s%d' % (base, element['cols'])
            array = '[%d]' % element['rows'] if element['rows'] > 1 else ''
            semantic = element['semantic'] + (str(element['indices'][0]) if element['indices'][0] else '')
            interp = {2: 'linear ', 3: 'linear centroid ', 4: 'noperspective ', 1: 'nointerpolation '}.get(element['interp'], '')
            if element['interp'] == 2 or element['semantic'].upper().startswith('SV_'):
                interp = ''
            lines.append('    %s%-8s %s%s : %s;' % (interp, kind, element['field'], array, semantic))
        lines.append('};')
        return lines

    def run(self):
        refl = self.reflection
        entry = next((f for f in self.code.functions if not f.is_proto), None)
        if entry is None:
            raise CyToolError('Unsupported', 'This DXIL module has no function body (library or stripped).')
        kind = refl.kind
        prefix = {'ps': 'PS', 'vs': 'VS', 'cs': 'CS', 'gs': 'GS', 'hs': 'HS', 'ds': 'DS', 'ms': 'MS', 'as': 'AS'}.get(kind, 'Shader')
        body = self.function_text(entry)
        header = ['// %s shader (%s_%d_%d, entry "%s"), decompiled by CyDecompilator from DXIL bitcode.'
                  % ({'ps': 'Pixel', 'vs': 'Vertex', 'cs': 'Compute', 'gs': 'Geometry', 'hs': 'Hull', 'ds': 'Domain',
                      'ms': 'Mesh', 'as': 'Amplification', 'lib': 'Library'}.get(kind, kind), kind, refl.model[0],
                     refl.model[1], refl.entry_name),
                  '// DXIL is scalar SSA: temporaries are per component; names come from the reflection data.', '']
        header += self.resources_text()
        globals_text = self.globals_text()
        if globals_text:
            header += [''] + globals_text
        header.append('')
        parameters = []
        if refl.inputs:
            header += self.struct_text(prefix + 'Input', refl.inputs) + ['']
            parameters.append('%sInput input' % prefix)
        has_output = bool(refl.outputs) and kind not in ('cs',)
        if has_output:
            header += self.struct_text(prefix + 'Output', refl.outputs) + ['']
        for label, (kind_text, semantic) in sorted(self.system_values.items()):
            parameters.append('%s %s : %s' % (kind_text, label, semantic))
        attributes = []
        if refl.numthreads:
            attributes.append('[numthreads(%d, %d, %d)]' % refl.numthreads)
        returns = prefix + 'Output' if has_output else 'void'
        prologue = []
        if has_output:
            prologue.append('    %s output;' % returns)
        for type_name, names in sorted(self.declarations.items()):
            for start in range(0, len(names), 10):
                prologue.append('    %s %s;' % (type_name, ', '.join(names[start:start + 10])))
        epilogue = ['    return output;'] if has_output else []
        body = [line.replace('return;', 'return output;') if has_output else line for line in body]
        return '\n'.join(header + attributes + ['%s main(%s)' % (returns, ', '.join(parameters)), '{'] + prologue +
                         ([''] if prologue else []) + body + epilogue + ['}']) + '\n'


def decompile(data):
    try:
        return Writer(data).run()
    except llvmbc.BitcodeError as exc:
        raise CyToolError('EngineFailed', 'Malformed DXIL bitcode: %s' % exc)


def ir_listing(data):
    """Plain LLVM-like listing of the entry function (for the disassembly view)."""
    writer = Writer(data)
    entry = next((f for f in writer.code.functions if not f.is_proto), None)
    if entry is None:
        return '; no function body\n'
    writer.prepare(entry)
    lines = ['; DXIL entry function %s, %d blocks' % (entry.name, len(entry.blocks))]
    for index, block in enumerate(entry.blocks):
        lines.append('')
        lines.append('block_%d:' % index)
        for inst in block:
            callee = writer.values[inst.extra['callee']].name if inst.op == 'call' else ''
            operands = []
            for a in (inst.args[1:] if inst.op == 'call' else inst.args):
                value = writer.values[a] if a < len(writer.values) else None
                if value is not None and value.kind == 'const':
                    operands.append(writer.literal(value).text)
                elif value is not None and value.kind == 'global':
                    operands.append('@' + writer.global_name(value))
                else:
                    operands.append('%%%d' % (a - writer.first_local))
            extra = {k: v for k, v in inst.extra.items() if k not in ('callee', 'float', 'flags')}
            head = '  %%%d = ' % (inst.value_id - writer.first_local) if inst.value_id is not None else '  '
            lines.append('%s%s %s%s %s%s' % (head, inst.op, (callee + ' ') if callee else '', writer.hlsl_type(inst.type)
                                             if inst.value_id is not None else '', ', '.join(operands),
                                             (' ' + str(extra)) if extra else ''))
    return '\n'.join(lines) + '\n'
