"""Build the human CyDoc manual. Reading the export needs no build tool or network."""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import unquote

DOCS = Path(__file__).resolve().parent
APP = DOCS.parent
ROOT = APP.parent
GENERATED = DOCS / '.work'
DESTINATION = APP / 'Documentation'
TOOLS = DOCS
FACTS = ('app/CyTool.json', 'app/documentation.py', 'app/documentation_ui.py',
         'app/desktop.py', 'app/cyui_shell.py', 'app/project_ui.py', 'app/xbox_ui.py',
         'app/porting_ui.py', 'app/ui_common.py', 'app/operations.py',
         'app/scripts/build_documentation.py', 'app/scripts/make_release.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(path):
    data = path.read_bytes()
    if path.suffix.lower() in {'.md', '.py', '.json', '.mjs', '.html', '.css', '.txt', '.svg', '.tsv'} or path.name == '.gitignore':
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def reset_child(path, parent):
    path, parent = Path(path).absolute(), Path(parent).resolve()
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError('Refusing linked build directory')
    resolved = path.resolve()
    if resolved == parent or not resolved.is_relative_to(parent):
        raise ValueError('Build path escaped its root')
    if path.exists():
        for child in path.rglob('*'):
            if child.is_symlink() or not child.resolve().is_relative_to(resolved):
                raise ValueError('Refusing linked build child')
        shutil.rmtree(path)
    path.mkdir(parents=True)


def setup_tools(setup=False):
    dependency = json.loads((DOCS / 'vendor/cydoc-source.json').read_text('utf-8'))
    archive = (DOCS / dependency['package']).resolve()
    if not archive.is_relative_to(DOCS / 'vendor') or digest(archive) != dependency['sha256']:
        raise ValueError('Pinned CyDoc archive hash mismatch')
    node = shutil.which('node')
    if not node or int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0]) < 22:
        raise SystemExit('Node.js 22+ is required to regenerate documentation, not to read it.')
    lock = digest(DOCS / 'package-lock.json')
    stamp = DOCS / 'installed-lock.sha256'
    ready = stamp.is_file() and stamp.read_text().strip() == lock and (DOCS / 'node_modules/cydoc/tools/cli.mjs').is_file()
    if not ready:
        if not setup:
            raise SystemExit('Run app/scripts/build_documentation.py --setup once.')
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        subprocess.run([npm, 'ci', '--omit=dev', '--no-audit', '--no-fund'], cwd=DOCS,
            env={**os.environ, 'npm_config_cache': str(GENERATED / 'npm-cache')}, check=True)
        stamp.write_text(lock + '\n', encoding='ascii')
    if (DOCS / 'node_modules/three').exists():
        raise ValueError('Three.js is not selected for this manual')
    return node, dependency


def page(content, locale, identifier, title, description, section, body, revision='2', parent=None, order=100, kind=None, symbol=None):
    meta = dict(id=identifier, title=title, description=description, section=section, order=order)
    if parent:
        meta['parent'] = parent
    meta['revision' if locale == 'en' else 'sourceRevision'] = revision
    if kind:
        meta['kind'] = kind
    if symbol:
        meta['symbol'] = symbol
    text = '---\n' + '\n'.join(f'{key}: {value}' for key, value in meta.items()) + '\n---\n\n' + body.strip() + '\n'
    target = content / locale / (identifier + '.md')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8', newline='\n')


def operation_group(identifier):
    if identifier.startswith(('xbox_', 'porting_', 'unreal_')):
        return 'consoles'
    if identifier.startswith(('workspace_', 'reconstruction_')):
        return 'projects'
    if identifier.startswith(('patch_', 'managed_', 'debug_')):
        return 'patching'
    if identifier.startswith(('application_', 'investigation_', 'behavior_')):
        return 'investigation'
    if identifier.startswith('ai_'):
        return 'ai'
    if identifier.startswith('update_') or identifier in {'list_engines','list_components','install_component','remove_component','set_component_path','symbols_configure'}:
        return 'settings'
    return 'analysis'


API_GROUPS = {
    'analysis': ('Inspect and export code', 'Examiner et exporter le code', 'workspace'),
    'projects': ('Edit and reconstruct projects', 'Modifier et reconstruire les projets', 'projects'),
    'patching': ('Replace functions and debug', 'Remplacer les fonctions et déboguer', 'patching'),
    'investigation': ('Investigate and compare behavior', 'Examiner et comparer les comportements', 'investigation'),
    'ai': ('AI assistance', 'Assistance IA', 'ai'),
    'consoles': ('Console workflows', 'Parcours consoles', 'consoles'),
    'settings': ('Engines, settings and updates', 'Moteurs, réglages et mises à jour', 'settings'),
}


def generate_api(content, manifest):
    translations = dict(line.split('\t', 1) for line in (DOCS / 'api-fr.tsv').read_text('utf-8').splitlines() if line)
    examples = json.loads((DOCS / 'api-examples.json').read_text('utf-8'))
    def localize(value, locale):
        if isinstance(value, dict):
            return {key: translations[item] if key == 'description' and locale == 'fr' else localize(item, locale) for key, item in value.items()}
        if isinstance(value, list):
            return [localize(item, locale) for item in value]
        return value
    def table(schema, locale):
        t = lambda en, fr: fr if locale == 'fr' else en
        rows = [t('| Name | Type | Required | Description |', '| Nom | Type | Obligatoire | Description |'), '|---|---|---|---|']
        def visit(value, prefix=''):
            for name, field in value.get('properties', {}).items():
                identifier = prefix + name
                description = field.get('description', '')
                if locale == 'fr' and description:
                    description = translations[description]
                description = description.replace('|', '\\|').replace('\n', ' ')
                required = name in value.get('required', [])
                kind = field.get('type', 'any')
                rows.append(f'| `{identifier}` | `{kind}` | {t("Yes", "Oui") if required else t("No", "Non")} | {description} |')
                visit(field, identifier + '.')
        visit(schema)
        return '\n'.join(rows) if len(rows) > 2 else t('No named fields are declared. See the schema below.', 'Aucun champ nommé n’est déclaré. Consulter le schéma ci-dessous.')
    operations = manifest['operations']
    for operation in operations:
        # Validate every nested description, including optional array items.
        localize(operation, 'fr')
        revision = hashlib.sha256(json.dumps(operation, sort_keys=True).encode()).hexdigest()[:12]
        identifier = 'op-' + operation['id'].replace('_', '-')
        group = operation_group(operation['id'])
        for locale in ('en', 'fr'):
            t = lambda en, fr: fr if locale == 'fr' else en
            description = operation['description'] if locale == 'en' else translations[operation['description']]
            inputs = operation.get('inputSchema', {})
            outputs = operation.get('outputSchema', {})
            signature = ', '.join(inputs.get('properties', {}))
            body = description + '\n\n## Signature {#signature}\n\n```text\nop_' + operation['id'] + '(parameters: {' + signature + '}) -> jobId\n```\n\n'
            body += t('Submit a Runtime job, wait for its terminal state and inspect its outputs or error. ', 'Soumettre une tâche Runtime, attendre son état final puis examiner ses sorties ou son erreur. ')
            body += t('[MCP and CLI usage](doc:automation#discover-submit-wait-inspect).\n\n', '[Utilisation MCP et CLI](doc:automation#discover-submit-wait-inspect).\n\n')
            body += '## ' + t('Parameters', 'Paramètres') + ' {#parameters}\n\n' + table(inputs, locale) + '\n\n'
            body += '## ' + t('Returns', 'Retours') + ' {#returns}\n\n' + table(outputs, locale) + '\n\n'
            if operation['id'] in examples:
                body += '## ' + t('Example parameters', 'Exemple de paramètres') + ' {#example}\n\n'
                body += t('Replace sample paths and IDs with values from your installation and previous job outputs. Save this object in a parameters file or use it inside the MCP `parameters` envelope.\n\n',
                    'Remplacer les chemins et identifiants d’exemple par ceux de votre installation et des sorties précédentes. Enregistrer cet objet dans un fichier de paramètres ou le placer dans l’enveloppe MCP `parameters`.\n\n')
                body += '```json\n' + json.dumps(examples[operation['id']], ensure_ascii=False, indent=2) + '\n```\n\n'
            body += '## ' + t('Permissions and jobs', 'Autorisations et tâches') + ' {#permissions}\n\n'
            body += ', '.join('`' + p + '`' for p in operation.get('permissions', [])) or t('No additional permission declared.', 'Aucune autorisation supplémentaire déclarée.')
            body += '\n\n' + t('Cancellation: ', 'Annulation : ') + (t('supported', 'prise en charge') if operation.get('canCancel') else t('not declared', 'non déclarée')) + '. '
            body += t('Progress notifications: ', 'Notifications de progression : ') + (t('supported', 'prises en charge') if operation.get('supportsProgress') else t('not declared', 'non déclarées')) + '.\n\n'
            body += '## ' + t('Contract and constraints', 'Contrat et contraintes') + ' {#contract}\n\n'
            contract = {key: localize(operation[key], locale) for key in ('id','inputSchema','outputSchema','resourceRequirements','permissions','exclusiveGroups','canRunAsync','canCancel','supportsProgress') if key in operation}
            body += t('The schema specifies defaults, accepted values, bounds and additional-field rules.\n\n', 'Le schéma précise les valeurs par défaut, les choix acceptés, les bornes et les règles concernant les champs supplémentaires.\n\n')
            body += '```details\n' + json.dumps({'title': t('Show the complete schema', 'Afficher le schéma complet'), 'body': '```json\n' + json.dumps(contract, ensure_ascii=False, indent=2) + '\n```'}, ensure_ascii=False) + '\n```\n\n'
            body += '## ' + t('Related workflow', 'Parcours associé') + ' {#related}\n\n'
            body += f'[{API_GROUPS[group][0 if locale == "en" else 1]}](doc:{API_GROUPS[group][2]}) · [API](doc:operation-api)\n'
            page(content, locale, identifier, operation['id'], description, t('Reference / Operations', 'Références / Opérations'), body, revision,
                 parent='api-' + group, kind='api', symbol=operation['id'])
    for locale in ('en', 'fr'):
        t = lambda en, fr: fr if locale == 'fr' else en
        overview = t('Use these public contracts to automate the same tasks as the interface. Parameters and results describe the installed version; optional engines must be installed separately.\n\n',
            'Utiliser ces contrats publics pour automatiser les mêmes tâches que l’interface. Les paramètres et résultats correspondent à la version installée ; les moteurs facultatifs doivent être installés séparément.\n\n')
        overview += f'{len(operations)} ' + t('operations, organized by task:\n\n', 'opérations, organisées par objectif :\n\n')
        for group, (en, fr, guide) in API_GROUPS.items():
            label = t(en, fr)
            overview += f'- [{label}](doc:api-{group})\n'
            body = t('Start with the ', 'Commencer par le ') + f'[{t("user guide", "guide utilisateur")}](doc:{guide}).\n\n'
            for operation in operations:
                if operation_group(operation['id']) == group:
                    desc = operation['description'] if locale == 'en' else translations[operation['description']]
                    body += '- [`' + operation['id'] + '`](doc:op-' + operation['id'].replace('_','-') + ') — ' + desc + '\n'
            page(content, locale, 'api-' + group, label, t('Public operations for this workflow.', 'Opérations publiques pour ce parcours.'),
                 t('Reference / Operations', 'Références / Opérations'), body, parent='operation-api', kind='api')
        overview += f'\n[{t("Native help-link API", "API des liens d’aide natifs")}](doc:help-api).\n'
        page(content, locale, 'operation-api', t('Operation API', 'API des opérations'), t('Parameters, results and constraints for public Runtime operations.', 'Paramètres, résultats et contraintes des opérations publiques du Runtime.'),
             t('Reference / Operations', 'Références / Opérations'), overview, order=90, kind='api')


def make_routes(site):
    manifest = json.loads((site / 'DocData/manifest.json').read_text('utf-8'))
    compatibility = json.loads((DOCS / 'compatibility.json').read_text('utf-8'))
    catalog = json.loads((DOCS / 'catalog.json').read_text('utf-8'))
    routes = dict(schemaVersion=1, defaultLocale='en', locales=['en','fr'], modules=['image'],
        aliases=manifest.get('aliases', {}), legacyAnchors=compatibility['anchors'], contexts=compatibility['contexts'],
        chapters=[{'id': topic['id'], 'title': topic['title']} for topic in catalog['topics']], pages={})
    for item in manifest['pages']:
        if item.get('kind') == 'source' or item.get('sourcePageId'):
            raise ValueError('Implementation browsing is not distributed')
        if not item.get('description') or not item.get('parent') and item['id'].startswith('op-'):
            raise ValueError('Missing useful description or API hierarchy')
        p = routes['pages'].setdefault(item['id'], {'locales': [], 'title': {}, 'anchors': {}, 'media': {}})
        locale = item['locale']
        p['locales'].append(locale); p['title'][locale] = item['title']
        p['anchors'][locale] = [h['id'] for h in item['headings']] + item.get('anchors', [])
        media = {}
        for match in re.finditer(r'data-cydoc-id="([^"]+)"[^>]*data-config="([^"]+)"', item['html']):
            config = json.loads(html.unescape(match[2])); media[match[1]] = [a['id'] for a in config.get('annotations', [])]
        p['media'][locale] = media
        for asset in item.get('assets', []):
            if not asset.startswith('assets/') or not (site / 'DocData' / unquote(asset)).is_file():
                raise ValueError('Missing or nonlocal media: ' + asset)
    for identifier, item in routes['pages'].items():
        if set(item['locales']) != {'en','fr'}:
            raise ValueError('Incomplete bilingual page: ' + identifier)
        headings = lambda loc: [a for a in item['anchors'][loc] if not re.fullmatch(r'(?:code-\d+-)?L\d+', a)]
        if headings('en') != headings('fr') or item['media']['en'] != item['media']['fr']:
            raise ValueError('Translated anchors/media differ: ' + identifier)
    report = json.loads((site / 'DocData/translation-report.json').read_text('utf-8'))
    if report['missing'] or report['outdated'] or report['untracked']:
        raise ValueError('Finish and review every translation before distribution')
    if {p.name for p in (site / 'DocData').glob('media-*.js')} != {'media-image.js'}:
        raise ValueError('Unexpected media modules')
    write_json(site / 'DocData/routes.json', routes)
    return manifest, routes


def input_hashes():
    files = [ROOT / name for name in FACTS]
    files += [p for p in DOCS.rglob('*') if p.is_file() and not any(part in {'node_modules','.work','internal','__pycache__'} for part in p.relative_to(DOCS).parts)
              and p.name not in {'build-info.json', 'installed-lock.sha256'}]
    return {p.relative_to(ROOT).as_posix(): source_digest(p) for p in sorted(set(files))}


def check_current():
    info = json.loads((DOCS / 'build-info.json').read_text('utf-8'))
    if info['inputs'] != input_hashes():
        raise ValueError('Documentation is stale; regenerate it')
    actual = {p.relative_to(DESTINATION).as_posix() for p in DESTINATION.rglob('*') if p.is_file()}
    if actual != set(info['outputs']):
        raise ValueError('Unexpected or missing exported files')
    for name, expected in info['outputs'].items():
        if digest(DESTINATION / name) != expected:
            raise ValueError('Changed export resource: ' + name)
    print('CyDoc: current bilingual export; every resource hash verified.')


def build(setup=False):
    node, dependency = setup_tools(setup)
    # Clean this build's exact output children only; retain npm's cache and dependencies.
    content, site = GENERATED / 'content', GENERATED / 'site'
    for path in (content, site):
        reset_child(path, GENERATED)
    shutil.copytree(DOCS / 'manual', content, dirs_exist_ok=True)
    manifest = json.loads((APP / 'CyTool.json').read_text('utf-8'))
    generate_api(content, manifest)
    subprocess.run([node, str(DOCS / 'extract-api.mjs'), str(content)], cwd=DOCS, check=True)
    config = json.loads((DOCS / 'cydoc.config.json').read_text('utf-8'))
    config.update(version=manifest['version'], content='.work/content', out='.work/site')
    config['aliases'] = json.loads((DOCS / 'aliases.json').read_text('utf-8'))
    config_path = DOCS / '.build-config.json'
    try:
        write_json(config_path, config)
        subprocess.run([node, str(DOCS / 'node_modules/cydoc/tools/cli.mjs'), 'check', str(config_path)], cwd=DOCS, check=True)
    finally:
        config_path.unlink(missing_ok=True)
    data, routes = make_routes(site)
    # The host template and compatibility adapter are authored inputs. CyDoc's
    # stock export, core, viewer and image module are used without source patches.
    shutil.copy2(DOCS / 'Documentation.html', site / 'Documentation.html')
    subprocess.run([node, str(DOCS / 'bundle-compat.mjs'), str(site)], cwd=DOCS, check=True)
    for source, name in ((DOCS / 'vendor/CyDoc-LICENSE.txt', 'CyDoc-LICENSE.txt'), (ROOT / 'LICENSE', 'CyDecompilator-LICENSE.txt')):
        shutil.copy2(source, site / 'DocData' / name)
    # Sidecar only: neither the human manifest nor its search indexes include it.
    ai = site / 'DocAI.md'
    with ai.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write('\n\n' + (DOCS / 'DocAI-extra.md').read_text('utf-8'))
        stream.write('\n\n## Installed operation contracts\n\n```json\n' + json.dumps(manifest['operations'], indent=2) + '\n```\n')
    redirect = (DOCS / 'redirect.html').read_text('utf-8')
    (site / 'index.html').write_text(redirect.replace('{{ENTRY}}', 'Documentation.html'), encoding='utf-8', newline='\n')
    staging = GENERATED / 'install'
    reset_child(staging, GENERATED)
    shutil.copytree(site, staging, dirs_exist_ok=True)
    if DESTINATION.exists():
        reset_child(DESTINATION, APP)
        DESTINATION.rmdir()
    staging.rename(DESTINATION)
    write_json(DOCS / 'build-info.json', {'schemaVersion': 2, 'cydoc': dependency, 'inputs': input_hashes(),
        'outputs': {p.relative_to(DESTINATION).as_posix(): digest(p) for p in sorted(DESTINATION.rglob('*')) if p.is_file()}})
    # Compatibility for previous native file bookmarks; no old reader/data is shipped.
    legacy = APP / 'help'
    legacy.mkdir(exist_ok=True)
    (legacy / 'index.html').write_text(redirect.replace('{{ENTRY}}', '../Documentation/Documentation.html'), encoding='utf-8', newline='\n')
    size = sum(p.stat().st_size for p in DESTINATION.rglob('*') if p.is_file())
    print(f'CyDoc: {len(data["pages"])} fully translated pages; image only; {size:,} bytes.')
    check_current()
    return DESTINATION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--check', action='store_true', help='Read-only freshness and output-hash check')
    options = parser.parse_args()
    check_current() if options.check else build(options.setup)


if __name__ == '__main__':
    main()
