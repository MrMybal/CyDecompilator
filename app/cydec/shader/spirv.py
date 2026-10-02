"""SPIR-V binary reader and disassembler (Khronos SPIR-V specification, unified 1.6).

`parse(data)` returns a Module: instructions with their words, debug names, decorations,
types, constants, global variables, entry points and functions split into blocks.
`disassemble(module)` prints a spirv-dis style listing with names resolved.
"""
import struct

from cytools_core import CyToolError

# opcode: (name, has result type, has result id)
OPS = {
    0: ('OpNop', 0, 0), 1: ('OpUndef', 1, 1), 2: ('OpSourceContinued', 0, 0), 3: ('OpSource', 0, 0),
    4: ('OpSourceExtension', 0, 0), 5: ('OpName', 0, 0), 6: ('OpMemberName', 0, 0), 7: ('OpString', 0, 1),
    8: ('OpLine', 0, 0), 10: ('OpExtension', 0, 0), 11: ('OpExtInstImport', 0, 1), 12: ('OpExtInst', 1, 1),
    14: ('OpMemoryModel', 0, 0), 15: ('OpEntryPoint', 0, 0), 16: ('OpExecutionMode', 0, 0),
    17: ('OpCapability', 0, 0), 19: ('OpTypeVoid', 0, 1), 20: ('OpTypeBool', 0, 1), 21: ('OpTypeInt', 0, 1),
    22: ('OpTypeFloat', 0, 1), 23: ('OpTypeVector', 0, 1), 24: ('OpTypeMatrix', 0, 1), 25: ('OpTypeImage', 0, 1),
    26: ('OpTypeSampler', 0, 1), 27: ('OpTypeSampledImage', 0, 1), 28: ('OpTypeArray', 0, 1),
    29: ('OpTypeRuntimeArray', 0, 1), 30: ('OpTypeStruct', 0, 1), 31: ('OpTypeOpaque', 0, 1),
    32: ('OpTypePointer', 0, 1), 33: ('OpTypeFunction', 0, 1), 34: ('OpTypeEvent', 0, 1),
    35: ('OpTypeDeviceEvent', 0, 1), 36: ('OpTypeReserveId', 0, 1), 37: ('OpTypeQueue', 0, 1),
    38: ('OpTypePipe', 0, 1), 39: ('OpTypeForwardPointer', 0, 0), 41: ('OpConstantTrue', 1, 1),
    42: ('OpConstantFalse', 1, 1), 43: ('OpConstant', 1, 1), 44: ('OpConstantComposite', 1, 1),
    45: ('OpConstantSampler', 1, 1), 46: ('OpConstantNull', 1, 1), 48: ('OpSpecConstantTrue', 1, 1),
    49: ('OpSpecConstantFalse', 1, 1), 50: ('OpSpecConstant', 1, 1), 51: ('OpSpecConstantComposite', 1, 1),
    52: ('OpSpecConstantOp', 1, 1), 54: ('OpFunction', 1, 1), 55: ('OpFunctionParameter', 1, 1),
    56: ('OpFunctionEnd', 0, 0), 57: ('OpFunctionCall', 1, 1), 59: ('OpVariable', 1, 1),
    60: ('OpImageTexelPointer', 1, 1), 61: ('OpLoad', 1, 1), 62: ('OpStore', 0, 0), 63: ('OpCopyMemory', 0, 0),
    64: ('OpCopyMemorySized', 0, 0), 65: ('OpAccessChain', 1, 1), 66: ('OpInBoundsAccessChain', 1, 1),
    67: ('OpPtrAccessChain', 1, 1), 68: ('OpArrayLength', 1, 1), 69: ('OpGenericPtrMemSemantics', 1, 1),
    70: ('OpInBoundsPtrAccessChain', 1, 1), 71: ('OpDecorate', 0, 0), 72: ('OpMemberDecorate', 0, 0),
    73: ('OpDecorationGroup', 0, 1), 74: ('OpGroupDecorate', 0, 0), 75: ('OpGroupMemberDecorate', 0, 0),
    77: ('OpVectorExtractDynamic', 1, 1), 78: ('OpVectorInsertDynamic', 1, 1), 79: ('OpVectorShuffle', 1, 1),
    80: ('OpCompositeConstruct', 1, 1), 81: ('OpCompositeExtract', 1, 1), 82: ('OpCompositeInsert', 1, 1),
    83: ('OpCopyObject', 1, 1), 84: ('OpTranspose', 1, 1), 86: ('OpSampledImage', 1, 1),
    87: ('OpImageSampleImplicitLod', 1, 1), 88: ('OpImageSampleExplicitLod', 1, 1),
    89: ('OpImageSampleDrefImplicitLod', 1, 1), 90: ('OpImageSampleDrefExplicitLod', 1, 1),
    91: ('OpImageSampleProjImplicitLod', 1, 1), 92: ('OpImageSampleProjExplicitLod', 1, 1),
    93: ('OpImageSampleProjDrefImplicitLod', 1, 1), 94: ('OpImageSampleProjDrefExplicitLod', 1, 1),
    95: ('OpImageFetch', 1, 1), 96: ('OpImageGather', 1, 1), 97: ('OpImageDrefGather', 1, 1),
    98: ('OpImageRead', 1, 1), 99: ('OpImageWrite', 0, 0), 100: ('OpImage', 1, 1),
    101: ('OpImageQueryFormat', 1, 1), 102: ('OpImageQueryOrder', 1, 1), 103: ('OpImageQuerySizeLod', 1, 1),
    104: ('OpImageQuerySize', 1, 1), 105: ('OpImageQueryLod', 1, 1), 106: ('OpImageQueryLevels', 1, 1),
    107: ('OpImageQuerySamples', 1, 1), 109: ('OpConvertFToU', 1, 1), 110: ('OpConvertFToS', 1, 1),
    111: ('OpConvertSToF', 1, 1), 112: ('OpConvertUToF', 1, 1), 113: ('OpUConvert', 1, 1),
    114: ('OpSConvert', 1, 1), 115: ('OpFConvert', 1, 1), 116: ('OpQuantizeToF16', 1, 1),
    117: ('OpConvertPtrToU', 1, 1), 118: ('OpSatConvertSToU', 1, 1), 119: ('OpSatConvertUToS', 1, 1),
    120: ('OpConvertUToPtr', 1, 1), 124: ('OpBitcast', 1, 1), 126: ('OpSNegate', 1, 1),
    127: ('OpFNegate', 1, 1), 128: ('OpIAdd', 1, 1), 129: ('OpFAdd', 1, 1), 130: ('OpISub', 1, 1),
    131: ('OpFSub', 1, 1), 132: ('OpIMul', 1, 1), 133: ('OpFMul', 1, 1), 134: ('OpUDiv', 1, 1),
    135: ('OpSDiv', 1, 1), 136: ('OpFDiv', 1, 1), 137: ('OpUMod', 1, 1), 138: ('OpSRem', 1, 1),
    139: ('OpSMod', 1, 1), 140: ('OpFRem', 1, 1), 141: ('OpFMod', 1, 1), 142: ('OpVectorTimesScalar', 1, 1),
    143: ('OpMatrixTimesScalar', 1, 1), 144: ('OpVectorTimesMatrix', 1, 1), 145: ('OpMatrixTimesVector', 1, 1),
    146: ('OpMatrixTimesMatrix', 1, 1), 147: ('OpOuterProduct', 1, 1), 148: ('OpDot', 1, 1),
    149: ('OpIAddCarry', 1, 1), 150: ('OpISubBorrow', 1, 1), 151: ('OpUMulExtended', 1, 1),
    152: ('OpSMulExtended', 1, 1), 154: ('OpAny', 1, 1), 155: ('OpAll', 1, 1), 156: ('OpIsNan', 1, 1),
    157: ('OpIsInf', 1, 1), 158: ('OpIsFinite', 1, 1), 159: ('OpIsNormal', 1, 1), 160: ('OpSignBitSet', 1, 1),
    161: ('OpLessOrGreater', 1, 1), 162: ('OpOrdered', 1, 1), 163: ('OpUnordered', 1, 1),
    164: ('OpLogicalEqual', 1, 1), 165: ('OpLogicalNotEqual', 1, 1), 166: ('OpLogicalOr', 1, 1),
    167: ('OpLogicalAnd', 1, 1), 168: ('OpLogicalNot', 1, 1), 169: ('OpSelect', 1, 1), 170: ('OpIEqual', 1, 1),
    171: ('OpINotEqual', 1, 1), 172: ('OpUGreaterThan', 1, 1), 173: ('OpSGreaterThan', 1, 1),
    174: ('OpUGreaterThanEqual', 1, 1), 175: ('OpSGreaterThanEqual', 1, 1), 176: ('OpULessThan', 1, 1),
    177: ('OpSLessThan', 1, 1), 178: ('OpULessThanEqual', 1, 1), 179: ('OpSLessThanEqual', 1, 1),
    180: ('OpFOrdEqual', 1, 1), 181: ('OpFUnordEqual', 1, 1), 182: ('OpFOrdNotEqual', 1, 1),
    183: ('OpFUnordNotEqual', 1, 1), 184: ('OpFOrdLessThan', 1, 1), 185: ('OpFUnordLessThan', 1, 1),
    186: ('OpFOrdGreaterThan', 1, 1), 187: ('OpFUnordGreaterThan', 1, 1), 188: ('OpFOrdLessThanEqual', 1, 1),
    189: ('OpFUnordLessThanEqual', 1, 1), 190: ('OpFOrdGreaterThanEqual', 1, 1),
    191: ('OpFUnordGreaterThanEqual', 1, 1), 194: ('OpShiftRightLogical', 1, 1),
    195: ('OpShiftRightArithmetic', 1, 1), 196: ('OpShiftLeftLogical', 1, 1), 197: ('OpBitwiseOr', 1, 1),
    198: ('OpBitwiseXor', 1, 1), 199: ('OpBitwiseAnd', 1, 1), 200: ('OpNot', 1, 1),
    201: ('OpBitFieldInsert', 1, 1), 202: ('OpBitFieldSExtract', 1, 1), 203: ('OpBitFieldUExtract', 1, 1),
    204: ('OpBitReverse', 1, 1), 205: ('OpBitCount', 1, 1), 207: ('OpDPdx', 1, 1), 208: ('OpDPdy', 1, 1),
    209: ('OpFwidth', 1, 1), 210: ('OpDPdxFine', 1, 1), 211: ('OpDPdyFine', 1, 1), 212: ('OpFwidthFine', 1, 1),
    213: ('OpDPdxCoarse', 1, 1), 214: ('OpDPdyCoarse', 1, 1), 215: ('OpFwidthCoarse', 1, 1),
    218: ('OpEmitVertex', 0, 0), 219: ('OpEndPrimitive', 0, 0), 220: ('OpEmitStreamVertex', 0, 0),
    221: ('OpEndStreamPrimitive', 0, 0), 224: ('OpControlBarrier', 0, 0), 225: ('OpMemoryBarrier', 0, 0),
    227: ('OpAtomicLoad', 1, 1), 228: ('OpAtomicStore', 0, 0), 229: ('OpAtomicExchange', 1, 1),
    230: ('OpAtomicCompareExchange', 1, 1), 231: ('OpAtomicCompareExchangeWeak', 1, 1),
    232: ('OpAtomicIIncrement', 1, 1), 233: ('OpAtomicIDecrement', 1, 1), 234: ('OpAtomicIAdd', 1, 1),
    235: ('OpAtomicISub', 1, 1), 236: ('OpAtomicSMin', 1, 1), 237: ('OpAtomicUMin', 1, 1),
    238: ('OpAtomicSMax', 1, 1), 239: ('OpAtomicUMax', 1, 1), 240: ('OpAtomicAnd', 1, 1),
    241: ('OpAtomicOr', 1, 1), 242: ('OpAtomicXor', 1, 1), 245: ('OpPhi', 1, 1), 246: ('OpLoopMerge', 0, 0),
    247: ('OpSelectionMerge', 0, 0), 248: ('OpLabel', 0, 1), 249: ('OpBranch', 0, 0),
    250: ('OpBranchConditional', 0, 0), 251: ('OpSwitch', 0, 0), 252: ('OpKill', 0, 0),
    253: ('OpReturn', 0, 0), 254: ('OpReturnValue', 0, 0), 255: ('OpUnreachable', 0, 0),
    256: ('OpLifetimeStart', 0, 0), 257: ('OpLifetimeStop', 0, 0), 317: ('OpNoLine', 0, 0),
    330: ('OpModuleProcessed', 0, 0), 331: ('OpExecutionModeId', 0, 0), 332: ('OpDecorateId', 0, 0),
    333: ('OpGroupNonUniformElect', 1, 1), 334: ('OpGroupNonUniformAll', 1, 1),
    335: ('OpGroupNonUniformAny', 1, 1), 336: ('OpGroupNonUniformAllEqual', 1, 1),
    337: ('OpGroupNonUniformBroadcast', 1, 1), 338: ('OpGroupNonUniformBroadcastFirst', 1, 1),
    339: ('OpGroupNonUniformBallot', 1, 1), 340: ('OpGroupNonUniformInverseBallot', 1, 1),
    341: ('OpGroupNonUniformBallotBitExtract', 1, 1), 342: ('OpGroupNonUniformBallotBitCount', 1, 1),
    343: ('OpGroupNonUniformBallotFindLSB', 1, 1), 344: ('OpGroupNonUniformBallotFindMSB', 1, 1),
    345: ('OpGroupNonUniformShuffle', 1, 1), 346: ('OpGroupNonUniformShuffleXor', 1, 1),
    347: ('OpGroupNonUniformShuffleUp', 1, 1), 348: ('OpGroupNonUniformShuffleDown', 1, 1),
    349: ('OpGroupNonUniformIAdd', 1, 1), 350: ('OpGroupNonUniformFAdd', 1, 1),
    351: ('OpGroupNonUniformIMul', 1, 1), 352: ('OpGroupNonUniformFMul', 1, 1),
    353: ('OpGroupNonUniformSMin', 1, 1), 354: ('OpGroupNonUniformUMin', 1, 1),
    355: ('OpGroupNonUniformFMin', 1, 1), 356: ('OpGroupNonUniformSMax', 1, 1),
    357: ('OpGroupNonUniformUMax', 1, 1), 358: ('OpGroupNonUniformFMax', 1, 1),
    4416: ('OpTerminateInvocation', 0, 0), 4421: ('OpSubgroupBallotKHR', 1, 1),
    4422: ('OpSubgroupFirstInvocationKHR', 1, 1), 5380: ('OpDemoteToHelperInvocation', 0, 0),
    5632: ('OpDecorateString', 0, 0), 5633: ('OpMemberDecorateString', 0, 0),
}
NAME_TO_OP = {name: code for code, (name, _, _) in OPS.items()}

EXECUTION_MODELS = {0: 'Vertex', 1: 'TessellationControl', 2: 'TessellationEvaluation', 3: 'Geometry',
                    4: 'Fragment', 5: 'GLCompute', 6: 'Kernel', 5267: 'TaskNV', 5268: 'MeshNV',
                    5313: 'RayGeneration', 5314: 'Intersection', 5315: 'AnyHit', 5316: 'ClosestHit',
                    5317: 'Miss', 5318: 'Callable', 5364: 'TaskEXT', 5365: 'MeshEXT'}
STORAGE = {0: 'UniformConstant', 1: 'Input', 2: 'Uniform', 3: 'Output', 4: 'Workgroup', 5: 'CrossWorkgroup',
           6: 'Private', 7: 'Function', 8: 'Generic', 9: 'PushConstant', 10: 'AtomicCounter', 11: 'Image',
           12: 'StorageBuffer', 5328: 'CallableData', 5329: 'IncomingCallableData', 5338: 'RayPayload',
           5339: 'HitAttribute', 5342: 'IncomingRayPayload', 5343: 'ShaderRecordBuffer',
           5349: 'PhysicalStorageBuffer', 5402: 'TaskPayloadWorkgroupEXT'}
DECORATIONS = {0: 'RelaxedPrecision', 1: 'SpecId', 2: 'Block', 3: 'BufferBlock', 4: 'RowMajor', 5: 'ColMajor',
               6: 'ArrayStride', 7: 'MatrixStride', 8: 'GLSLShared', 9: 'GLSLPacked', 10: 'CPacked',
               11: 'BuiltIn', 13: 'NoPerspective', 14: 'Flat', 15: 'Patch', 16: 'Centroid', 17: 'Sample',
               18: 'Invariant', 19: 'Restrict', 20: 'Aliased', 21: 'Volatile', 22: 'Constant', 23: 'Coherent',
               24: 'NonWritable', 25: 'NonReadable', 26: 'Uniform', 28: 'SaturatedConversion', 29: 'Stream',
               30: 'Location', 31: 'Component', 32: 'Index', 33: 'Binding', 34: 'DescriptorSet', 35: 'Offset',
               36: 'XfbBuffer', 37: 'XfbStride', 38: 'FuncParamAttr', 39: 'FPRoundingMode',
               40: 'FPFastMathMode', 41: 'LinkageAttributes', 42: 'NoContraction', 43: 'InputAttachmentIndex',
               44: 'Alignment', 5634: 'UserSemantic', 5635: 'UserTypeGOOGLE', 5300: 'NonUniform'}
BUILTINS = {0: 'gl_Position', 1: 'gl_PointSize', 3: 'gl_ClipDistance', 4: 'gl_CullDistance',
            5: 'gl_VertexID', 6: 'gl_InstanceID', 7: 'gl_PrimitiveID', 8: 'gl_InvocationID', 9: 'gl_Layer',
            10: 'gl_ViewportIndex', 11: 'gl_TessLevelOuter', 12: 'gl_TessLevelInner', 13: 'gl_TessCoord',
            14: 'gl_PatchVerticesIn', 15: 'gl_FragCoord', 16: 'gl_PointCoord', 17: 'gl_FrontFacing',
            18: 'gl_SampleID', 19: 'gl_SamplePosition', 20: 'gl_SampleMask', 22: 'gl_FragDepth',
            23: 'gl_HelperInvocation', 24: 'gl_NumWorkGroups', 25: 'gl_WorkGroupSize', 26: 'gl_WorkGroupID',
            27: 'gl_LocalInvocationID', 28: 'gl_GlobalInvocationID', 29: 'gl_LocalInvocationIndex',
            36: 'gl_SubgroupSize', 38: 'gl_NumSubgroups', 40: 'gl_SubgroupID', 41: 'gl_SubgroupInvocationID',
            42: 'gl_VertexIndex', 43: 'gl_InstanceIndex', 4424: 'gl_BaseVertex', 4425: 'gl_BaseInstance',
            4426: 'gl_DrawID', 4440: 'gl_ViewIndex', 5014: 'gl_FragStencilRefARB'}
DIMS = {0: '1D', 1: '2D', 2: '3D', 3: 'Cube', 4: 'Rect', 5: 'Buffer', 6: 'SubpassData'}
EXECUTION_MODES = {0: 'Invocations', 1: 'SpacingEqual', 2: 'SpacingFractionalEven', 3: 'SpacingFractionalOdd',
                   4: 'VertexOrderCw', 5: 'VertexOrderCcw', 6: 'PixelCenterInteger', 7: 'OriginUpperLeft',
                   8: 'OriginLowerLeft', 9: 'EarlyFragmentTests', 10: 'PointMode', 11: 'Xfb',
                   12: 'DepthReplacing', 14: 'DepthGreater', 15: 'DepthLess', 16: 'DepthUnchanged',
                   17: 'LocalSize', 18: 'LocalSizeHint', 19: 'InputPoints', 20: 'InputLines',
                   21: 'InputLinesAdjacency', 22: 'Triangles', 23: 'InputTrianglesAdjacency', 24: 'Quads',
                   25: 'Isolines', 26: 'OutputVertices', 27: 'OutputPoints', 28: 'OutputLineStrip',
                   29: 'OutputTriangleStrip', 38: 'LocalSizeId'}
GENERATORS = {0: 'Khronos', 1: 'LunarG', 2: 'Valve', 3: 'Codeplay', 4: 'NVIDIA', 5: 'ARM',
              6: 'Khronos LLVM/SPIR-V Translator', 7: 'Khronos SPIR-V Tools Assembler',
              8: 'Khronos Glslang Reference Front End', 9: 'Qualcomm', 10: 'AMD', 11: 'Intel',
              12: 'Imagination', 13: 'Google Shaderc over Glslang', 14: 'Google spiregg (DXC)',
              15: 'Google rspirv', 16: 'X-LEGEND Mesa-IR/SPIR-V Translator', 17: 'Khronos SPIR-V Tools Linker',
              18: 'Wine VKD3D Shader Compiler', 19: 'Clay Clay Shader Compiler', 20: 'W3C WebGPU Group WHLSL',
              21: 'Google Clspv', 22: 'Google MLIR SPIR-V Serializer', 23: 'Google Tint Compiler',
              24: 'Google ANGLE Shader Compiler', 25: 'Netease Messiah Shader Compiler',
              26: 'Xenia Xenia Emulator Microcode Translator', 27: 'Embark Studios Rust GPU',
              28: 'gfx-rs community Naga', 29: 'Mikkosoft Productions MSP Shader Compiler',
              30: 'SpvGenTwo', 31: 'Google Skia SkSL', 32: 'TornadoVM', 33: 'Taichi', 34: 'heroseh Hero C Compiler',
              35: 'Meta SparkSL', 36: 'SirLynix Nazara ShaderLang', 37: 'NVIDIA Slang'}


class Instruction:
    __slots__ = ('opcode', 'name', 'words', 'type', 'result', 'operands', 'index')

    def __init__(self, opcode, words, index):
        self.opcode = opcode
        info = OPS.get(opcode, ('Op%d' % opcode, 0, 0))
        self.name = info[0]
        self.words = words
        self.index = index
        position = 0
        self.type = None
        self.result = None
        if info[1]:
            self.type = words[position]
            position += 1
        if info[2]:
            self.result = words[position]
            position += 1
        self.operands = words[position:]


class Block:
    def __init__(self, label):
        self.label = label
        self.instructions = []
        self.merge = None        # ('selection', merge) or ('loop', merge, continue)
        self.terminator = None


class Function:
    def __init__(self, instruction):
        self.id = instruction.result
        self.return_type = instruction.type
        self.function_type = instruction.operands[1] if len(instruction.operands) > 1 else None
        self.control = instruction.operands[0] if instruction.operands else 0
        self.parameters = []
        self.variables = []
        self.blocks = []


class Module:
    def __init__(self):
        self.version = (1, 0)
        self.generator = 0
        self.bound = 0
        self.instructions = []
        self.names = {}
        self.member_names = {}
        self.decorations = {}
        self.member_decorations = {}
        self.types = {}
        self.constants = {}
        self.globals = []
        self.entry_points = []
        self.execution_modes = {}
        self.functions = []
        self.ext_imports = {}
        self.capabilities = []
        self.extensions = []
        self.source = ''
        self.strings = {}
        self.defs = {}

    @property
    def generator_name(self):
        vendor = self.generator >> 16
        return '%s (version %d)' % (GENERATORS.get(vendor, 'vendor %d' % vendor), self.generator & 0xffff)


def literal_string(words):
    data = b''.join(struct.pack('<I', w) for w in words)
    end = data.find(b'\0')
    text = data[:end if end >= 0 else len(data)].decode('utf-8', 'replace')
    used = (len(text.encode('utf-8')) // 4) + 1
    return text, used


def parse(data):
    if len(data) < 20 or len(data) % 4:
        raise CyToolError('EngineFailed', 'Truncated SPIR-V module.')
    magic = struct.unpack_from('<I', data, 0)[0]
    endian = '<' if magic == 0x07230203 else '>' if magic == 0x03022307 else None
    if endian is None:
        raise CyToolError('EngineFailed', 'Not a SPIR-V module.')
    words = list(struct.unpack('%s%dI' % (endian, len(data) // 4), data))
    module = Module()
    version = words[1]
    module.version = ((version >> 16) & 0xff, (version >> 8) & 0xff)
    module.generator = words[2]
    module.bound = words[3]
    position = 5
    function = None
    block = None
    while position < len(words):
        head = words[position]
        count, opcode = head >> 16, head & 0xffff
        if count == 0 or position + count > len(words):
            raise CyToolError('EngineFailed', 'Malformed SPIR-V instruction at word %d.' % position)
        instruction = Instruction(opcode, words[position + 1:position + count], len(module.instructions))
        module.instructions.append(instruction)
        position += count
        name = instruction.name
        if instruction.result is not None:
            module.defs[instruction.result] = instruction
        if name == 'OpName':
            module.names[instruction.operands[0]] = literal_string(instruction.operands[1:])[0]
        elif name == 'OpMemberName':
            module.member_names[(instruction.operands[0], instruction.operands[1])] = literal_string(instruction.operands[2:])[0]
        elif name == 'OpString':
            module.strings[instruction.result] = literal_string(instruction.operands)[0]
        elif name in ('OpDecorate', 'OpDecorateId', 'OpDecorateString'):
            target, decoration = instruction.operands[0], instruction.operands[1]
            module.decorations.setdefault(target, {})[decoration] = instruction.operands[2:]
        elif name in ('OpMemberDecorate', 'OpMemberDecorateString'):
            target, member, decoration = instruction.operands[:3]
            module.member_decorations.setdefault((target, member), {})[decoration] = instruction.operands[3:]
        elif name == 'OpExtInstImport':
            module.ext_imports[instruction.result] = literal_string(instruction.operands)[0]
        elif name == 'OpCapability':
            module.capabilities.append(instruction.operands[0])
        elif name == 'OpExtension':
            module.extensions.append(literal_string(instruction.operands)[0])
        elif name == 'OpSource':
            module.source = {1: 'ESSL', 2: 'GLSL', 3: 'OpenCL_C', 4: 'OpenCL_CPP', 5: 'HLSL',
                             6: 'CPP_for_OpenCL', 7: 'SYCL', 8: 'HERO_C', 9: 'NZSL', 10: 'WGSL',
                             11: 'Slang', 12: 'Zig'}.get(instruction.operands[0], 'Unknown') + \
                (' %d' % instruction.operands[1] if len(instruction.operands) > 1 else '')
        elif name == 'OpEntryPoint':
            model, function_id = instruction.operands[0], instruction.operands[1]
            text, used = literal_string(instruction.operands[2:])
            module.entry_points.append({'model': EXECUTION_MODELS.get(model, str(model)), 'function': function_id,
                                        'name': text, 'interface': instruction.operands[2 + used:]})
        elif name in ('OpExecutionMode', 'OpExecutionModeId'):
            module.execution_modes.setdefault(instruction.operands[0], []).append(
                (instruction.operands[1], instruction.operands[2:]))
        elif name.startswith('OpType'):
            module.types[instruction.result] = instruction
        elif name.startswith(('OpConstant', 'OpSpecConstant')) or name == 'OpUndef' and function is None:
            module.constants[instruction.result] = instruction
        elif name == 'OpVariable' and function is None:
            module.globals.append(instruction)
        elif name == 'OpFunction':
            function = Function(instruction)
            module.functions.append(function)
        elif name == 'OpFunctionParameter' and function is not None:
            function.parameters.append(instruction)
        elif name == 'OpFunctionEnd':
            function = None
            block = None
        elif name == 'OpLabel' and function is not None:
            block = Block(instruction.result)
            function.blocks.append(block)
        elif function is not None and block is not None:
            if name == 'OpVariable':
                function.variables.append(instruction)
            elif name == 'OpSelectionMerge':
                block.merge = ('selection', instruction.operands[0])
            elif name == 'OpLoopMerge':
                block.merge = ('loop', instruction.operands[0], instruction.operands[1])
            elif name in ('OpBranch', 'OpBranchConditional', 'OpSwitch', 'OpReturn', 'OpReturnValue', 'OpKill',
                          'OpUnreachable', 'OpTerminateInvocation'):
                block.terminator = instruction
            elif name not in ('OpLine', 'OpNoLine'):
                block.instructions.append(instruction)
    return module


# ---------------------------------------------------------------------- disassembly

def id_text(module, value):
    name = module.names.get(value)
    return '%%%d' % value + ('(%s)' % name if name else '')


def type_text(module, type_id):
    instruction = module.types.get(type_id)
    if instruction is None:
        return id_text(module, type_id)
    name = instruction.name
    ops = instruction.operands
    if name == 'OpTypeVoid':
        return 'void'
    if name == 'OpTypeBool':
        return 'bool'
    if name == 'OpTypeInt':
        return ('i' if ops[1] else 'u') + str(ops[0])
    if name == 'OpTypeFloat':
        return 'f' + str(ops[0])
    if name == 'OpTypeVector':
        return 'v%d%s' % (ops[1], type_text(module, ops[0]))
    if name == 'OpTypeMatrix':
        return 'mat%d<%s>' % (ops[1], type_text(module, ops[0]))
    if name == 'OpTypePointer':
        return 'ptr<%s, %s>' % (STORAGE.get(ops[0], ops[0]), type_text(module, ops[1]))
    if name == 'OpTypeStruct':
        return module.names.get(type_id) or 'struct%d' % type_id
    if name == 'OpTypeArray':
        return '%s[%s]' % (type_text(module, ops[0]), constant_value(module, ops[1]))
    if name == 'OpTypeRuntimeArray':
        return '%s[]' % type_text(module, ops[0])
    if name == 'OpTypeImage':
        return 'image%s' % DIMS.get(ops[1], '?')
    if name == 'OpTypeSampledImage':
        return 'sampled<%s>' % type_text(module, ops[0])
    return name[6:].lower()


def constant_value(module, constant_id):
    instruction = module.constants.get(constant_id)
    if instruction is None or instruction.name not in ('OpConstant', 'OpSpecConstant'):
        return id_text(module, constant_id)
    type_info = module.types.get(instruction.type)
    words = instruction.operands
    if type_info is not None and type_info.name == 'OpTypeFloat':
        if type_info.operands[0] == 32:
            return format_float(struct.unpack('<f', struct.pack('<I', words[0]))[0])
        if type_info.operands[0] == 64 and len(words) > 1:
            return format_float(struct.unpack('<d', struct.pack('<II', words[0], words[1]))[0])
        if type_info.operands[0] == 16:
            return format_float(struct.unpack('<e', struct.pack('<H', words[0] & 0xffff))[0])
    if type_info is not None and type_info.name == 'OpTypeInt':
        value = words[0] | ((words[1] << 32) if len(words) > 1 and type_info.operands[0] == 64 else 0)
        if type_info.operands[1] and value & (1 << (type_info.operands[0] - 1)):
            value -= 1 << type_info.operands[0]
        return str(value)
    return str(words[0]) if words else '0'


def format_float(value):
    if value != value:
        return 'NaN'
    if value in (float('inf'), float('-inf')):
        return '1.0 / 0.0' if value > 0 else '-1.0 / 0.0'
    text = '%.9g' % value
    if 'e' not in text and '.' not in text:
        text += '.0'
    single = struct.unpack('<f', struct.pack('<f', value))[0] if abs(value) < 3.4e38 else value
    for digits in range(1, 10):
        shorter = '%.*g' % (digits, value)
        candidate = float(shorter)
        rounded = struct.unpack('<f', struct.pack('<f', candidate))[0] if abs(candidate) < 3.4e38 else candidate
        if rounded == single:
            text = shorter
            if 'e' not in text and '.' not in text:
                text += '.0'
            break
    return text


def disassemble(module):
    lines = ['; SPIR-V %d.%d' % module.version, '; Generator: ' + module.generator_name,
             '; Bound: %d' % module.bound, '; Source: %s' % (module.source or 'unknown'), '']
    for instruction in module.instructions:
        name = instruction.name
        ops = instruction.operands
        if name in ('OpName', 'OpMemberName', 'OpSourceExtension', 'OpExtension', 'OpModuleProcessed'):
            text, used = literal_string(ops[2 if name == 'OpMemberName' else 1 if name == 'OpName' else 0:])
            prefix = ' '.join(id_text(module, o) if i == 0 else str(o)
                              for i, o in enumerate(ops[:2 if name == 'OpMemberName' else 1 if name == 'OpName' else 0]))
            body = '%s "%s"' % (prefix, text) if prefix else '"%s"' % text
        elif name in ('OpString', 'OpExtInstImport'):
            body = '"%s"' % literal_string(ops)[0]
        elif name == 'OpEntryPoint':
            text, used = literal_string(ops[2:])
            body = '%s %s "%s" %s' % (EXECUTION_MODELS.get(ops[0], ops[0]), id_text(module, ops[1]), text,
                                      ' '.join(id_text(module, o) for o in ops[2 + used:]))
        elif name in ('OpDecorate', 'OpMemberDecorate'):
            member = name == 'OpMemberDecorate'
            target = id_text(module, ops[0])
            decoration_index = 2 if member else 1
            decoration = ops[decoration_index]
            arguments = ops[decoration_index + 1:]
            if decoration == 11 and arguments:
                arguments = [BUILTINS.get(arguments[0], arguments[0])]
            body = '%s %s%s %s' % (target, ('%d ' % ops[1]) if member else '', DECORATIONS.get(decoration, decoration),
                                   ' '.join(str(a) for a in arguments))
        elif name == 'OpExecutionMode':
            body = '%s %s %s' % (id_text(module, ops[0]), EXECUTION_MODES.get(ops[1], ops[1]),
                                 ' '.join(str(o) for o in ops[2:]))
        elif name in ('OpConstant', 'OpSpecConstant'):
            body = constant_value(module, instruction.result)
        elif name == 'OpVariable':
            body = STORAGE.get(ops[0], str(ops[0])) + ''.join(' ' + id_text(module, o) for o in ops[1:])
        elif name == 'OpTypePointer':
            body = '%s %s' % (STORAGE.get(ops[0], ops[0]), id_text(module, ops[1]))
        elif name in ('OpTypeInt', 'OpTypeFloat', 'OpTypeVector', 'OpTypeMatrix') or name == 'OpCapability':
            body = ' '.join(id_text(module, o) if i == 0 and name in ('OpTypeVector', 'OpTypeMatrix') else str(o)
                            for i, o in enumerate(ops))
        elif name == 'OpTypeImage':
            body = '%s %s depth=%d arrayed=%d ms=%d sampled=%d format=%d' % (
                id_text(module, ops[0]), DIMS.get(ops[1], ops[1]), ops[2], ops[3], ops[4], ops[5], ops[6])
        elif name == 'OpExtInst':
            from .glsl import GLSL_STD
            set_name = module.ext_imports.get(ops[0], '')
            function = GLSL_STD.get(ops[1], (str(ops[1]),))[0] if set_name == 'GLSL.std.450' else str(ops[1])
            body = '%s %s %s' % (id_text(module, ops[0]), function, ' '.join(id_text(module, o) for o in ops[2:]))
        elif name in ('OpCompositeExtract', 'OpCompositeInsert', 'OpVectorShuffle', 'OpLoopMerge', 'OpSelectionMerge',
                      'OpSwitch', 'OpMemoryModel', 'OpSource', 'OpControlBarrier', 'OpMemoryBarrier', 'OpFunction',
                      'OpLoad', 'OpStore'):
            fixed = {'OpCompositeExtract': 1, 'OpCompositeInsert': 2, 'OpVectorShuffle': 2, 'OpLoopMerge': 2,
                     'OpSelectionMerge': 1, 'OpSwitch': 2, 'OpMemoryModel': 0, 'OpSource': 0,
                     'OpControlBarrier': 0, 'OpMemoryBarrier': 0, 'OpFunction': 0, 'OpLoad': 1, 'OpStore': 2}[name]
            parts = []
            for i, o in enumerate(ops):
                if name == 'OpSwitch' and i >= 2:
                    parts.append(str(o) if i % 2 == 0 else id_text(module, o))
                elif name == 'OpFunction' and i == 1:
                    parts.append(id_text(module, o))
                else:
                    parts.append(id_text(module, o) if i < fixed else str(o))
            body = ' '.join(parts)
        else:
            body = ' '.join(id_text(module, o) if o in module.defs or 0 < o < module.bound and o in module.names
                            else str(o) for o in ops)
        left = ''
        if instruction.result is not None:
            left = id_text(module, instruction.result) + ' = '
        type_part = (type_text(module, instruction.type) + ' ') if instruction.type is not None else ''
        indent = '' if name in ('OpLabel', 'OpFunction', 'OpFunctionEnd') else '      '
        lines.append(('%s%s%s %s%s' % (indent, left, name, type_part, body)).rstrip())
    return '\n'.join(lines) + '\n'
