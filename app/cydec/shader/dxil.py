"""DXIL (Shader Model 6) container reader.

DXIL programs are LLVM bitcode inside a DXBC-style container. This module reads what the
container states directly (shader kind and model, signatures, pipeline state validation
resources, root signature presence, debug name) so an SM6 shader can be identified and
explained. The bitcode itself is reported as such; the AI actions work from this summary.
"""
import struct

from .dxbc import COMPONENTS, chunks, parse_signature, _cstring

KINDS = {0: 'Pixel', 1: 'Vertex', 2: 'Geometry', 3: 'Hull', 4: 'Domain', 5: 'Compute', 6: 'Library',
         7: 'RayGeneration', 8: 'Intersection', 9: 'AnyHit', 10: 'ClosestHit', 11: 'Miss', 12: 'Callable',
         13: 'Mesh', 14: 'Amplification', 15: 'Node'}
PSV_RESOURCES = {0: 'Invalid', 1: 'Sampler', 2: 'CBV', 3: 'SRVTyped', 4: 'SRVRaw', 5: 'SRVStructured',
                 6: 'UAVTyped', 7: 'UAVRaw', 8: 'UAVStructured', 9: 'UAVStructuredWithCounter'}


def parse(data):
    info = {'chunks': [], 'inputs': [], 'outputs': [], 'resources': [], 'kind': '', 'model': '',
            'bitcodeBytes': 0, 'debugName': '', 'rootSignature': False}
    for fourcc, blob in chunks(data):
        info['chunks'].append(fourcc)
        if fourcc == 'DXIL' and len(blob) >= 24:
            version, size_dwords = struct.unpack_from('<II', blob, 0)
            info['kind'] = KINDS.get(version >> 16, 'Unknown')
            info['model'] = '%d.%d' % ((version >> 4) & 0xf, version & 0xf)
            magic, dxil_version, offset, size = struct.unpack_from('<4sIII', blob, 8)
            info['dxilVersion'] = '%d.%d' % (dxil_version >> 8, dxil_version & 0xff)
            info['bitcodeBytes'] = size
        elif fourcc in ('ISG1', 'ISGN'):
            info['inputs'] = parse_signature(fourcc, blob)
        elif fourcc in ('OSG1', 'OSGN', 'OSG5'):
            info['outputs'] = parse_signature(fourcc, blob)
        elif fourcc == 'ILDN' and len(blob) > 4:
            flags, length = struct.unpack_from('<HH', blob, 0)
            info['debugName'] = blob[4:4 + length].decode('utf-8', 'replace')
        elif fourcc == 'RTS0':
            info['rootSignature'] = True
        elif fourcc == 'PSV0' and len(blob) >= 4:
            try:
                info['resources'] = _psv_resources(blob)
            except struct.error:
                pass
    return info


def _psv_resources(blob):
    runtime_size = struct.unpack_from('<I', blob, 0)[0]
    offset = 4 + runtime_size
    count = struct.unpack_from('<I', blob, offset)[0]
    offset += 4
    resources = []
    if count:
        stride = struct.unpack_from('<I', blob, offset)[0]
        offset += 4
        for index in range(count):
            kind, space, lower, upper = struct.unpack_from('<4I', blob, offset + index * stride)
            resources.append({'type': PSV_RESOURCES.get(kind, str(kind)), 'space': space,
                              'register': lower, 'upper': upper})
    return resources


def describe(info):
    lines = ['// %s shader, Shader Model %s (DXIL %s)' % (info['kind'], info['model'], info.get('dxilVersion', '?')),
             '// Container chunks: ' + ' '.join(info['chunks'])]
    if info['debugName']:
        lines.append('// Debug name: ' + info['debugName'])
    lines.append('// LLVM bitcode: %d bytes%s' % (info['bitcodeBytes'], '; root signature embedded' if info['rootSignature'] else ''))
    lines.append('')
    if info['resources']:
        lines.append('// Resource bindings (pipeline state validation):')
        prefix = {'Sampler': 's', 'CBV': 'b'}
        for resource in info['resources']:
            letter = prefix.get(resource['type'], 'u' if resource['type'].startswith('UAV') else 't')
            count = resource['upper'] - resource['register'] + 1 if resource['upper'] != 0xffffffff else 0
            lines.append('//   %-24s register(%s%d, space%d)%s' % (
                resource['type'], letter, resource['register'], resource['space'],
                '' if count == 1 else ' x%s' % (count or 'unbounded')))
        lines.append('')
    for title, elements in (('Input', info['inputs']), ('Output', info['outputs'])):
        if elements:
            lines.append('struct %s' % title)
            lines.append('{')
            for element in elements:
                count = bin(element['mask']).count('1')
                base = {'uint': 'uint', 'int': 'int'}.get(element['componentType'], 'float')
                type_name = base if count == 1 else '%s%d' % (base, count)
                semantic = element['name'] + (str(element['index']) if element['index'] else '')
                lines.append('    %-8s %-20s : %s;  // register %d.%s' % (
                    type_name, semantic.lower() if not semantic.upper().startswith('SV_') else semantic,
                    semantic, element['register'],
                    ''.join(COMPONENTS[i] for i in range(4) if element['mask'] & (1 << i))))
            lines.append('};')
            lines.append('')
    return '\n'.join(lines) + '\n'
