"""DXBC container, reflection (RDEF), signatures and SM4/SM5 token stream.

`parse(data)` returns a Shader with the program type/version, the declarations, the
instruction list, resource bindings with their HLSL names, constant buffer variables and
input/output signatures. `disassemble(shader)` prints an fxc-like listing;
`decompile.py` turns the same structure into HLSL.
"""
import struct

from cytools_core import CyToolError

PROGRAM_TYPES = {0: ('ps', 'Pixel'), 1: ('vs', 'Vertex'), 2: ('gs', 'Geometry'), 3: ('hs', 'Hull'),
                 4: ('ds', 'Domain'), 5: ('cs', 'Compute')}

OPCODES = [
    'add', 'and', 'break', 'breakc', 'call', 'callc', 'case', 'continue', 'continuec', 'cut',
    'default', 'deriv_rtx', 'deriv_rty', 'discard', 'div', 'dp2', 'dp3', 'dp4', 'else', 'emit',
    'emitthencut', 'endif', 'endloop', 'endswitch', 'eq', 'exp', 'frc', 'ftoi', 'ftou', 'ge',
    'iadd', 'if', 'ieq', 'ige', 'ilt', 'imad', 'imax', 'imin', 'imul', 'ine',
    'ineg', 'ishl', 'ishr', 'itof', 'label', 'ld', 'ld_ms', 'log', 'loop', 'lt',
    'mad', 'min', 'max', 'customdata', 'mov', 'movc', 'mul', 'ne', 'nop', 'not',
    'or', 'resinfo', 'ret', 'retc', 'round_ne', 'round_ni', 'round_pi', 'round_z', 'rsq', 'sample',
    'sample_c', 'sample_c_lz', 'sample_l', 'sample_d', 'sample_b', 'sqrt', 'switch', 'sincos', 'udiv', 'ult',
    'uge', 'umul', 'umad', 'umax', 'umin', 'ushr', 'utof', 'xor', 'dcl_resource', 'dcl_constantbuffer',
    'dcl_sampler', 'dcl_indexrange', 'dcl_outputtopology', 'dcl_inputprimitive', 'dcl_maxout', 'dcl_input', 'dcl_input_sgv', 'dcl_input_siv', 'dcl_input_ps', 'dcl_input_ps_sgv',
    'dcl_input_ps_siv', 'dcl_output', 'dcl_output_sgv', 'dcl_output_siv', 'dcl_temps', 'dcl_indexableTemp', 'dcl_globalFlags', 'reserved_107', 'lod', 'gather4',
    'samplepos', 'sampleinfo', 'reserved_112', 'hs_decls', 'hs_control_point_phase', 'hs_fork_phase', 'hs_join_phase', 'emit_stream', 'cut_stream', 'emitthencut_stream',
    'interface_call', 'bufinfo', 'deriv_rtx_coarse', 'deriv_rtx_fine', 'deriv_rty_coarse', 'deriv_rty_fine', 'gather4_c', 'gather4_po', 'gather4_po_c', 'rcp',
    'f32tof16', 'f16tof32', 'uaddc', 'usubb', 'countbits', 'firstbit_hi', 'firstbit_lo', 'firstbit_shi', 'ubfe', 'ibfe',
    'bfi', 'bfrev', 'swapc', 'dcl_stream', 'dcl_function_body', 'dcl_function_table', 'dcl_interface', 'dcl_input_control_point_count', 'dcl_output_control_point_count', 'dcl_tessellator_domain',
    'dcl_tessellator_partitioning', 'dcl_tessellator_output_primitive', 'dcl_hs_max_tessfactor', 'dcl_hs_fork_phase_instance_count', 'dcl_hs_join_phase_instance_count', 'dcl_thread_group', 'dcl_uav_typed', 'dcl_uav_raw', 'dcl_uav_structured', 'dcl_tgsm_raw',
    'dcl_tgsm_structured', 'dcl_resource_raw', 'dcl_resource_structured', 'ld_uav_typed', 'store_uav_typed', 'ld_raw', 'store_raw', 'ld_structured', 'store_structured', 'atomic_and',
    'atomic_or', 'atomic_xor', 'atomic_cmp_store', 'atomic_iadd', 'atomic_imax', 'atomic_imin', 'atomic_umax', 'atomic_umin', 'imm_atomic_alloc', 'imm_atomic_consume',
    'imm_atomic_iadd', 'imm_atomic_and', 'imm_atomic_or', 'imm_atomic_xor', 'imm_atomic_exch', 'imm_atomic_cmp_exch', 'imm_atomic_imax', 'imm_atomic_imin', 'imm_atomic_umax', 'imm_atomic_umin',
    'sync', 'dadd', 'dmax', 'dmin', 'dmul', 'deq', 'dge', 'dlt', 'dne', 'dmov',
    'dmovc', 'dtof', 'ftod', 'eval_snapped', 'eval_sample_index', 'eval_centroid', 'dcl_gs_instance_count', 'abort', 'debug_break', 'reserved_209',
    'ddiv', 'dfma', 'drcp', 'msad', 'dtoi', 'dtou', 'itod', 'utod', 'reserved_218', 'gather4_feedback',
    'gather4_c_feedback', 'gather4_po_feedback', 'gather4_po_c_feedback', 'ld_feedback', 'ld_ms_feedback', 'ld_uav_typed_feedback', 'ld_raw_feedback', 'ld_structured_feedback', 'sample_l_feedback', 'sample_c_lz_feedback',
    'sample_clamp_feedback', 'sample_b_clamp_feedback', 'sample_d_clamp_feedback', 'sample_c_clamp_feedback', 'check_access_fully_mapped',
]

OPERAND_TYPES = {
    0: 'r', 1: 'v', 2: 'o', 3: 'x', 4: 'l', 5: 'd', 6: 's', 7: 't', 8: 'cb', 9: 'icb', 10: 'label',
    11: 'vPrim', 12: 'oDepth', 13: 'null', 14: 'rasterizer', 15: 'oMask', 16: 'm', 17: 'fb', 18: 'ft',
    19: 'fp', 20: 'fi', 21: 'fo', 22: 'vOutputControlPointID', 23: 'vForkInstanceID',
    24: 'vJoinInstanceID', 25: 'vicp', 26: 'vocp', 27: 'vpc', 28: 'vDomain', 29: 'this', 30: 'u',
    31: 'g', 32: 'vThreadID', 33: 'vThreadGroupID', 34: 'vThreadIDInGroup', 35: 'vCoverage',
    36: 'vThreadIDInGroupFlattened', 37: 'vGSInstanceID', 38: 'oDepthGE', 39: 'oDepthLE',
    40: 'vCycleCounter', 41: 'oStencilRef', 42: 'vInnerCoverage',
}
# Operand types printed without an index.
NO_INDEX = {11, 12, 13, 14, 15, 22, 23, 24, 28, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42}

RESOURCE_DIMENSIONS = {0: 'unknown', 1: 'buffer', 2: 'texture1d', 3: 'texture2d', 4: 'texture2dms',
                       5: 'texture3d', 6: 'texturecube', 7: 'texture1darray', 8: 'texture2darray',
                       9: 'texture2dmsarray', 10: 'texturecubearray', 11: 'raw_buffer',
                       12: 'structured_buffer'}
RETURN_TYPES = {1: 'unorm', 2: 'snorm', 3: 'sint', 4: 'uint', 5: 'float', 6: 'mixed', 7: 'double',
                8: 'continued', 9: 'unused'}
INTERPOLATION = {0: '', 1: 'constant', 2: 'linear', 3: 'linear centroid', 4: 'linear noperspective',
                 5: 'linear noperspective centroid', 6: 'linear sample', 7: 'linear noperspective sample'}
SYSTEM_NAMES = {0: 'undefined', 1: 'position', 2: 'clip_distance', 3: 'cull_distance',
                4: 'rendertarget_array_index', 5: 'viewport_array_index', 6: 'vertex_id',
                7: 'primitive_id', 8: 'instance_id', 9: 'is_front_face', 10: 'sampleIndex',
                11: 'finalQuadUeq0EdgeTessFactor', 12: 'finalQuadVeq0EdgeTessFactor',
                13: 'finalQuadUeq1EdgeTessFactor', 14: 'finalQuadVeq1EdgeTessFactor',
                15: 'finalQuadUInsideTessFactor', 16: 'finalQuadVInsideTessFactor',
                17: 'finalTriUeq0EdgeTessFactor', 18: 'finalTriVeq0EdgeTessFactor',
                19: 'finalTriWeq0EdgeTessFactor', 20: 'finalTriInsideTessFactor',
                21: 'finalLineDetailTessFactor', 22: 'finalLineDensityTessFactor'}
GLOBAL_FLAGS = {11: 'refactoringAllowed', 12: 'enableDoublePrecisionFloatOps',
                13: 'forceEarlyDepthStencil', 14: 'enableRawAndStructuredBuffers',
                15: 'skipOptimization', 16: 'enableMinimumPrecision',
                17: 'enable11_1DoubleExtensions', 18: 'enable11_1ShaderExtensions'}
COMPONENTS = 'xyzw'

# RDEF enumerations.
BIND_TYPES = {0: 'cbuffer', 1: 'tbuffer', 2: 'texture', 3: 'sampler', 4: 'uav_typed',
              5: 'structured', 6: 'uav_structured', 7: 'byteaddress', 8: 'uav_byteaddress',
              9: 'uav_append', 10: 'uav_consume', 11: 'uav_structured_counter'}
SRV_DIMENSIONS = {0: 'unknown', 1: 'Buffer', 2: 'Texture1D', 3: 'Texture1DArray', 4: 'Texture2D',
                  5: 'Texture2DArray', 6: 'Texture2DMS', 7: 'Texture2DMSArray', 8: 'Texture3D',
                  9: 'TextureCube', 10: 'TextureCubeArray', 11: 'BufferEx'}
RETURN_HLSL = {1: 'unorm float', 2: 'snorm float', 3: 'int', 4: 'uint', 5: 'float', 6: 'float',
               7: 'double'}
VAR_TYPES = {0: 'void', 1: 'bool', 2: 'int', 3: 'float', 19: 'uint', 20: 'uint8', 39: 'double',
             57: 'min8float', 58: 'min10float', 59: 'min16float', 60: 'min12int', 61: 'min16int',
             62: 'min16uint'}
COMPONENT_TYPES = {0: 'unknown', 1: 'uint', 2: 'int', 3: 'float'}


class ParseError(Exception):
    pass


class Operand:
    __slots__ = ('type', 'num_components', 'selection', 'mask', 'swizzle', 'select1', 'indices',
                 'values', 'modifier', 'min_precision', 'nonuniform')

    def __init__(self):
        self.type = 0
        self.num_components = 0
        self.selection = 0
        self.mask = 0xf
        self.swizzle = (0, 1, 2, 3)
        self.select1 = 0
        self.indices = []      # list of (immediate or None, relative Operand or None)
        self.values = []       # immediate values (raw 32-bit words, or 64-bit for doubles)
        self.modifier = 0      # 1 neg, 2 abs, 3 -abs
        self.min_precision = 0
        self.nonuniform = False

    @property
    def register(self):
        return OPERAND_TYPES.get(self.type, 'op%d' % self.type)

    def components(self):
        """Component indices this operand reads/writes, in order (mask, swizzle or select1)."""
        if self.num_components != 4:
            return [0] if self.num_components == 1 else []
        if self.selection == 0:
            return [i for i in range(4) if self.mask & (1 << i)]
        if self.selection == 1:
            return list(self.swizzle)
        return [self.select1]


class Instruction:
    __slots__ = ('opcode', 'name', 'token', 'operands', 'extra', 'offset', 'length', 'sample_offsets',
                 'resource_dim', 'resource_stride', 'return_types', 'custom')

    def __init__(self, opcode, token, offset):
        self.opcode = opcode
        self.name = OPCODES[opcode] if opcode < len(OPCODES) else 'op_%d' % opcode
        self.token = token
        self.operands = []
        self.extra = []
        self.offset = offset
        self.length = 0
        self.sample_offsets = None
        self.resource_dim = None
        self.resource_stride = None
        self.return_types = None
        self.custom = None

    def control(self, low, high):
        return (self.token >> low) & ((1 << (high - low + 1)) - 1)

    @property
    def saturate(self):
        return bool(self.token & (1 << 13))

    @property
    def test_nonzero(self):
        return bool(self.token & (1 << 18))


class Shader:
    def __init__(self):
        self.program = 'ps'
        self.program_name = 'Pixel'
        self.major = 5
        self.minor = 0
        self.instructions = []
        self.declarations = []
        self.bindings = []
        self.cbuffers = []
        self.inputs = []
        self.outputs = []
        self.patch_constants = []
        self.chunks = []
        self.creator = ''
        self.flags = []
        self.thread_group = None
        self.temps = 0

    @property
    def profile(self):
        return '%s_%d_%d' % (self.program, self.major, self.minor)


# ---------------------------------------------------------------------- container

def chunks(data):
    if data[:4] != b'DXBC':
        raise ParseError('Not a DXBC container')
    count = struct.unpack_from('<I', data, 28)[0]
    result = []
    for index in range(count):
        offset = struct.unpack_from('<I', data, 32 + index * 4)[0]
        fourcc = data[offset:offset + 4].decode('ascii', 'replace')
        size = struct.unpack_from('<I', data, offset + 4)[0]
        result.append((fourcc, data[offset + 8:offset + 8 + size]))
    return result


def _cstring(blob, offset):
    end = blob.find(b'\0', offset)
    return blob[offset:end if end >= 0 else len(blob)].decode('utf-8', 'replace')


def parse_signature(fourcc, blob):
    count = struct.unpack_from('<I', blob, 0)[0]
    elements = []
    stride = {'OSG5': 28, 'ISG1': 32, 'OSG1': 32, 'PSG1': 32}.get(fourcc, 24)
    for index in range(count):
        base = 8 + index * stride
        stream = 0
        min_precision = 0
        if fourcc in ('OSG5', 'ISG1', 'OSG1', 'PSG1'):
            stream = struct.unpack_from('<I', blob, base)[0]
            base += 4
        name_offset, semantic_index, system_value, component_type, register = struct.unpack_from('<5I', blob, base)
        mask, rw_mask = blob[base + 20], blob[base + 21]
        if stride == 32:
            min_precision = struct.unpack_from('<I', blob, base + 24)[0]
        elements.append({'name': _cstring(blob, name_offset), 'index': semantic_index,
                         'systemValue': system_value, 'componentType': COMPONENT_TYPES.get(component_type, 'unknown'),
                         'register': register, 'mask': mask, 'rwMask': rw_mask, 'stream': stream,
                         'minPrecision': min_precision})
    return elements


def _rdef_type(blob, offset, sm5):
    cls, typ, rows, cols, elements, members, member_offset = struct.unpack_from('<6HI', blob, offset)
    base = VAR_TYPES.get(typ, 'type%d' % typ)
    name = ''
    if sm5:
        name_offset = struct.unpack_from('<I', blob, offset + 32)[0] if offset + 36 <= len(blob) else 0
        name = _cstring(blob, name_offset) if name_offset else ''
    if cls == 0:
        text = base
    elif cls == 1:
        text = '%s%d' % (base, cols)
    elif cls in (2, 3):
        text = '%s%dx%d' % (base, rows, cols)
    elif cls == 5:
        text = name or 'struct'
    else:
        text = name or base
    fields = []
    if cls == 5 and members:
        for index in range(members):
            m_name, m_type, m_offset = struct.unpack_from('<3I', blob, member_offset + index * 12)
            sub = _rdef_type(blob, m_type, sm5)
            fields.append({'name': _cstring(blob, m_name), 'type': sub['type'], 'offset': m_offset,
                           'elements': sub['elements']})
    return {'type': text, 'class': cls, 'rows': rows, 'columns': cols, 'elements': elements,
            'fields': fields}


def parse_rdef(blob):
    cb_count, cb_offset, bind_count, bind_offset = struct.unpack_from('<4I', blob, 0)
    minor, major = blob[16], blob[17]
    creator_offset = struct.unpack_from('<I', blob, 24)[0]
    sm5 = major >= 5
    var_stride = 40 if sm5 else 24
    bindings = []
    for index in range(bind_count):
        base = bind_offset + index * 32
        name_offset, kind, ret, dim, samples, point, count, flags = struct.unpack_from('<8I', blob, base)
        bindings.append({'name': _cstring(blob, name_offset), 'type': BIND_TYPES.get(kind, str(kind)),
                         'returnType': ret, 'dimension': dim, 'samples': samples, 'register': point,
                         'count': count, 'flags': flags})
    cbuffers = []
    for index in range(cb_count):
        base = cb_offset + index * 24
        name_offset, var_count, var_offset, size, flags, cb_type = struct.unpack_from('<6I', blob, base)
        variables = []
        for v in range(var_count):
            vb = var_offset + v * var_stride
            v_name, start, v_size, v_flags, type_offset, default_offset = struct.unpack_from('<6I', blob, vb)
            info = _rdef_type(blob, type_offset, sm5)
            variables.append({'name': _cstring(blob, v_name), 'offset': start, 'size': v_size,
                              'used': bool(v_flags & 2), 'type': info['type'], 'class': info['class'],
                              'rows': info['rows'], 'columns': info['columns'],
                              'elements': info['elements'], 'fields': info['fields']})
        cbuffers.append({'name': _cstring(blob, name_offset), 'size': size, 'variables': variables,
                         'kind': cb_type})
    return {'bindings': bindings, 'cbuffers': cbuffers, 'creator': _cstring(blob, creator_offset),
            'version': '%d.%d' % (major, minor)}


# ---------------------------------------------------------------------- tokens

class TokenReader:
    def __init__(self, words):
        self.words = words
        self.pos = 0

    def take(self):
        if self.pos >= len(self.words):
            raise ParseError('Unexpected end of shader tokens')
        value = self.words[self.pos]
        self.pos += 1
        return value


def read_operand(reader):
    token = reader.take()
    operand = Operand()
    num = token & 3
    operand.num_components = {0: 0, 1: 1, 2: 4, 3: 4}[num]
    if num == 2:
        operand.selection = (token >> 2) & 3
        if operand.selection == 0:
            operand.mask = (token >> 4) & 0xf
        elif operand.selection == 1:
            operand.swizzle = tuple((token >> (4 + 2 * i)) & 3 for i in range(4))
        else:
            operand.select1 = (token >> 4) & 3
    operand.type = (token >> 12) & 0xff
    dimension = (token >> 20) & 3
    representations = [(token >> 22) & 7, (token >> 25) & 7, (token >> 28) & 7]
    extended = bool(token & 0x80000000)
    while extended:
        ext = reader.take()
        extended = bool(ext & 0x80000000)
        if ext & 0x3f == 1:
            operand.modifier = (ext >> 6) & 0xff
            operand.min_precision = (ext >> 14) & 7
            operand.nonuniform = bool(ext & (1 << 17))
    if operand.type == 4:  # immediate32
        operand.values = [reader.take() for _ in range(max(1, operand.num_components))]
        return operand
    if operand.type == 5:  # immediate64
        count = max(1, operand.num_components // 2 if operand.num_components == 4 else 1)
        operand.values = []
        for _ in range(count):
            low, high = reader.take(), reader.take()
            operand.values.append(low | (high << 32))
        return operand
    for level in range(dimension):
        rep = representations[level]
        immediate, relative = None, None
        if rep == 0:
            immediate = reader.take()
        elif rep == 1:
            low, high = reader.take(), reader.take()
            immediate = low | (high << 32)
        elif rep == 2:
            relative = read_operand(reader)
        elif rep == 3:
            immediate = reader.take()
            relative = read_operand(reader)
        elif rep == 4:
            low, high = reader.take(), reader.take()
            immediate = low | (high << 32)
            relative = read_operand(reader)
        operand.indices.append((immediate, relative))
    return operand


# Declarations whose payload after the operand is a fixed number of raw words.
DECL_OPERAND_THEN_WORDS = {
    'dcl_input_sgv': 1, 'dcl_input_siv': 1, 'dcl_input_ps_sgv': 1, 'dcl_input_ps_siv': 1,
    'dcl_output_sgv': 1, 'dcl_output_siv': 1, 'dcl_indexrange': 1, 'dcl_uav_structured': 1,
    'dcl_tgsm_raw': 1, 'dcl_tgsm_structured': 2, 'dcl_resource_structured': 1,
    'dcl_resource': 1, 'dcl_uav_typed': 1,
}
DECL_OPERAND_ONLY = {'dcl_constantbuffer', 'dcl_sampler', 'dcl_input', 'dcl_input_ps', 'dcl_output',
                     'dcl_uav_raw', 'dcl_resource_raw', 'dcl_stream'}
DECL_WORDS_ONLY = {'dcl_temps', 'dcl_indexableTemp', 'dcl_maxout', 'dcl_thread_group',
                   'dcl_function_body', 'dcl_hs_max_tessfactor', 'dcl_hs_fork_phase_instance_count',
                   'dcl_hs_join_phase_instance_count', 'dcl_gs_instance_count'}


def parse_program(blob, shader):
    words = list(struct.unpack_from('<%dI' % (len(blob) // 4), blob))
    version = words[0]
    shader.minor = version & 0xf
    shader.major = (version >> 4) & 0xf
    shader.program, shader.program_name = PROGRAM_TYPES.get(version >> 16, ('xs', 'Unknown'))
    total = min(words[1], len(words))
    position = 2
    while position < total:
        token = words[position]
        opcode = token & 0x7ff
        instruction = Instruction(opcode, token, position)
        if instruction.name == 'customdata':
            length = words[position + 1]
            data_class = token >> 11
            instruction.custom = {'class': data_class, 'words': words[position + 2:position + length]}
            instruction.length = length
            shader.declarations.append(instruction)
            position += max(length, 2)
            continue
        length = (token >> 24) & 0x7f
        if length == 0:
            raise ParseError('Zero-length instruction at token %d' % position)
        instruction.length = length
        reader = TokenReader(words[position + 1:position + length])
        extended = bool(token & 0x80000000)
        while extended:
            ext = reader.take()
            extended = bool(ext & 0x80000000)
            kind = ext & 0x3f
            if kind == 1:
                def signed4(v):
                    return v - 16 if v & 8 else v
                instruction.sample_offsets = (signed4((ext >> 9) & 0xf), signed4((ext >> 13) & 0xf),
                                              signed4((ext >> 17) & 0xf))
            elif kind == 2:
                instruction.resource_dim = (ext >> 6) & 0x1f
                instruction.resource_stride = (ext >> 11) & 0xfff
            elif kind == 3:
                instruction.return_types = tuple((ext >> (6 + 4 * i)) & 0xf for i in range(4))
        name = instruction.name
        try:
            if name in DECL_OPERAND_ONLY:
                instruction.operands.append(read_operand(reader))
            elif name in DECL_OPERAND_THEN_WORDS:
                instruction.operands.append(read_operand(reader))
                instruction.extra = [reader.take() for _ in range(DECL_OPERAND_THEN_WORDS[name])]
            elif name in DECL_WORDS_ONLY or name in ('dcl_function_table', 'dcl_interface'):
                instruction.extra = reader.words[reader.pos:]
                reader.pos = len(reader.words)
            elif name == 'interface_call':
                instruction.extra = [reader.take()]
                while reader.pos < len(reader.words):
                    instruction.operands.append(read_operand(reader))
            elif name.startswith('dcl_') or name in ('hs_decls', 'hs_control_point_phase',
                                                      'hs_fork_phase', 'hs_join_phase'):
                instruction.extra = reader.words[reader.pos:]
            else:
                while reader.pos < len(reader.words):
                    instruction.operands.append(read_operand(reader))
        except ParseError:
            instruction.extra = words[position + 1:position + length]
        if name.startswith('dcl_'):
            shader.declarations.append(instruction)
            if name == 'dcl_temps':
                shader.temps = instruction.extra[0] if instruction.extra else 0
            elif name == 'dcl_thread_group':
                shader.thread_group = tuple(instruction.extra[:3])
            elif name == 'dcl_globalFlags':
                shader.flags = [label for bit, label in GLOBAL_FLAGS.items() if token & (1 << bit)]
        else:
            shader.instructions.append(instruction)
        position += length
    return shader


def parse(data):
    shader = Shader()
    program = None
    for fourcc, blob in chunks(data):
        shader.chunks.append(fourcc)
        if fourcc == 'RDEF':
            try:
                reflection = parse_rdef(blob)
                shader.bindings = reflection['bindings']
                shader.cbuffers = reflection['cbuffers']
                shader.creator = reflection['creator']
            except (struct.error, IndexError):
                pass
        elif fourcc in ('ISGN', 'ISG1'):
            shader.inputs = parse_signature(fourcc, blob)
        elif fourcc in ('OSGN', 'OSG5', 'OSG1'):
            shader.outputs = parse_signature(fourcc, blob)
        elif fourcc in ('PCSG', 'PSG1'):
            shader.patch_constants = parse_signature(fourcc, blob)
        elif fourcc in ('SHDR', 'SHEX'):
            program = blob
    if program is None:
        if 'DXIL' in shader.chunks:
            raise CyToolError('Unsupported', 'This is a DXIL (Shader Model 6) container.')
        raise CyToolError('EngineFailed', 'No SHDR/SHEX bytecode chunk in this DXBC container.')
    try:
        parse_program(program, shader)
    except (ParseError, struct.error, IndexError) as exc:
        raise CyToolError('EngineFailed', 'Malformed shader bytecode: %s' % exc)
    return shader


# ---------------------------------------------------------------------- disassembly

def float_text(word):
    value = struct.unpack('<f', struct.pack('<I', word & 0xffffffff))[0]
    if value != value:
        return 'NaN'
    if value in (float('inf'), float('-inf')):
        return '%sINF' % ('-' if value < 0 else '')
    return '%f' % value


def looks_like_float(word):
    if word in (0, 0x80000000):
        return False
    exponent = (word >> 23) & 0xff
    return 0x60 < exponent < 0x9f and not (word < 0x10000 or word > 0xffff0000)


def immediate_text(operand, as_float=None):
    parts = []
    for word in operand.values:
        if operand.type == 5:
            parts.append('%rd' % struct.unpack('<d', struct.pack('<Q', word))[0])
            continue
        use_float = looks_like_float(word) if as_float is None else as_float
        if use_float:
            parts.append(float_text(word))
        else:
            signed = word - (1 << 32) if word & 0x80000000 else word
            parts.append(str(signed) if -0x10000 < signed < 0x10000 else '0x%08x' % word)
    return 'l(%s)' % ', '.join(parts) if operand.type == 4 else 'd(%s)' % ', '.join(parts)


def operand_text(operand, as_float=None):
    if operand.type in (4, 5):
        text = immediate_text(operand, as_float)
    else:
        text = operand.register
        if operand.type not in NO_INDEX and operand.indices:
            first = operand.indices[0]
            if operand.type == 9 or first[1] is not None:
                text += '[%s]' % _relative_text(first)
            else:
                text += str(first[0])
            for index in operand.indices[1:]:
                text += '[%s]' % _relative_text(index)
        if operand.num_components == 4:
            if operand.selection == 0:
                if operand.mask != 0xf or operand.type in (0, 1, 2, 3, 30):
                    text += '.' + ''.join(COMPONENTS[i] for i in range(4) if operand.mask & (1 << i))
            elif operand.selection == 1:
                text += '.' + ''.join(COMPONENTS[i] for i in operand.swizzle)
            else:
                text += '.' + COMPONENTS[operand.select1]
    if operand.modifier == 1:
        text = '-' + text
    elif operand.modifier == 2:
        text = '|%s|' % text
    elif operand.modifier == 3:
        text = '-|%s|' % text
    return text


def _relative_text(index):
    immediate, relative = index
    if relative is None:
        return str(immediate)
    text = operand_text(relative)
    return text + (' + %d' % immediate if immediate else '')


FLOAT_OPS = {'add', 'mul', 'mad', 'div', 'min', 'max', 'dp2', 'dp3', 'dp4', 'eq', 'ne', 'lt', 'ge',
             'frc', 'exp', 'log', 'rsq', 'sqrt', 'rcp', 'round_ne', 'round_ni', 'round_pi', 'round_z',
             'ftoi', 'ftou', 'sincos', 'deriv_rtx', 'deriv_rty', 'deriv_rtx_coarse', 'deriv_rtx_fine',
             'deriv_rty_coarse', 'deriv_rty_fine', 'sample', 'sample_l', 'sample_b', 'sample_c',
             'sample_c_lz', 'sample_d', 'f32tof16', 'lod'}
INT_OPS = {'iadd', 'imul', 'imad', 'imax', 'imin', 'ieq', 'ine', 'ilt', 'ige', 'ineg', 'ishl',
           'ishr', 'itof', 'and', 'or', 'xor', 'not', 'ushr', 'udiv', 'umul', 'umad', 'umax', 'umin',
           'ult', 'uge', 'utof', 'countbits', 'firstbit_hi', 'firstbit_lo', 'firstbit_shi', 'ubfe',
           'ibfe', 'bfi', 'bfrev', 'uaddc', 'usubb', 'f16tof32', 'switch', 'case', 'ld', 'ld_ms',
           'ld_raw', 'ld_structured', 'store_raw', 'store_structured', 'ld_uav_typed',
           'store_uav_typed', 'bufinfo', 'resinfo'}


def literal_kind(name):
    if name in FLOAT_OPS:
        return True
    if name in INT_OPS or name.startswith(('atomic_', 'imm_atomic_')):
        return False
    return None


def instruction_text(instruction, shader=None):
    name = instruction.name
    suffix = ''
    if name in ('if', 'breakc', 'continuec', 'retc', 'discard', 'callc'):
        suffix = '_nz' if instruction.test_nonzero else '_z'
    if instruction.saturate:
        suffix += '_sat'
    if name == 'resinfo':
        suffix += {0: '', 1: '_rcpFloat', 2: '_uint'}.get(instruction.control(11, 12), '')
    if name == 'sync':
        flags = instruction.control(11, 14)
        suffix += ''.join(part for bit, part in ((2, '_g'), (4, '_uglobal'), (8, '_ugroup'), (1, '_t'))
                          if flags & bit)
    head = name + suffix
    if instruction.sample_offsets and any(instruction.sample_offsets):
        head += '_aoffimmi(%d,%d,%d)' % instruction.sample_offsets
    if instruction.resource_dim is not None:
        dim = RESOURCE_DIMENSIONS.get(instruction.resource_dim, '?')
        head += '_indexable(%s%s)' % (dim, ', stride=%d' % instruction.resource_stride
                                      if instruction.resource_stride else '')
    if instruction.return_types:
        head += '(%s)' % ','.join(RETURN_TYPES.get(t, '?') for t in instruction.return_types)
    as_float = literal_kind(name)
    operands = ', '.join(operand_text(o, as_float) for o in instruction.operands)
    return (head + ' ' + operands).rstrip()


def declaration_text(instruction):
    name = instruction.name
    if name == 'customdata':
        if instruction.custom['class'] == 3:
            words = instruction.custom['words']
            rows = ['{ %s }' % ', '.join(float_text(w) if looks_like_float(w) else str(w)
                                         for w in words[i:i + 4]) for i in range(0, len(words), 4)]
            return 'dcl_immediateConstantBuffer { %s }' % ',\n                              '.join(rows)
        return 'customdata class %d (%d words)' % (instruction.custom['class'], len(instruction.custom['words']))
    operand = operand_text(instruction.operands[0]) if instruction.operands else ''
    if name == 'dcl_globalFlags':
        return 'dcl_globalFlags ' + ' | '.join(label for bit, label in GLOBAL_FLAGS.items()
                                               if instruction.token & (1 << bit))
    if name == 'dcl_constantbuffer':
        o = instruction.operands[0]
        size = o.indices[1][0] if len(o.indices) > 1 else 0
        return 'dcl_constantbuffer CB%d[%d], %s' % (o.indices[0][0], size,
                                                    'dynamicIndexed' if instruction.control(11, 11) else 'immediateIndexed')
    if name == 'dcl_sampler':
        return 'dcl_sampler %s, %s' % (operand, {0: 'mode_default', 1: 'mode_comparison', 2: 'mode_mono'}.get(instruction.control(11, 14), 'mode_?'))
    if name in ('dcl_resource', 'dcl_uav_typed'):
        dim = RESOURCE_DIMENSIONS.get(instruction.control(11, 15), '?')
        word = instruction.extra[0] if instruction.extra else 0
        types = ','.join(RETURN_TYPES.get((word >> (4 * i)) & 0xf, '?') for i in range(4))
        prefix = 'dcl_resource_' if name == 'dcl_resource' else 'dcl_uav_typed_'
        return '%s%s (%s) %s' % (prefix, dim, types, operand)
    if name in ('dcl_input_ps', 'dcl_input_ps_siv', 'dcl_input_ps_sgv'):
        mode = INTERPOLATION.get(instruction.control(11, 14), '')
        text = '%s %s%s' % (name, mode + ' ' if mode else '', operand)
        if instruction.extra:
            text += ', ' + SYSTEM_NAMES.get(instruction.extra[0], str(instruction.extra[0]))
        return text
    if name in ('dcl_input_siv', 'dcl_input_sgv', 'dcl_output_siv', 'dcl_output_sgv'):
        return '%s %s, %s' % (name, operand, SYSTEM_NAMES.get(instruction.extra[0], str(instruction.extra[0])))
    if name == 'dcl_temps':
        return 'dcl_temps %d' % instruction.extra[0]
    if name == 'dcl_indexableTemp':
        return 'dcl_indexableTemp x%d[%d], %d' % tuple(instruction.extra[:3])
    if name == 'dcl_thread_group':
        return 'dcl_thread_group %d, %d, %d' % tuple(instruction.extra[:3])
    if name in ('dcl_resource_structured', 'dcl_uav_structured'):
        return '%s %s, %d' % (name, operand, instruction.extra[0])
    if name == 'dcl_tgsm_raw':
        return 'dcl_tgsm_raw %s, %d' % (operand, instruction.extra[0])
    if name == 'dcl_tgsm_structured':
        return 'dcl_tgsm_structured %s, %d, %d' % (operand, instruction.extra[0], instruction.extra[1])
    if name == 'dcl_indexrange':
        return 'dcl_indexrange %s, %d' % (operand, instruction.extra[0])
    if name == 'dcl_maxout':
        return 'dcl_maxout %d' % instruction.extra[0]
    if operand:
        return '%s %s%s' % (name, operand, (' ' + ' '.join(map(str, instruction.extra))) if instruction.extra else '')
    if instruction.extra:
        return '%s %s' % (name, ' '.join(str(x) for x in instruction.extra))
    return name + (' %d' % instruction.control(11, 23) if instruction.control(11, 23) else '')


def disassemble(shader):
    lines = ['// %s Shader, Shader Model %d.%d (%s)' % (shader.program_name, shader.major, shader.minor, shader.profile)]
    if shader.creator:
        lines.append('// Compiled by: ' + shader.creator)
    lines.append('// Chunks: ' + ' '.join(shader.chunks))
    if shader.cbuffers:
        lines.append('//')
        for cb in shader.cbuffers:
            lines.append('// cbuffer %s (%d bytes)' % (cb['name'], cb['size']))
            for var in cb['variables']:
                lines.append('//   %-12s %-28s offset %4d size %4d%s' % (
                    var['type'], var['name'] + ('[%d]' % var['elements'] if var['elements'] else ''),
                    var['offset'], var['size'], '' if var['used'] else '  [unused]'))
    if shader.bindings:
        lines.append('//')
        lines.append('// Resource bindings:')
        for binding in shader.bindings:
            prefix = {'cbuffer': 'cb', 'tbuffer': 't', 'texture': 't', 'sampler': 's', 'structured': 't',
                      'byteaddress': 't'}.get(binding['type'], 'u')
            lines.append('//   %-28s %-22s %s%d' % (binding['name'], binding['type'], prefix, binding['register']))
    for title, signature in (('Input', shader.inputs), ('Output', shader.outputs),
                             ('Patch constant', shader.patch_constants)):
        if signature:
            lines.append('//')
            lines.append('// %s signature:' % title)
            for element in signature:
                lines.append('//   %-20s %2d  %-4s  reg %2d  %-8s %s' % (
                    element['name'], element['index'],
                    ''.join(COMPONENTS[i] if element['mask'] & (1 << i) else ' ' for i in range(4)),
                    element['register'], SYSTEM_NAMES.get(element['systemValue'], '') if element['systemValue'] else 'NONE',
                    element['componentType']))
    lines.append('')
    lines.append('%s_%d_%d' % (shader.program, shader.major, shader.minor))
    for declaration in shader.declarations:
        lines.append(declaration_text(declaration))
    depth = 0
    for instruction in shader.instructions:
        if instruction.name in ('endif', 'endloop', 'endswitch', 'else', 'case', 'default'):
            depth = max(0, depth - 1)
        lines.append('  ' * depth + instruction_text(instruction, shader))
        if instruction.name in ('if', 'loop', 'switch', 'else', 'case', 'default'):
            depth += 1
    return '\n'.join(lines) + '\n'
