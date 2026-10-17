"""Ghidra instruction/type/value dossiers joined to the existing native call graph."""
import hashlib
from pathlib import Path
from cytools_core import CyToolError
from . import investigation as inv, process
from .engines import get
from .engines.ghidra import SCRIPTS
from .paths import read_json, write_json


def inspect(project, function, context, refresh=False):
    engine = get('ghidra')
    engine.require()
    analysis = project.analysis('ghidra')
    selected = project.find_function('ghidra', function)
    cache = project.dir / 'investigation/native' / (inv.identity(selected['id']) + '.json')
    dossier = read_json(cache)
    if refresh or dossier.get('targetSha256') != project.meta()['sha256']:
        work = Path(context.workdir)
        work.mkdir(parents=True, exist_ok=True)
        output = work / 'native-dossier.json'
        output.unlink(missing_ok=True)
        gproj = project.engine_dir('ghidra') / 'gproj'
        command = [engine._headless(), str(gproj), 'cydec', '-process', project.binary.name,
                   '-noanalysis', '-readOnly', '-scriptPath', str(SCRIPTS), '-postScript',
                   'CyInspect.java', str(output), selected['address']]
        code, out, err = process.run(command, context=context, env=engine._environment(),
                                     timeout=600, log_name='ghidra-investigation')
        dossier = read_json(output)
        if code != 0 or not dossier.get('address'):
            raise CyToolError('EngineFailed', 'Native investigation failed: ' + process.tail(out + '\n' + err, 20))
        dossier['targetSha256'] = project.meta()['sha256']
        write_json(cache, dossier)
    report = inv.graph(project, 'ghidra')
    functions = {}
    selected_functions = analysis['functions'][:20000]
    if selected not in selected_functions:
        selected_functions = [*selected_functions, selected]
    for f in selected_functions:
        functions[f['id']] = inv.node(report, 'function', f['name'], {'address': f['address']},
                                     functionId=f['id'], signature=f.get('signature', ''))
    for f in selected_functions:
        for callee in f.get('callees', []):
            if callee in functions:
                inv.edge(report, functions[f['id']], functions[callee], 'calls',
                         {'address': f['address'], 'targetSha256': report['targetSha256']})
    owner = functions[selected['id']]
    signature = inv.node(report, 'signature', dossier['prototype'], {'address': dossier['address']},
                         parameters=dossier['parameters'], returnType=dossier['returnType'],
                         callingConvention=dossier.get('callingConvention'))
    inv.edge(report, owner, signature, 'has-type')
    instructions = {}
    for row in dossier['instructions']:
        key = inv.node(report, 'instruction', row['text'], {'address': row['address']}, length=row['length'])
        instructions[row['address']] = key
        inv.edge(report, owner, key, 'contains')
    for row in dossier['references']:
        if row.get('string'):
            key = inv.node(report, 'literal', row['string'], {'address': row['to']})
        else:
            key = inv.node(report, 'reference', row.get('targetFunction') or row['to'],
                           {'address': row['to']}, kindOfReference=row['kind'])
        inv.edge(report, instructions.get(row['from'], owner), key, 'calls' if row['call'] else 'references',
                 {'address': row['from'], 'targetAddress': row['to'], 'targetSha256': report['targetSha256']})
    values = {}
    for row in dossier['values']:
        values[row['id']] = inv.node(report, 'value', row.get('name') or row['storage'],
                                    {'address': dossier['address'], 'valueId': row['id']}, **row)
    for row in dossier['operations']:
        key = inv.node(report, 'pcode', row['opcode'], {'address': row['address'], 'operationId': row['id']})
        inv.edge(report, instructions.get(row['address'], owner), key, 'lifted-to')
        for index, value in enumerate(row['inputs']):
            inv.edge(report, values[value], key, 'input', {'operand': index, 'address': row['address']})
        if row['output'] is not None:
            inv.edge(report, key, values[row['output']], 'defines', {'address': row['address']})
    inv.unknown(report, 'static-analysis-does-not-prove-execution')
    inv.unknown(report, 'native-types-are-analysis-results')
    inv.unknown(report, 'aliasing-indirect-calls-and-cross-function-values-not-resolved')
    if dossier.get('instructionsLimited') or dossier.get('valuesLimited') or len(analysis['functions']) > 20000:
        report['truncated'] = True
        inv.unknown(report, 'native-dossier-limit')
    if dossier.get('decompilerError'):
        inv.unknown(report, 'native-values-unavailable', message=dossier['decompilerError'])
    inv.save(project, report)
    return {'projectId': project.id, 'dossier': dossier,
            'evidence': inv.query(project, selected['name'], 1, 100)}
