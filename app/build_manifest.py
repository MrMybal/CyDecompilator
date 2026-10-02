"""Write CyTool.json from operations.py. Run after changing an operation contract:

    runtime/python/Scripts/python.exe app/build_manifest.py
"""
import json
from pathlib import Path

from operations import OPERATIONS

APP = Path(__file__).resolve().parent
VERSION = '1.3.0'


def operation(spec):
    output_properties = dict(spec.get('outputs', {}))
    return {
        'id': spec['id'], 'name': spec['name'], 'description': spec['description'],
        'inputSchema': {'type': 'object', 'properties': spec.get('inputs', {}),
                        'required': spec.get('required', []), 'additionalProperties': False},
        'outputSchema': {'type': 'object', 'properties': output_properties, 'additionalProperties': True},
        'resourceRequirements': {'ramBytes': spec.get('ram', 64 * 1024 ** 2),
                                 **({'networkRequired': True} if spec.get('network') else {})},
        'supportedBackends': [], 'permissions': spec.get('permissions', []),
        'exclusiveGroups': spec.get('groups', []),
        'canRunAsync': True, 'canCancel': True, 'supportsProgress': True,
    }


def manifest():
    return {
        'schemaVersion': 1, 'protocolVersion': '1.0', 'id': 'cy.tool.decompilator', 'name': 'CyDecompilator',
        'displayName': 'CyDecompilator', 'version': VERSION,
        'description': 'AI assisted multi-engine decompiler: native code (Ghidra, own x86/x64 C decompiler, built-in disassembler), .NET '
                       '(ILSpy), Java (Vineflower), Android (JADX), Python bytecode and shaders (own DXBC/SPIR-V/DXIL '
                       'engine), with an assistant that explains, renames and converts pseudo-code into real code.',
        'vendor': 'Cyberalien', 'author': 'Cyberalien', 'license': 'GPL-3.0-only',
        'executable': 'runtime/python/Scripts/python.exe app/tool.py',
        'categories': ['reverse-engineering', 'developer-tools'],
        'tags': ['decompiler', 'disassembler', 'ghidra', 'ilspy', 'java', 'android', 'python', 'shader', 'hlsl',
                 'glsl', 'spirv', 'dxbc', 'ai'],
        'capabilities': ['jobs', 'cancellation', 'progress'],
        'backends': [],
        'platforms': [
            {'os': 'Windows', 'architecture': 'x64', 'status': 'Supported', 'computeBackends': ['CPU']},
            {'os': 'Linux', 'architecture': 'x64', 'status': 'Experimental', 'computeBackends': ['CPU']},
        ],
        'interfaces': ['Native', 'CLI', 'JSONL', 'HTTP', 'MCP', 'ImGui'],
        'runtimeRequirements': [],
        'concurrency': {'policy': 'Concurrent', 'maxWorkers': 6},
        'operations': [operation(spec) for spec in OPERATIONS],
        'standaloneExecutable': 'CyDecompilator.exe',
        'distributionStatus': 'Portable on the machine where runtime/ was created; see README.',
    }


if __name__ == '__main__':
    path = APP / 'CyTool.json'
    path.write_text(json.dumps(manifest(), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Wrote %s (%d operations)' % (path, len(OPERATIONS)))
