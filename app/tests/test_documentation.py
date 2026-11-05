"""Offline export, real contracts, safe local routing and native help integration."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
from types import SimpleNamespace, MethodType
from urllib.parse import urlsplit, parse_qs
import zipfile

import pytest

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))
from documentation import Documentation


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def builder():
    spec = importlib.util.spec_from_file_location('documentation_build', APP / 'scripts/build_documentation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_hashes_are_current_and_all_resources_are_distributed():
    builder().check_current()
    metadata = load_json(APP / 'help/build-info.json')
    assert len(metadata['outputs']) >= 13
    assert (APP / 'help/CyDoc-LICENSE.txt').read_text().startswith('MIT License')
    assert {p.name for p in (APP / 'help').glob('media-*.js')} == {'media-image.js'}
    assert 'type="module"' not in (APP / 'help/index.html').read_text()
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', (APP / 'help/index.html').read_text())
    assert set(scripts) == {'data.js', 'compatibility.js', 'viewer.js'}
    assert not (ROOT / 'runtime/documentation-tools/node_modules/three').exists()


def test_common_ids_anchors_media_and_tracked_chapter_translations():
    docs = Documentation()
    manifest = load_json(APP / 'help/manifest.json')
    pages = {(page['locale'], page['id']): page for page in manifest['pages']}
    assert len(docs.routes['chapters']) == 22
    for chapter in docs.routes['chapters']:
        identifier = chapter['id']
        en, fr = pages['en', identifier], pages['fr', identifier]
        assert [h['id'] for h in en['headings']] == [h['id'] for h in fr['headings']]
        assert fr['sourceRevision'] == en['revision']
        assert docs.routes['pages'][identifier]['media']['en'] == docs.routes['pages'][identifier]['media']['fr']
    report = load_json(APP / 'help/translation-report.json')
    assert not report['missing'] and not report['outdated']
    assert report['untracked']  # Original-language technical references are never falsely reviewed.


def test_every_declared_operation_keeps_its_complete_contract():
    operations = load_json(APP / 'CyTool.json')['operations']
    data = load_json(APP / 'help/manifest.json')
    for operation in operations:
        identifier = 'op-' + operation['id'].replace('_', '-')
        for locale in ('en', 'fr'):
            page = next(page for page in data['pages'] if page['id'] == identifier and page['locale'] == locale)
            # CyDoc retains raw code text in the manifest, independently of syntax highlighting.
            assert json.loads(page['code']) == operation


def test_technical_sources_preserved_with_auditable_hashes_and_no_private_indexing():
    audit = load_json(APP / 'help/migration-report.json')
    expected = {p.relative_to(ROOT).as_posix() for p in builder().references()}
    assert {entry['source'] for entry in audit['references']} == expected
    for entry in audit['references']:
        assert builder().source_digest(ROOT / entry['source']) == entry['sha256']
        assert entry['translation'] == 'original-language-unreviewed'
    assert audit['sourceAllowlist'] == list(builder().SOURCE_FILES)
    sources = [page for page in load_json(APP / 'help/manifest.json')['pages'] if page.get('kind') == 'source']
    assert len(sources) == 2 * len(builder().SOURCE_FILES)
    assert not any(word in page['source'].lower() for page in sources for word in ('credentials', 'runtime/', 'data/', 'vendor/'))


def test_original_screenshot_bytes_and_user_code_examples_are_preserved():
    original = load_json(ROOT / 'docs/cydoc/migrated-manual.json')
    assert len(original['chapters']) == 44
    for chapter in original['chapters']:
        text = (ROOT / chapter['target']).read_text('utf-8')
        code = [hashlib.sha256(body.encode()).hexdigest() for lang, body in
                re.findall(r'^```([^\n]*)\n(.*?)^```', text, re.M | re.S) if lang not in {'diagram', 'image'}]
        assert all(block['sha256'] in code for block in chapter['codeBlocks']), chapter['source']
    for name, expected in original['screenshots'].items():
        assert hashlib.sha256((APP / 'help/assets' / name).read_bytes()).hexdigest() == expected


def test_safe_local_urls_legacy_filenames_and_french_heading_slugs():
    docs = Documentation()
    uri = docs.url('app/manual/fr/workspace.md', 'fr', anchor='suivre-le-code')
    assert uri.startswith((APP / 'help/index.html').resolve().as_uri())
    assert uri.endswith('#/fr/workspace/follow-the-code')
    assert docs.url('overview', 'de').endswith('#/en/start')
    assert docs.url('workspace', anchor='workspace-inspect-and-navigate').endswith('#/en/workspace')
    assert docs.url('doc:workspace#follow-the-code', 'fr-CA') == uri
    media = docs.url('start', 'fr', media='workspace-screenshot', note='function-list', zoom=2)
    parts = urlsplit(media)
    assert parts.scheme == 'file' and not parts.query
    assert parse_qs(parts.fragment.split('?')[1]) == {'media':['workspace-screenshot'], 'note':['function-list'], 'zoom':['2']}


@pytest.mark.parametrize('options', [
    {'topic':'../../private'}, {'topic':'https://example.com'}, {'topic':'javascript:alert(1)'},
    {'anchor':'missing'}, {'media':'../../private.png'}, {'media':'missing'}, {'zoom':2},
    {'media':'workspace-screenshot', 'note':'missing'}, {'media':'workspace-screenshot', 'zoom':'nan'},
    {'media':'workspace-screenshot', 'zoom':100}, {'media':'workspace-screenshot', 'command':'execute'},
])
def test_invalid_destinations_and_media_states_are_rejected(options):
    with pytest.raises((ValueError, TypeError)):
        Documentation().url(**options)


def test_unicode_and_spaces_in_relocated_self_contained_export(tmp_path):
    target = tmp_path / 'Mon application été 100% #1' / 'help'
    shutil.copytree(APP / 'help', target)
    with zipfile.ZipFile(tmp_path / 'help.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in target.rglob('*'):
            if file.is_file(): archive.write(file, file.relative_to(target))
    relocated = tmp_path / 'Another install'
    with zipfile.ZipFile(tmp_path / 'help.zip') as archive:
        archive.extractall(relocated)
    docs = Documentation(target)
    assert '%C3%A9t%C3%A9%20100%25%20%231/help/index.html#/en/start' in docs.url()
    assert Documentation(relocated).url('projects').startswith(relocated.as_uri())
    assert (relocated / 'assets/workspace.png').is_file()


def test_only_explicit_open_calls_browser_and_reports_failure(tmp_path):
    opened = []
    docs = Documentation(opener=lambda url, **kwargs: opened.append((url, kwargs)) or True)
    docs.url(); assert not opened
    assert docs.open('projects') == opened[0][0]
    assert opened[0][1] == {'new':0}
    with pytest.raises(ValueError): docs.open('missing')
    assert len(opened) == 1
    docs.opener = lambda *args, **kwargs: False
    with pytest.raises(OSError): docs.open()
    shutil.copy(APP / 'help/routes.json', tmp_path / 'routes.json')
    with pytest.raises(FileNotFoundError): Documentation(tmp_path).open()


@pytest.fixture
def native_frame(monkeypatch, tmp_path):
    import cyui, ui_common
    from imgui_bundle import imgui
    context = imgui.create_context()
    io = imgui.get_io()
    io.display_size, io.delta_time = (1100, 800), 1/60
    io.set_ini_filename('')
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
    monkeypatch.setattr(ui_common, 'preferences', ui_common.Preferences(tmp_path / 'preferences.json'))
    cyui.apply('navy')
    def frame(callback):
        imgui.new_frame(); imgui.set_next_window_pos((0,0));imgui.set_next_window_size((1100,800))
        imgui.begin('Documentation test', None, imgui.WindowFlags_.no_saved_settings)
        try: callback()
        finally: imgui.end()
        imgui.render()
    yield frame
    imgui.destroy_context(context)


def test_native_launcher_language_override_and_palette_action(native_frame, monkeypatch):
    import ui_common
    from documentation_ui import DocumentationUI
    from cyui_shell import execute_command
    from ui_views import stable_id
    opened = []
    panel = DocumentationUI(Documentation(opener=lambda url, **kw: opened.append(url) or True))
    host = SimpleNamespace(documentation=panel, force_tab='')
    from desktop import App
    host.open_help = MethodType(App.open_help, host)
    ui_common.preferences.values.update(language='fr', manual_language='auto')
    native_frame(lambda: panel.draw(host)); assert not opened
    assert host.open_help(context='project') and opened[-1].endswith('#/fr/projects')
    ui_common.preferences.values['manual_language'] = 'en'
    assert host.open_help('start', media='workspace-screenshot')
    assert '#/en/start?media=' in opened[-1]
    execute_command(host, stable_id('page','help'))
    assert opened[-1].endswith('#/en/start') and host.force_tab == 'help'
    assert len(opened) == 3


def test_real_f1_key_opens_contextual_help(native_frame, monkeypatch):
    import cyui_shell
    from desktop import App
    from documentation_ui import DocumentationUI
    from imgui_bundle import imgui
    opened = []
    panel = DocumentationUI(Documentation(opener=lambda url, **kw: opened.append(url) or True))
    noop = lambda: None
    host = SimpleNamespace(documentation=panel, frames=0, active_page='investigation', force_tab='',
        jobs=SimpleNamespace(poll=noop), ide=SimpleNamespace(draw=noop, debug=SimpleNamespace(tick=noop)),
        investigation=SimpleNamespace(draw=noop), porting=SimpleNamespace(draw=noop), xbox=SimpleNamespace(draw=noop),
        unreal=SimpleNamespace(draw=noop), poll_dialogs=noop, workspace=noop, assistant_page=noop,
        engines_tab=noop, ai_tab=noop)
    host.open_help = MethodType(App.open_help, host)
    monkeypatch.setattr(cyui_shell, 'draw', lambda app, render: render('help'))
    native_frame(lambda: App.draw(host)); assert not opened
    imgui.get_io().add_key_event(imgui.Key.f1, True)
    native_frame(lambda: App.draw(host))
    assert opened[-1].endswith('#/en/investigation') and host.force_tab == 'help'
    imgui.get_io().add_key_event(imgui.Key.f1, False)
    native_frame(lambda: App.draw(host))
    assert len(opened) == 1


def test_unavailable_help_is_visible_without_crashing_the_window(native_frame, monkeypatch, tmp_path):
    import documentation_ui
    monkeypatch.setattr(documentation_ui, 'Documentation', lambda: Documentation(tmp_path))
    panel = documentation_ui.DocumentationUI()
    assert panel.documentation is None and panel.error
    native_frame(lambda: panel.draw(SimpleNamespace()))


def test_build_cleanup_refuses_paths_outside_its_root(tmp_path):
    parent = tmp_path / 'build';parent.mkdir()
    outside = tmp_path / 'valuable';outside.mkdir();(outside/'keep').write_text('keep')
    with pytest.raises(ValueError): builder().reset_child(outside, parent)
    with pytest.raises(ValueError): builder().reset_child(parent, parent)
    assert (outside/'keep').read_text() == 'keep'


def test_private_work_media_is_preserved_locally_and_omitted_from_export(tmp_path, monkeypatch):
    module = builder()
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    source = tmp_path / 'modules/example/README.md'
    private = source.parent / 'work/session.png'
    private.parent.mkdir(parents=True)
    private.write_bytes(b'private local capture')
    assets = tmp_path / 'assets'; assets.mkdir()
    body, audit = module.rewrite_reference('![Local result](work/session.png)', source, {}, assets)
    assert body == 'Local result' and private.read_bytes() == b'private local capture'
    assert not list(assets.iterdir())
    assert audit and 'outside the distributable' in audit[0]['reason']


@pytest.mark.parametrize('name', ['guide.md', 'module.py', 'config.json', '.gitignore', 'icon.svg'])
def test_input_text_hashes_survive_git_line_ending_conversion(tmp_path, name):
    source = tmp_path / name
    source.write_bytes(b'# Guide\n\nUseful content.\n')
    expected = builder().source_digest(source)
    source.write_bytes(b'# Guide\r\n\r\nUseful content.\r\n')
    assert builder().source_digest(source) == expected


def test_release_overlays_the_complete_fresh_export_without_old_help(tmp_path, monkeypatch):
    """Exercise release ZIP assembly without publishing, compiling a launcher or committing unrelated work."""
    import io
    from scripts import make_release, build_documentation
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as source:
        source.writestr('CyDecompilator/app/help/obsolete.js', 'stale')
        source.writestr('CyDecompilator/README.md', 'source checkout')
    monkeypatch.setattr(make_release, 'git', lambda *args: '' if args[0] == 'status' else
                        '\n'.join(build_documentation.input_hashes()) if args[0] == 'ls-files' else 'a'*40)
    monkeypatch.setattr(build_documentation, 'build', lambda: APP / 'help')
    monkeypatch.setattr(make_release.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=buffer.getvalue()))
    monkeypatch.setattr(make_release, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(make_release, 'DIST', tmp_path)
    archive, version, commit, sha = make_release.build()
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == sha
    with zipfile.ZipFile(archive) as exported:
        assert 'CyDecompilator/app/help/obsolete.js' not in exported.namelist()
        for source in (APP / 'help').rglob('*'):
            if source.is_file():
                assert exported.read('CyDecompilator/app/help/' + source.relative_to(APP / 'help').as_posix()) == source.read_bytes()
