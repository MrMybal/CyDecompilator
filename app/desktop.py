"""CyDecompilator desktop window (Dear ImGui).

The window submits jobs to the same Runtime as the CLI and MCP: opening and analysing a
file, decompiling a unit, installing an engine or asking the AI are all jobs, so the
interface never blocks and every action can be cancelled. Small reads of the project
store (function lists, cached code) go through the same service layer as the handlers.
"""
import json
import re
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from imgui_bundle import hello_imgui, imgui_color_text_edit as ed  # noqa: E402
from imgui_bundle import portable_file_dialogs as pfd  # noqa: E402

from ui_common import configure_generation, imgui, label, preferences, run, tr  # noqa: E402
from tool import create_runtime  # noqa: E402
import cyui

TERMINAL = ('Completed', 'Failed', 'Cancelled')
LANGUAGES = {'c': 'c', 'cpp': 'cpp', 'csharp': 'cs', 'java': 'cpp', 'python': 'python', 'hlsl': 'hlsl',
             'glsl': 'glsl', 'asm': None, 'il': None, 'jvm': None, 'pybytecode': None, 'dxasm': None,
             'spvasm': None, 'xml': None, 'markdown': 'markdown', 'rust': 'cpp', 'go': 'cpp',
             'javascript': 'cpp'}
TARGETS = ['same', 'c', 'cpp', 'csharp', 'java', 'python', 'rust', 'go', 'hlsl', 'glsl', 'javascript']
TARGET_NAMES = ['Same language', 'C', 'C++', 'C#', 'Java', 'Python', 'Rust', 'Go', 'HLSL', 'GLSL', 'JavaScript']
def color(role):
    return cyui.vec(getattr(cyui.palette(), role))


PLAIN = ed.TextEditor.Language()
FONTS = {'mono': None}


# System fonts merged after the interface fonts for scripts they lack (Chinese, Japanese,
# Korean; Cyrillic where the default font misses glyphs). Glyphs are rasterised on demand,
# so the merges cost nothing until a character is drawn. The selected language goes first,
# which picks the right regional shapes of shared Han characters.
FALLBACK_FONTS = {
    'zh': ['C:/Windows/Fonts/msyh.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
           '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc', '/System/Library/Fonts/PingFang.ttc'],
    'ja': ['C:/Windows/Fonts/YuGothM.ttc', 'C:/Windows/Fonts/meiryo.ttc',
           '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc'],
    'ko': ['C:/Windows/Fonts/malgun.ttf', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
           '/System/Library/Fonts/AppleSDGothicNeo.ttc'],
    'latin': ['C:/Windows/Fonts/segoeui.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
}


def merge_fallback_fonts(size, destination=None):
    language = preferences.values.get('language', 'en')
    order = [language] if language in FALLBACK_FONTS else []
    order += [code for code in ('latin', 'zh', 'ja', 'ko') if code not in order]
    for code in order:
        path = next((p for p in FALLBACK_FONTS[code] if Path(p).is_file()), None)
        if path is None:
            continue
        try:
            config = imgui.ImFontConfig()
            config.merge_mode = True
            if destination is not None: config.dst_font = destination
            imgui.get_io().fonts.add_font_from_file_ttf(str(path), size, config)
        except Exception:
            pass


APP_ASSETS = Path(__file__).resolve().parent / 'assets'


def prepare_assets():
    """One assets folder for hello_imgui: imgui_bundle's fonts plus ours (logo; app_settings/
    icon.png is the window and taskbar icon). Rebuilt in runtime/ui-assets when either changes."""
    import shutil
    import imgui_bundle
    bundled = Path(imgui_bundle.__file__).resolve().parent / 'assets'
    target = ROOT / 'runtime' / 'ui-assets'
    stamp = '%s|%s' % (getattr(imgui_bundle, '__version__', ''),
                       max((f.stat().st_mtime_ns for f in APP_ASSETS.rglob('*') if f.is_file()), default=0))
    try:
        if (target / '.stamp').read_text(encoding='utf-8') == stamp:
            return target
    except OSError:
        pass
    try:
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(bundled / 'fonts', target / 'fonts')
        shutil.copytree(APP_ASSETS, target, dirs_exist_ok=True)
        (target / '.stamp').write_text(stamp, encoding='utf-8')
        return target
    except OSError:
        return bundled      # read-only installation: bundled fonts, default window icon


def load_fonts():
    from ui_common import apply_style
    apply_style()
    cyui.load_fonts(fallback_folder=str(prepare_assets() / 'fonts'))
    for font in (cyui.ui_font(), cyui.bold_font(), cyui.mono_font()):
        merge_fallback_fonts(cyui.metrics().font_size, font)
    FONTS['mono'] = cyui.mono_font()


def render_editor(editor, title, size):
    """Code views use a monospace font; prose stays in the interface font."""
    if FONTS['mono'] is not None:
        imgui.push_font(FONTS['mono'], imgui.get_style().font_size_base)
    try:
        editor.render(title, size)
    finally:
        if FONTS['mono'] is not None:
            imgui.pop_font()


def make_editor(language=None, read_only=True):
    editor = ed.TextEditor()
    editor.set_read_only_enabled(read_only)
    editor.set_show_line_numbers_enabled(True)
    editor.set_tab_size(4)
    editor.set_show_whitespaces_enabled(False)
    set_language(editor, language)
    return editor


def set_language(editor, language):
    name = LANGUAGES.get(language or '', None)
    factory = getattr(ed.TextEditor.Language, name, None) if name else None
    editor.set_language(factory() if factory is not None else PLAIN)


def palette(editor):
    if cyui.is_light():
        editor.set_palette(ed.TextEditor.get_light_palette())
    else:
        editor.set_palette(ed.TextEditor.get_dark_palette())


class Jobs:
    """Track submitted jobs, deliver results to callbacks and collect AI text deltas."""

    def __init__(self, runtime, actor, session):
        self.runtime, self.actor, self.session = runtime, actor, session
        self.jobs = {}
        self.cursor = 0
        self.deltas = {}
        self.tools = {}
        self.message = ''

    def submit(self, operation, parameters, *, tag, done=None, failed=None, streamed=None, timeout=None, priority='Interactive'):
        try:
            job = self.runtime.submit(self.actor, self.session, operation, parameters, priority=priority,
                                      execution_timeout=timeout)
        except Exception as exc:
            self.message = '%s: %s' % (operation, exc)
            if failed:
                failed(str(exc))
            return None
        self.jobs[job['jobId']] = {'job': job, 'tag': tag, 'done': done, 'failed': failed,
                                 'streamed': streamed, 'output': '', 'operation': operation}
        self.deltas[job['jobId']] = ''
        return job['jobId']

    def poll(self):
        changed_output = set()
        try:
            events = self.runtime.events(self.actor, self.cursor)
            self.cursor = events['cursor']
            for event in events['events']:
                job_id = event.get('jobId')
                kind = event.get('type') or event.get('eventType')
                data = event.get('data') or event.get('payload') or {}
                if job_id in self.deltas and kind == 'AiDelta':
                    self.deltas[job_id] += data.get('text', '')
                elif job_id in self.deltas and kind == 'AiTool':
                    self.tools.setdefault(job_id, []).append(data)
                elif job_id in self.jobs and kind == 'ProcessOutput':
                    record = self.jobs[job_id]
                    record['output'] = (record['output'] + data.get('text', ''))[-200000:]
                    changed_output.add(job_id)
        except Exception:
            pass
        for job_id in changed_output:
            record = self.jobs[job_id]
            if record['streamed']:
                try:
                    record['streamed'](record['output'])
                except Exception as exc:
                    self.message = 'UI callback failed: %s' % exc
        for job_id in list(self.jobs):
            record = self.jobs[job_id]
            try:
                record['job'] = self.runtime.get_job(self.actor, job_id)
            except Exception:
                continue
            state = record['job']['state']
            if state in TERMINAL:
                self.jobs.pop(job_id)
                if state == 'Completed':
                    if record['done']:
                        try:
                            record['done'](record['job'].get('outputs') or {})
                        except Exception as exc:
                            self.message = 'UI callback failed: %s' % exc
                    notices = {'workspace_save': 'Save all', 'workspace_execute': 'Build',
                               'patch_apply': 'Edit function / patch',
                               'reconstruction_run': 'Reconstruction', 'ai_agent': 'Autonomous workflow'}
                    if record['operation'] in notices:
                        output = record['job'].get('outputs') or {}
                        status = output.get('status', '')
                        tone = 'error' if status in ('failed', 'compilation-failed', 'tests-failed') else 'success'
                        if status in ('blocked', 'compiled-unverified', 'budget-exhausted', 'behavior-differs', 'cancelled', 'no-tests'):
                            tone = 'warning'
                        outcome = 'Failed' if tone == 'error' else ('Completed' if tone == 'success' else 'Status')
                        from reconstruction_ui import STATUS
                        outcome = STATUS.get(status, {'budget-exhausted': 'Resume autonomous task',
                                                      'no-tests': 'no-tests'}.get(status, outcome))
                        action = notices[record['operation']]
                        if record['operation'] == 'workspace_execute':
                            action = {'build': 'Build', 'rebuild': 'Rebuild', 'test': 'Test', 'run': 'Run'}.get(output.get('action'), action)
                        cyui.notify(tr(action) + ': ' + tr(outcome), tone)
                else:
                    error = record['job'].get('error') or {}
                    text = error.get('message') if isinstance(error, dict) else str(error)
                    text = text or state
                    if state == 'Cancelled':
                        text = tr('Cancelled')
                    self.message = '%s: %s' % (tr(record['operation']), tr(text))
                    if record['failed']:
                        record['failed'](text)

    def active(self, tag):
        for job_id, record in self.jobs.items():
            if record['tag'] == tag:
                return job_id, record['job']
        return None, None

    def busy(self, tag):
        return self.active(tag)[0] is not None

    def cancel(self, tag):
        job_id, _ = self.active(tag)
        if job_id:
            try:
                self.runtime.cancel(self.actor, job_id)
            except Exception as exc:
                self.message = str(exc)

    def progress_widget(self, tag, width=-1.0):
        job_id, job = self.active(tag)
        if not job_id:
            return False
        progress = job.get('progress') or {}
        percent = float(progress.get('percent', 0) or 0)
        step = progress.get('currentStep') or job['state']
        room = max(cyui.dp(40), imgui.get_content_region_avail().x-cyui.button_width(tr('Cancel'))-imgui.get_style().item_spacing.x)
        cyui.progress_bar(percent / 100.0, (min(width, room) if width > 0 else room, 0), '%s  %d%%' % (tr(step), percent))
        imgui.same_line()
        if imgui.small_button(label('Cancel##' + tag)):
            self.cancel(tag)
        return True


class App:
    def __init__(self, runtime, actor, session):
        self.runtime = runtime
        self.jobs = Jobs(runtime, actor, session)
        from project_ui import ProjectIDE
        self.ide = ProjectIDE(self, make_editor, set_language, palette, render_editor)
        from investigation_ui import InvestigationUI
        self.investigation = InvestigationUI(self, make_editor, set_language, palette, render_editor)
        from porting_ui import PortingUI
        self.porting = PortingUI(self)
        from unreal_ui import UnrealUI
        self.unreal = UnrealUI(self)
        self.projects = []
        self.project = None           # project_info output
        self.engine = ''
        self.functions = []
        self.filtered = []
        self.query = ''
        self.selected = None          # function record (public)
        self.details = None           # function_info output
        self.view = 'decompiled'
        self.code_editor = make_editor()
        self.ai_editor = make_editor('markdown')
        self.ai_editor.set_show_line_numbers_enabled(False)
        self.converted_editor = make_editor('c')
        self.code_meta = {}
        self.converted = None
        self.history = []
        self.future = []
        self.path_input = ''
        self.dialog = None
        self.folder_dialog = None
        self.folder_target = None
        self.engine_choice = 0
        self.strings = []
        self.string_query = ''
        self.string_matched = 0
        self.search_query = ''
        self.search_hits = []
        self.rename_old = ''
        self.rename_new = ''
        self.rename_local = False
        self.comment_text = ''
        self.notes_text = ''
        self.ask_text = ''
        self.agent_workflow = 1
        self.ai_mode = 0
        self.agent_run = None
        self.conversation_id = ''
        self.transcript = ''
        self.ai_title = ''
        self.target_index = 0
        self.verify = True
        self.apply_names = True
        self.convert_instructions = ''
        self.components = []
        self.engines = []
        self.override_paths = {}
        self.ai_status = None
        self.ai_draft = None
        self.api_key = ''
        self.models = {}
        self.model_future = None
        self.status_message = ''
        self.frames = 0
        self.first_poll = True
        self.analysis_options = {'maxDecompile': 2000, 'functionTimeout': 60}
        self.batch_limit = 20
        self.export_folder = ''
        self.update_state = None
        self.extraction = None
        self.extract_filter = ''
        self.symbol_draft = None
        self.update_repository = None
        self.update_report = None
        self.force_tab = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-test-tab=')), '')
        self.refresh_projects()
        self.refresh_components(False)
        self.refresh_ai(True)
        from cydec.paths import read_json
        self.ui_state_path = ROOT / 'data/settings/workspace.json'
        if any(a.startswith('--ui-test-') for a in sys.argv) or '--smoke-test' in sys.argv:
            self.ui_state_path = ROOT / 'data/reports/ui-test-workspace.json'
        state = read_json(self.ui_state_path, {})
        last = state.get('lastProject') if isinstance(state, dict) else None
        if last and any(p['projectId'] == last for p in self.projects):
            self.load_project(last)

    # ------------------------------------------------------------------ data loading

    def refresh_projects(self):
        self.jobs.submit('list_projects', {}, tag='projects',
                         done=lambda out: setattr(self, 'projects', out.get('projects', [])))

    def refresh_components(self, refresh=True):
        self.jobs.submit('list_components', {'refresh': refresh}, tag='components',
                         done=lambda out: setattr(self, 'components', out.get('components', [])))
        self.jobs.submit('list_engines', {}, tag='engines',
                         done=lambda out: setattr(self, 'engines', out.get('engines', [])))

    def refresh_ai(self, probe=True):
        def done(out):
            self.ai_status = out
            if self.ai_draft is None:
                self.ai_draft = json.loads(json.dumps(out['settings']))
        self.jobs.submit('ai_status', {'refresh': probe}, tag='ai_status', done=done, timeout=120)

    def open_path(self, path, engine=''):
        path = path.strip().strip('"')
        if not path:
            return
        self.path_input = path
        options = {k: v for k, v in self.analysis_options.items() if v not in ('', None)}

        def done(out):
            self.refresh_projects()
            self.load_project(out['projectId'])
        self.jobs.submit('open_file', {'path': path, 'engine': engine, 'options': options}, tag='open',
                         done=done, priority='Interactive')

    def analyze(self, engine, force=True):
        if not self.project:
            return
        options = {k: v for k, v in self.analysis_options.items() if v not in ('', None)}
        project_id = self.project['projectId']
        self.jobs.submit('analyze', {'projectId': project_id, 'engine': engine, 'force': force, 'options': options},
                         tag='open', done=lambda out: (self.load_project(project_id, out.get('engine', '')),
                                                       self.refresh_projects()))

    def load_project(self, project_id, engine=''):
        def done(out):
            self.project = out
            self.engine = out.get('engine') or out.get('defaultEngine') or ''
            self.notes_text = out.get('annotations', {}).get('notes', '')
            self.selected = None
            self.details = None
            self.code_editor.set_text('')
            self.history, self.future = [], []
            self.load_functions()
            self.strings = []
            self.search_hits = []
            self.load_strings()
            from cydec.paths import write_json
            try:
                write_json(self.ui_state_path, {'lastProject': project_id})
            except OSError:
                pass
        self.jobs.submit('project_info', {'projectId': project_id, 'engine': engine}, tag='project', done=done)

    def load_functions(self, keep=None):
        if not self.project or not self.engine:
            self.functions, self.filtered = [], []
            return

        def done(out):
            self.functions = out.get('functions', [])
            self.apply_filter()
            if keep:
                match = next((f for f in self.functions if f['id'] == keep), None)
                if match:
                    self.selected = match
            elif self.functions and self.selected is None:
                self.open_function(self.preferred_start(), push=False)
        self.jobs.submit('list_functions', {'projectId': self.project['projectId'], 'engine': self.engine,
                                            'limit': 200000}, tag='functions', done=done)

    def preferred_start(self):
        for name in ('main', 'wmain', 'WinMain', 'wWinMain', 'entry', '_start', 'DllMain', '<module>'):
            for function in self.functions:
                if function['displayName'] == name or function['name'] == name:
                    return function
        return self.functions[0]

    def load_strings(self):
        if not self.project or not self.engine:
            return

        def done(out):
            self.strings = out.get('strings', [])
            self.string_matched = out.get('matched', 0)
        self.jobs.submit('strings', {'projectId': self.project['projectId'], 'engine': self.engine,
                                     'query': self.string_query, 'limit': 5000}, tag='strings', done=done)

    def apply_filter(self):
        query = self.query.lower().strip()
        if not query:
            self.filtered = self.functions
        else:
            self.filtered = [f for f in self.functions
                             if query in f['displayName'].lower() or query in f.get('address', '').lower()
                             or query in f['id'].lower()]

    def open_function(self, function, push=True, view=None):
        if function is None or not self.project:
            return
        if push and self.selected is not None and self.selected['id'] != function['id']:
            self.history.append(self.selected)
            self.future = []
        self.selected = function
        if view:
            self.view = view
        self.comment_text = ''
        self.request_code()
        project_id = self.project['projectId']

        def done(out):
            self.details = out.get('function')
            if self.details:
                self.comment_text = self.details.get('comment', '')
        self.jobs.submit('function_info', {'projectId': project_id, 'function': function['id'],
                                           'engine': self.engine}, tag='details', done=done)

    def request_code(self, refresh=False):
        if not self.selected:
            return
        self.jobs.cancel('code')
        target = self.selected['id']

        def done(out):
            if self.selected and self.selected['id'] == target:
                self.code_meta = out
                set_language(self.code_editor, out.get('language'))
                palette(self.code_editor)
                note = ('// ' + out['note'] + '\n') if out.get('note') else ''
                self.code_editor.set_text(note + out.get('code', ''))

        def failed(message):
            if self.selected and self.selected['id'] == target:
                self.code_editor.set_text('/* %s */\n' % message)
        self.code_editor.set_text('/* %s */' % tr('Decompiling...'))
        self.jobs.submit('decompile', {'projectId': self.project['projectId'], 'function': target,
                                       'engine': self.engine, 'view': self.view, 'refresh': refresh},
                         tag='code', done=done, failed=failed, timeout=900)

    def navigate(self, word):
        """Open the unit named `word` (double click / context menu in the code)."""
        word = word.strip()
        if not word or not self.functions:
            return False
        for function in self.functions:
            if function['displayName'] == word or function['name'] == word:
                self.open_function(function)
                return True
        if word.startswith(('FUN_', 'sub_', 'LAB_', 'thunk_FUN_')):
            address = word.split('_')[-1].lower()
            for function in self.functions:
                if function.get('address', '').lower().lstrip('0x').lstrip('0') == address.lstrip('0'):
                    self.open_function(function)
                    return True
        return False

    def after_annotation(self):
        keep = self.selected['id'] if self.selected else None
        self.load_functions(keep)
        self.request_code()
        if self.selected:
            self.open_function(self.selected, push=False)

    # ------------------------------------------------------------------ frame

    def draw(self):
        self.frames += 1
        self.jobs.poll()
        self.ide.debug.tick()
        self.poll_dialogs()
        from cyui_shell import draw, utility_page
        panels = {'workspace': self.workspace, 'project': self.ide.draw, 'investigation': self.investigation.draw,
                  'assistant': self.assistant_page, 'engines': self.engines_tab, 'ai': self.ai_tab,
                  'porting':self.porting.draw,'unreal':self.unreal.draw}
        if imgui.is_key_chord_pressed(imgui.Key.mod_ctrl | imgui.Key.o): self.choose_file()
        draw(self, lambda page: panels[page]() if page in panels else utility_page(page))

    def choose_file(self):
        self.dialog = pfd.open_file(tr('Open a file to decompile'), str(Path.home()), ['All files', '*'])

    def poll_dialogs(self):
        if self.dialog is not None and self.dialog.ready():
            files = self.dialog.result()
            self.dialog = None
            if files:
                self.open_path(files[0])
        if self.folder_dialog is not None and self.folder_dialog.ready():
            folder = self.folder_dialog.result()
            self.folder_dialog = None
            if folder and self.folder_target:
                kind, key = self.folder_target
                if kind == 'override':
                    self.override_paths[key] = folder
                elif kind == 'export':
                    self.export_folder = folder

    # ------------------------------------------------------------------ workspace

    def logo(self, size):
        """The application logo (app/assets/logo-*.png), drawn at `size` pixels."""
        try:
            name = 'logo-512.png' if size > 128 else 'logo-128.png'
            hello_imgui.image_from_asset(str(APP_ASSETS / name), imgui.ImVec2(size, size))
            return True
        except Exception:
            return False

    def toolbar(self):
        if cyui.begin_toolbar('###file-toolbar'):
            if cyui.icon_button(cyui.icon.open_file, tr('Open file...') + ' (Ctrl+O)'):
                self.choose_file()
            imgui.same_line()
            available = imgui.get_content_region_avail().x
            recent_width = max(cyui.dp(150), available * .26)
            imgui.set_next_item_width(max(cyui.dp(90), available-recent_width-imgui.get_style().item_spacing.x))
            changed, self.path_input = imgui.input_text_with_hint('##path', tr('or paste a file path and press Enter'),
                self.path_input, imgui.InputTextFlags_.enter_returns_true)
            if changed: self.open_path(self.path_input)
            imgui.same_line()
            names = [tr('Recent projects')] + ['%s  [%s]' % (p['name'], p['format']['formatName']) for p in self.projects]
            imgui.set_next_item_width(recent_width)
            changed, index = imgui.combo('##recent', 0, names)
            if changed and index > 0: self.load_project(self.projects[index - 1]['projectId'])
        cyui.end_toolbar()
        if self.project:
            cyui.begin_toolbar('###analysis-toolbar')
            with cyui.scoped_disabled(not self.history):
                if cyui.icon_button(cyui.icon.back, tr('Back')) and self.history:
                    self.future.append(self.selected)
                    self.open_function(self.history.pop(), push=False)
            imgui.same_line()
            with cyui.scoped_disabled(not self.future):
                if cyui.icon_button(cyui.icon.forward, tr('Forward')) and self.future:
                    self.history.append(self.selected)
                    self.open_function(self.future.pop(), push=False)
            cyui.toolbar_separator()
            engines = self.project['format'].get('engines', [])
            analysed = list(self.project.get('analyses', {}).keys())
            choices = list(dict.fromkeys(engines + analysed))
            if choices:
                current = choices.index(self.engine) if self.engine in choices else 0
                labels = [e + ('' if e in analysed else tr(' (not analyzed)')) for e in choices]
                cyui.text_dim(tr('Engine'))
                imgui.same_line()
                imgui.set_next_item_width(cyui.dp(210))
                changed, current = imgui.combo('###Engine', current, labels)
                if changed:
                    chosen = choices[current]
                    if chosen in analysed:
                        self.engine = chosen
                        self.load_project(self.project['projectId'], chosen)
                    else: self.analyze(chosen, force=False)
                imgui.same_line()
                if cyui.icon_button(cyui.icon.refresh, tr('Re-analyze')):
                    self.analyze(self.engine or choices[0], force=True)
            cyui.end_toolbar()
        self.jobs.progress_widget('open')
        message = self.jobs.message or self.status_message
        if message:
            cyui.callout('warning' if self.jobs.message else 'info', message)
            if imgui.small_button(label('Dismiss')):
                self.jobs.message = ''
                self.status_message = ''

    def workspace(self):
        self.toolbar()
        if not self.project:
            cyui.space(24)
            cyui.panel_header(tr('Start an investigation'), tr('Analyze an application, rebuild its project, then validate your changes.'))
            cyui.space(12)
            if cyui.begin_card('###welcome', tr('Open an application')):
                imgui.text_wrapped(tr('Executables, libraries, .NET, Java, Android, Python and shaders.'))
                cyui.space(8)
                if cyui.primary_button(label('Open file...')): self.choose_file()
                imgui.same_line()
                if cyui.button(label('Choose application folder')): self.force_tab = 'investigation'
            cyui.end_card()
            cyui.space(12)
            if cyui.begin_card('###recent-projects', tr('Recent projects')):
                if not self.projects: cyui.text_faint(tr('Your recent projects will appear here.'))
                for project in self.projects[:8]:
                    if imgui.selectable(project['name'] + '###recent-' + project['projectId'], False)[0]:
                        self.load_project(project['projectId'])
                    cyui.text_dim(project['format']['formatName'])
            cyui.end_card()
            if self.jobs.busy('open') or self.jobs.busy('project'):
                imgui.text(tr('Loading...'))
            return
        flags = imgui.TableFlags_.resizable | imgui.TableFlags_.borders_inner_v
        avail = imgui.get_content_region_avail()
        inspector = avail.x >= cyui.dp(1100)
        self.compact_workspace = not inspector
        if imgui.begin_table('###layout', 3 if inspector else 2, flags, imgui.ImVec2(avail.x, avail.y)):
            imgui.table_setup_column('left', imgui.TableColumnFlags_.width_stretch, 0.24)
            imgui.table_setup_column('center', imgui.TableColumnFlags_.width_stretch, 0.48)
            if inspector: imgui.table_setup_column('right', imgui.TableColumnFlags_.width_stretch, 0.28)
            imgui.table_next_row()
            imgui.table_next_column()
            self.left_panel()
            imgui.table_next_column()
            self.center_panel()
            if inspector:
                imgui.table_next_column()
                self.right_panel()
            imgui.end_table()

    def submit_c_module(self, project, functions, folder):
        stem = Path(project['name']).stem + ('_' + self.selected['name'] if functions and self.selected else '')
        destination = str(Path(folder) / (re.sub(r'[^A-Za-z0-9_.-]', '_', stem) + '.c'))
        self.jobs.submit('c_module', {'projectId': project['projectId'], 'functions': functions,
                                      'includeCallees': True, 'destination': destination},
                         tag='cmodule', timeout=None,
                         done=lambda out: setattr(self, 'status_message',
                                                  tr('C module written: ') + out.get('path', '')))

    def left_panel(self):
        project = self.project
        cyui.heading(project['name'], 3)
        cyui.text_dim('%s%s' % (project['format']['formatName'],
                                            (' | ' + str(project.get('arch'))) if project.get('arch') else ''))
        if project.get('message'):
            imgui.text_wrapped(project['message'])
        packers = (project.get('pe') or {}).get('packers', [])
        extractable = [p for p in packers if p.get('extractable')]
        for packer in extractable:
            imgui.text_colored(color('warning'), tr('Contains: ') + packer['name'])
            imgui.same_line()
            imgui.begin_disabled(self.jobs.busy('extract'))
            if imgui.small_button(label('Extract##') + packer['id']):
                self.extract(packer['id'])
            imgui.end_disabled()
        self.jobs.progress_widget('extract')
        if imgui.begin_tab_bar('###left'):
            opened, _ = imgui.begin_tab_item(label('Functions') + ' (%d)###functions' % len(self.functions))
            if opened:
                self.function_list()
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Strings'))
            if opened:
                self.string_list()
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Search'))
            if opened:
                self.search_panel()
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Program'))
            if opened:
                self.program_panel()
                imgui.end_tab_item()
            imgui.end_tab_bar()

    def function_list(self):
        imgui.set_next_item_width(-1)
        changed, self.query = cyui.search_field('##filter', self.query, tr('Filter by name or address'), width=-1)
        if changed:
            self.apply_filter()
        if self.jobs.busy('functions'):
            imgui.text(tr('Loading...'))
        imgui.begin_child('###function-list', imgui.ImVec2(0, 0))
        clipper = imgui.ListClipper()
        clipper.begin(len(self.filtered))
        while clipper.step():
            for index in range(clipper.display_start, clipper.display_end):
                function = self.filtered[index]
                selected = self.selected is not None and self.selected['id'] == function['id']
                text = function['displayName']
                if function.get('address'):
                    text = '%s  %s' % (function['address'], text)
                if function['displayName'] != function['name']:
                    text += '  *'
                clicked, _ = imgui.selectable('%s###f%d' % (text, index), selected)
                if clicked:
                    self.open_function(function)
                if imgui.is_item_hovered() and function.get('signature'):
                    imgui.set_tooltip(function['signature'])
        clipper.end()
        imgui.end_child()

    def string_list(self):
        imgui.set_next_item_width(-1)
        changed, self.string_query = imgui.input_text_with_hint('##strings', tr('Filter strings (Enter)'),
                                                                self.string_query,
                                                                imgui.InputTextFlags_.enter_returns_true)
        if changed:
            self.load_strings()
        imgui.text_colored(color('textDim'), tr('Matches: ') + str(self.string_matched))
        imgui.begin_child('###string-list', imgui.ImVec2(0, 0))
        clipper = imgui.ListClipper()
        clipper.begin(len(self.strings))
        while clipper.step():
            for index in range(clipper.display_start, clipper.display_end):
                item = self.strings[index]
                text = item.get('text', '').replace('\n', '\\n')[:160]
                clicked, _ = imgui.selectable('%s  %s###s%d' % (item.get('address', ''), text, index), False)
                if clicked:
                    self.search_query = item.get('text', '')[:80]
                    self.run_search()
                if imgui.begin_popup_context_item('###sctx%d' % index):
                    if imgui.menu_item(label('Copy'), '', False)[0]:
                        imgui.set_clipboard_text(item.get('text', ''))
                    if imgui.menu_item(label('Find uses in code'), '', False)[0]:
                        self.search_query = item.get('text', '')[:80]
                        self.run_search()
                    imgui.end_popup()
        clipper.end()
        imgui.end_child()

    def run_search(self):
        if not self.search_query.strip() or not self.project:
            return
        self.jobs.submit('search', {'projectId': self.project['projectId'], 'query': self.search_query,
                                    'engine': self.engine}, tag='search',
                         done=lambda out: setattr(self, 'search_hits', out.get('hits', [])))

    def search_panel(self):
        imgui.set_next_item_width(-1)
        changed, self.search_query = imgui.input_text_with_hint('##search', tr('Search names, code and strings (Enter)'),
                                                                self.search_query,
                                                                imgui.InputTextFlags_.enter_returns_true)
        if changed:
            self.run_search()
        imgui.text_colored(color('textDim'), tr('Searches decompiled code that is already cached.'))
        imgui.begin_child('###search-list', imgui.ImVec2(0, 0))
        for index, hit in enumerate(self.search_hits):
            if hit['type'] == 'string':
                text = '[str] %s  %s' % (hit.get('address', ''), hit.get('text', ''))
            elif hit['type'] == 'code':
                text = '[code] %s: %s' % (hit.get('name', hit['id']), hit.get('line', ''))
            else:
                text = '[fn] %s' % hit.get('name', hit['id'])
            clicked, _ = imgui.selectable('%s###h%d' % (text[:200], index), False)
            if clicked and hit['type'] in ('code', 'function'):
                match = next((f for f in self.functions if f['id'] == hit['id']), None)
                self.open_function(match)
        imgui.end_child()

    def program_panel(self):
        project = self.project
        imgui.begin_child('###program', imgui.ImVec2(0, 0))
        rows = [('File', project['name']), ('SHA256', project['sha256']), ('Size', '%d bytes' % project['size']),
                ('Format', project['format']['formatName']), ('Engine', self.engine)]
        for key in ('arch', 'imageBase', 'entryPoint', 'functionCount', 'importCount', 'stringCount'):
            if project.get(key) not in (None, ''):
                rows.append((key, str(project[key])))
        for key, value in rows:
            imgui.text_colored(color('textDim'), tr(key) + ':')
            imgui.same_line()
            imgui.text_wrapped(str(value))
        if project.get('pe'):
            self.pe_section(project)
        if self.extraction is not None and self.extraction.get('projectId') == project['projectId']:
            self.extraction_section()
        if project.get('shader'):
            if imgui.collapsing_header(label('Shader reflection')):
                imgui.input_text_multiline('##shader', json.dumps(project['shader'], indent=1, ensure_ascii=False),
                                           imgui.ImVec2(-1, cyui.dp(220)), imgui.InputTextFlags_.read_only)
        if project.get('sections') and imgui.collapsing_header(label('Sections')):
            for section in project['sections']:
                imgui.text('%-10s %s  %d%s' % (section.get('name', ''), section.get('address', ''), section.get('size', 0),
                                               '  exec' if section.get('executable') else ''))
        if project.get('imports') and imgui.collapsing_header(label('Imports') + ' (%d)###imports' % project.get('importCount', 0)):
            for item in project['imports'][:2000]:
                imgui.text('%s!%s' % (item.get('library', ''), item.get('name', '')))
        if project.get('exports') and imgui.collapsing_header(label('Exports')):
            for item in project['exports'][:2000]:
                clicked, _ = imgui.selectable('%s  %s###x%s' % (item.get('address', ''), item.get('name', ''), item.get('address', '')), False)
                if clicked:
                    self.navigate(item.get('name', ''))
        if imgui.collapsing_header(label('Project notes')):
            _, self.notes_text = imgui.input_text_multiline('##notes', self.notes_text, imgui.ImVec2(-1, cyui.dp(160)))
            if imgui.button(label('Save notes')):
                self.jobs.submit('set_notes', {'projectId': project['projectId'], 'text': self.notes_text}, tag='notes')
        imgui.separator()
        imgui.text(tr('Export sources'))
        imgui.set_next_item_width(-120)
        _, self.export_folder = imgui.input_text_with_hint('##export', tr('Destination folder'), self.export_folder)
        imgui.same_line()
        if imgui.button(label('Browse##export')):
            self.folder_dialog = pfd.select_folder(tr('Export destination'), str(Path.home()))
            self.folder_target = ('export', None)
        if imgui.button(label('Export')) and self.export_folder.strip():
            parameters = {'projectId': project['projectId'], 'engine': self.engine,
                          'destination': self.export_folder.strip(), 'decompileMissing': True}
            if project['format']['format'] == 'pe-dotnet' and self.engine == 'ilspy':
                parameters['csharpProject'] = True
            self.jobs.submit('export_sources', parameters, tag='export', timeout=None,
                             done=lambda out: setattr(self, 'status_message',
                                                      tr('Exported %d files to ') % out.get('written', 0) + out.get('directory', '')))
        self.jobs.progress_widget('export')
        if project['format'].get('arch') in ('x86', 'x86_64', 'arm64') and \
                project['format']['format'] in ('pe', 'pe-dotnet', 'elf', 'raw'):
            # Built-in C decompiler: one recompilable C file into the destination folder.
            imgui.text_wrapped(tr('Recompilable C (built-in decompiler) into the destination folder:'))
            folder = self.export_folder.strip()
            if imgui.button(label('Exported functions')) and folder:
                self.submit_c_module(project, [], folder)
            if self.selected:
                imgui.same_line()
                if imgui.button(label('This function and its callees')) and folder:
                    self.submit_c_module(project, [self.selected['id']], folder)
            self.jobs.progress_widget('cmodule')
        imgui.separator()
        if imgui.button(label('Delete this project')):
            imgui.open_popup('###confirm-delete')
        opened, _ = imgui.begin_popup_modal(label('Delete project?') + '###confirm-delete', None,
                                            imgui.WindowFlags_.always_auto_resize)
        if opened:
            imgui.text(tr('The analysis, caches and AI results are deleted. The original file is not touched.'))
            if imgui.button(label('Delete')):
                project_id = project['projectId']
                self.jobs.submit('delete_project', {'projectId': project_id}, tag='delete',
                                 done=lambda out: (setattr(self, 'project', None), self.refresh_projects()))
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button(label('Keep')):
                imgui.close_current_popup()
            imgui.end_popup()
        imgui.end_child()

    def extract(self, kind):
        project_id = self.project['projectId']

        def done(out):
            self.extraction = out
            self.status_message = tr('Extracted %d files to ') % len(out.get('files', [])) + out.get('directory', '')
            self.load_project(project_id, self.engine)
        self.jobs.submit('extract_embedded', {'projectId': project_id, 'kind': kind}, tag='extract', done=done,
                         timeout=None)

    def pe_section(self, project):
        pe = project['pe']
        if imgui.collapsing_header(label('Executable details'), imgui.TreeNodeFlags_.default_open):
            for line in project.get('peSummary', []):
                imgui.text_wrapped(line)
            pdb_info = pe.get('pdb')
            if pdb_info:
                imgui.begin_disabled(self.jobs.busy('symbols'))
                if imgui.small_button(label('Load debug symbols (PDB)')):
                    project_id = project['projectId']
                    self.jobs.submit('load_symbols', {'projectId': project_id}, tag='symbols', timeout=300,
                                     done=lambda out: (setattr(self, 'status_message', out.get('status', '') + '. ' +
                                                               tr('Re-analyze to apply the names.'))))
                imgui.end_disabled()
                self.jobs.progress_widget('symbols')
        if pe.get('version') and imgui.collapsing_header(label('Version information')):
            for key, value in pe['version'].items():
                imgui.text_colored(color('textDim'), key + ':')
                imgui.same_line()
                imgui.text_wrapped(value)
        if pe.get('exports') and imgui.collapsing_header(label('Exports') + ' (%d)###pe-exports' % len(pe['exports'])):
            if imgui.begin_table('###exports', 3, imgui.TableFlags_.borders_inner_v | imgui.TableFlags_.row_bg |
                                 imgui.TableFlags_.scroll_y, imgui.ImVec2(0, cyui.dp(260))):
                imgui.table_setup_column(tr('Ordinal'), imgui.TableColumnFlags_.width_fixed, 60)
                imgui.table_setup_column(tr('Name'))
                imgui.table_setup_column(tr('Address / forwarded to'))
                imgui.table_headers_row()
                clipper = imgui.ListClipper()
                clipper.begin(len(pe['exports']))
                while clipper.step():
                    for index in range(clipper.display_start, clipper.display_end):
                        item = pe['exports'][index]
                        imgui.table_next_row()
                        imgui.table_next_column()
                        imgui.text(str(item['ordinal']))
                        imgui.table_next_column()
                        clicked, _ = imgui.selectable('%s###ex%d' % (item['name'] or '(ordinal only)', index), False)
                        if clicked and not item['forwarder']:
                            self.navigate(item['name'])
                        imgui.table_next_column()
                        imgui.text_colored(color('warning') if item['forwarder'] else color('textDim'), item['forwarder'] or item['address'])
                clipper.end()
                imgui.end_table()
        if pe.get('sections') and imgui.collapsing_header(label('Sections and entropy')):
            for section in pe['sections']:
                color = color('error') if 'X' in section['flags'] and section['entropy'] > 7.2 else color('textDim')
                imgui.text_colored(color, '%-9s %s  %-3s  virt %8d  raw %8d  entropy %.2f' % (
                    section['name'], section['address'], section['flags'], section['virtualSize'], section['rawSize'],
                    section['entropy']))
        if pe.get('rich') and imgui.collapsing_header(label('Build tools (Rich header)')):
            for item in pe['rich']:
                imgui.text('%-28s build %5d  x%d' % (item['product'], item['build'], item['count']))
        if pe.get('manifest') and imgui.collapsing_header(label('Manifest')):
            imgui.input_text_multiline('##manifest', pe['manifest'], imgui.ImVec2(-1, cyui.dp(200)), imgui.InputTextFlags_.read_only)
        for kind in project.get('extracted', []):
            if self.extraction is None or self.extraction.get('kind') != kind:
                if imgui.small_button(label('Show extracted files') + ' (%s)###show-%s' % (kind, kind)):
                    self.jobs.submit('extracted_files', {'projectId': project['projectId'], 'kind': kind}, tag='extract',
                                     done=lambda out: setattr(self, 'extraction', out))

    def extraction_section(self):
        extraction = self.extraction
        files = extraction.get('files', [])
        title = '%s (%d)###extracted' % (tr('Extracted files'), len(files))
        if not imgui.collapsing_header(title, imgui.TreeNodeFlags_.default_open):
            return
        imgui.text_colored(color('textDim'), extraction.get('directory', ''))
        if extraction.get('entryScripts'):
            imgui.text_colored(color('success'), tr('Entry scripts: ') + ', '.join(Path(p).name for p in extraction['entryScripts']))
        _, self.extract_filter = imgui.input_text_with_hint('##extract-filter', tr('Filter'), self.extract_filter)
        query = self.extract_filter.lower()
        shown = [f for f in files if not query or query in f['name'].lower()]
        imgui.begin_child('###extracted-list', imgui.ImVec2(0, cyui.dp(260)))
        clipper = imgui.ListClipper()
        clipper.begin(len(shown))
        while clipper.step():
            for index in range(clipper.display_start, clipper.display_end):
                item = shown[index]
                if item.get('openable') and item.get('path'):
                    if imgui.small_button(label('Open##o%d' % index)):
                        self.open_path(item['path'])
                    imgui.same_line()
                text = '%s  [%s]' % (item['name'], item.get('format') or item.get('type', ''))
                if item.get('error'):
                    imgui.text_colored(color('error'), text + '  ' + item['error'])
                else:
                    imgui.text(text)
        clipper.end()
        imgui.end_child()

    def center_panel(self):
        selected = self.selected
        if selected is None:
            imgui.text(tr('Select a function or unit on the left.'))
            return
        title = selected['displayName']
        if selected.get('address'):
            title += '  @ ' + selected['address']
        imgui.text(title)
        if self.details and self.details.get('signature'):
            imgui.text_colored(color('textDim'), self.details['signature'])
        if imgui.begin_tab_bar('###views'):
            views = [('decompiled', 'Decompiled'), ('disassembly', 'Disassembly / bytecode'),
                     ('converted', 'AI rewrite')]
            if getattr(self, 'compact_workspace', False):
                views.append(('details', 'Details'))
            for key, caption in views:
                flags = imgui.TabItemFlags_.set_selected if getattr(self, '_force_view', None) == key else 0
                opened, _ = imgui.begin_tab_item(label(caption) + '###view-' + key, None, flags)
                if opened:
                    if key in ('decompiled', 'disassembly') and self.view != key:
                        self.view = key
                        self.request_code()
                    self.current_tab = key
                    imgui.end_tab_item()
            self._force_view = None
            imgui.end_tab_bar()
        if getattr(self, 'current_tab', 'decompiled') == 'converted':
            self.converted_view()
            return
        if getattr(self, 'current_tab', '') == 'details':
            self.details_panel()
            return
        if cyui.icon_button(cyui.icon.refresh, tr('Refresh')):
            self.request_code(refresh=True)
        imgui.same_line()
        if cyui.icon_button(cyui.icon.copy, tr('Copy')):
            imgui.set_clipboard_text(self.code_editor.get_text())
        imgui.same_line()
        if cyui.icon_button(cyui.icon.edit, tr('Edit function / patch')):
            self.ide.start_patch()
            _, ide_session = self.ide.session()
            ide_session['force_patch'] = True
        imgui.same_line()
        if cyui.icon_button(cyui.icon.rename, tr('Rename...')):
            word = self.code_editor.get_cursor_text() if hasattr(self.code_editor, 'get_cursor_text') else ''
            self.rename_old = (word or selected['displayName']).strip()
            self.rename_new = self.rename_old
            self.rename_local = self.rename_old != selected['displayName']
            imgui.open_popup('###rename')
        imgui.same_line()
        cyui.help_marker(tr('Double-click a name to open it. Right-click for actions.'))
        if self.jobs.busy('code'):
            self.jobs.progress_widget('code')
        self.rename_popup()
        palette(self.code_editor)
        render_editor(self.code_editor, '###code', imgui.ImVec2(0, 0))
        if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
            word = self.code_editor.get_word_at_mouse_pos(imgui.get_mouse_pos())
            if word:
                self.navigate(word)
        if imgui.is_item_hovered() and imgui.is_mouse_clicked(1):
            self.context_word = self.code_editor.get_word_at_mouse_pos(imgui.get_mouse_pos())
            imgui.open_popup('###code-menu')
        if imgui.begin_popup('###code-menu'):
            word = getattr(self, 'context_word', '') or ''
            imgui.text_colored(color('textDim'), word or tr('(no identifier)'))
            imgui.separator()
            if word and imgui.menu_item(label('Go to definition'), '', False)[0]:
                if not self.navigate(word):
                    self.status_message = tr('No unit named ') + word
            if word and imgui.menu_item(label('Rename symbol...'), '', False)[0]:
                self.rename_old, self.rename_new = word, word
                self.rename_local = word != selected['displayName'] and not any(
                    f['displayName'] == word for f in self.functions[:50000])
                self.open_rename = True
            if word and imgui.menu_item(label('Search everywhere'), '', False)[0]:
                self.search_query = word
                self.run_search()
            if imgui.menu_item(label('Copy all'), '', False)[0]:
                imgui.set_clipboard_text(self.code_editor.get_text())
            imgui.end_popup()
        if getattr(self, 'open_rename', False):
            self.open_rename = False
            imgui.open_popup('###rename')

    def rename_popup(self):
        opened, _ = imgui.begin_popup_modal(label('Rename symbol') + '###rename', None,
                                            imgui.WindowFlags_.always_auto_resize)
        if not opened:
            return
        imgui.text(tr('Current name'))
        imgui.set_next_item_width(cyui.dp(320))
        _, self.rename_old = imgui.input_text('##old', self.rename_old)
        imgui.text(tr('New name'))
        imgui.set_next_item_width(cyui.dp(320))
        _, self.rename_new = imgui.input_text('##new', self.rename_new)
        _, self.rename_local = imgui.checkbox(label('Only in this function (local variable)'), self.rename_local)
        if imgui.button(label('Apply')):
            parameters = {'projectId': self.project['projectId'], 'old': self.rename_old, 'new': self.rename_new,
                          'engine': self.engine, 'function': self.selected['id'] if self.rename_local else ''}
            self.jobs.submit('rename', parameters, tag='rename', done=lambda out: self.after_annotation())
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button(label('Close')):
            imgui.close_current_popup()
        imgui.end_popup()

    def converted_view(self):
        converted = self.converted
        if not converted:
            imgui.text_wrapped(tr('Use "Convert to source" in the AI panel to rewrite this unit as real code.'))
            return
        status = converted.get('verification', 'skipped')
        color = color('success') if status == 'passed' else color('error') if status == 'failed' else color('textDim')
        tool = next((c.get('tool') for c in reversed(converted.get('checks', [])) if c.get('tool')), '')
        imgui.text_colored(color, '%s: %s%s' % (tr('Compile check'), tr(status), (' (%s)' % tool) if tool else ''))
        imgui.same_line()
        if imgui.small_button(label('Copy##converted')):
            imgui.set_clipboard_text(self.converted_editor.get_text())
        imgui.text_colored(color('textDim'), tr('Saved to: ') + converted.get('file', ''))
        if converted.get('checks') and status == 'failed':
            imgui.text_wrapped(converted['checks'][-1].get('output', '')[:1500])
        if converted.get('notes'):
            imgui.text_wrapped(converted['notes'][:2000])
        palette(self.converted_editor)
        render_editor(self.converted_editor, '###converted', imgui.ImVec2(0, 0))

    # ------------------------------------------------------------------ right panel

    def right_panel(self):
        if imgui.begin_tab_bar('###right'):
            opened, _ = imgui.begin_tab_item(label('AI'))
            if opened:
                self.ai_panel()
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Details'))
            if opened:
                self.details_panel()
                imgui.end_tab_item()
            imgui.end_tab_bar()

    def details_panel(self):
        details = self.details
        if not details:
            imgui.text(tr('No unit selected.'))
            return
        imgui.begin_child('###details', imgui.ImVec2(0, 0))
        imgui.text_colored(color('textDim'), tr('Name') + ':')
        imgui.same_line()
        imgui.text(details['displayName'])
        if details['displayName'] != details['name']:
            imgui.text_colored(color('textDim'), tr('Original') + ': ' + details['name'])
        for key in ('address', 'size', 'kind', 'callingConvention'):
            if details.get(key) not in (None, ''):
                imgui.text_colored(color('textDim'), tr(key) + ': ' + str(details[key]))
        imgui.separator()
        imgui.text(tr('Comment'))
        _, self.comment_text = imgui.input_text_multiline('##comment', self.comment_text, imgui.ImVec2(-1, cyui.dp(70)))
        if imgui.small_button(label('Save comment')):
            self.jobs.submit('set_comment', {'projectId': self.project['projectId'], 'function': details['id'],
                                             'text': self.comment_text, 'engine': self.engine},
                             tag='comment', done=lambda out: self.request_code())
        for title, key in (('Called by', 'callers'), ('Calls', 'callees')):
            items = details.get(key) or []
            if imgui.collapsing_header('%s (%d)###%s' % (tr(title), len(items), key), imgui.TreeNodeFlags_.default_open):
                for index, item in enumerate(items[:500]):
                    clicked, _ = imgui.selectable('%s###%s%d' % (item['name'], key, index), False)
                    if clicked:
                        match = next((f for f in self.functions if f['id'] == item['id']), None)
                        self.open_function(match)
        if details.get('imports') and imgui.collapsing_header(label('Imported functions used')):
            for item in details['imports']:
                imgui.bullet_text(item)
        if details.get('strings') and imgui.collapsing_header(label('Strings referenced')):
            for item in details['strings']:
                imgui.bullet_text(item[:120])
        if details.get('localRenames') and imgui.collapsing_header(label('Local renames')):
            for old, new in details['localRenames'].items():
                imgui.bullet_text('%s -> %s' % (old, new))
        imgui.end_child()

    def ai_language(self):
        return preferences.values.get('language', 'en')

    def ai_job(self, operation, parameters, title, on_done):
        if not self.project or not self.selected:
            return
        self.ai_title = title
        self.ai_editor.set_text('')
        self.jobs.submit(operation, parameters, tag='ai', done=on_done, timeout=None,
                         failed=lambda message: self.ai_editor.set_text('**%s**\n\n%s' % (tr('Error'), message)))

    def ai_panel(self):
        status = self.ai_status or {}
        settings = status.get('settings', {})
        provider = settings.get('provider', '?')
        available = next((p.get('available') for p in status.get('providers', []) if p.get('id') == provider), None)
        cyui.panel_header(tr('AI'), provider + (' / ' + settings['model'] if settings.get('model') else ''))
        if available is False:
            imgui.text_wrapped(tr('This provider is not ready. Configure it in the "AI assistant settings" tab.'))
        project_id = self.project['projectId']
        unit = self.selected['id'] if self.selected else ''
        busy = (self.jobs.busy('ai') or self.jobs.busy('ide-' + project_id)
                or (project_id in self.ide.sessions and self.ide.debug.active(project_id)))
        _, self.ai_mode = cyui.segmented('###ai-modes', [tr('Autonomous workflow'), tr('Conversation'), tr('Function')], self.ai_mode, width=-1)
        cyui.space(8)
        if self.ai_mode == 2:
            imgui.begin_disabled(busy or not unit)
            if imgui.button(label('Explain')):
                self.ai_job('ai_explain', {'projectId': project_id, 'function': unit, 'engine': self.engine,
                                           'language': self.ai_language()}, tr('Explanation'),
                            lambda out: self.ai_editor.set_text(out.get('text', '')))
            imgui.same_line()
            if imgui.button(label('Suggest names')):
                def done(out):
                    lines = ['**%s** %s' % (tr('Function'), out.get('functionName') or '-'), '']
                    for item in out.get('variables', []):
                        lines.append('- `%s` -> `%s`  %s' % (item['old'], item['new'], item.get('reason', '')))
                    if out.get('comment'):
                        lines += ['', '> ' + out['comment']]
                    if out.get('applied'):
                        lines += ['', tr('Applied: %d, errors: %d') % (len(out['applied']['applied']), len(out['applied']['errors']))]
                        self.after_annotation()
                    self.ai_editor.set_text('\n'.join(lines))
                self.ai_job('ai_rename', {'projectId': project_id, 'function': unit, 'engine': self.engine,
                                          'apply': self.apply_names}, tr('Names'), done)
            _, self.apply_names = imgui.checkbox(label('Apply'), self.apply_names)
            cyui.space(8)
            cyui.section_title(tr('Conversion'))
            if cyui.begin_properties('###conversion-properties', 120):
                cyui.property(tr('Language'))
                _, self.target_index = imgui.combo('##target', self.target_index, [tr(n) for n in TARGET_NAMES])
                cyui.property(tr('Compile check'))
                _, self.verify = cyui.toggle_switch('###Compile check', self.verify)
                cyui.end_properties()
            imgui.set_next_item_width(-1)
            _, self.convert_instructions = imgui.input_text_with_hint('##instructions', tr('Extra instructions for the rewrite (optional)'),
                                                                      self.convert_instructions)
            if cyui.primary_button(label('Convert to source'), (-1, 0)):
                target = TARGETS[self.target_index]

                def done(out):
                    self.converted = out
                    set_language(self.converted_editor, out.get('target'))
                    self.converted_editor.set_text(out.get('code', ''))
                    self._force_view = 'converted'
                    self.ai_editor.set_text('**%s** %s\n\n%s' % (tr('Compile check:'), out.get('verification'), out.get('notes', '')))
                self.ai_job('ai_convert', {'projectId': project_id, 'function': unit, 'engine': self.engine,
                                           'target': target, 'verify': self.verify,
                                           'instructions': self.convert_instructions,
                                           'language': self.ai_language()}, tr('Conversion'), done)
            imgui.end_disabled()
            cyui.space(8)
            cyui.section_title(tr('Batch naming'))
            imgui.set_next_item_width(cyui.dp(60))
            _, self.batch_limit = imgui.input_int('##batch', self.batch_limit, 0)
            imgui.same_line()
            imgui.begin_disabled(busy)
            if imgui.button(label('Name functions')):
                def done(out):
                    lines = ['| %s | %s |' % (tr('Before'), tr('After')), '|---|---|']
                    for item in out.get('results', []):
                        lines.append('| %s | %s |' % (item.get('old'), item.get('new') or item.get('error', '')))
                    self.ai_editor.set_text('\n'.join(lines))
                    self.after_annotation()
                self.ai_job('ai_batch_rename', {'projectId': project_id, 'engine': self.engine,
                                                'limit': max(1, int(self.batch_limit))}, tr('Batch naming'), done)
            imgui.end_disabled()
            if imgui.is_item_hovered():
                imgui.set_tooltip(tr('Let the AI name this many auto-named functions (FUN_*, sub_*) and apply the names.'))
        else:
            if cyui.begin_card('###ai-task-card', tr('Autonomous workflow') if self.ai_mode == 0 else tr('Conversation')):
                cyui.text_faint(tr('Describe the result you want.'))
                _, self.ask_text = imgui.input_text_multiline('##ask', self.ask_text, cyui.dp2(-1, 110))
                with cyui.scoped_disabled(busy):
                    if self.ai_mode == 0:
                        imgui.set_next_item_width(-1)
                        _, self.agent_workflow = imgui.combo('##autonomous-workflow', self.agent_workflow,
                            [tr('Investigate'), tr('Reconstruct and validate'), tr('Patch and test'), tr('Port and test')])
                with cyui.scoped_disabled(busy or not self.ask_text.strip()):
                    if self.ai_mode == 0:
                        if cyui.primary_button(label('Run autonomous task'), (-1, 0)):
                            self.start_agent(project_id, self.ask_text.strip(), ['investigate', 'reconstruct', 'patch', 'port'][self.agent_workflow])
                            self.ask_text = ''
                    else:
                        if imgui.button(label('Send')):
                            question = self.ask_text.strip()
                            self.transcript += '\n\n### %s\n%s\n' % (tr('You'), question)

                            def done(out):
                                self.conversation_id = out.get('conversationId', '')
                                tools = ', '.join(t['tool'] for t in out.get('tools', []))
                                self.transcript += '\n### %s%s\n%s\n' % (tr('Assistant'), ('  _(%s: %s)_' % (tr('tools'), tools)) if tools else '',
                                                                         out.get('answer', ''))
                                self.ai_editor.set_text(self.transcript.strip())
                            self.ai_title = tr('Conversation')
                            self.ai_editor.set_text(self.transcript.strip())
                            self.jobs.submit('ai_ask', {'projectId': project_id, 'question': question, 'function': unit,
                                                        'engine': self.engine, 'conversationId': self.conversation_id,
                                                        'language': self.ai_language()}, tag='ai', done=done, timeout=None,
                                             failed=lambda message: self.ai_editor.set_text(self.transcript + '\n\n**%s** %s' % (tr('Error'), message)))
                            self.ask_text = ''
                if self.ai_mode == 1 and cyui.ghost_button(label('New conversation')):
                    self.conversation_id = ''
                    self.transcript = ''
                    self.ai_editor.set_text('')
                if self.ai_mode == 0 and self.agent_run and self.agent_run['projectId'] == project_id and self.agent_run.get('runId'):
                    with cyui.scoped_disabled(busy or self.agent_run.get('status') == 'completed'):
                        if cyui.button(label('Resume autonomous task')):
                            self.start_agent(project_id, self.agent_run['objective'], self.agent_run['workflow'], self.agent_run['runId'])
            cyui.end_card()
        cyui.space(8)
        job_id, job = self.jobs.active('ai')
        if job_id:
            self.jobs.progress_widget('ai')
            streamed = self.jobs.deltas.get(job_id, '')
            tools = self.jobs.tools.get(job_id, [])
            if tools:
                imgui.text_colored(color('textDim'), tr('Tools used: ') + ', '.join(t.get('tool', '') for t in tools))
            if streamed:
                text = (self.transcript + '\n\n### %s\n' % tr('Assistant') if self.ai_title == tr('Conversation') else '') + streamed
                if text != self.ai_editor.get_text():
                    self.ai_editor.set_text(text)
        if self.ai_title:
            imgui.text_colored(color('textDim'), self.ai_title)
            imgui.same_line()
            if imgui.small_button(label('Copy##ai')):
                imgui.set_clipboard_text(self.ai_editor.get_text())
        if not self.ai_editor.get_text().strip() and not job_id:
            cyui.empty_state(tr('Ready to assist'), tr('Give the AI a task to begin.'), cyui.icon.code)
            return
        palette(self.ai_editor)
        self.ai_editor.set_word_wrap_enabled(True) if hasattr(self.ai_editor, 'set_word_wrap_enabled') else None
        self.ai_editor.render('###ai-output', imgui.ImVec2(0, 0))

    def assistant_page(self):
        if not self.project:
            cyui.empty_state(tr('No application selected'), tr('Open an application in Workspace.'), cyui.icon.code)
            return
        self.ai_panel()

    def start_agent(self, project_id, objective, workflow, run_id=''):
        self.ai_title = tr('Autonomous workflow')
        self.ai_editor.set_text(objective)
        parameters = {'projectId': project_id, 'objective': objective, 'workflow': workflow,
                      'runId': run_id, 'language': self.ai_language()}
        self.agent_run = dict(parameters)

        def release_editor():
            state = self.ide.sessions.get(project_id)
            if state and workflow != 'investigate':
                state.update(reconstruction_busy=False, tabs={}, active='', history_preview=None, history=None)
                self.ide.refresh(project_id)

        def done(out):
            release_editor()
            self.agent_run = out
            self.ai_editor.set_text(tr('Status') + ': ' + out.get('status', '') + '\n\n' + out.get('answer', ''))

        def failed(message):
            release_editor()
            self.ai_editor.set_text(tr('Error') + ': ' + message)
            self.jobs.submit('ai_agent_status', {'projectId': project_id}, tag='agent-report', done=done)

        def submit():
            if project_id in self.ide.sessions and workflow != 'investigate':
                self.ide.sessions[project_id]['reconstruction_busy'] = True
            self.jobs.submit('ai_agent', parameters, tag='ai', done=done, failed=failed, timeout=None)

        if project_id in self.ide.sessions and workflow != 'investigate':
            self.ide.save_all(project_id, submit)
        else:
            submit()

    # ------------------------------------------------------------------ engines tab

    def engines_tab(self):
        cyui.panel_header(tr('Engines'))
        imgui.text_wrapped(tr('Engines are downloaded from their official sources, verified (SHA256/SHA512 when the '
                              'source publishes one) and installed under runtime/engines. A program already installed '
                              'on this computer (Java 21+, .NET, Ghidra) can be used instead.'))
        if imgui.button(label('Refresh status')):
            self.refresh_components(True)
        if self.jobs.busy('components'):
            imgui.same_line()
            imgui.text(tr('Probing...'))
        self.jobs.progress_widget('install')
        imgui.separator()
        cyui.section_title(tr('Engines'))
        flags = imgui.TableFlags_.borders | imgui.TableFlags_.row_bg | imgui.TableFlags_.resizable
        if imgui.begin_table('###engines', 4, flags):
            for caption in ('Engine', 'Formats', 'Status', 'Licence'):
                imgui.table_setup_column(tr(caption))
            imgui.table_headers_row()
            for engine in self.engines:
                imgui.table_next_row()
                imgui.table_next_column()
                imgui.text(engine['name'])
                if imgui.is_item_hovered():
                    imgui.set_tooltip(engine['description'])
                imgui.table_next_column()
                imgui.text(', '.join(engine['formats']))
                imgui.table_next_column()
                imgui.text_colored(color('success') if engine['available'] else color('error'), tr(engine['detail']))
                imgui.table_next_column()
                imgui.text_wrapped(engine['license'])
            imgui.end_table()
        imgui.separator()
        cyui.section_title(tr('Engine components'))
        busy = self.jobs.busy('install')
        if imgui.begin_table('###components', 5, flags):
            for caption, width in (('Component', 0.22), ('Status', 0.25), ('Size', 0.08), ('Licence', 0.15), ('Actions', 0.30)):
                imgui.table_setup_column(tr(caption), imgui.TableColumnFlags_.width_stretch, width)
            imgui.table_headers_row()
            for component in self.components:
                key = component['id']
                imgui.table_next_row()
                imgui.table_next_column()
                imgui.text(component['name'])
                if imgui.is_item_hovered():
                    imgui.set_tooltip(component['description'])
                imgui.table_next_column()
                location = component.get('location') or {}
                if component['installed']:
                    imgui.text_colored(color('success'), '%s %s (%s)' % (tr('Installed'), location.get('version', ''),
                                                              tr(location.get('source', ''))))
                    imgui.text_colored(color('textDim'), location.get('path', '')[:90])
                else:
                    imgui.text_colored(color('error'), tr('Not installed'))
                imgui.table_next_column()
                imgui.text('%d MB' % (component['approxBytes'] // 1000000))
                imgui.table_next_column()
                imgui.text_wrapped(component['license'])
                imgui.table_next_column()
                imgui.push_id(key)
                imgui.begin_disabled(busy)
                caption = 'Update' if component['installed'] and location.get('source') == 'private' else 'Install'
                if imgui.small_button(label(caption)):
                    self.jobs.submit('install_component', {'component': key}, tag='install', timeout=None,
                                     done=lambda out: (self.refresh_components(True), self.refresh_ai(False)))
                if component.get('privateVersions'):
                    imgui.same_line()
                    if imgui.small_button(label('Remove')):
                        self.jobs.submit('remove_component', {'component': key}, tag='install',
                                         done=lambda out: self.refresh_components(True))
                imgui.end_disabled()
                imgui.same_line()
                if imgui.small_button(label('Website')):
                    import webbrowser
                    webbrowser.open(component['url'])
                path = self.override_paths.setdefault(key, component.get('override', ''))
                imgui.set_next_item_width(-140)
                _, self.override_paths[key] = imgui.input_text_with_hint('##override', tr('existing installation folder'), path)
                imgui.same_line()
                if imgui.small_button(label('Browse')):
                    self.folder_dialog = pfd.select_folder(tr('Existing installation'), str(Path.home()))
                    self.folder_target = ('override', key)
                imgui.same_line()
                if imgui.small_button(label('Use')):
                    self.jobs.submit('set_component_path', {'component': key, 'path': self.override_paths[key]},
                                     tag='override', done=lambda out: self.refresh_components(True))
                imgui.pop_id()
            imgui.end_table()
        imgui.separator()
        self.symbols_section()
        imgui.separator()
        self.updates_section()
        imgui.separator()
        cyui.section_title(tr('Analysis options'))
        imgui.set_next_item_width(cyui.dp(160))
        _, self.analysis_options['maxDecompile'] = imgui.input_int(label('Ghidra: functions decompiled during analysis'),
                                                                   int(self.analysis_options['maxDecompile']))
        imgui.set_next_item_width(cyui.dp(160))
        _, self.analysis_options['functionTimeout'] = imgui.input_int(label('Ghidra: timeout per function (s)'),
                                                                      int(self.analysis_options['functionTimeout']))

    def symbols_section(self):
        from cydec import symbols
        cyui.section_title(tr('Debug symbols (PDB) for Windows executables and DLLs'))
        if self.symbol_draft is None:
            current = symbols.settings()
            self.symbol_draft = {'enabled': current['enabled'], 'server': current['server'],
                                 'folders': '; '.join(current['localFolders'])}
        draft = self.symbol_draft
        _, draft['enabled'] = imgui.checkbox(label('Load symbols during analysis'), draft['enabled'])
        imgui.set_next_item_width(cyui.dp(420))
        _, draft['server'] = imgui.input_text_with_hint(label('Symbol server'), tr('empty = local folders only'), draft['server'])
        imgui.set_next_item_width(cyui.dp(420))
        _, draft['folders'] = imgui.input_text_with_hint(label('Local PDB folders'), tr('separated by ;'), draft['folders'])
        if imgui.button(label('Save symbol settings')):
            folders = [f.strip() for f in draft['folders'].split(';') if f.strip()]
            self.jobs.submit('symbols_configure', {'enabled': draft['enabled'], 'server': draft['server'].strip(),
                                                   'localFolders': folders}, tag='symbols_configure',
                             done=lambda out: setattr(self, 'status_message', tr('Symbol settings saved.')))
        imgui.same_line()
        if imgui.button(label('Microsoft symbol server')):
            draft['server'] = 'https://msdl.microsoft.com/download/symbols'
        imgui.text_colored(color('textDim'), tr('PDBs are cached in data/symbols and checked against the binary (GUID and age).'))

    def updates_section(self):
        cyui.section_title(tr('Application updates'))
        if self.update_state is None and not self.jobs.busy('update_state'):
            self.refresh_updates()
        state = self.update_state or {}
        settings = state.get('settings', {})
        imgui.text_colored(color('textDim'), '%s %s' % (tr('Installed version:'), state.get('current', '?')))
        imgui.set_next_item_width(cyui.dp(320))
        if self.update_repository is None:
            self.update_repository = settings.get('applicationRepository', '')
        _, self.update_repository = imgui.input_text_with_hint(label('GitHub repository'), 'owner/name', self.update_repository)
        imgui.same_line()
        changed, automatic = imgui.checkbox(label('Check at start-up'), bool(settings.get('automaticCheck')))
        if imgui.button(label('Save repository')) or changed:
            self.jobs.submit('update_configure', {'repository': self.update_repository, 'automaticCheck': automatic},
                             tag='update', done=lambda out: self.refresh_updates())
        # Private repository: a read-only GitHub token, sealed like the AI keys (never a job parameter).
        from cydec.ai import credentials
        token_status = state.get('token') or {}
        imgui.text_colored(color('success') if token_status.get('configured') else color('textDim'), '%s: %s' % (
            tr('GitHub token (private repository)'),
            tr('configured') if token_status.get('configured') else tr('none')))
        imgui.set_next_item_width(cyui.dp(320))
        if not hasattr(self, 'github_token'):
            self.github_token = ''
        _, self.github_token = imgui.input_text_with_hint('##github-token', tr('paste a token to store it'),
                                                          self.github_token, imgui.InputTextFlags_.password)
        imgui.same_line()
        if imgui.button(label('Store token')) and self.github_token.strip():
            try:
                credentials.store('github', self.github_token)
                self.status_message = tr('Token stored.')
            except Exception as exc:
                self.jobs.message = str(exc)
            self.github_token = ''
            self.refresh_updates()
        imgui.same_line()
        if imgui.button(label('Remove token')):
            credentials.clear('github')
            self.refresh_updates()
        imgui.same_line()
        busy = self.jobs.busy('update')
        imgui.begin_disabled(busy)
        if imgui.button(label('Check for updates')):
            self.jobs.submit('update_check', {}, tag='update', done=lambda out: setattr(self, 'update_report', out))
        imgui.same_line()
        if imgui.button(label('Download and verify')):
            self.jobs.submit('update_download', {}, tag='update', timeout=None,
                             done=lambda out: (self.refresh_updates(), setattr(self, 'status_message', tr('Update staged and verified.'))))
        imgui.same_line()
        imgui.begin_disabled(not state.get('staged'))
        if imgui.button(label('Apply update')):
            self.jobs.submit('update_apply', {}, tag='update',
                             done=lambda out: setattr(self, 'status_message', tr('Applied. Restart CyDecompilator to run the new version.')))
        imgui.end_disabled()
        imgui.same_line()
        imgui.begin_disabled(not state.get('lastApplied', {}).get('backup'))
        if imgui.button(label('Restore previous version')):
            self.jobs.submit('update_rollback', {}, tag='update',
                             done=lambda out: setattr(self, 'status_message', tr('Restored. Restart CyDecompilator.')))
        imgui.end_disabled()
        imgui.end_disabled()
        self.jobs.progress_widget('update')
        report = self.update_report
        if report:
            if report.get('updateAvailable'):
                imgui.text_colored(color('success'), '%s %s' % (tr('Update available:'), report.get('available')))
            elif report.get('available'):
                imgui.text_colored(color('textDim'), '%s %s' % (tr('Latest release:'), report.get('available')))
            if report.get('notes'):
                imgui.text_wrapped(tr(report['notes']))
        imgui.text_colored(color('textDim'), tr('Updates are staged in runtime/updates and verified before activation. data/ is never replaced; '
                                    'the previous app/ is kept in runtime/backups.'))

    def refresh_updates(self):
        self.jobs.submit('update_state', {}, tag='update_state', done=lambda out: setattr(self, 'update_state', out))

    # ------------------------------------------------------------------ AI settings tab

    def ai_tab(self):
        from cydec.ai import credentials
        cyui.panel_header(tr('AI assistant settings'))
        status = self.ai_status
        if status is None or self.ai_draft is None:
            imgui.text(tr('Loading...'))
            return
        draft = self.ai_draft
        providers = [p for p in status.get('providers', []) if p.get('id')]
        ids = [p['id'] for p in providers]
        if imgui.button(label('Detect providers')):
            self.refresh_ai(True)
        if self.jobs.busy('ai_status'):
            imgui.same_line()
            imgui.text(tr('Probing...'))
        flags = imgui.TableFlags_.borders | imgui.TableFlags_.row_bg
        if imgui.begin_table('###providers', 3, flags):
            for caption in ('Provider', 'Status', 'Detail'):
                imgui.table_setup_column(tr(caption))
            imgui.table_headers_row()
            for provider in providers:
                imgui.table_next_row()
                imgui.table_next_column()
                imgui.text(provider.get('name', provider['id']))
                imgui.table_next_column()
                imgui.text_colored(color('success') if provider.get('available') else color('error'), tr(str(provider.get('status', ''))))
                imgui.table_next_column()
                imgui.text_wrapped(str(provider.get('detail', ''))[:200])
            imgui.end_table()
        imgui.separator()
        current = ids.index(draft['provider']) if draft['provider'] in ids else 0
        imgui.set_next_item_width(cyui.dp(260))
        changed, current = imgui.combo(label('Provider##ai'), current, [p.get('name', p['id']) for p in providers])
        if changed and ids:
            draft['provider'] = ids[current]
        provider_id = draft['provider']
        imgui.set_next_item_width(cyui.dp(260))
        _, draft['model'] = imgui.input_text_with_hint(label('Model'), tr('empty = provider default'), draft.get('model') or '')
        imgui.same_line()
        if imgui.button(label('List models')):
            from concurrent.futures import ThreadPoolExecutor
            from cydec.ai import assistant
            self.model_future = ThreadPoolExecutor(max_workers=1).submit(
                lambda: assistant.registry().get(provider_id).list_models())
        if self.model_future is not None and self.model_future.done():
            try:
                self.models[provider_id] = [m['id'] for m in self.model_future.result()]
            except Exception as exc:
                self.models[provider_id] = []
                self.jobs.message = str(exc)
            self.model_future = None
        models = self.models.get(provider_id) or []
        if models:
            imgui.set_next_item_width(cyui.dp(260))
            index = models.index(draft['model']) if draft.get('model') in models else 0
            changed, index = imgui.combo(label('Available models'), index, models)
            if changed:
                draft['model'] = models[index]
        options = draft.setdefault('providers', {}).setdefault(provider_id, {})
        if provider_id in ('openai-compatible', 'ollama', 'openai', 'anthropic', 'openrouter'):
            imgui.set_next_item_width(cyui.dp(360))
            _, base = imgui.input_text_with_hint(label('Base URL'), tr('empty = default'), options.get('base_url', ''))
            if base:
                options['base_url'] = base
            else:
                options.pop('base_url', None)
        if provider_id in ('openai', 'anthropic', 'openrouter', 'openai-compatible'):
            key_status = credentials.status(provider_id)
            imgui.text_colored(color('success') if key_status['configured'] else color('warning'),
                               '%s: %s (%s)' % (tr('API key'), tr('configured') if key_status['configured'] else tr('missing'),
                                                tr(key_status['source'])))
            imgui.set_next_item_width(cyui.dp(360))
            _, self.api_key = imgui.input_text_with_hint('##key', tr('paste a key to store it (sealed with Windows DPAPI)'),
                                                         self.api_key, imgui.InputTextFlags_.password)
            imgui.same_line()
            if imgui.button(label('Store key')) and self.api_key.strip():
                try:
                    credentials.store(provider_id, self.api_key)
                    self.status_message = tr('Key stored.')
                except Exception as exc:
                    self.jobs.message = str(exc)
                self.api_key = ''
                self.refresh_ai(True)
            imgui.same_line()
            if imgui.button(label('Remove key')):
                credentials.clear(provider_id)
                self.refresh_ai(True)
            if key_status.get('environmentVariable'):
                imgui.text_colored(color('textDim'), tr('or set the environment variable ') + key_status['environmentVariable'])
        if provider_id in ('claude-code', 'codex', 'antigravity', 'opencode'):
            imgui.text_wrapped(tr('Agent command lines use the account you already signed into in that program. '
                                  'They run read-only: the assistant only reads what CyDecompilator sends it.'))
        imgui.separator()
        imgui.set_next_item_width(cyui.dp(120))
        _, draft['maxToolSteps'] = imgui.input_int(label('Tool calls per question'), int(draft.get('maxToolSteps', 12)))
        imgui.set_next_item_width(cyui.dp(120))
        _, draft['verifyRounds'] = imgui.input_int(label('Repair rounds after a failed compile check'), int(draft.get('verifyRounds', 2)))
        imgui.set_next_item_width(cyui.dp(120))
        _, draft['maxTokens'] = imgui.input_int(label('Maximum tokens per reply'), int(draft.get('maxTokens', 8192)))
        _, draft['allowEdits'] = imgui.checkbox(label('Let the assistant rename and comment when asked'), bool(draft.get('allowEdits', True)))
        if imgui.button(label('Save AI settings')):
            clean = {k: draft[k] for k in ('provider', 'model', 'transport', 'maxTokens', 'maxToolSteps',
                                           'allowEdits', 'verifyRounds', 'providers')}
            clean['maxToolSteps'] = max(1, min(60, int(clean['maxToolSteps'])))
            clean['verifyRounds'] = max(0, min(10, int(clean['verifyRounds'])))
            clean['maxTokens'] = max(256, min(200000, int(clean['maxTokens'])))
            self.jobs.submit('ai_configure', clean, tag='ai_configure',
                             done=lambda out: (setattr(self, 'status_message', tr('AI settings saved.')), self.refresh_ai(True)))
        verifiers = status.get('verifiers', {})
        imgui.separator()
        cyui.section_title(tr('Compile checks available on this computer'))
        imgui.text_wrapped(', '.join('%s %s' % (k, 'yes' if v else 'no') for k, v in verifiers.items()))
        if self.status_message:
            imgui.text_colored(color('textDim'), self.status_message)


def main():
    if '--smoke-test' in sys.argv:
        print('smoke', file=sys.stderr)
    runner = hello_imgui.RunnerParams()
    hello_imgui.set_assets_folder(str(prepare_assets()))
    runner.app_window_params.window_title = 'CyDecompilator'
    runner.app_window_params.window_geometry.size = (1600, 960)
    test_size = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--ui-test-size=')), '')
    if test_size:
        width, height = map(int, test_size.lower().split('x'))
        runner.app_window_params.window_geometry.size = (max(800,width), max(600,height))
    (ROOT / 'data/settings').mkdir(parents=True, exist_ok=True)
    testing_layout = any(a.startswith('--ui-test-') for a in sys.argv) or '--smoke-test' in sys.argv
    runner.ini_filename = str(ROOT / ('data/reports/ui-test-imgui.ini' if testing_layout else 'data/settings/imgui.ini'))
    runner.imgui_window_params.default_imgui_window_type = hello_imgui.DefaultImGuiWindowType.no_default_window
    with create_runtime(ROOT / 'data/jobs') as runtime:
        from tool import declared_permissions
        actor = runtime.authenticate(runtime.create_client('ImGui', declared_permissions(runtime))['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        app = App(runtime, actor, session)
        frames = [0]
        idle_frames = [0]

        test_open = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-test-open=')), '')
        test_frames = int(next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-test-frames=')), '40'))
        screenshot = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--screenshot=')), '')
        test_unit = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ui-test-unit=')), '')
        test_project = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--ui-test-project=')), '')
        test_source = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--ui-test-source=')), '')

        def gui():
            frames[0] += 1
            app.draw()
            app.ide.exit_modal(runner)
            if test_open and frames[0] == 3:
                app.open_path(test_open)
            if test_project and frames[0] == 3:
                app.load_project(test_project)
            if test_source and app.project and not getattr(app, '_test_source_done', False):
                pid = app.project['projectId']
                state = app.ide.sessions.get(pid)
                if state and state['info'].get('available'):
                    app.ide.open_file(pid, test_source)
                    state['force_editor'] = True
                    app._test_source_done = True
            if test_unit and app.functions and not getattr(app, '_test_unit_done', False):
                app._test_unit_done = app.navigate(test_unit) or True
            testing = '--smoke-test' in sys.argv or test_open or screenshot
            idle_frames[0] = idle_frames[0] + 1 if not app.jobs.jobs else 0
            # TextEditor lays out newly delivered source over subsequent frames.
            if testing and frames[0] > test_frames and idle_frames[0] >= 6:
                runner.app_shall_exit = True
            _ = (runtime, actor)

        def capture_config():
            parameters = {'path': app.path_input or (app.project or {}).get('sourcePath', ''),
                          'engine': app.engine, 'options': dict(app.analysis_options)}
            return {'operationId': 'open_file', 'parameters': parameters}

        def restore_config(value):
            parameters = value.get('parameters', {})
            app.path_input = parameters.get('path', '')
            app.analysis_options.update(parameters.get('options', {}))

        configure_generation(runtime, capture_config, restore_config)
        runner.callbacks.show_gui = gui
        runner.callbacks.confirm_exit = app.ide.confirm_exit
        runner.callbacks.load_additional_fonts = load_fonts
        run(runner, shell_navigation=True)
        if screenshot:
            from standalone_log import save_screenshot
            Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
            save_screenshot(screenshot, hello_imgui.final_app_window_screenshot())


if __name__ == '__main__':
    main()
