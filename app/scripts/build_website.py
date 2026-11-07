"""Build the static showcase and unchanged CyDoc reader for GitHub Pages.

Only website/index.html, website/assets, translated copy, and the documentation
export enter the output. No application runtime or project store is traversed.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'website'
MANUAL = ROOT / 'app/Documentation'
DIST = ROOT / 'dist'
DESTINATION = DIST / 'site'
BUILD_INFO = DIST / 'site-build.json'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix in ('.html', '.css', '.js', '.json', '.py', '.md', '.yml'):
        content = content.replace(b'\r\n', b'\n')
    return hashlib.sha256(content).hexdigest()


def input_files():
    return sorted([SOURCE / 'index.html', SOURCE / 'content.json', Path(__file__).resolve(),
                   ROOT / 'app/CyTool.json', *[p for p in (SOURCE / 'assets').rglob('*') if p.is_file()],
                   *[p for p in MANUAL.rglob('*') if p.is_file()]])


def inputs():
    return {p.relative_to(ROOT).as_posix(): source_digest(p) for p in input_files()}


class Page(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.references = []
        self.translations = set()
        self.docs = []
        self.images = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if 'id' in attrs:
            if attrs['id'] in self.ids:
                raise ValueError('Duplicate HTML ID: ' + attrs['id'])
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if attrs.get(key): self.references.append(attrs[key])
        for key in ('data-i18n', 'data-i18n-aria', 'data-i18n-alt', 'data-caption'):
            if attrs.get(key): self.translations.add(attrs[key])
        if 'data-doc' in attrs: self.docs.append((attrs['data-doc'], attrs.get('data-anchor', '')))
        if tag == 'img' and attrs.get('src'): self.images.append(attrs)


def read_copy(version):
    copy = json.loads((SOURCE / 'content.json').read_text('utf-8'))
    if set(copy) != {'en', 'fr'} or set(copy['en']) != set(copy['fr']):
        raise ValueError('English and French must have identical translation keys.')
    for values in copy.values():
        for key, value in values.items():
            if not isinstance(value, str) or not value.strip(): raise ValueError('Empty translation: ' + key)
            values[key] = value.replace('{{version}}', version)
    return copy


def check_links(root: Path, page: Page, copy):
    missing = page.translations - copy['en'].keys()
    if missing: raise ValueError('Missing translations: ' + ', '.join(sorted(missing)))
    routes = json.loads((MANUAL / 'DocData/routes.json').read_text('utf-8'))['pages']
    for topic, anchor in page.docs:
        for language in ('en', 'fr'):
            if topic not in routes or language not in routes[topic]['locales']:
                raise ValueError('Unknown manual topic: ' + topic)
            if anchor and anchor not in routes[topic]['anchors'][language]:
                raise ValueError('Unknown manual anchor: ' + topic + '/' + anchor)
    for ref in page.references:
        url = urlsplit(ref)
        if url.scheme or url.netloc:
            if url.scheme != 'https': raise ValueError('Unexpected external link: ' + ref)
            continue
        if not url.path:
            if url.fragment and url.fragment not in page.ids: raise ValueError('Unknown section: ' + ref)
            continue
        target = (root / unquote(url.path)).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError('Missing or escaping resource: ' + ref)
    for image in page.images:
        if 'alt' not in image: raise ValueError('Missing image alternative text.')
        data = (root / image['src']).read_bytes()
        if data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError('Expected a real PNG image.')
        width, height = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
        if width * int(image.get('height', 0)) != height * int(image.get('width', 0)) or not int(image.get('width', 0)):
            raise ValueError('Incorrect image dimensions: ' + image['src'])


def reset_output(path: Path):
    resolved = path.resolve()
    if resolved != DESTINATION.resolve() or path.parent.resolve() != DIST.resolve():
        raise ValueError('Only the generated dist/site directory may be replaced.')
    if not path.exists(): return
    if not BUILD_INFO.is_file(): raise ValueError('Refusing to replace an unrecognized output directory.')
    for child in [path, *path.rglob('*')]:
        if child.is_symlink() or getattr(child.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Refusing cleanup of linked output.')
    shutil.rmtree(path)


def build():
    from scripts import build_documentation
    build_documentation.check_current()
    version = json.loads((ROOT / 'app/CyTool.json').read_text('utf-8'))['version']
    copy = read_copy(version)
    DIST.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='showcase-', dir=DIST) as temporary:
        stage = Path(temporary)
        (stage / 'assets').mkdir()
        replacements = {}

        def add_asset(name, contents):
            suffix = Path(name).suffix
            filename = Path(name).stem + '.' + hashlib.sha256(contents).hexdigest()[:12] + suffix
            (stage / 'assets' / filename).write_bytes(contents)
            replacements['assets/' + name] = 'assets/' + filename

        def rewrite(value):
            for old, new in replacements.items(): value = value.replace(old, new)
            return value

        allowed = {'.png', '.css', '.js'}
        for path in sorted((SOURCE / 'assets').iterdir()):
            if path.suffix not in allowed or not path.is_file() or path.is_symlink():
                raise ValueError('Unexpected source asset: ' + path.name)
            if path.name == 'site.js': continue
            contents = path.read_bytes()
            if path.suffix == '.css': contents = contents.replace(b'\r\n', b'\n')
            add_asset(path.name, contents)
        add_asset('content.js', ('window.CYDEC_SITE_COPY=' + json.dumps(copy, ensure_ascii=False, separators=(',', ':')) + ';\n').encode())
        add_asset('site.js', rewrite((SOURCE / 'assets/site.js').read_text('utf-8')).encode())
        template = (SOURCE / 'index.html').read_text('utf-8')
        values = {**copy['en'], 'version': version, 'year': '2026'}
        template = re.sub(r'\{\{([^{}]+)\}\}', lambda match: html.escape(values[match[1]], quote=True), template)
        if '{{' in template: raise ValueError('Unexpanded template variable.')
        rendered = rewrite(template)
        (stage / 'index.html').write_text(rendered, encoding='utf-8', newline='\n')
        (stage / '.nojekyll').write_bytes(b'')
        # Copy only the distributable reader, without modifying a byte of it.
        shutil.copytree(MANUAL, stage / 'manual')
        check_links(stage, Page(rendered), copy)
        output_hashes = {p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob('*')) if p.is_file()}
        info = {'schemaVersion': 1, 'version': version, 'inputs': inputs(), 'outputs': output_hashes}
        reset_output(DESTINATION)
        shutil.copytree(stage, DESTINATION)
        BUILD_INFO.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    check_current()
    print('Showcase: ' + str(DESTINATION / 'index.html'))
    return DESTINATION


def check_current():
    info = json.loads(BUILD_INFO.read_text('utf-8'))
    if info['inputs'] != inputs(): raise ValueError('Showcase sources changed; rebuild the site.')
    actual = {p.relative_to(DESTINATION).as_posix(): digest(p) for p in sorted(DESTINATION.rglob('*')) if p.is_file()}
    if info['outputs'] != actual: raise ValueError('Showcase output hashes differ or unexpected files were added.')
    copy = read_copy(info['version'])
    check_links(DESTINATION, Page((DESTINATION / 'index.html').read_text('utf-8')), copy)
    for path in MANUAL.rglob('*'):
        if path.is_file() and (DESTINATION / 'manual' / path.relative_to(MANUAL)).read_bytes() != path.read_bytes():
            raise ValueError('The CyDoc export must remain byte-identical.')
    print('Showcase: translations, links, image dimensions, fingerprints and unchanged CyDoc export verified.')


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT / 'app'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify the current build without modifying it.')
    args = parser.parse_args()
    check_current() if args.check else build()
