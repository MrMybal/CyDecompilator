"""Portable reconstruction knowledge; no game assets, builds or module execution."""
import hashlib
import json
from pathlib import Path
from cytools_core import CyToolError

APP = Path(__file__).resolve().parents[1]
CATALOG = APP / 'unreal_support/reconstruction-rules.json'
MODULE = APP.parent / 'modules/unreal-reconstruction'


def rules(profile='halo-cea-x360', category='', language='en'):
    if language not in ('en', 'fr'):
        raise CyToolError('InvalidParameters', 'Unsupported reconstruction guide language.')
    raw = CATALOG.read_bytes()
    catalog = json.loads(raw)
    if profile not in catalog['profiles'] or (category and category not in catalog['categories']):
        raise CyToolError('InvalidParameters', 'Unknown Unreal reconstruction profile or category.')
    selected = catalog['profiles'][profile]
    rows = []
    for row in catalog['rules']:
        if profile not in row['profiles'] or (category and row['category'] != category):
            continue
        rows.append({key: (value[language] if key in ('title', 'requirement', 'validation') else value)
                     for key, value in row.items()})
    return {
        'schemaVersion': catalog['schemaVersion'], 'catalogVersion': catalog['version'],
        'catalogSha256': hashlib.sha256(raw).hexdigest(), 'language': language,
        'scope': 'rules-only', 'enforcement': catalog['enforcement'],
        'automaticConversion': False, 'fullGameEquivalence': False,
        'profile': {**selected, 'name': selected['name'][language],
                    'description': selected['description'][language]},
        'categories': [{'id': key, 'name': value[language]}
                       for key, value in catalog['categories'].items()],
        'category': category, 'rules': rows,
        'limits': [value[language] for value in selected['limits']],
        'implementation': {'available': (MODULE / 'unreal_reconstruction/core.py').is_file(),
                           'path': str(MODULE), 'executionIntegrated': False},
        'evidencePolicy': catalog['evidencePolicy'][language],
    }


def guide(profile='halo-cea-x360', category='', language='en'):
    result = rules(profile, category, language)
    fr = language == 'fr'
    lines = ['# ' + result['profile']['name'], '', result['profile']['description'], '',
             result['evidencePolicy'], '', '## ' + ('Limites' if fr else 'Limits'), '']
    lines.extend('- ' + text for text in result['limits'])
    for section in result['categories']:
        rows = [row for row in result['rules'] if row['category'] == section['id']]
        if not rows:
            continue
        lines += ['', '## ' + section['name'], '']
        for row in rows:
            lines += ['### ' + row['title'] + ' (`' + row['id'] + '`)', '', row['requirement'], '',
                      ('Contrôle : ' if fr else 'Check: ') + row['validation'], '',
                      ('Références : ' if fr else 'References: ') + ', '.join(
                          '`' + ref['path'] + '` (SHA-256 `' + ref['sha256'] + '`)'
                          for ref in row['evidence'])]
    result['documentation'] = '\n'.join(lines) + '\n'
    return result
