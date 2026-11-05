"""Build and validate the offline CyDoc help shipped with CyDecompilator.

First build: python app/scripts/build_documentation.py --setup
Subsequent builds: python app/scripts/build_documentation.py
No sibling checkout, npm, Node or network is needed to READ app/help/index.html.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/cydoc'
TOOLS = ROOT / 'runtime/documentation-tools'
GENERATED = DOCS / '.generated'
DESTINATION = ROOT / 'app/help'
SOURCE_FILES = ('app/documentation.py', 'app/operations.py', 'app/cydec/engines/base.py')
APP_REFERENCES = {'AIIntegration', 'CapabilityCoverage', 'CyUIMigration', 'Investigation',
                  'PS5Porting', 'Reconstruction', 'XboxPorting', 'XboxPorting.fr',
                  'UnrealReconstruction', 'UnrealReconstruction.fr'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(path):
    """Canonical LF text hashes survive Git's Windows checkout conversion."""
    data = path.read_bytes()
    if path.name == '.gitignore' or path.suffix.lower() in {'.md', '.py', '.json', '.mjs', '.html', '.css', '.txt', '.svg'}:
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def reset_child(path, parent):
    """Delete only an exact, non-symlink build child within an explicitly checked root."""
    path, parent = Path(path).absolute(), Path(parent).resolve()
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError('Refusing linked build directory: ' + str(path))
    resolved = path.resolve()
    if resolved == parent or not resolved.is_relative_to(parent):
        raise ValueError('Build path escaped its root: ' + str(path))
    if path.exists():
        for child in path.rglob('*'):
            if child.is_symlink() or not child.resolve().is_relative_to(resolved):
                raise ValueError('Refusing a linked build child: ' + str(child))
        shutil.rmtree(path)
    path.mkdir(parents=True)


def setup_tools(setup=False):
    source = json.loads((ROOT / 'app/vendor/cydoc-source.json').read_text(encoding='utf-8'))
    archive = DOCS / 'vendor/cydoc-0.1.0.tgz'
    if digest(archive) != source['sha256']:
        raise ValueError('Pinned CyDoc archive hash mismatch')
    node = shutil.which('node')
    if not node or int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0]) < 22:
        raise SystemExit('Node.js 22+ is required to regenerate documentation (not to read it).')
    stamp = TOOLS / 'installed-lock.sha256'
    lock_hash = digest(DOCS / 'package-lock.json')
    ready = stamp.is_file() and stamp.read_text().strip() == lock_hash
    ready = ready and (TOOLS / 'node_modules/cydoc/tools/cli.mjs').is_file()
    if not ready:
        if not setup:
            raise SystemExit('Documentation build dependencies are missing. Run with --setup once.')
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            raise SystemExit('npm is required for --setup.')
        (TOOLS / 'vendor').mkdir(parents=True, exist_ok=True)
        for name in ('package.json', 'package-lock.json'):
            shutil.copy2(DOCS / name, TOOLS / name)
        shutil.copy2(archive, TOOLS / 'vendor' / archive.name)
        env = {**os.environ, 'npm_config_cache': str(ROOT / 'runtime/cache/npm')}
        subprocess.run([npm, 'ci', '--omit=dev', '--no-audit', '--no-fund'], cwd=TOOLS, env=env, check=True)
        stamp.write_text(lock_hash + '\n', encoding='ascii')
    if (TOOLS / 'node_modules/three').exists():
        raise ValueError('Unselected Three.js dependency in documentation tools')
    return node, source


def page(folder, locale, identifier, title, section, body, revision='1', translated=True, order=100, kind=None):
    metadata = [f'id: {identifier}', f'title: {title.replace(chr(10), " ")}',
                f'section: {section}', f'order: {order}', f'revision: {revision}']
    if locale == 'fr' and translated:
        metadata.append(f'sourceRevision: {revision}')
    if kind:
        metadata.append('kind: ' + kind)
    target = folder / locale / (identifier + '.md')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('---\n' + '\n'.join(metadata) + '\n---\n\n' + body.strip() + '\n', encoding='utf-8')


def references():
    return sorted((ROOT / 'app/Docs').glob('*.md')) + [DOCS / 'README.md', ROOT / 'README.md', ROOT / 'LISEZ-MOI.md',
            ROOT / 'CHANGELOG.md', ROOT / 'app/CyToolsGuide.md', ROOT / 'app/README.md',
            ROOT / 'app/skills/cydecompilator/SKILL.md'] + sorted(
            (ROOT / 'app/skills/cydecompilator/references').glob('*.md')) + sorted(
            (ROOT / 'modules').glob('*/README.md')) + sorted((ROOT / 'modules').glob('*/docs/*.md'))


def reference_id(path):
    return 'ref-' + re.sub(r'[^a-z0-9]+', '-', path.relative_to(ROOT).as_posix().lower()).strip('-').removesuffix('-md')


def rewrite_reference(text, source, mapping, asset_root):
    """Rewrite presentation links, never code examples. Keep originals in their source files."""
    parts = re.split(r'(^`{3,}[^\n]*\n[\s\S]*?^`{3,}\s*$|^~{3,}[^\n]*\n[\s\S]*?^~{3,}\s*$)', text, flags=re.M)
    changes = []

    def target(value, image=False):
        original = value
        value = html.unescape(value.strip().strip('<>'))
        parsed = urlsplit(value)
        if parsed.scheme or value.startswith('//'):
            if image:
                changes.append({'url': original, 'reason': 'Remote badge/image replaced by its text label'})
                return None
            return value
        if value.startswith('#'):
            return value
        location = (source.parent / unquote(parsed.path)).resolve()
        if location in mapping:
            return 'doc:' + mapping[location] + ('#' + parsed.fragment if parsed.fragment else '')
        private_parts = {'work', 'runtime', 'data', 'build', 'tools', 'dist', '.git'}
        if image and location.is_relative_to(ROOT) and private_parts.intersection(location.relative_to(ROOT).parts):
            changes.append({'url': original, 'reason': 'Local working/build media retained outside the distributable documentation'})
            return None
        if image and location.is_file() and location.is_relative_to(ROOT) and location.suffix.lower() in {'.png', '.jpg', '.jpeg', '.svg', '.webp'}:
            name = 'ref-' + digest(location)[:12] + location.suffix.lower()
            shutil.copy2(location, asset_root / name)
            return 'assets/' + name
        reason = ('Source/build file retained as a path; not an offline documentation page' if location.exists() else
                  'Reference target is absent from this repository; retained as a path, not fabricated')
        changes.append({'url': original, 'reason': reason})
        return None

    for i in range(0, len(parts), 2):
        block = parts[i]
        def link(match):
            bang, label, url = match.groups()
            result = target(url, bool(bang))
            return f'{bang}[{label}]({result})' if result else label + (f' (`{url}`)' if not bang else '')
        block = re.sub(r'(!?)\[([^\[\]\n]*)\]\(([^)\n]+)\)', link, block)
        def img(match):
            tag = match.group(0)
            src = re.search(r'\bsrc=[\"\x27]([^\"\x27]+)', tag)
            alt = re.search(r'\balt=[\"\x27]([^\"\x27]+)', tag)
            label = alt.group(1) if alt else 'Image'
            result = target(src.group(1), True) if src else None
            return f'![{label}]({result})' if result else label
        block = re.sub(r'<img\b[^>]*>', img, block, flags=re.I)
        # Markdown is sanitized by CyDoc; remove layout wrappers instead of showing raw HTML.
        block = re.sub(r'</?(?:p|div|details|summary)(?:\s[^>]*)?>', '', block)
        parts[i] = block
    return ''.join(parts), changes


def generate_references(content, asset_root):
    sources = references()
    mapping = {path.resolve(): reference_id(path) for path in sources}
    audit, links = [], []
    for path in sources:
        relative = path.relative_to(ROOT).as_posix()
        original = path.read_text(encoding='utf-8-sig')
        identifier = mapping[path.resolve()]
        title = next((line.lstrip('# ').strip() for line in original.splitlines() if line.startswith('# ')), path.stem)
        title = re.sub(r'\{#[^}]+\}', '', title).replace('`', '').strip()
        body, changes = rewrite_reference(original, path, mapping, asset_root)
        sdk = (path.parent.name == 'Docs' and path.stem not in APP_REFERENCES) or path.name == 'CyToolsGuide.md'
        prototype = path.is_relative_to(ROOT / 'modules')
        section = ('SDK reference snapshot' if sdk else 'Technical reference')
        sha = source_digest(path)
        for locale in ('en', 'fr'):
            if locale == 'en':
                notice = (f'Original reference: `{relative}`. This appendix preserves the source language; '
                          'it is not a reviewed translation. Commands and code examples retain their original meaning.\n\n')
                if sdk:
                    notice += '**Versioned SDK reference.** This describes the bundled CyToolsCore contract; example versions, tools and platforms are not guarantees about CyDecompilator. Check the application capability guide and generated operation contracts.\n\n'
                if prototype:
                    notice += '**Experimental module snapshot.** Historical standalone/integration statements and local test reports describe their recorded stage. Work directories, private game inputs and proof files are not part of this help bundle. Check current application contracts for integrated functionality.\n\n'
            else:
                notice = (f'Référence originale : `{relative}`. Cette annexe conserve sa langue source ; '
                          'elle ne constitue pas une traduction révisée. Les commandes et exemples sont conservés.\n\n')
                if sdk:
                    notice += '**Référence SDK versionnée.** Ce contrat CyToolsCore inclut des exemples historiques ; ils ne garantissent pas les fonctionnalités de CyDecompilator. Consultez les capacités de l’application et les contrats générés.\n\n'
                if prototype:
                    notice += '**Instantané d’un module expérimental.** Les anciens états d’intégration et rapports locaux décrivent leur étape enregistrée. Dossiers de travail, jeux et fichiers de preuves privés ne sont pas inclus. Consultez les contrats actuels pour les fonctions intégrées.\n\n'
            page(content, locale, identifier, title, section, notice + body, sha[:12], translated=False, order=500)
        audit.append({'source': relative, 'id': identifier, 'sha256': sha, 'translation': 'original-language-unreviewed',
                      'status': 'versioned-sdk-snapshot' if sdk else 'experimental-module-snapshot' if prototype else 'preserved-technical-reference', 'rewrittenLinks': changes})
        links.append(f'- [{title}](doc:{identifier}) — `{relative}`')
    for locale in ('en', 'fr'):
        body = ('Original technical guides, API contracts, examples and SDK snapshots are preserved below. '
                'These appendices keep their source language. Their translation status is deliberately untracked. '
                'The complete user guide is translated into English and French.\n\n' if locale == 'en' else
                'Les guides techniques, exemples et contrats SDK sont conservés ci-dessous dans leur langue originale. '
                'Leur traduction est explicitement non suivie. Le guide utilisateur est traduit en anglais et en français.\n\n')
        page(content, locale, 'technical-references', 'Technical references' if locale == 'en' else 'Références techniques',
             'Reference' if locale == 'en' else 'Références', body + '\n'.join(links), order=90)
    return audit


def generate_api(content, manifest):
    operations = manifest['operations']
    ids = set()
    for operation in operations:
        identifier = 'op-' + operation['id'].replace('_', '-')
        if identifier in ids:
            raise ValueError('Duplicate operation documentation id')
        ids.add(identifier)
        contract = json.dumps(operation, ensure_ascii=False, indent=2)
        revision = hashlib.sha256(contract.encode()).hexdigest()[:12]
        for locale in ('en', 'fr'):
            intro = ('Generated from the installed `app/CyTool.json`. Contract names, descriptions and schema strings retain their original language. '
                     'This is the declared interface, not evidence that an optional engine is installed or a scenario succeeds.\n\n' if locale == 'en' else
                     'Généré depuis `app/CyTool.json`. Les noms, descriptions et chaînes des schémas conservent leur langue originale. '
                     'Ce contrat décrit l’interface déclarée ; il ne prouve pas qu’un moteur facultatif est installé ou qu’un scénario réussit.\n\n')
            body = intro + f"`{operation['id']}` — {operation['description']}\n\n"
            body += '## ' + ('Permissions' if locale == 'en' else 'Autorisations') + ' {#permissions}\n\n'
            body += ', '.join('`' + p + '`' for p in operation.get('permissions', [])) or ('None declared.' if locale == 'en' else 'Aucune déclarée.')
            body += '\n\n## ' + ('Complete contract' if locale == 'en' else 'Contrat complet') + ' {#contract}\n\n```json\n' + contract + '\n```\n\n'
            body += '[MCP / CLI](doc:automation) · [API](doc:operation-api)\n'
            page(content, locale, identifier, operation['id'], 'Operation API' if locale == 'en' else 'API des opérations', body, revision, order=200, kind='api')
    for locale in ('en', 'fr'):
        intro = (f'The {len(operations)} contracts below come from the installed operation manifest. Use the CLI or MCP job protocol described in the automation guide; permissions, cancellation and schemas are preserved verbatim.\n\n' if locale == 'en' else
                 f'Les {len(operations)} contrats ci-dessous proviennent du manifeste des opérations. Utilisez le protocole CLI ou MCP décrit dans le guide d’automatisation ; autorisations, annulation et schémas sont conservés intégralement.\n\n')
        rows = ['- [`' + op['id'] + '`](doc:op-' + op['id'].replace('_', '-') + ')' for op in operations]
        page(content, locale, 'operation-api', 'Operation API' if locale == 'en' else 'API des opérations',
             'Reference' if locale == 'en' else 'Références', intro + '\n'.join(rows),
             source_digest(ROOT / 'app/CyTool.json')[:12], order=91, kind='api')


def source_policy(content):
    for locale in ('en', 'fr'):
        body = ('CyDoc extracts explicit Python `@doc` docstrings and creates a lexical source/import index for this allowlist only. '
                'The index does not infer types or resolve dynamic imports. Runtime data, inspected applications, credentials, optional engines, third-party code and private projects are excluded. '
                'Operation API pages are generated from the real JSON manifest rather than a nonexistent Python API importer. '
                'Source/annotation pages do not carry reviewed translation revisions in this CyDoc version; they are reported as untracked.\n\n' if locale == 'en' else
                'CyDoc extrait les annotations Python `@doc` et construit un index lexical des sources/imports pour cette seule liste. '
                'Cet index n’infère pas les types et ne résout pas les imports dynamiques. Données d’exécution, applications analysées, identifiants, moteurs, code tiers et projets privés sont exclus. '
                'L’API des opérations est générée depuis le manifeste JSON réel, sans supposer un importeur API Python inexistant. '
                'Cette version de CyDoc ne suit pas les révisions traduites des pages de sources/annotations ; elles restent signalées comme non suivies.\n\n')
        for filename in SOURCE_FILES:
            identifier = 'source-generated-sources-' + re.sub('[^a-zA-Z0-9]+', '-', filename).strip('-').lower()
            body += f'- [`{filename}`](doc:{identifier})\n'
        page(content, locale, 'source-policy', 'Source index scope' if locale == 'en' else 'Portée de l’index des sources',
             'Reference' if locale == 'en' else 'Références', body, order=92)


def make_routes(site):
    manifest = json.loads((site / 'manifest.json').read_text(encoding='utf-8'))
    compatibility = json.loads((DOCS / 'compatibility.json').read_text(encoding='utf-8'))
    routes = {'schemaVersion': 1, 'defaultLocale': 'en', 'locales': ['en', 'fr'], 'modules': ['image'],
              'contexts': compatibility['contexts'], 'aliases': compatibility['pages'],
              'legacyAnchors': compatibility['anchors'], 'pages': {},
              'chapters': json.loads((DOCS / 'catalog.json').read_text(encoding='utf-8'))['topics']}
    for entry in manifest['pages']:
        value = routes['pages'].setdefault(entry['id'], {'locales': [], 'anchors': {}, 'media': {}, 'title': {}})
        locale = entry['locale']
        value['title'][locale] = entry['title']
        value['locales'].append(locale)
        value['anchors'][locale] = [h['id'] for h in entry['headings']] + entry.get('anchors', [])
        media = {}
        for block in re.finditer(r'<figure\b[^>]*data-cydoc-module="([^"]+)"[^>]*data-config="([^"]+)"', entry['html']):
            if block[1] != 'image':
                raise ValueError('Unexpected documentation module: ' + block[1])
            config = json.loads(html.unescape(block[2]))
            media[config['id']] = [annotation['id'] for annotation in config.get('annotations', [])]
        value['media'][locale] = media
        for src in re.findall(r'(?:src|poster)="([^"]+)"', entry['html']):
            if not src.startswith('assets/') or not (site / unquote(src)).is_file():
                raise ValueError('Non-local or missing resource: ' + src)
    for chapter in routes['chapters']:
        p = routes['pages'][chapter['id']]
        en = [x for x in p['anchors']['en'] if not x.startswith(('L', 'code-'))]
        fr = [x for x in p['anchors']['fr'] if not x.startswith(('L', 'code-'))]
        if en != fr or p['media']['en'] != p['media']['fr']:
            raise ValueError('Translated chapter anchors/media differ: ' + chapter['id'])
    if set(p.name for p in site.glob('media-*.js')) != {'media-image.js'}:
        raise ValueError('Unexpected exported media modules')
    write_json(site / 'routes.json', routes)
    (site / 'compatibility.js').write_text('globalThis.CYDEC_HELP_COMPAT=' +
        json.dumps({'pages': compatibility['pages'], 'anchors': compatibility['anchors']}, ensure_ascii=True).replace('<', '\\u003c') + ';\n', encoding='utf-8')
    return manifest, routes


def input_hashes():
    files = references() + [ROOT / f for f in SOURCE_FILES] + [ROOT / 'app/CyTool.json',
            ROOT / 'app/vendor/cydoc-source.json', Path(__file__).resolve()]
    files += [f for f in DOCS.rglob('*') if f.is_file() and not any(
        part in {'.generated', 'node_modules', '__pycache__'} for part in f.relative_to(DOCS).parts)]
    return {p.relative_to(ROOT).as_posix(): source_digest(p) for p in sorted(set(files))}


def check_current():
    metadata = json.loads((DESTINATION / 'build-info.json').read_text(encoding='utf-8'))
    if metadata['inputs'] != input_hashes():
        raise ValueError('Documentation is stale; regenerate it before distribution')
    actual = {p.relative_to(DESTINATION).as_posix() for p in DESTINATION.rglob('*') if p.is_file()}
    if actual != set(metadata['outputs']) | {'build-info.json'}:
        raise ValueError('Unexpected or missing documentation export files')
    for name, expected in metadata['outputs'].items():
        if digest(DESTINATION / name) != expected:
            raise ValueError('Documentation output changed: ' + name)
    print('CyDoc: installed export is current and its resources are intact.')


def build(setup=False):
    node, dependency = setup_tools(setup)
    reset_child(GENERATED, DOCS)
    content, site = GENERATED / 'content', GENERATED / 'site'
    shutil.copytree(DOCS / 'content', content)
    for chapter in content.rglob('*.md'):
        chapter.write_text(chapter.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
    # Work on a fresh asset tree, so removed resources cannot survive a rebuild.
    assets = GENERATED / 'assets'
    shutil.copytree(DOCS / 'assets', assets)
    audit = generate_references(content, assets)
    manifest = json.loads((ROOT / 'app/CyTool.json').read_text(encoding='utf-8'))
    generate_api(content, manifest)
    source_policy(content)
    for filename in SOURCE_FILES:
        target = GENERATED / 'sources' / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / filename).read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
    config = json.loads((DOCS / 'cydoc.config.json').read_text(encoding='utf-8'))
    config['version'] = manifest['version']
    config['assets'] = '.generated/assets'
    # Config stays at the project root so all generated paths/IDs are deterministic.
    config_path = DOCS / '.build-config.json'
    try:
        write_json(config_path, config)
        subprocess.run([node, str(TOOLS / 'node_modules/cydoc/tools/cli.mjs'), 'check', str(config_path)], cwd=TOOLS, check=True)
        subprocess.run([node, str(DOCS / 'bundle-reader.mjs'), str(DOCS), str(site)], cwd=TOOLS, check=True)
    finally:
        config_path.unlink(missing_ok=True)
    shutil.copy2(DOCS / 'index.html', site / 'index.html')
    shutil.copy2(DOCS / 'vendor/CyDoc-LICENSE.txt', site / 'CyDoc-LICENSE.txt')
    shutil.copy2(ROOT / 'LICENSE', site / 'CyDecompilator-LICENSE.txt')
    data, routes = make_routes(site)
    write_json(site / 'migration-report.json', {'coreChapters': 22, 'locales': ['en', 'fr'], 'references': audit,
        'sourceHashEncoding': 'UTF-8 text with canonical LF line endings; binary resources are hashed byte-for-byte',
        'sourceAllowlist': list(SOURCE_FILES), 'operationCount': len(manifest['operations']),
        'knownLimits': ['Original-language technical appendices are not reviewed translations.',
            'SDK snapshots contain version-specific examples; current operation contracts take precedence.',
            'Source indexing is lexical; annotations/source pages have untracked translation revisions.',
            'Windows is supported; Linux is experimental. Browser checks on other platforms remain necessary.']})
    outputs = {p.relative_to(site).as_posix(): digest(p) for p in sorted(site.rglob('*')) if p.is_file()}
    write_json(site / 'build-info.json', {'schemaVersion': 1, 'cydoc': dependency,
               'inputs': input_hashes(), 'outputs': outputs})
    # Publish only after compilation, link/media checks and route validation succeeded.
    staging = ROOT / 'app/help.staging'
    reset_child(staging, ROOT / 'app')
    shutil.copytree(site, staging, dirs_exist_ok=True)
    if DESTINATION.exists():
        reset_child(DESTINATION, ROOT / 'app')
        DESTINATION.rmdir()
    staging.rename(DESTINATION)
    total = sum(p.stat().st_size for p in DESTINATION.rglob('*') if p.is_file())
    print(f'CyDoc: shipped {len(data["pages"])} pages, {len(audit)} reference sources, {len(manifest["operations"])} operation contracts; {total:,} bytes.')
    check_current()
    return DESTINATION


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true', help='Install pinned build-only npm dependencies into runtime/')
    parser.add_argument('--check', action='store_true', help='Check freshness and exported hashes without Node or rebuilding')
    options = parser.parse_args()
    if options.check:
        check_current()
    else:
        build(options.setup)
