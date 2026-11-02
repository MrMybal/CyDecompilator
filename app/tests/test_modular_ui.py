"""Exercise the application's migrated models and real ImGui input/render frames."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import cyui
import ui_common
from imgui_bundle import imgui
from cyui_modules import code, commands, diagnostics, images, inspector
from ui_views import ConversationView, DiffView, DocumentView, LogView, SourceView, diagnostic_rows, stable_id


@pytest.fixture
def frame():
    context = imgui.create_context()
    io = imgui.get_io()
    io.display_size, io.delta_time = (1000, 800), 1/60
    io.set_ini_filename('')
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
    cyui.apply('navy')
    def draw(callback, position=(-100, -100), button=None):
        io.add_mouse_pos_event(*position)
        if button:
            io.add_mouse_button_event(*button)
        imgui.new_frame()
        imgui.set_next_window_pos((0, 0))
        imgui.set_next_window_size((1000, 800))
        imgui.begin('Migration test', None, imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_saved_settings)
        imgui.set_cursor_screen_pos((20, 20))
        result = callback()
        imgui.dummy((0, 0))
        imgui.end()
        imgui.render()
        return result
    yield draw
    imgui.destroy_context(context)


@pytest.mark.parametrize('theme', ui_common.THEME_KEYS)
@pytest.mark.parametrize('density,dpi', [('compact', 1.), ('comfortable', 1.5)])
def test_selected_views_render_in_all_themes_without_changing_host_data(frame, theme, density, dpi):
    cyui.apply(theme, density, dpi)
    source, delta, prose, log, chat = SourceView('hlsl'), DiffView(), DocumentView(), LogView(), ConversationView()
    original = '\tfloat4 main() { return float4(1, 0, 0, 1); }\r\n// café 音楽\r\n'
    source.set_text(original)
    delta.set_texts(original, original.replace('(1,', '(2,'), 'hlsl')
    prose.set_text('# Report\n\n- **State:** ready\n\n```hlsl\n'+original+'```\n\n| A | B |\n|---|---|\n| 1 | 2 |')
    log.set_text('INFO ready\nWARNING keep original\nERROR sample diagnostic')
    chat.append('You', 'Explain **main**')
    chat.append('Assistant', '```hlsl\n'+original+'```')
    for view in (source, delta, prose, log):
        for _ in range(2):
            frame(lambda: view.render('view', (-1, 450)))
    frame(lambda: chat.render('chat', 'streamed response', (-1, 450)))
    for view in (source, delta, log):
        view.raw = True
        frame(lambda: view.render('raw', (-1, 450)))
    assert source.get_text() == original
    assert source.document.revision == 2
    assert len(chat.messages) == 2
    assert delta.document.revision == 1


def test_source_and_diff_keep_revisions_and_navigation():
    source = SourceView('python')
    source.set_text('a = 1\r\n# été\r\n')
    revision = source.document.revision
    source.focus_line(1)
    source.set_text(source.get_text())
    assert source.document.revision == revision and source.state.focus_line == 1
    source.set_text('changed\n')
    assert source.document.revision > revision and source.state.focus_line == -1
    delta = DiffView()
    delta.set_unified('--- old\n+++ new\n@@ -1 +1 @@\n-before\n+after\n', 'cpp')
    revision = delta.document.revision
    delta.state.query = 'after'
    delta.set_unified(delta.raw_text, 'cpp')
    assert delta.document.revision == revision and delta.state.query == 'after'
    assert [row.new_line for row in delta.document.rows if row.kind == 'added'] == [1]


def test_logs_bound_rows_keep_raw_copy_and_filter_state(frame):
    log = LogView()
    log.buffer = diagnostics.LogBuffer(capacity=3, max_bytes=90)
    log.set_text('DEBUG first\nINFO second\nWARNING troisième\nERROR fourth')
    log.state.query, log.state.follow = 'fourth', False
    frame(lambda: log.render('log', (500, 300)))
    assert len(log.state.rows) <= 3
    assert log.state.rows[-1].level == 'error'
    assert log.state.query == 'fourth' and not log.state.follow
    before = log.buffer.snapshot()[0]
    log.set_text(log.get_text())
    assert log.buffer.snapshot()[0] == before
    assert 'DEBUG first' in log.get_text()


def test_command_palette_keyboard_selects_and_cancels_without_executing(frame):
    state = commands.CommandState()
    model = [commands.Command(1, 'One'), commands.Command(2, 'Two')]
    draw = lambda: commands.command_palette('Commands', True, state, model)
    frame(draw); frame(draw)
    io = imgui.get_io()
    io.add_key_event(imgui.Key.down_arrow, True)
    assert frame(draw) == (True, 0)
    io.add_key_event(imgui.Key.down_arrow, False)
    frame(draw)
    io.add_key_event(imgui.Key.enter, True)
    assert frame(draw) == (False, 2)
    io.add_key_event(imgui.Key.enter, False)
    frame(lambda: commands.command_palette('Commands', False, state, model))
    frame(draw); frame(draw)
    io.add_key_event(imgui.Key.escape, True)
    assert frame(draw) == (False, 0)
    io.add_key_event(imgui.Key.escape, False)


def test_python_json_editor_native_undo(frame):
    editor = code.CodeEditor('{"value": 1}', 'json')
    editor.preview = False
    draw = lambda: editor.draw('JSON', (650, 300))
    frame(draw); frame(draw)
    frame(draw, (100, 40), (0, True))
    frame(draw, (100, 40), (0, False))
    io = imgui.get_io()
    io.add_input_characters_utf8('x')
    frame(draw)
    changed = editor.text
    assert changed != '{"value": 1}'
    io.add_key_event(imgui.Key.mod_ctrl, True)
    io.add_key_event(imgui.Key.z, True)
    frame(draw)
    assert editor.text == '{"value": 1}'
    io.add_key_event(imgui.Key.z, False)
    io.add_key_event(imgui.Key.mod_ctrl, False)
    frame(draw)


def test_native_source_editor_retains_single_undo_refactoring(frame):
    from desktop import make_editor
    from imgui_bundle import imgui_color_text_edit as ed
    editor = make_editor('csharp', False)
    original = 'class A { int Value = 1; }'
    editor.set_text(original)
    frame(lambda: editor.render('source', (600, 300)))
    before = editor.get_undo_index()
    editor.replace_section_text(ed.TextEditor.DocPos(0, 0), ed.TextEditor.DocPos(0, len(original)), original.replace('Value', 'Count'))
    assert editor.get_undo_index() == before + 1
    editor.undo()
    assert editor.get_text() == original
    editor.redo()
    assert 'Count' in editor.get_text()


def test_diagnostics_navigate_only_inside_workspace(tmp_path):
    from project_ui import ProjectIDE
    rows = diagnostic_rows([{'file': 'A.cs', 'line': 5, 'column': 2, 'code': 'CS1001',
        'message': 'Expected identifier', 'severity': 'warning'}], 'build')
    assert rows[0].id == diagnostic_rows([{'file': 'A.cs', 'line': 5, 'column': 2, 'code': 'CS1001',
        'message': 'Expected identifier', 'severity': 'warning'}], 'build')[0].id
    assert rows[0].message.startswith('CS1001:')
    calls = []
    host = SimpleNamespace(sessions={'p': {'info': {'directory': str(tmp_path)}}},
                           open_file=lambda *args: calls.append(args))
    ProjectIDE.open_diagnostic(host, 'p', rows[0])
    assert calls == [('p', 'A.cs', 5, 2)]
    ProjectIDE.open_diagnostic(host, 'p', diagnostics.Diagnostic(1, 'outside', str(tmp_path.parent/'outside.cs'), 1, 1))
    assert len(calls) == 1


def test_translated_controls_keep_ids_and_never_translate_documents(frame, monkeypatch):
    preferences = SimpleNamespace(values={'language': 'en'})
    monkeypatch.setattr(ui_common, 'preferences', preferences)
    ui_common.sync_cyui_locale()
    english = cyui.tr_label('Command palette###commands')
    preferences.values['language'] = 'fr'
    ui_common.sync_cyui_locale()
    french = cyui.tr_label('Command palette###commands')
    assert english != french and english.split('###')[1] == french.split('###')[1]
    query = cyui.TextFilter('reconstruction')
    assert query.matches('Unreal reconstruction')
    document = DocumentView()
    document.set_text('# Open file...\n\n`Command palette`')
    frame(lambda: document.render('data', (600, 300)))
    assert document.get_text() == '# Open file...\n\n`Command palette`'
    assert stable_id('a', 'bc') != stable_id('ab', 'c')
    cyui.set_locale('en')


def test_image_pan_zoom_and_fit_use_shared_canvas(frame):
    state = images.ImageState()
    data = images.ImageData(0, 640, 360)
    draw = lambda: images.image_viewport('image', state, data, (600, 400))
    frame(draw); frame(draw)
    initial = state.canvas.view.zoom
    frame(draw, (150, 150))
    imgui.get_io().add_mouse_wheel_event(0, 1)
    frame(draw, (150, 150))
    assert state.canvas.view.zoom > initial
    origin = state.canvas.view.origin
    frame(draw, (150, 150), (2, True))
    frame(draw, (180, 175))
    frame(draw, (180, 175), (2, False))
    assert state.canvas.view.origin != origin
    frame(draw, (180, 175), (0, True))
    frame(draw, (180, 175), (0, False))
    frame(draw, (180, 175), (0, True))
    frame(draw, (180, 175), (0, False))
    assert state.canvas.view.zoom == pytest.approx(initial)


def test_converted_code_and_function_properties_are_wired_to_shared_views(frame):
    from desktop import App
    view = SourceView('cpp')
    view.set_text('int value() { return 42; }')
    host = SimpleNamespace(converted={'verification': 'skipped', 'file': 'owned.cpp'}, converted_editor=view)
    frame(lambda: App.converted_view(host))
    assert view.get_text() == 'int value() { return 42; }'
    host = SimpleNamespace(details={'id': 'function', 'displayName': 'Value', 'name': 'Value', 'size': 16},
        function_properties=inspector.InspectorState(), function_filter=cyui.TextFilter(), comment_text='', functions=[],
        jobs=SimpleNamespace(submit=lambda *a, **kw: pytest.fail('Drawing must not submit a mutation')))
    frame(lambda: App.details_panel(host))
    assert host.details['size'] == 16 and not host.function_properties.active


def test_unavailable_commands_cannot_submit_and_page_ids_do_not_depend_on_language():
    from cyui_shell import command_model, execute_command
    host = SimpleNamespace(project=None, ide=SimpleNamespace(sessions={}),
        jobs=SimpleNamespace(busy=lambda tag: False), force_tab='',
        choose_file=lambda: pytest.fail('A disabled command must not open a dialog'))
    model = command_model(host)
    assert not next(command.enabled for command in model if command.id == stable_id('command', 'build'))
    execute_command(host, stable_id('command', 'build'))
    execute_command(host, stable_id('page', 'log'))
    assert host.force_tab == 'log'
    host.project = {'projectId': 'p'}
    host.ide.sessions['p'] = {'info': {'available': True}}
    host.ide.debug = SimpleNamespace(active=lambda pid: True)
    assert not next(command.enabled for command in command_model(host) if command.id == stable_id('command', 'build'))
    execute_command(host, stable_id('command', 'build'))
