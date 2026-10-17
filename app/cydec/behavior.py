"""Owned process captures and bounded filesystem comparisons, including Windows.

The working directory is disposable. This is observation, not an OS sandbox: network
access and writes outside the working directory are not intercepted or compared.
"""
import difflib
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from cytools_core import CyToolError
from . import investigation as inv, process
from .engines.base import EngineContext
from .javascript import read_tree, safe_relative
from .paths import read_json, write_json


def digest(path, context):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 ** 2), b''):
            context.check()
            h.update(block)
    return h.hexdigest()


def snapshot(root, context):
    # All observed files, including build folders, are significant here.
    from .javascript import is_link
    import os
    rows, unknowns, total = {}, [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        context.check()
        base = Path(directory)
        for name in list(dirs):
            if is_link(base / name):
                dirs.remove(name)
                unknowns.append({'code': 'capture-link-not-followed', 'path': (base / name).relative_to(root).as_posix()})
        for name in sorted(names):
            path = base / name
            relative = path.relative_to(root).as_posix()
            size = path.lstat().st_size
            if is_link(path) or not path.is_file() or len(rows) >= 4000 or size > 32 * 1024 ** 2 or total + size > 128 * 1024 ** 2:
                unknowns.append({'code': 'capture-file-not-observed', 'path': relative, 'size': size})
                continue
            rows[relative] = {'size': size, 'sha256': digest(path, context)}
            total += size
    return rows, unknowns


def changes(before, after):
    return [{'path': name, 'kind': 'added' if name not in before else 'deleted' if name not in after else 'modified',
             'before': before.get(name), 'after': after.get(name)}
            for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]


def capture(project, context, executable, arguments=(), stdin='', assets_directory='', seed_files=None, timeout=60, observation=None):
    from .runtime_observation import Observer
    executable = Path(executable)
    if not executable.is_absolute() or not executable.is_file():
        raise CyToolError('InvalidParameters', 'Select an absolute executable path for the capture.')
    if not isinstance(arguments, (list, tuple)) or len(arguments) > 100 or any(not isinstance(a, str) or len(a) > 8192 for a in arguments):
        raise CyToolError('InvalidParameters', 'Capture arguments must be a bounded array of strings.')
    if len(stdin.encode('utf-8')) > 65536:
        raise CyToolError('InvalidParameters', 'Capture input must be smaller than 64 KB.')
    timeout = min(300, max(1, int(timeout)))
    capture_id = uuid.uuid4().hex
    directory = project.dir / 'investigation/captures' / capture_id
    root = directory / 'working'
    root.mkdir(parents=True, exist_ok=False)
    files, exclusions = read_tree(assets_directory, context) if assets_directory else ({}, [])
    if not isinstance(seed_files or {}, dict) or len(seed_files or {}) > 100:
        raise CyToolError('InvalidParameters', 'Capture seed files must be a bounded object of text files.')
    for name, text in (seed_files or {}).items():
        name = safe_relative(name)
        if not isinstance(text, str) or len(text.encode()) > 1024 ** 2:
            raise CyToolError('InvalidParameters', 'Capture seed files must be a bounded object of text files.')
        files[name] = text.encode('utf-8')
    for name, data in files.items():
        context.check()
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    before, missing_before = snapshot(root, context)
    target_hash = digest(executable, context)
    argument_files = []
    for index, argument in enumerate(arguments):
        path = Path(argument)
        if path.is_absolute() and path.is_file():
            argument_files.append({'index': index, 'path': str(path), 'sha256': digest(path, context)})
    logs = directory / 'logs'
    logs.mkdir()
    run_context = EngineContext(context.cancellation, context._progress, context._log, logs,
                                emit=context._emit)
    observer=Observer(context,directory/'observation',observation,arguments)
    started = time.time()
    exit_code, stdout, stderr, complete, failure = None, '', '', True, ''
    try:
        exit_code, stdout, stderr = process.run([str(executable), *observer.arguments], context=run_context,
            cwd=root, stdin_text=stdin, timeout=timeout, log_name='capture',
            preserve_output=True, output_limit=1024 ** 2, own_children=True,
            on_started=observer.start,on_tick=observer.tick,stop_requested=observer.should_stop,on_finished=observer.close)
    except CyToolError as error:
        if error.code not in ('Timeout', 'ExecutionOutputLimit'):
            raise
        complete, failure = False, error.code
        with (logs / 'capture.stdout.log').open(encoding='utf-8', newline='') as handle:
            stdout = handle.read()
        with (logs / 'capture.stderr.log').open(encoding='utf-8', newline='') as handle:
            stderr = handle.read()
    finally:
        observer.cleanup()
    context.check()
    after, missing_after = snapshot(root, context)
    runtime=observer.result()
    record = {'captureId': capture_id, 'projectId': project.id, 'startedAt': started,
              'duration': time.time() - started, 'executable': str(executable), 'executableSha256': target_hash,
              'argumentFiles': argument_files, 'arguments': list(arguments), 'stdin': stdin,
              'stdinSha256': hashlib.sha256(stdin.encode()).hexdigest(), 'timeout': timeout,
              'exitCode': exit_code, 'stdout': stdout, 'stderr': stderr,
              'stdoutSha256': hashlib.sha256(stdout.encode()).hexdigest(),
              'stderrSha256': hashlib.sha256(stderr.encode()).hexdigest(),
              'complete': complete and runtime['complete'] and not (exclusions or missing_before or missing_after),
              'failure': failure, 'before': before, 'after': after,
              'changes': changes(before, after), 'workingDirectory': str(root),
              'runtime':runtime,'unknowns': exclusions + missing_before + missing_after + runtime['unknowns'] + [
                  {'code': 'external-files-not-observed'},
                  {'code': 'batch-stdin-not-timed-interaction'}]}
    if not runtime['options']['network'] and runtime['options']['driver']=='none':
        record['unknowns'].append({'code':'network-and-gui-observation-disabled'})
    if digest(executable, context) != target_hash:
        record['complete'] = False
        record['unknowns'].append({'code': 'executable-changed-during-capture'})
    for row in argument_files:
        if not Path(row['path']).is_file() or digest(row['path'], context) != row['sha256']:
            record['complete'] = False
            record['unknowns'].append({'code': 'argument-file-changed-during-capture', 'path': row['path']})
    write_json(directory / 'capture.json', record)
    try:
        report = inv.load(project)
    except CyToolError:
        report = inv.graph(project, 'process-capture')
    run = inv.node(report, 'capture', capture_id, {'captureId': capture_id, 'sha256': target_hash},
                   executable=str(executable), exitCode=exit_code, complete=record['complete'])
    next(r for r in report['nodes'] if r['id'] == run)['status'] = 'observed'
    for stream, text in (('stdout', stdout), ('stderr', stderr)):
        key = inv.node(report, 'output', stream + ': ' + text[:600],
                       {'captureId': capture_id, 'sha256': record[stream + 'Sha256']}, stream=stream)
        next(r for r in report['nodes'] if r['id'] == key)['status'] = 'observed'
        inv.edge(report, run, key, 'produced', status='observed')
    for change in record['changes']:
        key = inv.node(report, 'file-change', change['path'], {'captureId': capture_id}, change=change)
        next(r for r in report['nodes'] if r['id'] == key)['status'] = 'observed'
        inv.edge(report, run, key, 'changed', status='observed')
    publish_runtime(report,run,record)
    for row in record['unknowns']:
        inv.unknown(report, **row, captureId=capture_id)
    inv.save(project, report)
    return record


def get_capture(project, capture_id):
    if not isinstance(capture_id, str) or len(capture_id) != 32 or any(c not in '0123456789abcdef' for c in capture_id):
        raise CyToolError('InvalidParameters', 'Invalid capture identifier.')
    record = read_json(project.dir / 'investigation/captures' / capture_id / 'capture.json')
    if record.get('captureId') != capture_id or record.get('projectId') != project.id:
        raise CyToolError('NotFound', 'The capture does not belong to this project.')
    return record


def list_captures(project):
    records = [read_json(p) for p in (project.dir / 'investigation/captures').glob('*/capture.json')]
    return {'captures': sorted([{k: r.get(k) for k in ('captureId', 'startedAt', 'executable', 'arguments', 'exitCode', 'complete')}
                               for r in records if r.get('projectId') == project.id],
                              key=lambda r: r['startedAt'], reverse=True)}


def compare(project, left, right):
    a, b = get_capture(project, left), get_capture(project, right)
    same_scenario = a['stdinSha256'] == b['stdinSha256'] and a['before'] == b['before'] and a['timeout'] == b['timeout']
    # Version-bearing paths can differ; every other argument must match.
    a_files = {r['index'] for r in a['argumentFiles']}
    b_files = {r['index'] for r in b['argumentFiles']}
    same_arguments = len(a['arguments']) == len(b['arguments']) and all(
        x == y or (i in a_files and i in b_files) for i,(x,y) in enumerate(zip(a['arguments'],b['arguments'])))
    same_scenario = same_scenario and same_arguments
    ar,br=a.get('runtime',{}),b.get('runtime',{})
    same_scenario=same_scenario and ar.get('options',{})==br.get('options',{})
    streams = {}
    for key in ('stdout', 'stderr'):
        aa,bb=a[key],b[key]
        normalized=False
        if key=='stderr' and ar.get('options',{}).get('driver') in ('chromium','electron') and br.get('options',{}).get('driver') in ('chromium','electron'):
            # Strip only the endpoint banner introduced by our debugging flags.
            pattern=r'^DevTools listening on ws://127\.0\.0\.1:\d+/devtools/browser/[a-f0-9-]+\r?$'
            aa=re.sub(pattern,'DevTools listening on [capture endpoint]',aa,flags=re.MULTILINE)
            bb=re.sub(pattern,'DevTools listening on [capture endpoint]',bb,flags=re.MULTILINE)
            normalized=aa!=a[key] or bb!=b[key]
        diff = ''.join(difflib.unified_diff(aa.splitlines(True), bb.splitlines(True),
                                          fromfile=left + '/' + key, tofile=right + '/' + key))
        streams[key] = {'same': aa == bb, 'normalizedDebugBanner':normalized,'leftSha256': a[key + 'Sha256'],
                        'rightSha256': b[key + 'Sha256'], 'diff': diff[:100000], 'truncated': len(diff) > 100000}
    fs_changes = changes(a['after'], b['after'])
    network=compare_network(ar,br)
    graphics=compare_graphics(ar,br)
    termination_same=ar.get('termination','process-exit')==br.get('termination','process-exit')
    equal = all(r['same'] for r in streams.values()) and a['exitCode'] == b['exitCode'] and termination_same and not fs_changes and network['same'] and graphics['same']
    return {'left': left, 'right': right, 'sameScenario': same_scenario,
            'complete': a['complete'] and b['complete'], 'observationsMatch': equal,
            'exitCodes': [a['exitCode'], b['exitCode']], 'streams': streams,'network':network,'graphics':graphics,
            'termination':[ar.get('termination','process-exit'),br.get('termination','process-exit')],
            'fileChanges': fs_changes, 'leftChanges': a['changes'], 'rightChanges': b['changes'],
            'unknowns': a['unknowns'] + b['unknowns'] + [{'code': 'matching-observations-do-not-prove-equivalence'}],
            'commands': [[a['executable'], *a['arguments']], [b['executable'], *b['arguments']]]}


def compare_network(a,b):
    def rows(runtime):
        http=[{k:r.get(k) for k in ('url','method','type','status','mimeType','failed','finished','encodedDataLength','error')}
              for r in runtime.get('gui',{}).get('requests',[])]
        # TCP source ports, PIDs and observation times change between executions.
        tcp=sorted({(r['remoteAddress'],r['remotePort'],r['status']) for r in runtime.get('connections',[])})
        return {'http':http,'tcp':tcp,'console':runtime.get('gui',{}).get('console',[])}
    left,right=rows(a),rows(b)
    diff=''.join(difflib.unified_diff(json.dumps(left,ensure_ascii=False,indent=2).splitlines(True),
                                    json.dumps(right,ensure_ascii=False,indent=2).splitlines(True),fromfile='left/network',tofile='right/network'))
    return {'same':left==right,'left':left,'right':right,'diff':diff[:100000],'truncated':len(diff)>100000}


def compare_graphics(a,b):
    left,right=a.get('gui',{}),b.get('gui',{})
    rows=[]
    states_a,states_b=left.get('states',[]),right.get('states',[])
    for index in range(max(len(states_a),len(states_b))):
        aa=states_a[index] if index<len(states_a) else {}
        bb=states_b[index] if index<len(states_b) else {}
        images_a=aa.get('images',[aa['image']] if aa.get('image') else [])
        images_b=bb.get('images',[bb['image']] if bb.get('image') else [])
        pixel_same=[r.get('sha256') for r in images_a]==[r.get('sha256') for r in images_b]
        diff=''.join(difflib.unified_diff(json.dumps(aa.get('state'),ensure_ascii=False,indent=2).splitlines(True),
                                        json.dumps(bb.get('state'),ensure_ascii=False,indent=2).splitlines(True),fromfile='left/ui',tofile='right/ui'))
        rows.append({'step':aa.get('step',bb.get('step')),'label':aa.get('label',bb.get('label')),
                     'stateSame':aa.get('state')==bb.get('state'),'pixelsSame':pixel_same,
                     'leftImages':images_a,'rightImages':images_b,'diff':diff[:100000],'truncated':len(diff)>100000})
    return {'same':all(r['stateSame'] and r['pixelsSame'] for r in rows) and left.get('steps',[])==right.get('steps',[]),
            'states':rows,'leftSteps':left.get('steps',[]),'rightSteps':right.get('steps',[]),
            'leftError':left.get('error',''),'rightError':right.get('error','')}


def evidence(project,capture_id):
    record=get_capture(project,capture_id)
    runtime=record.get('runtime',{})
    images=[]
    for state in runtime.get('gui',{}).get('states',[]):
        for image in state.get('images',[state['image']] if state.get('image') else []):
            name=image.get('name','')
            if not name or Path(name).name!=name:continue
            path=project.dir/'investigation/captures'/capture_id/'observation'/name
            if not path.is_file() or digest(path,EngineContext())!=image.get('sha256'):
                raise CyToolError('IntegrityFailure','The recorded screenshot has changed.')
            images.append({**image,'step':state['step'],'path':str(path)})
    return {'captureId':capture_id,'runtime':runtime,'images':images,'complete':record['complete']}


def publish_runtime(report,run,record):
    from urllib.parse import urlsplit
    runtime=record['runtime']
    static=[n for n in report['nodes'] if n['kind'] in ('endpoint','route','ui')]
    step_nodes={}
    for step in runtime['gui'].get('steps',[]):
        location={'captureId':record['captureId'],'step':step['index']}
        key=inv.node(report,'gui-step','%s %s [%s]' % (step['index'],step['action'],step['status']),location,**step)
        next(n for n in report['nodes'] if n['id']==key)['status']='observed'
        inv.edge(report,run,key,'replayed',location,status='observed')
        step_nodes[step['index']]=key
    for index,r in enumerate(runtime.get('connections',[])):
        location={'captureId':record['captureId'],'connectionIndex':index,'executableSha256':record['executableSha256']}
        key=inv.node(report,'tcp-connection','%s:%s [%s]' % (r['remoteAddress'],r['remotePort'],r['status']),location,**r)
        next(n for n in report['nodes'] if n['id']==key)['status']='observed'
        inv.edge(report,run,key,'connected',location,status='observed')
    for r in runtime['gui'].get('requests',[]):
        location={'captureId':record['captureId'],'requestIndex':r['index'],'executableSha256':record['executableSha256']}
        key=inv.node(report,'network',r['method']+' '+r['url'],location,**r)
        next(n for n in report['nodes'] if n['id']==key)['status']='observed'
        inv.edge(report,run,key,'requested',location,status='observed')
        if r.get('step') in step_nodes:
            inv.edge(report,step_nodes[r['step']],key,'request-during-step',location,status='observed')
        for candidate in static:
            value=candidate['details'].get('value',candidate['label'])
            try:matched=value in (r['url'],urlsplit(r['url']).path)
            except ValueError:matched=False
            if candidate['kind'] in ('endpoint','route') and matched:
                inv.edge(report,candidate['id'],key,'network-candidate',location,status='inferred')
    for state in runtime['gui'].get('states',[]):
        key=inv.node(report,'gui-state',state['label'],{'captureId':record['captureId'],'step':state['step'],
            'stateSha256':state['stateSha256']},driver=runtime['gui']['driver'])
        next(n for n in report['nodes'] if n['id']==key)['status']='observed'
        inv.edge(report,run,key,'displayed',status='observed')
        if state['step'] in step_nodes:
            inv.edge(report,step_nodes[state['step']],key,'state-after-step',status='observed')
        controls=state.get('state',{}).get('elements',[])
        identifiers={str(c.get(k,'')) for c in controls for k in ('id','automationId','name','text')}
        for candidate in static:
            if candidate['kind']=='ui' and candidate['label'] and candidate['label'] in identifiers:
                inv.edge(report,candidate['id'],key,'ui-observation-candidate',status='inferred')
