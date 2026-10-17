"""Evidence-bearing graphs shared by native, Electron, web and runtime investigations.

Edges describe static relationships unless explicitly marked observed at runtime.
Every dossier is bound to immutable project bytes; queries never claim execution.
"""
import hashlib
import json
import re
from collections import deque
from pathlib import Path

from cytools_core import CyToolError
from .paths import read_json, write_json


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


def graph(project, engine):
    return {'schemaVersion': 1, 'projectId': project.id, 'targetSha256': project.meta()['sha256'],
            'engine': engine, 'nodes': [], 'edges': [], 'unknowns': [], 'truncated': False}


def node(report, kind, label, location, **details):
    key = identity(kind, label, location)
    index = report.get('_nodeIds')
    if index is None:
        index = report['_nodeIds'] = {r['id'] for r in report['nodes']}
    if key in index:
        return key
    index.add(key)
    report['nodes'].append({'id': key, 'kind': kind, 'label': str(label),
                            'location': location, 'status': 'static', 'details': details,
                            'evidence': {'targetSha256': report['targetSha256'], **location}})
    return key


def edge(report, source, target, kind, evidence=None, status='static'):
    if len(report['edges']) >= 100000:
        report['truncated'] = True
        unknown(report, 'graph-edge-limit')
        return
    row = {'source': source, 'target': target, 'kind': kind, 'status': status,
           'evidence': evidence or {'targetSha256': report['targetSha256']}}
    signature = (source, target, kind, status, json.dumps(row['evidence'], sort_keys=True))
    index = report.setdefault('_edgeIds', set())
    if signature not in index:
        index.add(signature)
        report['edges'].append(row)


def unknown(report, code, **details):
    row = {'code': code, **details}
    if len(report['unknowns']) >= 1000:
        report['truncated'] = True
        return
    if row not in report['unknowns']:
        report['unknowns'].append(row)


def save(project, report, name='graph'):
    if name == 'graph':
        previous = read_json(project.dir / 'investigation/graph.json')
        if previous.get('targetSha256') == report['targetSha256']:
            ids = {r['id'] for r in report['nodes']}
            for row in previous.get('nodes', []):
                if row['status'] == 'observed' and row['id'] not in ids:
                    report['nodes'].append(row)
                    ids.add(row['id'])
            observed = {r['id'] for r in report['nodes'] if r['status']=='observed'}
            for row in previous.get('edges', []):
                if row['source'] in ids and row['target'] in ids and (row['source'] in observed or row['target'] in observed) and row not in report['edges']:
                    report['edges'].append(row)
            for row in previous.get('unknowns', []):
                if row.get('captureId') or row.get('code') in ('har-does-not-prove-handler-execution','external-files-network-and-gui-not-observed','batch-stdin-not-timed-interaction'):
                    unknown(report,**row)
    report.pop('_nodeIds', None)
    report.pop('_edgeIds', None)
    write_json(project.dir / 'investigation' / (name + '.json'), report)
    return report


def load(project):
    report = read_json(project.dir / 'investigation/graph.json')
    if report.get('targetSha256') != project.meta()['sha256']:
        raise CyToolError('NotAnalyzed', 'Run an investigation before querying evidence.')
    return report


def query(project, text='', depth=2, limit=200):
    report = load(project)
    depth, limit = min(4, max(0, int(depth))), min(1000, max(1, int(limit)))
    rows = {row['id']: row for row in report['nodes']}
    text = str(text).casefold().strip()
    hits = [key for key, row in rows.items() if not text or text in
            (row['label'] + ' ' + json.dumps(row['details'], ensure_ascii=False)).casefold()]
    adjacency = {}
    for relation in report['edges']:
        adjacency.setdefault(relation['source'], []).append((relation['target'], relation))
        adjacency.setdefault(relation['target'], []).append((relation['source'], relation))
    selected, paths, queue = {}, {}, deque()
    for key in hits[:limit]:
        selected[key], paths[key] = rows[key], []
        queue.append((key, 0))
    truncated = len(hits) > limit
    while queue:
        key, level = queue.popleft()
        if level >= depth:
            continue
        for other, relation in adjacency.get(key, []):
            if other in selected or other not in rows:
                continue
            if len(selected) >= limit:
                truncated = True
                continue
            selected[other], paths[other] = rows[other], paths[key] + [relation]
            queue.append((other, level + 1))
    return {**{k: report[k] for k in ('projectId', 'targetSha256', 'engine', 'unknowns')},
            'query': text, 'matches': len(hits), 'nodes': list(selected.values()),
            'edges': [e for e in report['edges'] if e['source'] in selected and e['target'] in selected],
            'paths': paths, 'truncated': truncated or report['truncated']}


def source(project, path):
    """Read only a hashed snapshot file, never arbitrary paths from target metadata."""
    from .javascript import artifact_root, safe_relative
    manifest = read_json(project.binary)
    relative = safe_relative(path)
    entry = next((r for r in manifest.get('files', []) if r['path'] == relative), None)
    if not entry:
        raise CyToolError('NotFound', 'The source is not part of this application snapshot.')
    target = artifact_root(project) / relative
    data = target.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise CyToolError('IntegrityFailure', 'The application snapshot has changed; open it again.')
    if len(data) > 4 * 1024 ** 2:
        raise CyToolError('InvalidParameters', 'The source is too large to display.')
    return {'path': relative, 'sha256': entry['sha256'], 'text': data.decode('utf-8-sig', 'replace')}


def import_har(project, path, context):
    """Correlate an explicitly imported network recording; do not fetch target URLs."""
    from urllib.parse import urlsplit
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 32 * 1024 ** 2:
        raise CyToolError('InvalidParameters', 'Select a HAR recording smaller than 32 MB.')
    data = path.read_bytes()
    try:
        entries = json.loads(data)['log']['entries']
        if not isinstance(entries, list):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise CyToolError('InvalidParameters', 'Invalid HAR recording.')
    report = load(project)
    recording = hashlib.sha256(data).hexdigest()
    # Replace the same recording instead of accumulating duplicate observations.
    static = {}
    for row in report['nodes']:
        if row['kind'] in ('endpoint','route'):
            value=row['details'].get('value',row['label'])
            if isinstance(value,str):
                static.setdefault(value,[]).append(row)
    for index, entry in enumerate(entries[:5000]):
        context.check()
        request, response = entry.get('request', {}), entry.get('response', {})
        url = str(request.get('url', ''))[:4096]
        key = node(report, 'network', str(request.get('method', 'GET')) + ' ' + url,
                   {'recordingSha256': recording, 'entry': index}, url=url,
                   responseStatus=response.get('status'), time=entry.get('time'),
                   startedDateTime=entry.get('startedDateTime'))
        next(r for r in report['nodes'] if r['id'] == key)['status'] = 'observed'
        for candidate in static.get(url,[]) + static.get(urlsplit(url).path,[]):
            literal = candidate['details'].get('value', candidate['label'])
            if literal:
                edge(report, candidate['id'], key, 'network-candidate',
                     {'recordingSha256': recording, 'entry': index,
                      'source': candidate['evidence']}, status='inferred')
    unknown(report, 'har-does-not-prove-handler-execution')
    if len(entries) > 5000:
        report['truncated'] = True
        unknown(report, 'har-entry-limit', total=len(entries), retained=5000)
    # Store only metadata; request cookies, headers and bodies are not copied.
    save(project, report)
    return query(project, '', 0, 1000)
