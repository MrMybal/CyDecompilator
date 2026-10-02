"""DXBC (SM4/SM5) to HLSL.

The bytecode is already structured (if/else/loop/switch tokens), so control flow maps
directly. The work is in naming: inputs and outputs become fields of input/output structs
named after their semantics, constant buffer registers become the cbuffer variables from
the RDEF chunk (`cb0[4].xyz` -> `LightDir.xyz`), resource and sampler registers get their
HLSL names. Temporaries stay `r0..rN` (untyped float4, as in the bytecode).
"""
import struct

from .dxbc import COMPONENTS, OPERAND_TYPES, float_text, literal_kind, looks_like_float, SRV_DIMENSIONS, RETURN_HLSL

SYSTEM_SEMANTICS = {
    'vThreadID': ('uint3', 'SV_DispatchThreadID'), 'vThreadGroupID': ('uint3', 'SV_GroupID'),
    'vThreadIDInGroup': ('uint3', 'SV_GroupThreadID'), 'vThreadIDInGroupFlattened': ('uint', 'SV_GroupIndex'),
    'vPrim': ('uint', 'SV_PrimitiveID'), 'vCoverage': ('uint', 'SV_Coverage'),
    'vGSInstanceID': ('uint', 'SV_GSInstanceID'), 'vDomain': ('float3', 'SV_DomainLocation'),
    'vOutputControlPointID': ('uint', 'SV_OutputControlPointID'),
    'vInnerCoverage': ('uint', 'SV_InnerCoverage'),
}
SYSTEM_OUTPUTS = {'oDepth': ('float', 'SV_Depth'), 'oMask': ('uint', 'SV_Coverage'),
                  'oDepthGE': ('float', 'SV_DepthGreaterEqual'), 'oDepthLE': ('float', 'SV_DepthLessEqual'),
                  'oStencilRef': ('uint', 'SV_StencilRef')}
COORDS = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 2, 8: 3, 9: 3, 10: 4, 11: 1, 12: 1}

BINARY = {'add': '+', 'mul': '*', 'div': '/', 'iadd': '+', 'and': '&', 'or': '|', 'xor': '^',
          'ishl': '<<', 'ishr': '>>', 'ushr': '>>', 'dadd': '+', 'dmul': '*', 'ddiv': '/'}
COMPARE = {'eq': '==', 'ne': '!=', 'lt': '<', 'ge': '>=', 'ieq': '==', 'ine': '!=', 'ilt': '<',
           'ige': '>=', 'ult': '<', 'uge': '>=', 'deq': '==', 'dne': '!=', 'dlt': '<', 'dge': '>='}
CALLS = {'min': 'min', 'max': 'max', 'imin': 'min', 'imax': 'max', 'umin': 'min', 'umax': 'max',
         'dmin': 'min', 'dmax': 'max'}
UNARY = {'frc': 'frac', 'exp': 'exp2', 'log': 'log2', 'rsq': 'rsqrt', 'sqrt': 'sqrt', 'rcp': 'rcp',
         'round_ne': 'round', 'round_ni': 'floor', 'round_pi': 'ceil', 'round_z': 'trunc',
         'ftoi': '(int)', 'ftou': '(uint)', 'itof': '(float)', 'utof': '(float)', 'dtof': '(float)',
         'ftod': '(double)', 'deriv_rtx': 'ddx', 'deriv_rty': 'ddy', 'deriv_rtx_coarse': 'ddx_coarse',
         'deriv_rtx_fine': 'ddx_fine', 'deriv_rty_coarse': 'ddy_coarse', 'deriv_rty_fine': 'ddy_fine',
         'countbits': 'countbits', 'firstbit_hi': 'firstbithigh', 'firstbit_lo': 'firstbitlow',
         'firstbit_shi': 'firstbithigh', 'bfrev': 'reversebits', 'f32tof16': 'f32tof16',
         'f16tof32': 'f16tof32', 'drcp': 'rcp', 'dtoi': '(int)', 'dtou': '(uint)', 'itod': '(double)',
         'utod': '(double)'}
ATOMICS = {'and': 'InterlockedAnd', 'or': 'InterlockedOr', 'xor': 'InterlockedXor',
           'iadd': 'InterlockedAdd', 'imax': 'InterlockedMax', 'imin': 'InterlockedMin',
           'umax': 'InterlockedMax', 'umin': 'InterlockedMin', 'exch': 'InterlockedExchange',
           'cmp_exch': 'InterlockedCompareExchange', 'cmp_store': 'InterlockedCompareStore'}


def _type_for(component_type, count):
    base = {'uint': 'uint', 'int': 'int', 'float': 'float'}.get(component_type, 'float')
    return base if count == 1 else '%s%d' % (base, count)


class Namer:
    """Turns registers into HLSL names using signatures and reflection."""

    def __init__(self, shader):
        self.shader = shader
        self.inputs = self._signature(shader.inputs, 'input')
        self.outputs = self._signature(shader.outputs, 'output')
        self.bindings = {}
        for binding in shader.bindings:
            prefix = {'cbuffer': 'cb', 'tbuffer': 't', 'texture': 't', 'sampler': 's', 'structured': 't',
                      'byteaddress': 't'}.get(binding['type'], 'u')
            for offset in range(max(binding['count'], 1)):
                key = '%s%d' % (prefix, binding['register'] + offset)
                self.bindings[key] = binding['name'] + ('[%d]' % offset if binding['count'] > 1 else '')
        self.cb_vars = {}
        cb_bindings = [b for b in shader.bindings if b['type'] in ('cbuffer', 'tbuffer')]
        for binding in cb_bindings:
            cb = next((c for c in shader.cbuffers if c['name'] == binding['name']), None)
            if cb is not None:
                self.cb_vars[binding['register']] = cb['variables']
        self.system_inputs = set()

    @staticmethod
    def _signature(elements, root):
        by_register = {}
        names = {}
        for element in elements:
            name = element['name']
            if not name.upper().startswith('SV_') or element['index']:
                name = '%s%d' % (name, element['index'])
            if name in names.values():
                name = '%s_%d' % (name, element['register'])
            first = next((i for i in range(4) if element['mask'] & (1 << i)), 0)
            count = bin(element['mask']).count('1')
            record = dict(element, field=name, first=first, count=count)
            names[(element['register'], element['mask'])] = name
            by_register.setdefault(element['register'], []).append(record)
        return by_register

    def signature_name(self, table, root, register, components):
        for element in table.get(register, []):
            if all(element['mask'] & (1 << c) for c in components):
                rebased = [c - element['first'] for c in components]
                if element['count'] == 1 and all(c == 0 for c in rebased):
                    return '%s.%s' % (root, element['field']), None
                return '%s.%s' % (root, element['field']), rebased
        return None, None

    def cb_name(self, slot, register, components):
        variables = self.cb_vars.get(slot)
        if not variables or register is None:
            return None, None
        address = register * 16 + (components[0] * 4 if components else 0)
        for var in variables:
            if var['offset'] <= address < var['offset'] + max(var['size'], 4):
                if var['class'] in (2, 3) and not var['elements']:
                    register = register - var['offset'] // 16
                    start = var['offset'] % 16 // 4 if register == 0 else 0
                    parts = []
                    for c in components:
                        comp = c - start
                        # class 3 = column-major (HLSL default): a register holds one column.
                        row, column = (comp, register) if var['class'] == 3 else (register, comp)
                        parts.append('_m%d%d' % (row, column))
                    return '%s.%s' % (var['name'], ''.join(parts)), None
                if var['class'] in (2, 3) or var['elements'] or var['size'] > 16:
                    row = (address - var['offset']) // 16
                    start = var['offset'] % 16 // 4 if row == 0 else 0
                    base_reg = (var['offset'] + row * 16) // 16
                    if base_reg != register:
                        row = register - var['offset'] // 16
                    return '%s[%d]' % (var['name'], row), [c - start for c in components]
                start = var['offset'] % 16 // 4
                rebased = [c - start for c in components]
                if any(c < 0 or c >= max(var['columns'], 1) for c in rebased):
                    return None, None
                if var['columns'] <= 1 and var['class'] == 0:
                    return var['name'], None
                return var['name'], rebased
        return None, None


class Decompiler:
    def __init__(self, shader):
        self.shader = shader
        self.namer = Namer(shader)
        self.lines = []
        self.depth = 1
        self.icb = None
        self.indexable = {}
        self.resource_dims = {}
        self.uav_dims = {}
        self.structured = {}
        for declaration in shader.declarations:
            name = declaration.name
            if name == 'customdata' and declaration.custom['class'] == 3:
                self.icb = declaration.custom['words']
            elif name == 'dcl_indexableTemp':
                reg, count, comps = declaration.extra[:3]
                self.indexable[reg] = (count, comps)
            elif name in ('dcl_resource', 'dcl_uav_typed') and declaration.operands:
                index = declaration.operands[0].indices[0][0]
                target = self.resource_dims if name == 'dcl_resource' else self.uav_dims
                target[index] = (declaration.control(11, 15), declaration.extra[0] if declaration.extra else 0x5555)
            elif name in ('dcl_resource_structured', 'dcl_uav_structured', 'dcl_resource_raw',
                          'dcl_uav_raw', 'dcl_tgsm_raw', 'dcl_tgsm_structured') and declaration.operands:
                index = declaration.operands[0].indices[0][0]
                kind = declaration.operands[0].type
                self.structured[(kind, index)] = (name, declaration.extra[0] if declaration.extra else 0)

    # ------------------------------------------------------------------ operands

    def literal(self, word, as_float):
        if as_float is None:
            as_float = looks_like_float(word)
        if as_float:
            text = float_text(word)
            if '.' in text:
                text = text.rstrip('0')
                text = text + '0' if text.endswith('.') else text
            return text
        signed = word - (1 << 32) if word & 0x80000000 else word
        return str(signed) if -0x100000 < signed < 0x100000 else '0x%08x' % word

    def register_name(self, operand, components):
        """(base expression, rebased components or None) for a non-immediate operand."""
        reg = OPERAND_TYPES.get(operand.type, 'op%d' % operand.type)
        indices = operand.indices
        first = indices[0][0] if indices else None
        relative = indices[0][1] if indices else None
        if operand.type == 1 and relative is None and len(indices) == 1:
            name, rebased = self.namer.signature_name(self.namer.inputs, 'input', first, components)
            if name:
                return name, rebased
        if operand.type == 2 and relative is None and len(indices) == 1:
            name, rebased = self.namer.signature_name(self.namer.outputs, 'output', first, components)
            if name:
                return name, rebased
        if reg in SYSTEM_SEMANTICS:
            self.namer.system_inputs.add(reg)
            return reg, components
        if reg in SYSTEM_OUTPUTS:
            return 'output.' + SYSTEM_OUTPUTS[reg][1], None
        if operand.type == 8:  # constant buffer
            slot = first
            if len(indices) > 1 and indices[1][1] is None:
                name, rebased = self.namer.cb_name(slot, indices[1][0], components)
                if name:
                    return name, rebased
            label = self.namer.bindings.get('cb%d' % slot, 'cb%d' % slot)
            index = self.index_text(indices[1]) if len(indices) > 1 else '0'
            return '%s[%s]' % (label if label.startswith('cb') else 'cb%d' % slot, index), components
        if operand.type == 9:
            return 'icb[%s]' % self.index_text(indices[0]), components
        if operand.type == 3:
            return 'x%d[%s]' % (first, self.index_text(indices[1])), components
        if operand.type in (6, 7, 30):
            prefix = {6: 's', 7: 't', 30: 'u'}[operand.type]
            key = '%s%d' % (prefix, first)
            return self.namer.bindings.get(key, key), components
        if operand.type == 31:
            return 'g%d' % first, components
        if relative is not None:
            return '%s[%s]' % (reg, self.index_text(indices[0])), components
        if indices:
            suffix = ''.join('[%s]' % self.index_text(i) for i in indices[1:])
            return '%s%d%s' % (reg, first, suffix), components
        return reg, components

    def index_text(self, index):
        immediate, relative = index
        if relative is None:
            return str(immediate)
        text = self.source(relative, [relative.components()[0]] if relative.components() else [0], False)
        return '%s + %d' % (text, immediate) if immediate else text

    def source(self, operand, components, as_float):
        """Text of a source operand restricted to `components` (indices into xyzw)."""
        if operand.type in (4, 5):
            if operand.type == 5:
                values = ['%r' % struct.unpack('<d', struct.pack('<Q', w))[0] for w in operand.values]
                text = values[0] if len(values) == 1 else 'double%d(%s)' % (len(values), ', '.join(values))
            else:
                words = operand.values if len(operand.values) == 1 else [operand.values[c] for c in components]
                literals = [self.literal(w, as_float) for w in words]
                if len(literals) == 1 or len(set(literals)) == 1:
                    text = literals[0]
                else:
                    kind = 'float' if as_float or (as_float is None and any(looks_like_float(w) for w in words)) else 'int'
                    text = '%s%d(%s)' % (kind, len(literals), ', '.join(literals))
        else:
            base, rebased = self.register_name(operand, components)
            text = base
            if rebased is not None and operand.num_components == 4:
                text += '.' + ''.join(COMPONENTS[c] if 0 <= c < 4 else '?' for c in rebased)
        if operand.modifier in (2, 3):
            text = 'abs(%s)' % text
        if operand.modifier in (1, 3):
            text = '-' + text if text[0].isalnum() or text[0] in '(_' else '-(%s)' % text
        return text

    def picked(self, operand, dest_components, count=None):
        """Source components matching the destination mask (or the first `count`)."""
        if operand.type in (4, 5):
            # Immediate vectors carry one value per destination component position.
            if len(operand.values) == 1:
                return [0]
            if count is not None:
                return list(range(min(count, len(operand.values))))
            return list(dest_components) or [0]
        swizzle = operand.components() if operand.num_components == 4 else [0]
        if not swizzle:
            return [0]
        if count is not None:
            return [swizzle[i] if i < len(swizzle) else swizzle[-1] for i in range(count)]
        if operand.num_components == 4 and operand.selection == 1:
            return [operand.swizzle[c] for c in dest_components]
        if operand.num_components == 4 and operand.selection == 2:
            return [operand.select1]
        if operand.num_components == 4 and operand.selection == 0:
            return [c for c in range(4) if operand.mask & (1 << c)] or [0]
        return [0]

    def dest(self, operand):
        components = operand.components() if operand.num_components == 4 else [0]
        base, rebased = self.register_name(operand, components)
        if rebased is not None and operand.num_components == 4:
            return base + '.' + ''.join(COMPONENTS[c] for c in rebased), components
        return base, components

    # ------------------------------------------------------------------ statements

    def emit(self, text):
        self.lines.append('    ' * self.depth + text)

    def assign(self, instruction, expression, dest_operand=None):
        operand = dest_operand or instruction.operands[0]
        if operand.type == 13:  # null destination
            return
        target, _ = self.dest(operand)
        if instruction.saturate:
            expression = 'saturate(%s)' % expression
        self.emit('%s = %s;' % (target, expression))

    def statement(self, instruction):
        name = instruction.name
        ops = instruction.operands
        as_float = literal_kind(name)
        if name in ('loop',):
            self.emit('while (true) {')
            self.depth += 1
            return
        if name in ('endloop', 'endif', 'endswitch'):
            self.depth = max(1, self.depth - 1)
            self.emit('}')
            return
        if name == 'else':
            self.depth = max(1, self.depth - 1)
            self.emit('} else {')
            self.depth += 1
            return
        if name in ('if', 'breakc', 'continuec', 'retc', 'discard', 'callc'):
            condition = self.source(ops[0], self.picked(ops[0], [0], 1), None)
            test = '%s != 0' % condition if instruction.test_nonzero else '%s == 0' % condition
            if name == 'if':
                self.emit('if (%s) {' % test)
                self.depth += 1
            else:
                action = {'breakc': 'break;', 'continuec': 'continue;', 'retc': self.return_text(),
                          'discard': 'discard;', 'callc': 'label_%s();' % self.source(ops[1], [0], False)
                          if len(ops) > 1 else 'call();'}[name]
                self.emit('if (%s) %s' % (test, action))
            return
        if name == 'break':
            self.emit('break;')
            return
        if name == 'continue':
            self.emit('continue;')
            return
        if name == 'ret':
            if self.depth > 1:
                self.emit(self.return_text())
            return
        if name == 'switch':
            self.emit('switch (%s) {' % self.source(ops[0], self.picked(ops[0], [0], 1), False))
            self.depth += 1
            return
        if name == 'case':
            self.emit('case %s:' % self.source(ops[0], [0], False))
            return
        if name == 'default':
            self.emit('default:')
            return
        if name == 'label':
            self.emit('// label %s' % self.source(ops[0], [0], False))
            return
        if name == 'call':
            self.emit('label_%s();' % self.source(ops[0], [0], False))
            return
        if name in ('nop', 'hs_decls'):
            return
        if name in ('emit', 'emit_stream'):
            self.emit('stream.Append(output);')
            return
        if name in ('cut', 'cut_stream'):
            self.emit('stream.RestartStrip();')
            return
        if name == 'emitthencut' or name == 'emitthencut_stream':
            self.emit('stream.Append(output); stream.RestartStrip();')
            return
        if name == 'sync':
            flags = instruction.control(11, 14)
            barrier = 'AllMemoryBarrier' if flags & 4 else 'GroupMemoryBarrier' if flags & 2 else 'DeviceMemoryBarrier'
            self.emit('%s%s();' % (barrier, 'WithGroupSync' if flags & 1 else ''))
            return
        if name in ('abort', 'debug_break'):
            self.emit('%s();' % name)
            return
        if not ops:
            self.emit('// %s' % name)
            return
        dest_components = ops[0].components() if ops[0].num_components == 4 else [0]

        def src(index, count=None, kind=as_float):
            return self.source(ops[index], self.picked(ops[index], dest_components, count), kind)

        if name == 'mov' or name == 'dmov':
            self.assign(instruction, src(1, kind=None))
        elif name in BINARY:
            self.assign(instruction, '%s %s %s' % (self.wrap(src(1)), BINARY[name], self.wrap(src(2))))
        elif name in COMPARE:
            self.assign(instruction, '(%s %s %s) ? 0xffffffff : 0' % (src(1), COMPARE[name], src(2)))
        elif name in CALLS:
            self.assign(instruction, '%s(%s, %s)' % (CALLS[name], src(1), src(2)))
        elif name in ('mad', 'imad', 'umad', 'dfma'):
            self.assign(instruction, '%s * %s + %s' % (self.wrap(src(1)), self.wrap(src(2)), self.wrap(src(3))))
        elif name in ('dp2', 'dp3', 'dp4'):
            count = int(name[2])
            self.assign(instruction, 'dot(%s, %s)' % (src(1, count), src(2, count)))
        elif name in UNARY:
            function = UNARY[name]
            argument = src(1)
            self.assign(instruction, '%s%s' % (function, argument) if function.startswith('(')
                        and (argument.isidentifier() or '.' in argument and ' ' not in argument)
                        else '%s(%s)' % (function, argument))
        elif name in ('ineg',):
            self.assign(instruction, '-' + self.wrap(src(1)))
        elif name == 'not':
            self.assign(instruction, '~' + self.wrap(src(1)))
        elif name in ('movc', 'dmovc', 'swapc'):
            if name == 'swapc':
                self.emit('// swapc')
                self.assign(instruction, '%s ? %s : %s' % (self.source(ops[2], self.picked(ops[2], dest_components), None),
                                                          self.source(ops[4], self.picked(ops[4], dest_components), None),
                                                          self.source(ops[3], self.picked(ops[3], dest_components), None)))
            else:
                self.assign(instruction, '%s ? %s : %s' % (src(1, kind=None), src(2, kind=None), src(3, kind=None)))
        elif name == 'sincos':
            argument = self.source(ops[2], self.picked(ops[2], dest_components), True)
            if ops[0].type != 13:
                self.assign(instruction, 'sin(%s)' % argument, ops[0])
            if ops[1].type != 13:
                self.assign(instruction, 'cos(%s)' % argument, ops[1])
        elif name in ('udiv',):
            if ops[0].type != 13:
                self.assign(instruction, '%s / %s' % (self.wrap(self.source(ops[2], self.picked(ops[2], ops[0].components()), False)),
                                                      self.wrap(self.source(ops[3], self.picked(ops[3], ops[0].components()), False))), ops[0])
            if ops[1].type != 13:
                comps = ops[1].components()
                self.assign(instruction, '%s %% %s' % (self.wrap(self.source(ops[2], self.picked(ops[2], comps), False)),
                                                       self.wrap(self.source(ops[3], self.picked(ops[3], comps), False))), ops[1])
        elif name in ('imul', 'umul'):
            if ops[1].type != 13:
                comps = ops[1].components()
                self.assign(instruction, '%s * %s' % (self.wrap(self.source(ops[2], self.picked(ops[2], comps), False)),
                                                      self.wrap(self.source(ops[3], self.picked(ops[3], comps), False))), ops[1])
            if ops[0].type != 13:
                self.emit('// high 32 bits of the product go to %s' % self.dest(ops[0])[0])
        elif name in ('ubfe', 'ibfe'):
            self.assign(instruction, '(%s >> %s) & ((1 << %s) - 1)' % (self.wrap(src(3)), self.wrap(src(2)), src(1)))
        elif name == 'bfi':
            self.assign(instruction, 'bfi(%s, %s, %s, %s)' % (src(1), src(2), src(3), src(4)))
        elif name in ('uaddc', 'usubb'):
            op = '+' if name == 'uaddc' else '-'
            comps = ops[0].components()
            self.assign(instruction, '%s %s %s' % (self.source(ops[2], self.picked(ops[2], comps), False), op,
                                                   self.source(ops[3], self.picked(ops[3], comps), False)), ops[0])
        elif name == 'msad':
            self.assign(instruction, 'msad4(%s, %s, %s)' % (src(1), src(2), src(3)))
        elif name.startswith(('sample', 'gather4', 'ld', 'lod', 'resinfo', 'bufinfo', 'store_', 'eval_',
                              'sampleinfo', 'samplepos', 'atomic_', 'imm_atomic_', 'check_access')):
            self.resource_statement(instruction, dest_components)
        else:
            self.emit('// %s %s' % (name, ', '.join(self.source(o, o.components() or [0], None) for o in ops)))

    @staticmethod
    def wrap(text):
        """Parenthesise an expression only if it has an operator outside brackets."""
        depth = 0
        for index, char in enumerate(text):
            if char in '([':
                depth += 1
            elif char in ')]':
                depth -= 1
            elif depth == 0 and char == ' ' and index + 1 < len(text) and text[index + 1] in '+-*/?:&|^<>=%':
                return '(%s)' % text
        return text

    def coord_count(self, resource_operand, dims, default=2):
        index = resource_operand.indices[0][0] if resource_operand.indices else 0
        dim = dims.get(index, (0, 0))[0]
        return COORDS.get(dim, default)

    def result(self, instruction, call, resource_operand, dest_components):
        """Apply the resource swizzle (t0.xyzw) to the call result for the destination mask."""
        swizzle = resource_operand.components() if resource_operand.num_components == 4 else [0, 1, 2, 3]
        selected = [swizzle[c] if c < len(swizzle) else 0 for c in dest_components]
        return '%s.%s' % (call, ''.join(COMPONENTS[c] for c in selected))

    def resource_statement(self, instruction, dest_components):
        name = instruction.name.replace('_feedback', '')
        ops = instruction.operands
        if name.startswith(('sample', 'gather4', 'lod')) and name not in ('sampleinfo', 'samplepos'):
            texture = self.namer.bindings.get('t%d' % ops[2].indices[0][0], 't%d' % ops[2].indices[0][0])
            sampler = self.source(ops[3], [0], False) if len(ops) > 3 else 's?'
            count = self.coord_count(ops[2], self.resource_dims)
            coord = self.source(ops[1], self.picked(ops[1], [], count), True)
            offset = ''
            if instruction.sample_offsets and any(instruction.sample_offsets):
                offset = ', int%d(%s)' % (count if count > 1 else 1, ', '.join(map(str, instruction.sample_offsets[:count])))
            extra = [self.source(o, self.picked(o, [], 1), True) for o in ops[4:]]
            method, args = {
                'sample': ('Sample', [sampler, coord]),
                'sample_l': ('SampleLevel', [sampler, coord] + extra[:1]),
                'sample_b': ('SampleBias', [sampler, coord] + extra[:1]),
                'sample_c': ('SampleCmp', [sampler, coord] + extra[:1]),
                'sample_c_lz': ('SampleCmpLevelZero', [sampler, coord] + extra[:1]),
                'sample_d': ('SampleGrad', [sampler, coord] + [self.source(o, self.picked(o, [], count), True) for o in ops[4:6]]),
                'sample_clamp': ('Sample', [sampler, coord]),
                'sample_b_clamp': ('SampleBias', [sampler, coord] + extra[:1]),
                'sample_d_clamp': ('SampleGrad', [sampler, coord]),
                'sample_c_clamp': ('SampleCmp', [sampler, coord] + extra[:1]),
                'gather4': ('Gather', [sampler, coord]),
                'gather4_c': ('GatherCmp', [sampler, coord] + extra[:1]),
                'lod': ('CalculateLevelOfDetail', [sampler, coord]),
            }.get(name, (name, [sampler, coord]))
            if name in ('gather4_po', 'gather4_po_c'):
                texture = self.namer.bindings.get('t%d' % ops[3].indices[0][0], texture)
                sampler = self.source(ops[4], [0], False)
                method = 'Gather' if name == 'gather4_po' else 'GatherCmp'
                args = [sampler, coord, self.source(ops[2], self.picked(ops[2], [], 2), False)]
                if name == 'gather4_po_c':
                    args.append(self.source(ops[5], [0], True))
                call = '%s.%s(%s)' % (texture, method, ', '.join(args))
                self.assign(instruction, self.result(instruction, call, ops[3], dest_components))
                return
            call = '%s.%s(%s%s)' % (texture, method, ', '.join(args), offset)
            self.assign(instruction, self.result(instruction, call, ops[2], dest_components))
            return
        if name in ('ld', 'ld_ms'):
            texture = self.namer.bindings.get('t%d' % ops[2].indices[0][0], 't%d' % ops[2].indices[0][0])
            count = self.coord_count(ops[2], self.resource_dims) + (0 if name == 'ld_ms' else 1)
            coord = self.source(ops[1], self.picked(ops[1], [], count), False)
            args = coord if name == 'ld' else '%s, %s' % (coord, self.source(ops[3], [0], False))
            call = '%s.Load(%s)' % (texture, args)
            self.assign(instruction, self.result(instruction, call, ops[2], dest_components))
            return
        if name == 'ld_uav_typed':
            uav = self.source(ops[2], [0], False).split('.')[0]
            count = self.coord_count(ops[2], self.uav_dims)
            call = '%s[%s]' % (uav, self.source(ops[1], self.picked(ops[1], [], count), False))
            self.assign(instruction, self.result(instruction, call, ops[2], dest_components))
            return
        if name == 'store_uav_typed':
            uav = self.namer.bindings.get('u%d' % ops[0].indices[0][0], 'u%d' % ops[0].indices[0][0])
            count = self.coord_count(ops[0], self.uav_dims)
            coord = self.source(ops[1], self.picked(ops[1], [], count), False)
            value = self.source(ops[2], self.picked(ops[2], [0, 1, 2, 3]), None)
            self.emit('%s[%s] = %s;' % (uav, coord, value))
            return
        if name in ('ld_structured', 'ld_raw'):
            resource = ops[-1]
            label = self.resource_label(resource)
            if name == 'ld_structured':
                index = self.source(ops[1], self.picked(ops[1], [], 1), False)
                offset = self.source(ops[2], self.picked(ops[2], [], 1), False)
                call = '%s[%s]' % (label, index) if offset == '0' else '%s[%s].at_byte(%s)' % (label, index, offset)
            else:
                call = '%s.Load(%s)' % (label, self.source(ops[1], self.picked(ops[1], [], 1), False))
            self.assign(instruction, self.result(instruction, call, resource, dest_components))
            return
        if name in ('store_structured', 'store_raw'):
            label = self.resource_label(ops[0])
            mask = ops[0].components() or [0]
            if name == 'store_structured':
                index = self.source(ops[1], self.picked(ops[1], [], 1), False)
                offset = self.source(ops[2], self.picked(ops[2], [], 1), False)
                value = self.source(ops[3], self.picked(ops[3], mask), None)
                target = '%s[%s]' % (label, index) if offset == '0' else '%s[%s].at_byte(%s)' % (label, index, offset)
                self.emit('%s = %s;' % (target, value))
            else:
                value = self.source(ops[2], self.picked(ops[2], mask), None)
                self.emit('%s.Store(%s, %s);' % (label, self.source(ops[1], self.picked(ops[1], [], 1), False), value))
            return
        if name in ('resinfo', 'bufinfo', 'sampleinfo', 'samplepos'):
            resource = ops[2] if name == 'resinfo' else ops[1]
            label = self.resource_label(resource)
            self.emit('%s = GetDimensions(%s)%s;  // %s' % (self.dest(ops[0])[0], label,
                      '' if name != 'resinfo' else ' at mip ' + self.source(ops[1], [0], False), name))
            return
        if name.startswith(('atomic_', 'imm_atomic_')):
            immediate = name.startswith('imm_')
            kind = name.split('atomic_', 1)[1]
            function = ATOMICS.get(kind, 'Interlocked_' + kind)
            if kind in ('alloc', 'consume'):
                self.assign(instruction, '%s.%s()' % (self.resource_label(ops[1]),
                                                      'IncrementCounter' if kind == 'alloc' else 'DecrementCounter'))
                return
            base = 1 if immediate else 0
            label = self.resource_label(ops[base])
            address = self.source(ops[base + 1], self.picked(ops[base + 1], [], 1), False)
            values = [self.source(o, self.picked(o, [], 1), False) for o in ops[base + 2:]]
            call = '%s(%s[%s], %s)' % (function, label, address, ', '.join(values))
            if immediate:
                self.emit('%s(%s[%s], %s, %s);' % (function, label, address, ', '.join(values), self.dest(ops[0])[0]))
            else:
                self.emit(call + ';')
            return
        if name.startswith('eval_'):
            self.assign(instruction, 'Evaluate%s(%s)' % ({'eval_snapped': 'AttributeSnapped', 'eval_sample_index': 'AttributeAtSample',
                                                          'eval_centroid': 'AttributeAtCentroid'}[name],
                                                         ', '.join(self.source(o, self.picked(o, dest_components), True) for o in ops[1:])))
            return
        self.emit('// %s' % name)

    def resource_label(self, operand):
        prefix = {7: 't', 30: 'u', 31: 'g'}.get(operand.type, 't')
        index = operand.indices[0][0] if operand.indices else 0
        key = '%s%d' % (prefix, index)
        return self.namer.bindings.get(key, key)

    def return_text(self):
        return 'return output;' if self.has_output() else 'return;'

    def has_output(self):
        return bool(self.shader.outputs) and self.shader.program != 'cs'

    # ------------------------------------------------------------------ module

    def declarations(self):
        out = []
        shader = self.shader
        for cb_binding in [b for b in shader.bindings if b['type'] in ('cbuffer', 'tbuffer')]:
            cb = next((c for c in shader.cbuffers if c['name'] == cb_binding['name']), None)
            out.append('%s %s : register(b%d)' % (cb_binding['type'], cb_binding['name'], cb_binding['register']))
            out.append('{')
            for var in (cb['variables'] if cb else []):
                array = '[%d]' % var['elements'] if var['elements'] else ''
                kind = ('row_major ' if var['class'] == 2 else '') + var['type']
                out.append('    %-14s %s%s;%s' % (kind, var['name'], array,
                                                    '' if var['used'] else '  // unused'))
            out.append('};')
            out.append('')
        for binding in shader.bindings:
            kind = binding['type']
            if kind in ('cbuffer', 'tbuffer'):
                continue
            ret = RETURN_HLSL.get(binding['returnType'], 'float')
            components = ((binding['flags'] >> 2) & 3) + 1
            element = ret if components == 1 or ret.startswith(('unorm', 'snorm')) else '%s%d' % (ret, components)
            if kind == 'sampler':
                decl = '%s %s : register(s%d);' % ('SamplerComparisonState' if binding['flags'] & 2 else 'SamplerState',
                                                   binding['name'], binding['register'])
            elif kind == 'texture':
                dim = SRV_DIMENSIONS.get(binding['dimension'], 'Texture2D')
                decl = '%s<%s> %s : register(t%d);' % (dim, element, binding['name'], binding['register'])
            elif kind == 'structured':
                stride = self.structured.get((7, binding['register']), ('', 0))[1]
                decl = 'StructuredBuffer<%s> %s : register(t%d);  // stride %d' % (
                    'float4' if stride == 16 else 'uint%d' % max(1, stride // 4) if stride and stride <= 16 else 'Element',
                    binding['name'], binding['register'], stride)
            elif kind == 'byteaddress':
                decl = 'ByteAddressBuffer %s : register(t%d);' % (binding['name'], binding['register'])
            elif kind == 'uav_typed':
                dim = SRV_DIMENSIONS.get(binding['dimension'], 'Texture2D')
                decl = 'RW%s<%s> %s : register(u%d);' % (dim, element, binding['name'], binding['register'])
            elif kind in ('uav_structured', 'uav_append', 'uav_consume', 'uav_structured_counter'):
                stride = self.structured.get((30, binding['register']), ('', 0))[1]
                prefix = {'uav_append': 'AppendStructuredBuffer', 'uav_consume': 'ConsumeStructuredBuffer'}.get(kind, 'RWStructuredBuffer')
                decl = '%s<%s> %s : register(u%d);  // stride %d' % (
                    prefix, 'float4' if stride == 16 else 'Element', binding['name'], binding['register'], stride)
            elif kind == 'uav_byteaddress':
                decl = 'RWByteAddressBuffer %s : register(u%d);' % (binding['name'], binding['register'])
            else:
                decl = '// %s %s : register(%d)' % (kind, binding['name'], binding['register'])
            out.append(decl)
        if not shader.bindings:
            for declaration in shader.declarations:
                if declaration.name == 'dcl_constantbuffer':
                    o = declaration.operands[0]
                    out.append('cbuffer cb%d : register(b%d) { float4 cb%d[%d]; };' % (
                        o.indices[0][0], o.indices[0][0], o.indices[0][0], o.indices[1][0] if len(o.indices) > 1 else 1))
                elif declaration.name == 'dcl_sampler':
                    out.append('SamplerState s%d : register(s%d);' % ((declaration.operands[0].indices[0][0],) * 2))
                elif declaration.name == 'dcl_resource':
                    index = declaration.operands[0].indices[0][0]
                    out.append('Texture2D<float4> t%d : register(t%d);' % (index, index))
                elif declaration.name in ('dcl_uav_typed', 'dcl_uav_raw', 'dcl_uav_structured'):
                    index = declaration.operands[0].indices[0][0]
                    out.append('RWTexture2D<float4> u%d : register(u%d);' % (index, index))
        for declaration in shader.declarations:
            if declaration.name in ('dcl_tgsm_raw', 'dcl_tgsm_structured'):
                index = declaration.operands[0].indices[0][0]
                if declaration.name == 'dcl_tgsm_raw':
                    out.append('groupshared uint g%d[%d];' % (index, declaration.extra[0] // 4))
                else:
                    stride, count = declaration.extra[:2]
                    out.append('groupshared uint g%d[%d][%d];' % (index, count, max(1, stride // 4)))
        if self.icb:
            rows = []
            for i in range(0, len(self.icb), 4):
                rows.append('    { %s }' % ', '.join(self.literal(w, None) for w in self.icb[i:i + 4]))
            out.append('static const float4 icb[%d] = {\n%s\n};' % (len(rows), ',\n'.join(rows)))
        return out

    def struct(self, name, elements):
        lines = ['struct %s' % name, '{']
        for element in elements:
            count = bin(element['mask']).count('1')
            field = element['name']
            if not field.upper().startswith('SV_') or element['index']:
                field = '%s%d' % (field, element['index'])
            semantic = element['name'] + (str(element['index']) if element['index'] else '')
            lines.append('    %-8s %-20s : %-18s // %s%d.%s' % (
                _type_for(element['componentType'], count), field, semantic + ';',
                'v' if name.endswith('Input') else 'o', element['register'],
                ''.join(COMPONENTS[i] for i in range(4) if element['mask'] & (1 << i))))
        lines.append('};')
        return lines

    def run(self):
        shader = self.shader
        body_start = len(self.lines)
        for instruction in shader.instructions:
            self.statement(instruction)
        body = self.lines[body_start:]
        header = ['// %s shader (%s), decompiled by CyDecompilator from DXBC bytecode.'
                  % (shader.program_name, shader.profile),
                  '// Temporaries r# are untyped 32-bit registers, as in the bytecode.']
        if shader.creator:
            header.append('// Original compiler: ' + shader.creator)
        header.append('')
        header += self.declarations()
        header.append('')
        prefix = {'ps': 'PS', 'vs': 'VS', 'gs': 'GS', 'hs': 'HS', 'ds': 'DS', 'cs': 'CS'}.get(shader.program, 'Shader')
        parameters = []
        if shader.inputs:
            header += self.struct(prefix + 'Input', shader.inputs)
            header.append('')
            parameters.append('%sInput input' % prefix)
        outputs = [e for e in shader.outputs]
        system_outputs = set()
        for instruction in shader.instructions:
            for operand in instruction.operands:
                register = OPERAND_TYPES.get(operand.type)
                if register in SYSTEM_OUTPUTS:
                    system_outputs.add(register)
        if outputs or system_outputs:
            struct_lines = self.struct(prefix + 'Output', outputs)
            for register in sorted(system_outputs):
                kind, semantic = SYSTEM_OUTPUTS[register]
                struct_lines.insert(-1, '    %-8s %-20s : %s;' % (kind, semantic, semantic))
            header += struct_lines
            header.append('')
        for register in sorted(self.namer.system_inputs):
            kind, semantic = SYSTEM_SEMANTICS[register]
            parameters.append('%s %s : %s' % (kind, register, semantic))
        attributes = []
        if shader.thread_group:
            attributes.append('[numthreads(%d, %d, %d)]' % shader.thread_group)
        returns = (prefix + 'Output') if (outputs or system_outputs) and shader.program != 'cs' else 'void'
        signature = '%s main(%s)' % (returns, ', '.join(parameters))
        temps = ['r%d' % i for i in range(shader.temps)]
        prologue = []
        if returns != 'void':
            prologue.append('    %s output;' % returns)
        if temps:
            prologue.append('    float4 %s;' % ', '.join(temps))
        for register, (count, comps) in sorted(self.indexable.items()):
            prologue.append('    float%s x%d[%d];' % (comps if comps > 1 else '', register, count))
        epilogue = ['    return output;'] if returns != 'void' else []
        return '\n'.join(header + attributes + [signature, '{'] + prologue + ([''] if prologue else [])
                         + body + epilogue + ['}']) + '\n'


def decompile(shader):
    return Decompiler(shader).run()
