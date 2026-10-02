"""CyDecompilator shader engine (own implementation): DXBC -> HLSL, SPIR-V -> GLSL, DXIL info.

Units: one per shader entry point. DXBC holds a single program (`main`); SPIR-V can hold
several entry points, each decompiled with the module's declarations and helpers.
"""
import time

from cytools_core import CyToolError

from ..shader import dxbc, dxil, dxil_hlsl, glsl, hlsl, spirv
from .base import Engine


class ShaderEngine(Engine):
    id = 'shader'
    name = 'CyDecompilator shader engine'
    license = 'Part of CyDecompilator'
    url = ''
    description = ('Own engine: DXBC Shader Model 4/5 to HLSL and DXIL Shader Model 6 (LLVM bitcode) to HLSL '
                   'with reflection names, SPIR-V to GLSL, all with structured control flow.')
    formats = ('dxbc', 'dxil', 'spirv')
    components = ()
    language = 'hlsl'
    supports_disassemble = True

    def availability(self):
        return {'available': True, 'missing': [], 'detail': 'Built in'}

    def analyze(self, project, context):
        started = time.monotonic()
        data = project.binary.read_bytes()
        fmt = project.meta()['detect']['format']
        context.progress(20, 'Parsing shader')
        if fmt == 'dxbc':
            shader = dxbc.parse(data)
            functions = [{'id': 'main', 'name': 'main', 'kind': 'entry',
                          'signature': '%s shader %s' % (shader.program_name, shader.profile),
                          'lines': len(shader.instructions)}]
            summary = {'kind': shader.program_name, 'model': '%d.%d' % (shader.major, shader.minor),
                       'profile': shader.profile, 'instructions': len(shader.instructions),
                       'temps': shader.temps, 'bindings': shader.bindings,
                       'inputs': shader.inputs, 'outputs': shader.outputs,
                       'cbuffers': [{'name': c['name'], 'size': c['size'],
                                     'variables': [v['name'] for v in c['variables']]} for c in shader.cbuffers],
                       'creator': shader.creator, 'chunks': shader.chunks}
            message = '%s shader %s, %d instructions' % (shader.program_name, shader.profile, len(shader.instructions))
        elif fmt == 'spirv':
            module = spirv.parse(data)
            functions = []
            for entry in module.entry_points:
                functions.append({'id': entry['name'], 'name': entry['name'], 'kind': 'entry',
                                  'signature': '%s entry point' % entry['model']})
            if not functions:
                functions.append({'id': 'module', 'name': 'module', 'kind': 'module'})
            summary = {'version': '%d.%d' % module.version, 'generator': module.generator_name,
                       'source': module.source, 'entryPoints': [{'name': e['name'], 'model': e['model']}
                                                                 for e in module.entry_points],
                       'functions': len(module.functions), 'bound': module.bound,
                       'capabilities': module.capabilities, 'extensions': module.extensions}
            message = 'SPIR-V %d.%d, %d entry point(s), %d function(s)' % (
                module.version[0], module.version[1], len(module.entry_points), len(module.functions))
        elif fmt == 'dxil':
            info = dxil.parse(data)
            functions = [{'id': 'main', 'name': 'main', 'kind': 'entry',
                          'signature': '%s shader SM %s (DXIL)' % (info['kind'], info['model'])}]
            summary = info
            message = 'DXIL %s shader, Shader Model %s' % (info['kind'], info['model'])
        else:
            raise CyToolError('Unsupported', 'Not a shader format: %s' % fmt)
        context.progress(100, 'Done')
        return {'functions': functions, 'strings': [], 'imports': [], 'shader': summary,
                'message': message, 'seconds': round(time.monotonic() - started, 3)}

    def decompile(self, project, analysis, function, context):
        data = project.binary.read_bytes()
        fmt = project.meta()['detect']['format']
        if fmt == 'dxbc':
            return {'code': hlsl.decompile(dxbc.parse(data)), 'language': 'hlsl'}
        if fmt == 'spirv':
            module = spirv.parse(data)
            entry = function['id'] if function['id'] != 'module' else None
            return {'code': glsl.decompile(module, entry), 'language': 'glsl'}
        return {'code': dxil_hlsl.decompile(data), 'language': 'hlsl'}

    def disassemble(self, project, analysis, function, context):
        data = project.binary.read_bytes()
        fmt = project.meta()['detect']['format']
        if fmt == 'dxbc':
            return {'code': dxbc.disassemble(dxbc.parse(data)), 'language': 'dxasm'}
        if fmt == 'spirv':
            return {'code': spirv.disassemble(spirv.parse(data)), 'language': 'spvasm'}
        return {'code': dxil.describe(dxil.parse(data)) + chr(10) + dxil_hlsl.ir_listing(data), 'language': 'llvm'}
