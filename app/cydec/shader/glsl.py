"""SPIR-V to GLSL.

Control flow is rebuilt from the structured-control-flow rules SPIR-V guarantees for
shaders: every selection header names its merge block (OpSelectionMerge) and every loop
header names its merge and continue blocks (OpLoopMerge), so if/else, switch and loops
are recovered without guessing. Values used once are inlined into the expression that
uses them; loads from mutable memory are only inlined when nothing can write between the
load and its use. Phi nodes become variables assigned at the end of each predecessor.
"""
import re
import struct

from .spirv import BUILTINS, DIMS, STORAGE, constant_value, format_float

GLSL_STD = {
    1: ('round',), 2: ('roundEven',), 3: ('trunc',), 4: ('abs',), 5: ('abs',), 6: ('sign',), 7: ('sign',),
    8: ('floor',), 9: ('ceil',), 10: ('fract',), 11: ('radians',), 12: ('degrees',), 13: ('sin',),
    14: ('cos',), 15: ('tan',), 16: ('asin',), 17: ('acos',), 18: ('atan',), 19: ('sinh',), 20: ('cosh',),
    21: ('tanh',), 22: ('asinh',), 23: ('acosh',), 24: ('atanh',), 25: ('atan',), 26: ('pow',),
    27: ('exp',), 28: ('log',), 29: ('exp2',), 30: ('log2',), 31: ('sqrt',), 32: ('inversesqrt',),
    33: ('determinant',), 34: ('inverse',), 35: ('modf',), 36: ('modfStruct',), 37: ('min',), 38: ('min',),
    39: ('min',), 40: ('max',), 41: ('max',), 42: ('max',), 43: ('clamp',), 44: ('clamp',), 45: ('clamp',),
    46: ('mix',), 47: ('mix',), 48: ('step',), 49: ('smoothstep',), 50: ('fma',), 51: ('frexp',),
    52: ('frexpStruct',), 53: ('ldexp',), 54: ('packSnorm4x8',), 55: ('packUnorm4x8',), 56: ('packSnorm2x16',),
    57: ('packUnorm2x16',), 58: ('packHalf2x16',), 59: ('packDouble2x32',), 60: ('unpackSnorm2x16',),
    61: ('unpackUnorm2x16',), 62: ('unpackHalf2x16',), 63: ('unpackSnorm4x8',), 64: ('unpackUnorm4x8',),
    65: ('unpackDouble2x32',), 66: ('length',), 67: ('distance',), 68: ('cross',), 69: ('normalize',),
    70: ('faceforward',), 71: ('reflect',), 72: ('refract',), 73: ('findLSB',), 74: ('findMSB',),
    75: ('findMSB',), 76: ('interpolateAtCentroid',), 77: ('interpolateAtSample',),
    78: ('interpolateAtOffset',), 79: ('min',), 80: ('max',), 81: ('clamp',),
}

# name: (operator, precedence) for binary ops; lower precedence binds tighter.
BINARY = {
    'OpIAdd': ('+', 4), 'OpFAdd': ('+', 4), 'OpISub': ('-', 4), 'OpFSub': ('-', 4), 'OpIMul': ('*', 3),
    'OpFMul': ('*', 3), 'OpUDiv': ('/', 3), 'OpSDiv': ('/', 3), 'OpFDiv': ('/', 3), 'OpUMod': ('%', 3),
    'OpSRem': ('%', 3), 'OpSMod': ('%', 3), 'OpVectorTimesScalar': ('*', 3), 'OpMatrixTimesScalar': ('*', 3),
    'OpVectorTimesMatrix': ('*', 3), 'OpMatrixTimesVector': ('*', 3), 'OpMatrixTimesMatrix': ('*', 3),
    'OpShiftRightLogical': ('>>', 5), 'OpShiftRightArithmetic': ('>>', 5), 'OpShiftLeftLogical': ('<<', 5),
    'OpBitwiseOr': ('|', 10), 'OpBitwiseXor': ('^', 9), 'OpBitwiseAnd': ('&', 8), 'OpLogicalOr': ('||', 12),
    'OpLogicalAnd': ('&&', 11), 'OpLogicalEqual': ('==', 7), 'OpLogicalNotEqual': ('!=', 7),
    'OpIEqual': ('==', 7), 'OpINotEqual': ('!=', 7), 'OpUGreaterThan': ('>', 6), 'OpSGreaterThan': ('>', 6),
    'OpUGreaterThanEqual': ('>=', 6), 'OpSGreaterThanEqual': ('>=', 6), 'OpULessThan': ('<', 6),
    'OpSLessThan': ('<', 6), 'OpULessThanEqual': ('<=', 6), 'OpSLessThanEqual': ('<=', 6),
    'OpFOrdEqual': ('==', 7), 'OpFUnordEqual': ('==', 7), 'OpFOrdNotEqual': ('!=', 7),
    'OpFUnordNotEqual': ('!=', 7), 'OpFOrdLessThan': ('<', 6), 'OpFUnordLessThan': ('<', 6),
    'OpFOrdGreaterThan': ('>', 6), 'OpFUnordGreaterThan': ('>', 6), 'OpFOrdLessThanEqual': ('<=', 6),
    'OpFUnordLessThanEqual': ('<=', 6), 'OpFOrdGreaterThanEqual': ('>=', 6), 'OpFUnordGreaterThanEqual': ('>=', 6),
}
VECTOR_COMPARE = {'==': 'equal', '!=': 'notEqual', '<': 'lessThan', '<=': 'lessThanEqual',
                  '>': 'greaterThan', '>=': 'greaterThanEqual'}
CALLS = {
    'OpFRem': 'mod', 'OpFMod': 'mod', 'OpDot': 'dot', 'OpOuterProduct': 'outerProduct', 'OpTranspose': 'transpose',
    'OpAny': 'any', 'OpAll': 'all', 'OpIsNan': 'isnan', 'OpIsInf': 'isinf', 'OpDPdx': 'dFdx', 'OpDPdy': 'dFdy',
    'OpFwidth': 'fwidth', 'OpDPdxFine': 'dFdxFine', 'OpDPdyFine': 'dFdyFine', 'OpFwidthFine': 'fwidthFine',
    'OpDPdxCoarse': 'dFdxCoarse', 'OpDPdyCoarse': 'dFdyCoarse', 'OpFwidthCoarse': 'fwidthCoarse',
    'OpBitReverse': 'bitfieldReverse', 'OpBitCount': 'bitCount', 'OpBitFieldInsert': 'bitfieldInsert',
    'OpBitFieldSExtract': 'bitfieldExtract', 'OpBitFieldUExtract': 'bitfieldExtract',
    'OpImageQuerySize': 'imageSize', 'OpImageQuerySizeLod': 'textureSize', 'OpImageQueryLevels': 'textureQueryLevels',
    'OpImageQuerySamples': 'textureSamples', 'OpImageQueryLod': 'textureQueryLod', 'OpArrayLength': 'length',
    'OpGroupNonUniformElect': 'subgroupElect', 'OpGroupNonUniformAll': 'subgroupAll',
    'OpGroupNonUniformAny': 'subgroupAny', 'OpGroupNonUniformBroadcastFirst': 'subgroupBroadcastFirst',
    'OpGroupNonUniformBallot': 'subgroupBallot', 'OpGroupNonUniformFAdd': 'subgroupAdd',
    'OpGroupNonUniformIAdd': 'subgroupAdd', 'OpGroupNonUniformFMin': 'subgroupMin',
    'OpGroupNonUniformFMax': 'subgroupMax',
}
CASTS = {'OpConvertFToU': 'uint', 'OpConvertFToS': 'int', 'OpConvertSToF': 'float', 'OpConvertUToF': 'float',
         'OpUConvert': 'uint', 'OpSConvert': 'int', 'OpFConvert': 'float', 'OpBitcast': None,
         'OpQuantizeToF16': None, 'OpSatConvertSToU': 'uint', 'OpSatConvertUToS': 'int'}
SIDE_EFFECTS = {'OpStore', 'OpFunctionCall', 'OpImageWrite', 'OpControlBarrier', 'OpMemoryBarrier',
                'OpEmitVertex', 'OpEndPrimitive', 'OpCopyMemory', 'OpAtomicStore'} | {
    'OpAtomic' + x for x in ('Exchange', 'CompareExchange', 'IIncrement', 'IDecrement', 'IAdd', 'ISub',
                             'SMin', 'UMin', 'SMax', 'UMax', 'And', 'Or', 'Xor')}
READ_ONLY_STORAGE = {0, 1, 2, 9}  # UniformConstant, Input, Uniform, PushConstant
GLSL_KEYWORDS = {'input', 'output', 'filter', 'sample', 'texture', 'packed', 'common', 'partition', 'active',
                 'in', 'out', 'inout', 'uniform', 'buffer', 'shared', 'attribute', 'varying', 'layout',
                 'main', 'discard', 'return', 'true', 'false', 'struct', 'precision', 'highp', 'mediump',
                 'lowp', 'float', 'int', 'uint', 'bool', 'void', 'mat2', 'mat3', 'mat4', 'vec2', 'vec3',
                 'vec4', 'switch', 'case', 'default', 'while', 'for', 'do', 'if', 'else', 'break', 'continue'}
SWIZZLE = 'xyzw'
MODEL_NAMES = {'Vertex': 'Vertex', 'Fragment': 'Fragment', 'GLCompute': 'Compute', 'Geometry': 'Geometry',
               'TessellationControl': 'Tessellation control', 'TessellationEvaluation': 'Tessellation evaluation'}


class Expression:
    __slots__ = ('text', 'precedence', 'compare')

    def __init__(self, text, precedence=0, compare=None):
        self.text = text
        self.precedence = precedence
        self.compare = compare  # (left text, operator, right text) for scalar comparisons


INVERSE = {'<': '>=', '>=': '<', '>': '<=', '<=': '>', '==': '!=', '!=': '=='}
# Operand positions holding literals rather than ids, per opcode name.
LITERAL_FROM = {'OpCompositeExtract': 1, 'OpCompositeInsert': 2, 'OpVectorShuffle': 2}


def id_operands(instruction):
    ops = instruction.operands
    name = instruction.name
    if name in LITERAL_FROM:
        return ops[:LITERAL_FROM[name]]
    if name == 'OpExtInst':
        return ops[:1] + ops[2:]
    if name == 'OpSwitch':
        return [ops[0], ops[1]] + [ops[i] for i in range(3, len(ops), 2)]
    if name.startswith('OpImageSample') or name in ('OpImageFetch', 'OpImageGather', 'OpImageDrefGather', 'OpImageRead'):
        fixed = 3 if ('Dref' in name or 'Gather' in name) else 2
        return ops[:fixed] + ops[fixed + 1:]
    if name == 'OpImageWrite':
        return ops[:3] + ops[4:]
    return ops


class GlslWriter:
    def __init__(self, module):
        self.module = module
        self.names = {}
        self.used_names = set()
        self.values = {}
        self.lines = []
        self.depth = 0
        self.pointers = {}       # pointer id -> Expression of the pointed lvalue
        self.storage_of = {}     # pointer id -> storage class of its root variable
        self.member_builtin = {}
        for (struct_id, member), decorations in module.member_decorations.items():
            if 11 in decorations:
                self.member_builtin[(struct_id, member)] = BUILTINS.get(decorations[11][0], 'gl_Builtin%d' % decorations[11][0])

    # ------------------------------------------------------------------ naming

    def name(self, value, fallback=None):
        if value in self.names:
            return self.names[value]
        raw = self.module.names.get(value, '')
        raw = raw.split('(')[0]
        if raw.startswith('type.'):
            raw = raw[5:]
        raw = re.sub(r'[^A-Za-z0-9_]', '_', raw).strip('_')
        if not raw or raw[0].isdigit():
            raw = fallback or '_%d' % value
        if raw in GLSL_KEYWORDS or raw.startswith('gl_'):
            raw = raw + '_'
        candidate = raw
        counter = 1
        while candidate in self.used_names:
            counter += 1
            candidate = '%s_%d' % (raw, counter)
        self.used_names.add(candidate)
        self.names[value] = candidate
        return candidate

    def member(self, struct_id, index):
        name = self.module.member_names.get((struct_id, index), '')
        name = re.sub(r'[^A-Za-z0-9_]', '_', name)
        return name if name and not name[0].isdigit() else '_m%d' % index

    # ------------------------------------------------------------------ types

    def type_info(self, type_id):
        return self.module.types.get(type_id)

    def base_name(self, type_id):
        info = self.type_info(type_id)
        if info is None:
            return 'unknown'
        name, ops = info.name, info.operands
        if name == 'OpTypeFloat':
            return {16: 'float16_t', 32: 'float', 64: 'double'}.get(ops[0], 'float')
        if name == 'OpTypeInt':
            if ops[0] == 64:
                return 'int64_t' if ops[1] else 'uint64_t'
            return 'int' if ops[1] else 'uint'
        if name == 'OpTypeBool':
            return 'bool'
        return 'unknown'

    def type_name(self, type_id):
        info = self.type_info(type_id)
        if info is None:
            return 'unknown'
        name, ops = info.name, info.operands
        if name in ('OpTypeFloat', 'OpTypeInt', 'OpTypeBool'):
            return self.base_name(type_id)
        if name == 'OpTypeVoid':
            return 'void'
        if name == 'OpTypeVector':
            prefix = {'float': '', 'double': 'd', 'int': 'i', 'uint': 'u', 'bool': 'b'}.get(self.base_name(ops[0]), '')
            return '%svec%d' % (prefix, ops[1])
        if name == 'OpTypeMatrix':
            column = self.type_info(ops[0])
            rows = column.operands[1] if column is not None else 4
            cols = ops[1]
            prefix = 'd' if self.base_name(column.operands[0]) == 'double' else ''
            return '%smat%d' % (prefix, cols) if rows == cols else '%smat%dx%d' % (prefix, cols, rows)
        if name == 'OpTypeStruct':
            return self.name(type_id, 'Struct%d' % type_id)
        if name == 'OpTypeArray':
            return '%s[%s]' % (self.type_name(ops[0]), self.constant(ops[1]).text)
        if name == 'OpTypeRuntimeArray':
            return '%s[]' % self.type_name(ops[0])
        if name == 'OpTypePointer':
            return self.type_name(ops[1])
        if name in ('OpTypeImage', 'OpTypeSampledImage'):
            return self.image_type(type_id)
        if name == 'OpTypeSampler':
            return 'sampler'
        return name[6:]

    def image_type(self, type_id):
        info = self.type_info(type_id)
        sampled_image = info.name == 'OpTypeSampledImage'
        image = self.type_info(info.operands[0]) if sampled_image else info
        sampled_type, dim, depth, arrayed, ms, sampled = image.operands[:6]
        prefix = {'int': 'i', 'uint': 'u'}.get(self.base_name(sampled_type), '')
        dim_text = DIMS.get(dim, '2D')
        if dim_text == 'Rect':
            dim_text = '2DRect'
        suffix = ('MS' if ms else '') + ('Array' if arrayed else '')
        if dim_text == 'SubpassData':
            return '%ssubpassInput%s' % (prefix, 'MS' if ms else '')
        if dim_text == 'Buffer':
            return '%s%sBuffer' % (prefix, 'sampler' if sampled_image or sampled == 1 else 'image')
        if sampled_image:
            return '%ssampler%s%s%s' % (prefix, dim_text, suffix, 'Shadow' if depth == 1 else '')
        if sampled == 2:
            return '%simage%s%s' % (prefix, dim_text, suffix)
        return '%stexture%s%s' % (prefix, dim_text, suffix)

    def declaration(self, type_id, name):
        """`T name[N]` style declaration (arrays go after the name in GLSL)."""
        dims = ''
        info = self.type_info(type_id)
        while info is not None and info.name in ('OpTypeArray', 'OpTypeRuntimeArray'):
            dims += '[%s]' % (constant_value(self.module, info.operands[1]) if info.name == 'OpTypeArray' else '')
            type_id = info.operands[0]
            info = self.type_info(type_id)
        return '%s %s%s' % (self.type_name(type_id), name, dims)

    def components(self, type_id):
        info = self.type_info(type_id)
        if info is not None and info.name == 'OpTypeVector':
            return info.operands[1]
        return 1

    # ------------------------------------------------------------------ constants

    def constant(self, constant_id):
        instruction = self.module.constants.get(constant_id)
        if instruction is None:
            return Expression(self.name(constant_id))
        name = instruction.name
        if name in ('OpConstantTrue', 'OpSpecConstantTrue'):
            return Expression('true')
        if name in ('OpConstantFalse', 'OpSpecConstantFalse'):
            return Expression('false')
        if name in ('OpConstant', 'OpSpecConstant'):
            text = constant_value(self.module, constant_id)
            info = self.type_info(instruction.type)
            if info is not None and info.name == 'OpTypeInt' and not info.operands[1]:
                text += 'u'
            if name == 'OpSpecConstant' and constant_id in self.module.names:
                return Expression(self.name(constant_id))
            return Expression(text, 1 if text.startswith('-') else 0)
        if name in ('OpConstantComposite', 'OpSpecConstantComposite'):
            parts = [self.constant(c).text for c in instruction.operands]
            type_name = self.type_name(instruction.type)
            info = self.type_info(instruction.type)
            if info is not None and info.name == 'OpTypeVector' and len(set(parts)) == 1:
                return Expression('%s(%s)' % (type_name, parts[0]))
            if info is not None and info.name == 'OpTypeArray':
                type_name = self.type_name(info.operands[0]) + '[]'
            return Expression('%s(%s)' % (type_name, ', '.join(parts)))
        if name == 'OpConstantNull':
            return Expression('%s(0)' % self.type_name(instruction.type))
        if name == 'OpUndef':
            return Expression('%s(0) /* undef */' % self.type_name(instruction.type))
        return Expression(self.name(constant_id))

    # ------------------------------------------------------------------ values

    def value(self, value_id):
        if value_id in self.values:
            return self.values[value_id]
        if value_id in self.module.constants:
            return self.constant(value_id)
        if value_id in self.pointers:
            return self.pointers[value_id]
        return Expression(self.name(value_id))

    def wrap(self, expression, precedence, right=False):
        if expression.precedence > precedence or (right and expression.precedence == precedence and precedence > 2):
            return '(%s)' % expression.text
        return expression.text

    def emit(self, text):
        self.lines.append('    ' * self.depth + text)

    # ------------------------------------------------------------------ module

    def global_declarations(self):
        module = self.module
        out = []
        declared_structs = set()

        def struct_text(struct_id, indent=''):
            info = self.type_info(struct_id)
            lines = []
            for index, member_type in enumerate(info.operands):
                if (struct_id, index) in self.member_builtin:
                    continue
                layout = []
                decorations = module.member_decorations.get((struct_id, index), {})
                if 35 in decorations:
                    layout.append('offset = %d' % decorations[35][0])
                if 4 in decorations:
                    layout.append('row_major')
                prefix = 'layout(%s) ' % ', '.join(layout) if layout and len(layout) > 1 else ''
                lines.append('%s    %s%s;' % (indent, prefix, self.declaration(member_type, self.member(struct_id, index))))
            return lines

        def needed_structs(type_id, found):
            info = self.type_info(type_id)
            if info is None:
                return
            if info.name == 'OpTypeStruct':
                for member in info.operands:
                    needed_structs(member, found)
                if type_id not in found:
                    found.append(type_id)
            elif info.name in ('OpTypeArray', 'OpTypeRuntimeArray', 'OpTypePointer', 'OpTypeVector', 'OpTypeMatrix'):
                needed_structs(info.operands[0] if info.name != 'OpTypePointer' else info.operands[1], found)

        block_structs = set()
        for variable in module.globals:
            pointee = self.type_info(variable.type).operands[1]
            info = self.type_info(pointee)
            while info is not None and info.name in ('OpTypeArray', 'OpTypeRuntimeArray'):
                pointee = info.operands[0]
                info = self.type_info(pointee)
            if info is not None and info.name == 'OpTypeStruct':
                decorations = module.decorations.get(pointee, {})
                if 2 in decorations or 3 in decorations:
                    block_structs.add(pointee)
        # Plain structs used by blocks or variables are declared first.
        order = []
        for variable in module.globals:
            needed_structs(variable.type, order)
        for function in module.functions:
            for variable in function.variables:
                needed_structs(variable.type, order)
        for struct_id in order:
            if struct_id in block_structs or struct_id in declared_structs:
                continue
            if all((struct_id, i) in self.member_builtin for i in range(len(self.type_info(struct_id).operands))):
                continue
            declared_structs.add(struct_id)
            out.append('struct %s' % self.type_name(struct_id))
            out.append('{')
            out += struct_text(struct_id)
            out.append('};')
            out.append('')
        for variable in module.globals:
            storage = variable.operands[0]
            pointee = self.type_info(variable.type).operands[1]
            decorations = module.decorations.get(variable.result, {})
            if 11 in decorations:
                self.names[variable.result] = BUILTINS.get(decorations[11][0], 'gl_Builtin%d' % decorations[11][0])
                continue
            base = pointee
            info = self.type_info(base)
            while info is not None and info.name in ('OpTypeArray', 'OpTypeRuntimeArray'):
                base = info.operands[0]
                info = self.type_info(base)
            if info is not None and info.name == 'OpTypeStruct' and all(
                    (base, i) in self.member_builtin for i in range(len(info.operands))):
                self.names[variable.result] = '__builtin_block_%d' % variable.result
                continue
            layout = []
            for key, label in ((30, 'location'), (31, 'component'), (34, 'set'), (33, 'binding'),
                               (43, 'input_attachment_index')):
                if key in decorations:
                    layout.append('%s = %d' % (label, decorations[key][0]))
            qualifiers = []
            if 14 in decorations:
                qualifiers.append('flat')
            if 13 in decorations:
                qualifiers.append('noperspective')
            if 16 in decorations:
                qualifiers.append('centroid')
            if 24 in decorations:
                qualifiers.append('readonly')
            if 25 in decorations:
                qualifiers.append('writeonly')
            if 23 in decorations:
                qualifiers.append('coherent')
            storage_name = STORAGE.get(storage, '')
            block = base in block_structs
            block_decorations = module.decorations.get(base, {})
            if storage == 9:
                layout.insert(0, 'push_constant')
            if block and (storage == 12 or 3 in block_decorations):
                layout.insert(0, 'std430')
                keyword = 'buffer'
            elif block and storage in (2, 9):
                layout.insert(0, 'std140') if storage == 2 else None
                keyword = 'uniform'
            else:
                keyword = {'Input': 'in', 'Output': 'out', 'UniformConstant': 'uniform', 'Uniform': 'uniform',
                           'Workgroup': 'shared', 'Private': '', 'StorageBuffer': 'buffer',
                           'PushConstant': 'uniform'}.get(storage_name, '')
            prefix = ('layout(%s) ' % ', '.join(layout)) if layout else ''
            qualifier_text = ' '.join(qualifiers + ([keyword] if keyword else []))
            instance = self.name(variable.result, '_%d' % variable.result)
            if block:
                block_name = self.name(base, 'Block%d' % base)
                out.append('%s%s %s' % (prefix, qualifier_text, block_name))
                out.append('{')
                out += struct_text(base)
                dims = self.declaration(pointee, instance)[len(self.type_name(base)):].strip()
                out.append('} %s;' % dims)
            else:
                initializer = ''
                if len(variable.operands) > 1:
                    initializer = ' = ' + self.value(variable.operands[1]).text
                out.append('%s%s%s;' % (prefix, (qualifier_text + ' ') if qualifier_text else '',
                                        self.declaration(pointee, instance) + initializer))
        return out

    # ------------------------------------------------------------------ functions

    def function(self, function, entry=None):
        module = self.module
        self.values = {}
        self.pointers = {key: value for key, value in self.pointers.items() if key in self.global_ids}
        uses = {}
        position = {}
        for block in function.blocks:
            for instruction in block.instructions + ([block.terminator] if block.terminator else []):
                position[instruction.index] = block.label
                for operand in set(id_operands(instruction)):
                    uses[operand] = uses.get(operand, 0) + 1
                if instruction.type is not None:
                    uses[instruction.type] = uses.get(instruction.type, 0)
        self.uses = uses
        self.blocks = {block.label: block for block in function.blocks}
        self.emitted = set()
        self.phi_vars = {}
        self.loops = []
        params = []
        for parameter in function.parameters:
            pname = self.name(parameter.result, 'param%d' % parameter.result)
            info = self.type_info(parameter.type)
            if info is not None and info.name == 'OpTypePointer':
                self.pointers[parameter.result] = Expression(pname)
                params.append('inout ' + self.declaration(info.operands[1], pname))
            else:
                self.values[parameter.result] = Expression(pname)
                params.append(self.declaration(parameter.type, pname))
        name = 'main' if entry else self.name(function.id, 'function%d' % function.id)
        if entry:
            self.names[function.id] = 'main'
        header = '%s %s(%s)' % (self.type_name(function.return_type), name, ', '.join(params))
        self.lines = []
        self.depth = 1
        for variable in function.variables:
            vname = self.name(variable.result, 'local%d' % variable.result)
            self.pointers[variable.result] = Expression(vname)
            pointee = self.type_info(variable.type).operands[1]
            initializer = ''
            if len(variable.operands) > 1:
                initializer = ' = ' + self.value(variable.operands[1]).text
            self.emit('%s%s;' % (self.declaration(pointee, vname), initializer))
        for block in function.blocks:
            for instruction in block.instructions:
                if instruction.name == 'OpPhi':
                    vname = self.name(instruction.result, 'phi%d' % instruction.result)
                    self.phi_vars[instruction.result] = vname
                    self.values[instruction.result] = Expression(vname)
                    self.emit('%s;' % self.declaration(instruction.type, vname))
        if self.lines:
            self.emit('')
        self.function_return = function.return_type
        if function.blocks:
            self.sequence(function.blocks[0].label, set(), None)
        body = self.rewrite_loops(self.lines)
        while body and body[-1].strip() == 'return;':
            body.pop()
        return [header, '{'] + body + ['}']

    @staticmethod
    def rewrite_loops(lines):
        """for (;;) { if (c) { break; } ... }  ->  while (!c) { ... }"""
        result = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.strip() == 'for (;;)' and index + 5 < len(lines) and lines[index + 1].strip() == '{' \
                    and lines[index + 2].strip().startswith('if (') and lines[index + 3].strip() == '{' \
                    and lines[index + 4].strip() == 'break;' and lines[index + 5].strip() == '}':
                condition = lines[index + 2].strip()[4:-1]
                indent = line[:len(line) - len(line.lstrip())]
                negated = '!(%s)' % condition
                if condition.startswith('!') and condition[1:].replace('_', 'a').isalnum():
                    negated = condition[1:]
                for operator, inverse in ((' >= ', ' < '), (' < ', ' >= '), (' <= ', ' > '), (' > ', ' <= '),
                                          (' == ', ' != '), (' != ', ' == ')):
                    if condition.count(operator) == 1 and not any(o in condition for o in ('&&', '||', '?')):
                        negated = condition.replace(operator, inverse)
                        break
                result.append(indent + 'while (%s)' % negated)
                result.append(lines[index + 1])
                index += 6
                continue
            result.append(line)
            index += 1
        return result

    def phi_assignments(self, source_label, target_label):
        target = self.blocks.get(target_label)
        if target is None:
            return
        for instruction in target.instructions:
            if instruction.name != 'OpPhi':
                continue
            pairs = instruction.operands
            for index in range(0, len(pairs), 2):
                if pairs[index + 1] == source_label:
                    self.emit('%s = %s;' % (self.phi_vars[instruction.result], self.value(pairs[index]).text))

    def sequence(self, label, stops, follow):
        guard = 0
        while label is not None and label not in stops and guard < 100000:
            guard += 1
            if label in self.emitted:
                self.emit('// (control flow joins block %d)' % label)
                return
            block = self.blocks.get(label)
            if block is None:
                return
            if block.merge and block.merge[0] == 'loop':
                _, merge, cont = block.merge
                self.emit('for (;;)')
                self.emit('{')
                self.depth += 1
                self.loops.append((label, merge, cont))
                self.emitted.add(label)
                next_label = self.block_body(block, {merge, cont} | ({label} if cont != label else set()),
                                             cont, in_loop_header=True)
                if next_label is not None:
                    self.sequence(next_label, {merge, cont, label}, cont)
                if cont != label and cont not in self.emitted:
                    self.sequence(cont, {label, merge}, label)
                self.loops.pop()
                self.depth -= 1
                self.emit('}')
                label = merge
                continue
            self.emitted.add(label)
            label = self.block_body(block, stops, follow)

    def jump(self, source, target, follow, stops):
        """Text for an unconditional branch; returns the next label to continue with or None."""
        self.phi_assignments(source, target)
        if target == follow:
            return None
        if self.loops:
            header, merge, cont = self.loops[-1]
            if target == merge:
                self.emit('break;')
                return None
            if target == cont or target == header:
                self.emit('continue;')
                return None
        if target in stops:
            return None
        return target

    def block_body(self, block, stops, follow, in_loop_header=False):
        for instruction in block.instructions:
            self.instruction(instruction, block)
        terminator = block.terminator
        if terminator is None:
            return None
        name = terminator.name
        ops = terminator.operands
        if name == 'OpBranch':
            return self.jump(block.label, ops[0], follow, stops)
        if name == 'OpReturn':
            self.emit('return;')
            return None
        if name == 'OpReturnValue':
            self.emit('return %s;' % self.value(ops[0]).text)
            return None
        if name in ('OpKill', 'OpTerminateInvocation'):
            self.emit('discard;')
            return None
        if name == 'OpUnreachable':
            return None
        if name == 'OpBranchConditional':
            condition, true_label, false_label = ops[0], ops[1], ops[2]
            cond = self.value(condition)
            if block.merge and block.merge[0] == 'selection' or (in_loop_header and block.merge and block.merge[0] == 'loop'
                                                                and true_label not in self.loop_exits()
                                                                and false_label not in self.loop_exits()):
                merge = block.merge[1]
                return self.selection(block, cond, true_label, false_label, merge, stops)
            exits = self.loop_exits()
            if false_label in exits and true_label not in exits:
                self.emit('if (%s)' % self.negate(cond))
                self.emit('{')
                self.depth += 1
                self.jump(block.label, false_label, None, set())
                self.depth -= 1
                self.emit('}')
                return self.jump(block.label, true_label, follow, stops)
            if true_label in exits and false_label not in exits:
                self.emit('if (%s)' % cond.text)
                self.emit('{')
                self.depth += 1
                self.jump(block.label, true_label, None, set())
                self.depth -= 1
                self.emit('}')
                return self.jump(block.label, false_label, follow, stops)
            if true_label in exits and false_label in exits:
                self.emit('if (%s)' % cond.text)
                self.emit('{')
                self.depth += 1
                self.jump(block.label, true_label, None, set())
                self.depth -= 1
                self.emit('}')
                self.jump(block.label, false_label, None, set())
                return None
            merge = block.merge[1] if block.merge else None
            return self.selection(block, cond, true_label, false_label, merge, stops)
        if name == 'OpSwitch':
            selector = self.value(ops[0]).text
            default = ops[1]
            merge = block.merge[1] if block.merge else None
            cases = {}
            for index in range(2, len(ops), 2):
                cases.setdefault(ops[index + 1], []).append(ops[index])
            self.emit('switch (%s)' % selector)
            self.emit('{')
            inner = stops | ({merge} if merge else set())
            targets = list(cases.items())
            if default != merge:
                targets.append((default, None))
            for target, values in targets:
                if values is None:
                    self.emit('default:')
                else:
                    for value in values:
                        self.emit('case %d:' % (value - (1 << 32) if value & 0x80000000 else value))
                if target == default and values is not None and default != merge:
                    self.emit('default:')
                self.emit('{')
                self.depth += 1
                if target != merge:
                    self.loops.append((None, merge, None))
                    self.sequence(target, inner, merge)
                    self.loops.pop()
                self.emit('break;')
                self.depth -= 1
                self.emit('}')
            self.emit('}')
            if merge is None or merge in stops:
                return None
            return merge
        self.emit('// unsupported terminator ' + name)
        return None

    def loop_exits(self):
        exits = set()
        if self.loops:
            header, merge, cont = self.loops[-1]
            exits.add(merge)
            if cont is not None:
                exits.add(cont)
        return exits

    def negate(self, expression):
        if expression.compare is not None:
            left, operator, right = expression.compare
            return '%s %s %s' % (left, INVERSE[operator], right)
        if expression.text.startswith('!') and expression.precedence <= 1 and not expression.text.startswith('!('):
            return expression.text[1:]
        return '!' + self.wrap(expression, 1)

    def selection(self, block, cond, true_label, false_label, merge, stops):
        inner = stops | ({merge} if merge is not None else set())
        if true_label == merge:
            self.emit('if (%s)' % self.negate(cond))
            self.emit('{')
            self.depth += 1
            self.phi_assignments(block.label, true_label) if False else None
            self.branch(block.label, false_label, inner, merge)
            self.depth -= 1
            self.emit('}')
            self.phi_assignments(block.label, merge)
        else:
            self.emit('if (%s)' % cond.text)
            self.emit('{')
            self.depth += 1
            self.branch(block.label, true_label, inner, merge)
            self.depth -= 1
            self.emit('}')
            if false_label != merge:
                else_lines_start = len(self.lines)
                self.emit('else')
                self.emit('{')
                self.depth += 1
                self.branch(block.label, false_label, inner, merge)
                self.depth -= 1
                self.emit('}')
                # Collapse "else { if ... }" into "else if".
                body = self.lines[else_lines_start + 2:-1]
                if body and body[0].strip().startswith('if (') and self.single_statement(body):
                    indent = self.lines[else_lines_start][:len(self.lines[else_lines_start]) - len('else')]
                    self.lines[else_lines_start:] = [indent + 'else ' + body[0].strip()] + [
                        line[4:] if line.startswith('    ') else line for line in body[1:]]
            else:
                self.phi_assignments(block.label, merge)
        if merge is None or merge in stops:
            return None
        return merge

    @staticmethod
    def single_statement(lines):
        if not lines:
            return False
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

    def branch(self, source, target, stops, merge):
        self.phi_assignments(source, target)
        if target == merge:
            return
        if self.loops:
            header, loop_merge, cont = self.loops[-1]
            if target == loop_merge:
                self.emit('break;')
                return
            if target == cont and header is not None:
                self.emit('continue;')
                return
        self.sequence(target, stops, merge)

    # ------------------------------------------------------------------ instructions

    def inlinable(self, instruction, block):
        if self.uses.get(instruction.result, 0) != 1:
            return False
        name = instruction.name
        if name in ('OpFunctionCall', 'OpPhi', 'OpImageRead') or name.startswith('OpAtomic'):
            return False
        if name == 'OpLoad':
            storage = self.storage_of.get(instruction.operands[0])
            if storage in READ_ONLY_STORAGE:
                return True
            # Only inline when nothing in the block can write before the single use.
            seen = False
            for other in block.instructions + ([block.terminator] if block.terminator else []):
                if other is instruction:
                    seen = True
                    continue
                if not seen:
                    continue
                if instruction.result in other.operands:
                    return True
                if other.name in SIDE_EFFECTS:
                    return False
            return False
        return True

    def bind(self, instruction, expression, block):
        if instruction.result is None:
            return
        if self.inlinable(instruction, block) or instruction.name in ('OpSampledImage', 'OpImage'):
            self.values[instruction.result] = expression
            return
        name = self.name(instruction.result, '_%d' % instruction.result)
        self.emit('%s = %s;' % (self.declaration(instruction.type, name), expression.text))
        self.values[instruction.result] = Expression(name)

    def instruction(self, instruction, block):
        name = instruction.name
        ops = instruction.operands
        value = self.value
        if name in ('OpPhi', 'OpLine', 'OpNoLine', 'OpLoopMerge', 'OpSelectionMerge', 'OpVariable'):
            return
        if name in ('OpAccessChain', 'OpInBoundsAccessChain', 'OpPtrAccessChain'):
            self.pointers[instruction.result] = self.access_chain(ops[0], ops[1:] if name != 'OpPtrAccessChain' else ops[2:])
            self.storage_of[instruction.result] = self.storage_of.get(ops[0])
            return
        if name == 'OpLoad':
            pointer = self.pointers.get(ops[0]) or value(ops[0])
            self.storage_of[instruction.result] = None
            self.bind(instruction, Expression(pointer.text, pointer.precedence), block)
            return
        if name == 'OpStore':
            target = self.pointers.get(ops[0]) or value(ops[0])
            self.emit('%s = %s;' % (target.text, value(ops[1]).text))
            return
        if name == 'OpCopyMemory':
            self.emit('%s = %s;' % ((self.pointers.get(ops[0]) or value(ops[0])).text,
                                    (self.pointers.get(ops[1]) or value(ops[1])).text))
            return
        if name in BINARY:
            operator, precedence = BINARY[name]
            left, right = value(ops[0]), value(ops[1])
            if precedence in (6, 7) and self.components(self.type_of(ops[0])) > 1:
                function = VECTOR_COMPARE[operator]
                self.bind(instruction, Expression('%s(%s, %s)' % (function, left.text, right.text)), block)
                return
            left_text = self.wrap(left, precedence)
            right_text = self.wrap(right, precedence, right=True)
            text = '%s %s %s' % (left_text, operator, right_text)
            compare = (left_text, operator, right_text) if precedence in (6, 7) else None
            self.bind(instruction, Expression(text, precedence, compare), block)
            return
        if name in ('OpSNegate', 'OpFNegate'):
            self.bind(instruction, Expression('-' + self.wrap(value(ops[0]), 1), 1), block)
            return
        if name == 'OpNot':
            self.bind(instruction, Expression('~' + self.wrap(value(ops[0]), 1), 1), block)
            return
        if name == 'OpLogicalNot':
            self.bind(instruction, Expression(self.negate(value(ops[0])), 1), block)
            return
        if name == 'OpSelect':
            cond, a, b = value(ops[0]), value(ops[1]), value(ops[2])
            if self.components(self.type_of(ops[0])) > 1:
                self.bind(instruction, Expression('mix(%s, %s, %s)' % (b.text, a.text, cond.text)), block)
            else:
                self.bind(instruction, Expression('%s ? %s : %s' % (self.wrap(cond, 12), self.wrap(a, 12),
                                                                   self.wrap(b, 12)), 13), block)
            return
        if name in CASTS:
            target = self.type_name(instruction.type)
            argument = value(ops[0]).text
            if name == 'OpBitcast':
                source = self.base_name(self.scalar_type(self.type_of(ops[0])))
                destination = self.base_name(self.scalar_type(instruction.type))
                function = {('float', 'int'): 'floatBitsToInt', ('float', 'uint'): 'floatBitsToUint',
                            ('int', 'float'): 'intBitsToFloat', ('uint', 'float'): 'uintBitsToFloat'}.get(
                    (source, destination), target)
                self.bind(instruction, Expression('%s(%s)' % (function, argument)), block)
            else:
                self.bind(instruction, Expression('%s(%s)' % (target, argument)), block)
            return
        if name in CALLS:
            arguments = [value(o).text for o in ops]
            if name.startswith('OpGroupNonUniform') and arguments:
                arguments = arguments[1:]
                if name in ('OpGroupNonUniformFAdd', 'OpGroupNonUniformIAdd', 'OpGroupNonUniformFMin', 'OpGroupNonUniformFMax'):
                    arguments = arguments[1:]
            if name == 'OpArrayLength':
                base = self.pointers.get(ops[0]) or value(ops[0])
                struct_type = self.pointee(self.type_of_pointer(ops[0]))
                arguments = ['%s.%s' % (base.text, self.member(struct_type, ops[1]))]
                self.bind(instruction, Expression('%s.length()' % arguments[0]), block)
                return
            self.bind(instruction, Expression('%s(%s)' % (CALLS[name], ', '.join(arguments))), block)
            return
        if name == 'OpExtInst':
            set_name = self.module.ext_imports.get(ops[0], '')
            if set_name == 'GLSL.std.450':
                function = GLSL_STD.get(ops[1], ('glsl_std_%d' % ops[1],))[0]
            else:
                function = '%s_%d' % (re.sub(r'[^A-Za-z0-9]', '_', set_name), ops[1])
                if 'DebugInfo' in set_name or 'NonSemantic' in set_name:
                    return
            arguments = [value(o).text for o in ops[2:]]
            self.bind(instruction, Expression('%s(%s)' % (function, ', '.join(arguments))), block)
            return
        if name == 'OpCompositeConstruct':
            arguments = self.merge_swizzles([value(o).text for o in ops])
            type_name = self.type_name(instruction.type)
            vector = self.type_info(instruction.type)
            if vector is not None and vector.name == 'OpTypeVector' and len(arguments) > 1 and len(set(arguments)) == 1:
                arguments = arguments[:1]
            if vector is not None and vector.name == 'OpTypeVector' and len(arguments) == 1 and \
                    re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.\[\]]*\.[xyzw]{%d}' % vector.operands[1], arguments[0]):
                self.bind(instruction, Expression(arguments[0]), block)
                return
            info = self.type_info(instruction.type)
            if info is not None and info.name == 'OpTypeArray':
                type_name = self.type_name(info.operands[0]) + '[]'
            self.bind(instruction, Expression('%s(%s)' % (type_name, ', '.join(arguments))), block)
            return
        if name == 'OpCompositeExtract':
            self.bind(instruction, self.extract(ops[0], ops[1:]), block)
            return
        if name == 'OpCompositeInsert':
            temp = self.name(instruction.result, '_%d' % instruction.result)
            self.emit('%s = %s;' % (self.declaration(instruction.type, temp), value(ops[1]).text))
            target = self.extract_path(Expression(temp), self.type_of(ops[1]), ops[2:])
            self.emit('%s = %s;' % (target, value(ops[0]).text))
            self.values[instruction.result] = Expression(temp)
            return
        if name == 'OpVectorShuffle':
            first, second = ops[0], ops[1]
            count_first = self.components(self.type_of(first))
            indices = ops[2:]
            if all(i < count_first for i in indices) or first == second:
                swizzle = ''.join(SWIZZLE[i % count_first] for i in indices)
                self.bind(instruction, Expression('%s.%s' % (self.wrap(value(first), 0), swizzle)), block)
            elif all(i >= count_first for i in indices):
                swizzle = ''.join(SWIZZLE[i - count_first] for i in indices)
                self.bind(instruction, Expression('%s.%s' % (self.wrap(value(second), 0), swizzle)), block)
            else:
                parts = []
                for index in indices:
                    if index == 0xffffffff:
                        parts.append('0.0')
                    elif index < count_first:
                        parts.append('%s.%s' % (self.wrap(value(first), 0), SWIZZLE[index]))
                    else:
                        parts.append('%s.%s' % (self.wrap(value(second), 0), SWIZZLE[index - count_first]))
                self.bind(instruction, Expression('%s(%s)' % (self.type_name(instruction.type), ', '.join(parts))), block)
            return
        if name == 'OpVectorExtractDynamic':
            self.bind(instruction, Expression('%s[%s]' % (self.wrap(value(ops[0]), 0), value(ops[1]).text)), block)
            return
        if name == 'OpVectorInsertDynamic':
            temp = self.name(instruction.result, '_%d' % instruction.result)
            self.emit('%s = %s;' % (self.declaration(instruction.type, temp), value(ops[0]).text))
            self.emit('%s[%s] = %s;' % (temp, value(ops[2]).text, value(ops[1]).text))
            self.values[instruction.result] = Expression(temp)
            return
        if name in ('OpCopyObject',):
            self.bind(instruction, value(ops[0]), block)
            return
        if name == 'OpSampledImage':
            image, sampler = value(ops[0]).text, value(ops[1]).text
            self.values[instruction.result] = Expression('%s(%s, %s)' % (self.image_type(instruction.type), image, sampler))
            return
        if name == 'OpImage':
            self.values[instruction.result] = value(ops[0])
            return
        if name.startswith('OpImageSample') or name in ('OpImageFetch', 'OpImageGather', 'OpImageDrefGather',
                                                       'OpImageRead'):
            self.bind(instruction, self.image_call(name, ops), block)
            return
        if name == 'OpImageWrite':
            self.emit('imageStore(%s, %s, %s);' % (value(ops[0]).text, value(ops[1]).text, value(ops[2]).text))
            return
        if name == 'OpImageTexelPointer':
            self.pointers[instruction.result] = Expression('%s, %s' % (value(ops[0]).text, value(ops[1]).text))
            self.storage_of[instruction.result] = 'image'
            return
        if name == 'OpDot':
            self.bind(instruction, Expression('dot(%s, %s)' % (value(ops[0]).text, value(ops[1]).text)), block)
            return
        if name == 'OpFunctionCall':
            function = self.name(ops[0], 'function%d' % ops[0])
            arguments = [(self.pointers.get(o) or value(o)).text for o in ops[1:]]
            call = Expression('%s(%s)' % (function, ', '.join(arguments)))
            if self.type_name(instruction.type) == 'void':
                self.emit(call.text + ';')
            else:
                self.bind(instruction, call, block)
            return
        if name == 'OpControlBarrier':
            self.emit('barrier();')
            return
        if name == 'OpMemoryBarrier':
            self.emit('memoryBarrier();')
            return
        if name in ('OpEmitVertex', 'OpEmitStreamVertex'):
            self.emit('EmitVertex();')
            return
        if name in ('OpEndPrimitive', 'OpEndStreamPrimitive'):
            self.emit('EndPrimitive();')
            return
        if name in ('OpDemoteToHelperInvocation',):
            self.emit('demote;')
            return
        if name.startswith('OpAtomic'):
            pointer = self.pointers.get(ops[0]) or value(ops[0])
            operation = name[len('OpAtomic'):]
            if self.storage_of.get(ops[0]) == 'image':
                prefix, target = 'imageAtomic', pointer.text
            else:
                prefix, target = 'atomic', pointer.text
            if operation == 'Load':
                self.bind(instruction, Expression(target), block)
            elif operation == 'Store':
                self.emit('%s = %s;' % (target, value(ops[3]).text))
            elif operation in ('IIncrement', 'IDecrement'):
                self.bind(instruction, Expression('%sAdd(%s, %s)' % (prefix, target, '1' if operation == 'IIncrement' else '-1')), block)
            elif operation in ('CompareExchange', 'CompareExchangeWeak'):
                self.bind(instruction, Expression('%sCompSwap(%s, %s, %s)' % (prefix, target, value(ops[5]).text, value(ops[4]).text)), block)
            else:
                function = {'Exchange': 'Exchange', 'IAdd': 'Add', 'ISub': 'Add', 'SMin': 'Min', 'UMin': 'Min',
                            'SMax': 'Max', 'UMax': 'Max', 'And': 'And', 'Or': 'Or', 'Xor': 'Xor'}.get(operation, operation)
                argument = value(ops[3]).text
                if operation == 'ISub':
                    argument = '-' + argument
                call = '%s%s(%s, %s)' % (prefix, function, target, argument)
                if self.uses.get(instruction.result, 0) == 0:
                    self.emit(call + ';')
                else:
                    self.bind(instruction, Expression(call), block)
            return
        if name in ('OpUndef',):
            self.values[instruction.result] = Expression('%s(0)' % self.type_name(instruction.type))
            return
        if name in ('OpIAddCarry', 'OpISubBorrow', 'OpUMulExtended', 'OpSMulExtended'):
            function = {'OpIAddCarry': 'uaddCarry', 'OpISubBorrow': 'usubBorrow',
                        'OpUMulExtended': 'umulExtended', 'OpSMulExtended': 'imulExtended'}[name]
            self.bind(instruction, Expression('%s(%s, %s)' % (function, value(ops[0]).text, value(ops[1]).text)), block)
            return
        if name in ('OpLifetimeStart', 'OpLifetimeStop', 'OpNop'):
            return
        if instruction.result is not None:
            self.bind(instruction, Expression('%s(%s)' % (name, ', '.join(value(o).text for o in ops))), block)
        else:
            self.emit('// %s %s' % (name, ' '.join(str(o) for o in ops)))

    def image_call(self, name, ops):
        value = self.value
        image, coord = value(ops[0]).text, value(ops[1]).text
        rest = ops[2:]
        dref = None
        if 'Dref' in name and name != 'OpImageDrefGather':
            dref, rest = value(rest[0]).text, rest[1:]
        elif name in ('OpImageGather', 'OpImageDrefGather'):
            component, rest = value(rest[0]).text, rest[1:]
        mask = rest[0] if rest else 0
        args = rest[1:]
        extras = {}
        position = 0
        for bit, label in ((1, 'bias'), (2, 'lod'), (4, 'grad'), (8, 'offset'), (16, 'offset'), (32, 'offsets'),
                           (64, 'sample'), (128, 'minlod')):
            if mask & bit:
                if label == 'grad':
                    extras['grad'] = (value(args[position]).text, value(args[position + 1]).text)
                    position += 2
                else:
                    extras[label] = value(args[position]).text
                    position += 1
        proj = 'Proj' if 'Proj' in name else ''
        if dref is not None:
            # GLSL packs the depth reference into the coordinate for shadow samplers.
            coord = 'vec%d(%s, %s)' % (self.components(self.type_of(ops[1])) + 1, coord, dref)
        if name == 'OpImageFetch':
            function = 'texelFetch'
            arguments = [image, coord, extras.get('lod', extras.get('sample', '0'))]
        elif name == 'OpImageRead':
            return Expression('imageLoad(%s, %s)' % (image, coord))
        elif name == 'OpImageGather':
            return Expression('textureGather(%s, %s, %s)' % (image, coord, component))
        elif name == 'OpImageDrefGather':
            return Expression('textureGather(%s, %s, %s)' % (image, coord, component))
        elif 'grad' in extras:
            function = 'texture%sGrad' % proj
            arguments = [image, coord, extras['grad'][0], extras['grad'][1]]
        elif 'lod' in extras:
            function = 'texture%sLod' % proj
            arguments = [image, coord, extras['lod']]
        else:
            function = 'texture' + proj
            arguments = [image, coord]
            if 'bias' in extras:
                arguments.append(extras['bias'])
        if 'offset' in extras:
            function += 'Offset'
            arguments.insert(3 if function.endswith(('LodOffset',)) else len(arguments), extras['offset'])
        return Expression('%s(%s)' % (function, ', '.join(arguments)))

    @staticmethod
    def merge_swizzles(arguments):
        """vec4(a.x, a.y, a.z, b) -> vec4(a.xyz, b) for consecutive components of one value."""
        merged = []
        for argument in arguments:
            match = re.fullmatch(r'(.+)\.([xyzw]+)', argument)
            if merged and match:
                previous = re.fullmatch(r'(.+)\.([xyzw]+)', merged[-1])
                if previous and previous.group(1) == match.group(1) and \
                        len(previous.group(2)) + len(match.group(2)) <= 4 and \
                        re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.\[\]]*', match.group(1)):
                    merged[-1] = '%s.%s%s' % (match.group(1), previous.group(2), match.group(2))
                    continue
            merged.append(argument)
        return merged

    def type_of(self, value_id):
        definition = self.module.defs.get(value_id)
        if definition is not None and definition.type is not None:
            return definition.type
        return None

    def type_of_pointer(self, pointer_id):
        return self.type_of(pointer_id)

    def pointee(self, pointer_type):
        info = self.type_info(pointer_type)
        return info.operands[1] if info is not None and info.name == 'OpTypePointer' else pointer_type

    def scalar_type(self, type_id):
        info = self.type_info(type_id)
        if info is not None and info.name == 'OpTypeVector':
            return info.operands[0]
        return type_id

    def constant_int(self, value_id):
        instruction = self.module.constants.get(value_id)
        if instruction is not None and instruction.name == 'OpConstant':
            return instruction.operands[0]
        return None

    def access_chain(self, base_id, indices):
        base = self.pointers.get(base_id) or self.value(base_id)
        current_type = self.pointee(self.type_of(base_id))
        text = base.text
        for index_id in indices:
            info = self.type_info(current_type)
            if info is None:
                text += '[%s]' % self.value(index_id).text
                continue
            if info.name == 'OpTypeStruct':
                index = self.constant_int(index_id)
                builtin = self.member_builtin.get((current_type, index))
                if builtin:
                    text = builtin
                elif text.startswith('__builtin_block_'):
                    text = self.member(current_type, index)
                else:
                    text = '%s.%s' % (text, self.member(current_type, index))
                current_type = info.operands[index]
            elif info.name == 'OpTypeVector':
                index = self.constant_int(index_id)
                text = '%s.%s' % (text, SWIZZLE[index]) if index is not None and index < 4 else \
                    '%s[%s]' % (text, self.value(index_id).text)
                current_type = info.operands[0]
            else:
                text = '%s[%s]' % (text, self.value(index_id).text)
                current_type = info.operands[0]
        return Expression(text)

    def extract_path(self, base, type_id, indices):
        text = self.wrap(base, 0)
        current = type_id
        for index in indices:
            info = self.type_info(current)
            if info is None:
                text += '[%d]' % index
                continue
            if info.name == 'OpTypeStruct':
                builtin = self.member_builtin.get((current, index))
                text = builtin if builtin else '%s.%s' % (text, self.member(current, index))
                current = info.operands[index]
            elif info.name == 'OpTypeVector':
                text = '%s.%s' % (text, SWIZZLE[index])
                current = info.operands[0]
            else:
                text = '%s[%d]' % (text, index)
                current = info.operands[0]
        return text

    def extract(self, composite_id, indices):
        return Expression(self.extract_path(self.value(composite_id), self.type_of(composite_id), indices))

    # ------------------------------------------------------------------ entry

    def run(self, entry_name=None):
        module = self.module
        entries = module.entry_points
        entry = next((e for e in entries if e['name'] == entry_name), entries[0] if entries else None)
        for variable in module.globals:
            self.storage_of[variable.result] = variable.operands[0]
        globals_text = self.global_declarations()
        self.global_ids = set()
        for variable in module.globals:
            self.pointers[variable.result] = Expression(self.name(variable.result))
            self.global_ids.add(variable.result)
        header = ['#version 450']
        if module.source.startswith('HLSL'):
            header.append('// Original source language: HLSL (compiled to SPIR-V by DXC or glslang).')
        model = entry['model'] if entry else 'Unknown'
        header.append('// %s shader "%s", decompiled by CyDecompilator from SPIR-V %d.%d.'
                      % (MODEL_NAMES.get(model, model), entry['name'] if entry else '?', *module.version))
        header.append('// Generator: %s' % module.generator_name)
        header.append('')
        if entry:
            for mode, args in module.execution_modes.get(entry['function'], []):
                if mode == 17:
                    header.append('layout(local_size_x = %d, local_size_y = %d, local_size_z = %d) in;' % tuple(args[:3]))
                elif mode == 7:
                    header.append('// origin_upper_left')
                elif mode == 9:
                    header.append('layout(early_fragment_tests) in;')
                elif mode == 12:
                    header.append('// writes gl_FragDepth')
            header.append('')
        out = header + globals_text + ['']
        # Helper functions first (GLSL requires declaration before use), the entry point last.
        ordered = [f for f in module.functions if not entry or f.id != entry['function']]
        ordered += [f for f in module.functions if entry and f.id == entry['function']]
        for function in ordered:
            is_entry = bool(entry and function.id == entry['function'])
            out += self.function(function, entry=is_entry)
            out.append('')
        return '\n'.join(out)


def decompile(module, entry_name=None):
    return GlslWriter(module).run(entry_name)
