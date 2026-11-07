"""Shipped bilingual reader, API-only references, offline routes and packaging."""
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
DOCS = APP / '.CyDocBuild'
SITE = APP / 'Documentation'
sys.path.insert(0, str(APP))
from documentation import Documentation

def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def builder():
    spec = importlib.util.spec_from_file_location('documentation_build', DOCS / 'build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_export_hashes_layout_and_local_resources():
    builder().check_current()
    assert (SITE / 'DocAI.md').is_file()
    assert (SITE / 'DocData/CyDoc-LICENSE.txt').read_text().startswith('MIT License')
    assert {p.name for p in (SITE / 'DocData').glob('media-*.js')} == {'media-image.js'}
    html = (SITE / 'Documentation.html').read_text()
    assert 'type="module"' not in html and '<iframe' not in html
    assert set(re.findall(r'<script[^>]*src="([^"]+)"', html)) == {
        'DocData/data.js', 'DocData/compatibility.js', 'DocData/viewer.js'}
    assert not (DOCS / 'node_modules/three').exists()
    assert not any(p.name in {'build-info.json','migration-report.json'} for p in SITE.rglob('*'))

def test_complete_translations_stable_anchors_media_and_navigation_tree():
    docs = Documentation()
    data = load_json(SITE / 'DocData/manifest.json')
    pages = {(p['locale'],p['id']):p for p in data['pages']}
    ids = {p['id'] for p in data['pages']}
    assert data['defaultLocale'] == 'en' and [l['code'] for l in data['locales']] == ['en','fr']
    assert len(docs.routes['chapters']) == 22
    for identifier in ids:
        en,fr = pages['en',identifier],pages['fr',identifier]
        assert fr['sourceRevision'] == en['revision']
        assert en['description'] and fr['description']
        assert [h['id'] for h in en['headings']] == [h['id'] for h in fr['headings']]
        assert en.get('parent') == fr.get('parent')
        if en.get('parent'): assert en['parent'] in ids
        assert docs.routes['pages'][identifier]['media']['en'] == docs.routes['pages'][identifier]['media']['fr']
    assert pages['en','op-reconstruction-run']['parent'] == 'api-projects'
    assert pages['en','api-projects']['parent'] == 'operation-api'
    assert pages['en','native']['parent'] == 'workspace'
    report = load_json(SITE / 'DocData/translation-report.json')
    assert not report['missing'] and not report['outdated'] and not report['untracked']
    assert report['current'] == len(ids)

def test_public_operations_retain_schemas_with_translated_descriptions():
    data = load_json(SITE / 'DocData/manifest.json')
    for operation in load_json(APP / 'CyTool.json')['operations']:
        identifier='op-'+operation['id'].replace('_','-')
        en,fr=[next(p for p in data['pages'] if p['id']==identifier and p['locale']==loc) for loc in ('en','fr')]
        # Signature is the first code block; the contract follows it.
        contract=json.loads(en['code'][en['code'].index('{\n  \"id\":'):])
        translated=json.loads(fr['code'][fr['code'].index('{\n  \"id\":'):])
        assert contract['inputSchema']==operation['inputSchema']
        assert contract['outputSchema']==operation['outputSchema']
        assert operation['description'] in en['text'] and operation['description'] not in fr['text']
        def remove_descriptions(value):
            if isinstance(value,dict): return {k:remove_descriptions(v) for k,v in value.items() if k!='description'}
            if isinstance(value,list): return [remove_descriptions(v) for v in value]
            return value
        assert remove_descriptions(contract)==remove_descriptions(translated)
        assert en['symbol']==fr['symbol']==operation['id']

def test_new_untranslated_contract_description_stops_generation(tmp_path):
    manifest=load_json(APP/'CyTool.json')
    manifest['operations'][0]['inputSchema']['properties']['newField']={'type':'string','description':'Untranslated new API meaning.'}
    with pytest.raises(KeyError):builder().generate_api(tmp_path,manifest)

def test_public_parameter_examples_match_the_installed_api():
    import jsonschema
    operations={operation['id']:operation for operation in load_json(APP/'CyTool.json')['operations']}
    for name,example in load_json(DOCS/'api-examples.json').items():
        jsonschema.Draft202012Validator(operations[name]['inputSchema']).validate(example)

def test_legacy_entry_points_preserve_the_language_and_section_fragment():
    for entry in (SITE/'index.html',APP/'help/index.html'):
        text=entry.read_text('utf-8')
        assert 'location.search + location.hash' in text and 'Documentation.html' in text
    assert list((APP/'help').iterdir())==[APP/'help/index.html']

def test_agent_instructions_reports_and_implementations_are_not_human_content():
    data=load_json(SITE/'DocData/manifest.json')
    ids={p['id'] for p in data['pages']}
    assert not ids.intersection({'source-policy','translation-report','technical-references'})
    assert not any(p['id'].startswith(('source-','ref-')) or p.get('kind')=='source' for p in data['pages'])
    for page in data['pages']:
        assert 'def topic_for_context' not in page['text']
        assert 'migration-report.json' not in page['text'] and 'build_documentation.py' not in page['text']
        assert 'Server-checked completion proof.' not in page['text'] if page['locale']=='fr' else True
        assert '\ufffd' not in page['text']+page['title']
    assert 'Installed operation contracts' in (SITE/'DocAI.md').read_text('utf-8')
    assert data['logo']=='assets/app-logo.png'
    assert (SITE/'DocData/assets/app-logo.png').read_bytes()==(APP/'assets/logo-256.png').read_bytes()

def test_only_authored_assets_and_public_comment_documentation_are_distributed():
    assert {p.name for p in (SITE/'DocData/assets').iterdir()} == {p.name for p in (DOCS/'assets').iterdir()}
    assert not any(p.suffix in {'.py','.cpp','.h','.ts'} for p in SITE.rglob('*'))
    pages=load_json(SITE/'DocData/manifest.json')['pages']
    for locale in ('en','fr'):
        page=next(p for p in pages if p['id']=='help-route-api' and p['locale']==locale)
        assert page['symbol']=='Documentation.url' and '-> str' in page['code']
        assert 'import webbrowser' not in page['code']

def test_original_screenshots_and_user_code_examples_are_distributed():
    pages={(p['locale'],p['id']):p for p in load_json(SITE/'DocData/manifest.json')['pages']}
    for source in (ROOT/'docs/screenshots').glob('*.png'):
        assert (SITE/'DocData/assets'/source.name).read_bytes()==source.read_bytes()
    for locale in ('en','fr'):
        for source in (DOCS/'manual'/locale).glob('*.md'):
            text=source.read_text('utf-8')
            identifier=re.search(r'^id: (.+)$',text,re.M)[1]
            for language,code in re.findall(r'^```([^\n]*)\n(.*?)^```',text,re.M|re.S):
                if language in {'python','json','powershell','bash','cpp','c','javascript','hlsl','glsl'}:
                    assert code.strip() in pages[locale,identifier]['code']

def test_safe_native_legacy_and_french_links():
    docs=Documentation()
    uri=docs.url('app/manual/fr/workspace.md','fr',anchor='suivre-le-code')
    assert uri.startswith((SITE/'Documentation.html').resolve().as_uri())
    assert uri.endswith('#/fr/workspace/follow-the-code')
    assert docs.url('overview','de').endswith('#/en/start')
    assert docs.url('workspace',anchor='workspace-inspect-and-navigate').endswith('#/en/workspace')
    assert docs.url('doc:workspace#follow-the-code','fr-CA')==uri
    assert docs.url('ref-app-docs-xboxporting','fr').endswith('#/fr/xbox-methods')
    for alias in docs.routes['aliases']: assert docs.url(alias).startswith(SITE.resolve().as_uri())
    media=docs.url('start','fr',media='workspace-screenshot',note='function-list',zoom=2)
    parts=urlsplit(media)
    assert parts.scheme=='file' and not parts.query
    assert parse_qs(parts.fragment.split('?')[1])=={'media':['workspace-screenshot'],'note':['function-list'],'zoom':['2']}

@pytest.mark.parametrize('options',[
    {'topic':'../../private'},{'topic':'https://example.com'},{'topic':'javascript:alert(1)'},
    {'anchor':'missing'},{'media':'../../private.png'},{'media':'missing'},{'zoom':2},
    {'media':'workspace-screenshot','note':'missing'},{'media':'workspace-screenshot','zoom':'nan'},
    {'media':'workspace-screenshot','zoom':100},{'media':'workspace-screenshot','command':'execute'},
])
def test_invalid_destinations_and_media_states_are_rejected(options):
    with pytest.raises((ValueError,TypeError)):Documentation().url(**options)

def test_unicode_spaces_and_archive_relocation(tmp_path):
    target=tmp_path/'Mon application été 100% #1'/'Documentation'
    shutil.copytree(SITE,target)
    with zipfile.ZipFile(tmp_path/'manual.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for file in target.rglob('*'):
            if file.is_file():archive.write(file,file.relative_to(target))
    relocated=tmp_path/'Another install'
    with zipfile.ZipFile(tmp_path/'manual.zip') as archive:archive.extractall(relocated)
    assert '%C3%A9t%C3%A9%20100%25%20%231/Documentation/Documentation.html#/en/start' in Documentation(target).url()
    assert Documentation(relocated).url('projects').startswith(relocated.as_uri())
    assert (relocated/'DocData/assets/workspace.png').is_file()

def test_only_explicit_open_launches_browser_and_reports_failure(tmp_path):
    opened=[]
    docs=Documentation(opener=lambda url,**kw:opened.append((url,kw)) or True)
    docs.url();assert not opened
    assert docs.open('projects')==opened[0][0] and opened[0][1]=={'new':0}
    with pytest.raises(ValueError):docs.open('missing')
    docs.opener=lambda *a,**kw:False
    with pytest.raises(OSError):docs.open()
    (tmp_path/'DocData').mkdir();shutil.copy(SITE/'DocData/routes.json',tmp_path/'DocData/routes.json')
    with pytest.raises(FileNotFoundError):Documentation(tmp_path).open()

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



def test_cleanup_refuses_paths_outside_the_build_root(tmp_path):
    parent=tmp_path/'build';parent.mkdir()
    outside=tmp_path/'valuable';outside.mkdir();(outside/'keep').write_text('keep')
    with pytest.raises(ValueError):builder().reset_child(outside,parent)
    with pytest.raises(ValueError):builder().reset_child(parent,parent)
    assert (outside/'keep').read_text()=='keep'

@pytest.mark.parametrize('name',['guide.md','module.py','config.json','.gitignore','icon.svg','api-fr.tsv'])
def test_hashes_survive_windows_checkout_conversion(tmp_path,name):
    source=tmp_path/name;source.write_bytes(b'# Guide\n\nUseful content.\n')
    expected=builder().source_digest(source)
    source.write_bytes(b'# Guide\r\n\r\nUseful content.\r\n')
    assert builder().source_digest(source)==expected

def test_pages_uploads_only_the_fresh_distributable_directory():
    import yaml
    workflow=yaml.load((ROOT/'.github/workflows/documentation-pages.yml').read_text('utf-8'),Loader=yaml.BaseLoader)
    steps=workflow['jobs']['build']['steps']
    upload=next(s for s in steps if s.get('uses','').startswith('actions/upload-pages-artifact@'))
    assert upload['with']['path']=='dist/site'
    assert next(i for i,s in enumerate(steps) if s.get('run')=='python app/scripts/build_documentation.py --check')<steps.index(upload)
    assert next(i for i,s in enumerate(steps) if s.get('run')=='python app/scripts/build_website.py --check')<steps.index(upload)
    assert workflow['jobs']['deploy']['needs']=='build'

@pytest.mark.parametrize(('filename','language'),[('README.md','en'),('README.fr.md','fr'),('LISEZ-MOI.md','fr'),('app/README.md','en'),('app/.CyDocBuild/README.md','en')])
def test_readme_language_destinations(filename,language):
    href=re.search(r'\[Documentation\]\(([^)]+)\)',(ROOT/filename).read_text('utf-8'))[1]
    route=urlsplit(href)
    assert (route.scheme,route.netloc,route.path)==('https','mrmybal.github.io','/CyDecompilator/manual/Documentation.html')
    assert route.fragment=='/'+language+'/start'

def test_release_excludes_workspace_and_overlays_the_complete_export(tmp_path,monkeypatch):
    import io
    from scripts import make_release,build_documentation
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as source:
        source.writestr('CyDecompilator/app/help/obsolete.js','stale')
        source.writestr('CyDecompilator/app/Documentation/DocData/obsolete.js','stale')
        source.writestr('CyDecompilator/app/.CyDocBuild/internal/private.md','not shipped')
        source.writestr('CyDecompilator/README.md','source checkout')
    monkeypatch.setattr(make_release,'git',lambda *a:'' if a[0]=='status' else '\n'.join(build_documentation.input_hashes()) if a[0]=='ls-files' else 'a'*40)
    monkeypatch.setattr(build_documentation,'build',lambda:SITE)
    monkeypatch.setattr(make_release.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout=buffer.getvalue()))
    monkeypatch.setattr(make_release,'sys',SimpleNamespace(platform='linux'))
    monkeypatch.setattr(make_release,'DIST',tmp_path)
    archive,version,commit,sha=make_release.build()
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==sha
    with zipfile.ZipFile(archive) as exported:
        assert not any('/.CyDocBuild/' in n or n.endswith('/obsolete.js') for n in exported.namelist())
        for source in SITE.rglob('*'):
            if source.is_file():assert exported.read('CyDecompilator/app/Documentation/'+source.relative_to(SITE).as_posix())==source.read_bytes()
