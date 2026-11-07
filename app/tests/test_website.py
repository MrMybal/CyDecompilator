"""Check the actual publication boundary, bilingual routes and generated assets."""
import json
import re
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from scripts import build_website as site


@pytest.mark.parametrize(('filename', 'label', 'language'), [('README.md', 'Website', 'en'), ('README.fr.md', 'Présentation', 'fr'), ('LISEZ-MOI.md', 'Présentation', 'fr')])
def test_public_readmes_link_to_both_the_website_and_html_reader(filename, label, language):
    readme = (APP.parent / filename).read_text('utf-8')
    website = urlsplit(re.search(r'\[' + label + r'\]\(([^)]+)\)', readme)[1])
    manual = urlsplit(re.search(r'\[Documentation\]\(([^)]+)\)', readme)[1])
    assert (website.scheme, website.netloc, website.path) == ('https', 'mrmybal.github.io', '/CyDecompilator/')
    assert parse_qs(website.query) == {'lang': [language]}
    assert (manual.scheme, manual.netloc, manual.path) == ('https', 'mrmybal.github.io', '/CyDecompilator/manual/Documentation.html')
    assert manual.fragment == '/' + language + '/start'


@pytest.fixture
def exported(tmp_path, monkeypatch):
    monkeypatch.setattr(site, 'DIST', tmp_path)
    monkeypatch.setattr(site, 'DESTINATION', tmp_path / 'site')
    monkeypatch.setattr(site, 'BUILD_INFO', tmp_path / 'site-build.json')
    return site.build()


def test_only_the_showcase_and_identical_manual_are_distributed(exported):
    assert {p.name for p in exported.iterdir()} == {'index.html', 'assets', 'manual', '.nojekyll'}
    assert not (exported / 'manual/runtime').exists()
    assert not (exported / 'manual/data').exists()
    assert not (exported / '.site-build.json').exists()
    for source in site.MANUAL.rglob('*'):
        if source.is_file():
            assert (exported / 'manual' / source.relative_to(site.MANUAL)).read_bytes() == source.read_bytes()


def test_bilingual_copy_and_cache_fingerprints_are_in_the_real_output(exported):
    page = (exported / 'index.html').read_text('utf-8')
    assert '<html lang="en">' in page and '{{' not in page
    assert 'Development release' in page
    parsed = site.Page(page)
    assert len(parsed.images) >= 12
    content = next((exported / 'assets').glob('content.*.js')).read_text('utf-8')
    copy = json.loads(content.removeprefix('window.CYDEC_SITE_COPY=').rstrip(';\n'))
    assert copy['fr']['nav.documentation'] == 'Documentation'
    assert set(copy['en']) == set(copy['fr'])
    for filename in (exported / 'assets').iterdir():
        assert filename.name.split('.')[-2] == site.digest(filename)[:12]
    for language in ('en', 'fr'):
        for topic, anchor in parsed.docs:
            assert language in json.loads((exported / 'manual/DocData/routes.json').read_text('utf-8'))['pages'][topic]['locales']


def test_check_rejects_extra_unreviewed_files(exported):
    (exported / 'unrelated.json').write_text('{"private":"do not publish"}', encoding='utf-8')
    with pytest.raises(ValueError, match='unexpected files'):
        site.check_current()


def test_cleanup_does_not_delete_unknown_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(site, 'DIST', tmp_path)
    monkeypatch.setattr(site, 'DESTINATION', tmp_path / 'site')
    monkeypatch.setattr(site, 'BUILD_INFO', tmp_path / 'site-build.json')
    unknown = tmp_path / 'site'
    unknown.mkdir()
    (unknown / 'keep.txt').write_text('preserve')
    with pytest.raises(ValueError, match='unrecognized'):
        site.reset_output(unknown)
    assert (unknown / 'keep.txt').read_text() == 'preserve'
    with pytest.raises(ValueError, match='Only the generated'):
        site.reset_output(tmp_path)
