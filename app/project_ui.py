"""Integrated project editor. All filesystem writes and toolchains go through Runtime jobs."""
import re
import time
from pathlib import Path

from imgui_bundle import imgui_color_text_edit as ed, portable_file_dialogs as pfd
from ui_common import imgui, label, tr


class ProjectIDE:
    def __init__(self, app, make_editor, set_language, palette, render_editor):
        self.app = app
        self.make_editor, self.set_language = make_editor, set_language
        self.palette, self.render = palette, render_editor
        self.sessions = {}
        from debug_ui import DebugUI
        self.debug = DebugUI(self)
        self.dialog = None
        self.destination = ''
        self.create_scope = 0
        self.native_target=0
        self.native_entry=''
        from reconstruction_ui import ReconstructionUI
        self.reconstruction=ReconstructionUI(self)
        self.exit_requested = False

    def confirm_exit(self):
        if any(self.dirty(t) for s in self.sessions.values() for t in s['tabs'].values()):
            self.exit_requested = True
            return False
        for pid in self.sessions:
            if self.debug.active(pid):
                self.debug.stop(pid)
        return True

    def exit_modal(self, runner):
        if self.exit_requested:
            self.exit_requested = False
            imgui.open_popup('###ide-unsaved')
        opened, _ = imgui.begin_popup_modal(label('Unsaved source files') + '###ide-unsaved', None,
                                            imgui.WindowFlags_.always_auto_resize)
        if not opened:
            return
        imgui.text_wrapped(tr('Save edited source files before exiting?'))
        busy = any(self.app.jobs.busy('ide-' + pid) for pid in self.sessions)
        imgui.begin_disabled(busy)
        if imgui.button(label('Save all and exit')):
            pending = list(self.sessions)
            def save_next():
                if pending:
                    self.save_all(pending.pop(0), save_next)
                else:
                    runner.app_shall_exit = True
            save_next()
        imgui.same_line()
        if imgui.button(label('Discard edits and exit')):
            runner.app_shall_exit = True
        imgui.end_disabled()
        imgui.same_line()
        if imgui.button(label('Cancel##ide-exit')):
            imgui.close_current_popup()
        imgui.end_popup()

    def session(self):
        pid = self.app.project['projectId']
        if pid not in self.sessions:
            self.sessions[pid] = {'info': {}, 'tabs': {}, 'active': '', 'force': '', 'output': self.make_editor(),
                                  'result': {}, 'configuration': 0, 'executable': '', 'arguments': '',
                                  'new_file': '', 'patch': None, 'patch_editor': self.make_editor('c', False),
                                  'patch_symbol': '', 'patch_plan': None, 'patch_destination': '', 'patch_receipt': None,
                                  'managed': None, 'managed_index': 0, 'managed_donor': '', 'remove_strong_name': False,
                                  'allow_new_members': False, 'patch_symbols': True,
                                  'native_extended': False, 'native_bindings': '{}',
                                  'copies': [], 'copy_arguments': '', 'copy_timeout': 60, 'output_busy': False}
            self.sessions[pid].update(search_query='', search_case=False, search_word=False, search_result=None,
                                      file_filter='', goto_line=1, csharp_auto=True, csharp_seen=None, csharp_due=0,
                                      csharp_completion=None, csharp_diagnostics=None, csharp_symbols=None,
                                      csharp_definition=None, csharp_notes=[], csharp_error='',
                                      csharp_rename=None, csharp_format=None, csharp_references=None, csharp_name='')
            self.sessions[pid]['target_project'] = ''
            self.sessions[pid].update(history=None, history_commit='', history_message='', history_preview=None,
                                      history_restoring=False, history_preview_editor=self.make_editor())
            self.debug.init(self.sessions[pid])
            self.reconstruction.init(self.sessions[pid])
            self.refresh(pid)
        return pid, self.sessions[pid]

    def submit(self, pid, operation, parameters, done=None, failed=None):
        session = self.sessions[pid]
        live = operation in ('workspace_execute', 'managed_patch_prepare', 'patch_run','reconstruction_run','workspace_dependencies')
        if live:
            session['output'].set_text('')
            session['output_busy'] = True
        def completed(out):
            if operation == 'workspace_save':
                session['history_preview'] = None
            if live:
                session['output_busy'] = False
                session['result'] = out if 'status' in out else {'status': 'passed'}
                if operation=='reconstruction_run' and out.get('attempts'):
                    session['result']=out['attempts'][-1].get('build',{})
                if 'output' in out:
                    session['output'].set_text(out['output'])
            if operation == 'patch_apply':
                session['copies'].insert(0, out)
            if done:
                done(out)
        return self.app.jobs.submit(operation, dict(parameters, projectId=pid), tag='ide-' + pid,
                                    done=completed, timeout=1800, failed=failed or (lambda error: self.error(pid, error)),
                                    streamed=(lambda text: session['output'].set_text(text)) if live else None)

    def error(self, pid, error):
        session = self.sessions[pid]
        text = session['output'].get_text() if session['output_busy'] else ''
        session['output_busy'] = False
        session['output'].set_text((text + '\n' + error).strip())
        session['result'] = {'status': 'failed'}

    def refresh(self, pid):
        def done(out):
            session = self.sessions[pid]
            session['info'] = out
            if not session['result'] and out.get('lastBuild'):
                session['result'] = out['lastBuild']
                session['output'].set_text(out['lastBuild'].get('output', ''))
        self.submit(pid, 'workspace_info', {}, done)
        self.submit(pid,'reconstruction_status',{},lambda out:self.sessions[pid].update(reconstruction_report=out))
        def copies(out):
            session = self.sessions[pid]
            session['copies'] = out['copies']
            if not session['patch_receipt'] and out['copies']:
                session['patch_receipt'] = out['copies'][0]
            if not session['result'] and out.get('lastRun'):
                session['result'] = out['lastRun']
                session['output'].set_text(out['lastRun'].get('output', ''))
        self.submit(pid, 'patch_outputs', {}, copies)

    @staticmethod
    def dirty(tab):
        return tab['editor'].get_text() != tab['saved']

    def open_file(self, pid, path, line=None, column=1):
        session = self.sessions[pid]

        def activate(tab):
            session['active'] = session['force'] = path
            if line:
                tab['editor'].set_cursor(ed.TextEditor.DocPos(max(0, line - 1), max(0, column - 1)))

        if path in session['tabs']:
            activate(session['tabs'][path])
            return

        def done(out):
            editor = self.make_editor({'.cs': 'csharp', '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.py': 'python',
                                       '.java': 'java', '.xml': 'xml', '.xaml': 'xml', '.csproj': 'xml', '.vcxproj': 'xml',
                                       '.js':'javascript','.mjs':'javascript','.cjs':'javascript','.ts':'javascript','.tsx':'javascript','.jsx':'javascript',
                                       '.hlsl': 'hlsl', '.glsl': 'glsl'}.get(Path(path).suffix.lower()), False)
            editor.set_text(out['text'])
            tab = {'editor': editor, 'saved': out['text'], 'revision': out['revision']}
            session['tabs'][path] = tab
            activate(tab)
        self.submit(pid, 'workspace_read', {'path': path}, done)

    def save_all(self, pid, after=None):
        session = self.sessions[pid]
        pending = [p for p, tab in session['tabs'].items() if self.dirty(tab)]

        def step():
            if not pending:
                if any(self.dirty(t) for t in session['tabs'].values()):
                    self.error(pid, tr('Source changed while saving. Save again before building.'))
                elif after:
                    after()
                return
            path = pending.pop(0)
            tab = session['tabs'][path]
            text = tab['editor'].get_text()

            def done(out):
                tab.update(saved=out['text'], revision=out['revision'])
                step()
            self.submit(pid, 'workspace_save', {'path': path, 'text': text, 'revision': tab['revision']}, done)
        step()

    def reload_file(self, pid, path):
        session = self.sessions[pid]
        tab = session['tabs'][path]
        before = tab['editor'].get_text()
        def done(out):
            if path not in session['tabs'] or tab['editor'].get_text() != before:
                self.error(pid, tr('The editor changed while reloading. Try again.'))
                return
            tab['editor'].set_text(out['text'])
            tab.update(saved=out['text'], revision=out['revision'])
        self.submit(pid, 'workspace_read', {'path': path}, done)

    @staticmethod
    def csharp_buffers(session):
        return [{'path': path, 'text': tab['editor'].get_text()} for path, tab in sorted(session['tabs'].items())
                if path.endswith('.cs')]

    def csharp_request(self, pid, action, automatic=False):
        if self.app.jobs.busy('ide-' + pid):
            return
        session = self.sessions[pid]
        path = session['active']
        if path not in session['tabs'] or not path.endswith('.cs'):
            return
        editor = session['tabs'][path]['editor']
        cursor = editor.get_main_cursor_position()
        buffers = self.csharp_buffers(session)
        configuration = ['Debug', 'Release'][session['configuration']]
        session['csharp_error'] = ''
        def current():
            return buffers == self.csharp_buffers(session) and configuration == ['Debug', 'Release'][session['configuration']]
        def done(out):
            if not current():
                return
            if action in ('complete', 'definition', 'rename', 'references'):
                latest = editor.get_main_cursor_position()
                if session['active'] != path or latest.line != cursor.line or latest.index != cursor.index:
                    return
            session['csharp_notes'] = out['notes']
            session['csharp_' + {'complete': 'completion', 'diagnostics': 'diagnostics', 'symbols': 'symbols', 'definition': 'definition',
                                'rename': 'rename', 'format': 'format', 'references': 'references'}[action]] = out
            if action in ('rename', 'format'):
                out['buffers'] = buffers
                out['configuration'] = configuration
            if action == 'complete':
                out['buffers'] = buffers
                out['configuration'] = configuration
                out['requestPosition'] = {'line': cursor.line, 'index': cursor.index}
            if action == 'definition' and len(out['definitions']) == 1:
                location = out['definitions'][0]
                self.open_file(pid, location['path'], location['point']['line'], location['point']['column'])
            if not automatic:
                session['force_assistance'] = True
        def failed(error):
            session['csharp_error'] = error
            if automatic:
                session['csharp_auto'] = False
            session['force_assistance'] = True
        self.submit(pid, 'workspace_csharp', {'path': path, 'action': action,
                    'line': cursor.line + 1, 'column': cursor.index + 1, 'buffers': buffers,
                    'configuration': configuration, 'newName': session.get('csharp_name', ''), 'limit': 100 if action != 'complete' else 60}, done, failed)

    def apply_refactoring(self, pid, action):
        session = self.sessions[pid]
        result = session['csharp_' + action]
        if not result or self.debug.active(pid) or session.get('history_restoring'):
            return
        # Load closed files through Runtime first. No editor is modified until all
        # buffers and disk revisions have been checked, so a conflict cannot apply half a rename.
        pending = [e for e in result['edits'] if e['path'] not in session['tabs']]
        newly_loaded = {e['path'] for e in pending}
        def finish():
            if session.get('history_restoring'):
                return
            if session['csharp_' + action] is not result:
                return
            if result['configuration'] != ['Debug', 'Release'][session['configuration']]:
                session['csharp_error'] = tr('The source changed. Request refactoring again.')
                return
            if result['buffers'] != [r for r in self.csharp_buffers(session) if r['path'] not in newly_loaded]:
                session['csharp_error'] = tr('The source changed. Request refactoring again.')
                return
            if any(session['tabs'][e['path']]['editor'].get_text() != e['before'] for e in result['edits']):
                session['csharp_error'] = tr('The source changed. Request refactoring again.')
                return
            for edit in result['edits']:
                editor = session['tabs'][edit['path']]['editor']
                old = editor.get_text()
                editor.replace_section_text(ed.TextEditor.DocPos(0, 0),
                    ed.TextEditor.DocPos(old.count('\n'), len(old.rsplit('\n', 1)[-1])), edit['text'])
            session.update(csharp_rename=None, csharp_format=None, csharp_seen=None, patch_plan=None, force_editor=True)
        def step():
            if not pending:
                self.submit(pid, 'workspace_refactor_check', {'revision': result['sourceRevision']}, lambda out: finish())
                return
            edit = pending.pop(0)
            def loaded(out):
                editor = self.make_editor('csharp', False)
                editor.set_text(out['text'])
                session['tabs'][edit['path']] = {'editor': editor, 'saved': out['text'], 'revision': out['revision']}
                step()
            self.submit(pid, 'workspace_read', {'path': edit['path']}, loaded)
        step()

    def csharp_tick(self, pid, session, busy):
        path = session['active']
        if not session['csharp_auto'] or not path.endswith('.cs'):
            return
        signature = (path, session['configuration'], tuple((p, t['revision'], t['editor'].get_undo_index())
                     for p, t in sorted(session['tabs'].items()) if p.endswith('.cs')))
        if signature != session['csharp_seen']:
            session['csharp_seen'] = signature
            session['csharp_due'] = time.monotonic() + 1.2
            session['csharp_diagnostics'] = None
            session['csharp_completion'] = None
        if not busy and session['csharp_due'] and time.monotonic() >= session['csharp_due']:
            session['csharp_due'] = 0
            self.csharp_request(pid, 'diagnostics', automatic=True)

    def apply_completion(self, pid, item):
        session = self.sessions[pid]
        if session.get('history_restoring'):
            return
        result = session['csharp_completion']
        path = result['path'] if result else ''
        if (not result or path not in session['tabs'] or result['buffers'] != self.csharp_buffers(session)
                or result['configuration'] != ['Debug', 'Release'][session['configuration']]):
            session['csharp_completion'] = None
            session['csharp_error'] = tr('The source changed. Request completion again.')
            return
        editor = session['tabs'][path]['editor']
        cursor = editor.get_main_cursor_position()
        if session['active'] != path or result['requestPosition'] != {'line': cursor.line, 'index': cursor.index}:
            session['csharp_completion'] = None
            session['csharp_error'] = tr('The source changed. Request completion again.')
            return
        edit = item['edit']
        editor.replace_section_text(ed.TextEditor.DocPos(edit['start']['line'] - 1, edit['start']['column'] - 1),
                                    ed.TextEditor.DocPos(edit['end']['line'] - 1, edit['end']['column'] - 1), edit['text'])
        editor.set_cursor(ed.TextEditor.DocPos(edit['cursor']['line'] - 1, edit['cursor']['column'] - 1))
        editor.set_focus()
        session.update(csharp_completion=None, active=path, force=path, force_editor=True, patch_plan=None)

    def execute(self, pid, action):
        session = self.sessions[pid]
        try:
            from cydec.workspace import parse_arguments
            arguments = parse_arguments(session['arguments'])
        except ValueError:
            self.error(pid, tr('Invalid run arguments.'))
            return

        def run():
            session['output'].set_text(tr('Building or running...'))

            def done(out):
                session['result'] = out
                session['output'].set_text(out.get('output', ''))
                self.refresh(pid)
            self.submit(pid, 'workspace_execute', {'action': action,
                        'configuration': ['Debug', 'Release'][session['configuration']],
                        'executable': session['executable'], 'arguments': arguments,
                        'targetProject': session['target_project']}, done)
        self.save_all(pid, run)

    def start_patch(self):
        app = self.app
        if not app.project or not app.selected:
            return
        pid, session = self.session()
        fmt = app.project['format']
        if fmt['format'] != 'pe' or fmt.get('arch') not in ('x86', 'x86_64'):
            if fmt['format'] == 'pe-dotnet':
                self.load_managed_methods(pid, app.selected['id'])
                app.force_tab = 'project'
                return
            self.error(pid, tr('Direct patches support native x86/x64 PE functions. Edit other formats in the source project.'))
            app.force_tab = 'project'
            return
        function, engine = app.selected['id'], app.engine
        name = app.selected['name']

        def done(out):
            source = ('#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\n'
                      'typedef unsigned char byte; typedef unsigned short ushort; typedef unsigned int uint;\n'
                      'typedef long long longlong; typedef unsigned long long ulonglong;\n'
                      'typedef struct { ulonglong lo, hi; } uint128; typedef ulonglong code();\n'
                      'typedef uint8_t undefined, undefined1; typedef uint16_t undefined2;\n'
                      'typedef uint32_t undefined4; typedef uint64_t undefined8;\n\n' + out['code'])
            session.update(patch={'function': function, 'engine': engine, 'name': name}, patch_plan=None, patch_receipt=None, force_patch=True)
            session['patch_editor'].set_text(source)
            names = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*\{', out['code'])
            session['patch_symbol'] = next((n for n in names if n not in ('if', 'while', 'switch', 'for')), name)
            app.force_tab = 'project'
        self.submit(pid, 'decompile', {'function': function, 'engine': engine, 'annotate': False}, done)

    def load_managed_methods(self, pid, type_name=''):
        session = self.sessions[pid]
        def done(out):
            session.update(managed=out, managed_index=0, patch_plan=None, patch_receipt=None, force_patch=True)
            self.app.force_tab = 'project'
        self.submit(pid, 'managed_methods', {'type': type_name}, done)

    def edit_managed_type(self, pid, method):
        session = self.sessions[pid]
        def open_type():
            short = method['type'].split('/')[0].rsplit('.', 1)[-1].split('`')[0]
            files = session['info'].get('files', [])
            matches = [r['path'] for r in files if Path(r['path']).suffix == '.cs' and Path(r['path']).stem == short]
            if not matches:
                self.error(pid, tr('Open the declaring type in Project editor to edit the method.'))
                return
            self.open_file(pid, matches[0])
            session['force_editor'] = True
        if not session['info'].get('available'):
            def created(out):
                session['info'] = out
                open_type()
            self.submit(pid, 'workspace_create', {}, created)
        else:
            open_type()

    def draw(self):
        if not self.app.project:
            imgui.text_wrapped(tr('Open and analyze an application in Workspace first.'))
            return
        pid, session = self.session()
        busy = self.app.jobs.busy('ide-' + pid) or self.debug.active(pid) or session['history_restoring']
        info = session['info']
        if self.dialog is not None and self.dialog.ready():
            folder = self.dialog.result()
            self.dialog = None
            if folder:
                self.destination = folder
        imgui.text(self.app.project['name'])
        if self.app.jobs.message:
            imgui.text_wrapped(self.app.jobs.message)
        self.app.jobs.progress_widget('ide-' + pid)
        if imgui.collapsing_header(label('Source project'), imgui.TreeNodeFlags_.default_open):
            _, self.destination = imgui.input_text(label('Project folder'), self.destination)
            imgui.same_line()
            if imgui.small_button(label('Browse##ide-folder')):
                self.dialog = pfd.select_folder(tr('Project folder'), self.destination)
            native = self.app.project['format']['format'] in ('pe', 'elf')
            if native:
                _, self.create_scope = imgui.combo(label('Native export scope'), self.create_scope,
                                                   [tr('Exported functions / entry point'), tr('Selected function and callees')])
                _,self.native_target=imgui.combo(label('Native project target'),self.native_target,
                    [tr('Automatic target'),tr('Executable application'),tr('Shared library'),tr('Static library')])
                _,self.native_entry=imgui.input_text(label('Native application entry (optional)'),self.native_entry)
            imgui.begin_disabled(busy or bool(info.get('available')))
            if imgui.button(label('Create source project')):
                if native and self.create_scope == 1 and not self.app.selected:
                    self.error(pid, tr('Select a function first.'))
                else:
                    functions = [self.app.selected.get('address') or self.app.selected['id']] if native and self.create_scope == 1 and self.app.selected else []
                    self.submit(pid, 'workspace_create', {'destination': self.destination, 'functions': functions,
                        'nativeTarget':('auto','executable','shared','library')[self.native_target],'entryFunction':self.native_entry},
                                lambda out: session.update(info=out))
            imgui.end_disabled()
            imgui.same_line()
            imgui.begin_disabled(busy or any(self.dirty(t) for t in session['tabs'].values()))
            if imgui.button(label('Open source project')):
                def attached(out):
                    session.update(info=out, tabs={}, active='', result={})
                    session.update(history=None, history_commit='', history_preview=None)
                    self.debug.init(session)
                self.submit(pid, 'workspace_open', {'directory': self.destination}, attached)
            imgui.end_disabled()
            if info.get('directory'):
                imgui.text_wrapped(info['directory'])
            if info.get('note'):
                imgui.text_wrapped(tr(info['note']))
        if imgui.begin_tab_bar('###ide-modes'):
            opened,_=imgui.begin_tab_item(label('Reconstruction'))
            if opened:
                self.reconstruction.draw(pid,session,busy)
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Project editor'), None,
                                           imgui.TabItemFlags_.set_selected if session.pop('force_editor', False) else 0)
            if opened:
                self.draw_project(pid, session, busy)
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Function patch'), None,
                                           imgui.TabItemFlags_.set_selected if session.pop('force_patch', False) else 0)
            if opened:
                self.draw_patch(pid, session, busy)
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Saved modified copies'), None,
                    imgui.TabItemFlags_.set_selected if session.pop('force_copies', False) else 0)
            if opened:
                self.draw_modified_copy(pid, session, busy)
                self.draw_output(pid, session)
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Git history'), None,
                                           imgui.TabItemFlags_.set_selected if session.pop('force_history', False) else 0)
            if opened:
                self.draw_history(pid, session, busy)
                imgui.end_tab_item()
            imgui.end_tab_bar()

    def draw_project(self, pid, session, busy):
        info = session['info']
        if not info.get('available'):
            imgui.text_wrapped(tr('Create a reconstructed project or open an existing source folder.'))
            return
        imgui.begin_disabled(busy)
        if imgui.button(label('Save all')):
            self.save_all(pid)
        for action, caption in [('build', 'Build'), ('rebuild', 'Rebuild'), ('test', 'Test'), ('run', 'Run')]:
            imgui.same_line()
            if imgui.button(label(caption + '##ide')):
                self.execute(pid, action)
        imgui.same_line()
        imgui.begin_disabled(Path(session['target_project'] or info.get('entry', '')).suffix != '.csproj')
        if imgui.button(label('Debug (F5)')):
            self.debug.start(pid)
        imgui.end_disabled()
        imgui.same_line()
        imgui.set_next_item_width(110)
        changed, session['configuration'] = imgui.combo('##configuration', session['configuration'], ['Debug', 'Release'])
        if changed:
            session['patch_plan'] = None
        imgui.end_disabled()
        if self.debug.active(pid):
            imgui.same_line()
            if imgui.button(label('Stop debugging')):
                self.debug.stop(pid)
        self.debug.shortcuts(pid)
        projects = info.get('projects', [])
        if len(projects) > 1 or Path(info.get('entry', '')).suffix in ('.sln', '.slnx'):
            paths = [''] + [p['path'] for p in projects]
            current = paths.index(session['target_project']) if session['target_project'] in paths else 0
            imgui.begin_disabled(busy)
            changed, current = imgui.combo(label('Build / startup project'), current,
                                           [tr('Entire solution')] + [p['path'] for p in projects])
            imgui.end_disabled()
            if changed:
                session['target_project'] = paths[current]
                session['patch_plan'] = None
        if imgui.collapsing_header(label('Run settings')):
            if info.get('kind') != 'dotnet':
                _, session['executable'] = imgui.input_text(label('Electron / browser runtime' if info.get('kind')=='electron' else 'Executable relative to project'), session['executable'])
            _, session['arguments'] = imgui.input_text(label('Run arguments'), session['arguments'])
            imgui.begin_disabled(self.debug.active(pid))
            _, session['debug_stop_entry'] = imgui.checkbox(label('Stop at entry'), session['debug_stop_entry'])
            _, session['debug_executable'] = imgui.input_text(label('Debug assembly (optional)'), session['debug_executable'])
            imgui.end_disabled()
        height = max(140, imgui.get_content_region_avail().y - 255)
        if imgui.begin_table('###ide-layout', 2, imgui.TableFlags_.resizable | imgui.TableFlags_.borders_inner_v,
                             imgui.ImVec2(-1, height)):
            imgui.table_setup_column('files', imgui.TableColumnFlags_.width_stretch, 0.23)
            imgui.table_setup_column('editor', imgui.TableColumnFlags_.width_stretch, 0.77)
            imgui.table_next_row()
            imgui.table_next_column()
            imgui.begin_child('###ide-files', imgui.ImVec2(0, height))
            imgui.text(tr('Solution explorer'))
            _, session['file_filter'] = imgui.input_text_with_hint('##file-filter', tr('Filter files'), session['file_filter'])
            if imgui.small_button(label('Refresh##ide-files')) and not busy:
                self.refresh(pid)
            _, session['new_file'] = imgui.input_text_with_hint('##new-source', tr('New file: src/example.c'), session['new_file'])
            imgui.begin_disabled(busy or not session['new_file'])
            if imgui.small_button(label('Add file')):
                path = session['new_file']
                def added(out):
                    self.refresh(pid)
                    self.open_file(pid, out['path'])
                    session['new_file'] = ''
                self.submit(pid, 'workspace_save', {'path': path, 'text': '', 'revision': ''}, added)
            imgui.end_disabled()
            # A directory tree from paths, independent of the host filesystem.
            tree = {}
            for row in info.get('files', []):
                if session['file_filter'].casefold() not in row['path'].casefold():
                    continue
                branch = tree
                parts = row['path'].split('/')
                for part in parts[:-1]:
                    branch = branch.setdefault(part, {})
                branch[parts[-1]] = row['path']

            def draw_tree(branch, prefix=''):
                for name, child in branch.items():
                    if isinstance(child, dict):
                        if imgui.tree_node(name + '###' + prefix + name):
                            draw_tree(child, prefix + name + '/')
                            imgui.tree_pop()
                    elif imgui.selectable(name + '###' + child, session['active'] == child)[0]:
                        self.open_file(pid, child)
            draw_tree(tree)
            imgui.end_child()
            imgui.table_next_column()
            editor = None
            if imgui.begin_tab_bar('###source-tabs'):
                for path, tab in list(session['tabs'].items()):
                    dirty = self.dirty(tab)
                    flags = imgui.TabItemFlags_.set_selected if session['force'] == path else 0
                    opened, keep = imgui.begin_tab_item(Path(path).name + (' *' if dirty else '') + '###' + path, True, flags)
                    if opened:
                        session['active'] = path
                        editor = tab['editor']
                        imgui.end_tab_item()
                    if not keep:
                        if dirty:
                            self.error(pid, tr('Save the edited file before closing its tab.'))
                        else:
                            del session['tabs'][path]
                session['force'] = ''
                imgui.end_tab_bar()
            if editor:
                self.debug.markers(pid, session['active'], editor)
                editor.set_read_only_enabled(self.debug.active(pid) or session['history_restoring'] or session['reconstruction_busy'])
                self.draw_file_actions(pid, session, busy, editor)
                self.palette(editor)
                self.render(editor, '###source-editor', imgui.ImVec2(-1, max(80, height - 75)))
                self.csharp_tick(pid, session, busy)
            imgui.end_table()
        self.draw_output(pid, session)

    def history_request(self, pid, action):
        session = self.sessions[pid]
        def submit():
            parameters = {'action': action}
            if action == 'snapshot':
                parameters['message'] = session['history_message']
            elif action in ('compare', 'restore'):
                parameters['commit'] = session['history_commit']
            if action == 'restore':
                preview = session['history_preview']
                if not preview or preview['commit'] != session['history_commit'] or any(self.dirty(t) for t in session['tabs'].values()):
                    self.error(pid, tr('Save sources and compare again before restoring.'))
                    return
                parameters['revision'] = preview['revision']
                session['history_restoring'] = True
                for tab in session['tabs'].values():
                    tab['editor'].set_read_only_enabled(True)
            def done(out):
                session['history_restoring'] = False
                for tab in session['tabs'].values():
                    tab['editor'].set_read_only_enabled(self.debug.active(pid))
                session['history'] = out
                if action == 'compare':
                    session['history_preview'] = out
                    text = '\n\n'.join(row['path'] + ' | ' + tr(row['kind']) +
                            (' | ' + tr('Binary file changed') if row['binary'] else '') + '\n' + row['diff'] +
                            ('\n' + tr('Diff truncated') if row['truncated'] else '') for row in out['changes'])
                    session['history_preview_editor'].set_text(text or tr('No changes'))
                else:
                    session['history_preview'] = None
                    session['history_commit'] = out.get('commit') or out['head']
                if action == 'restore':
                    # Restore is submitted only with saved buffers. Freeze them until completion.
                    paths = list(session['tabs'])
                    session.update(tabs={}, active='', patch_plan=None, csharp_seen=None,
                                   result={},
                                   csharp_completion=None, csharp_rename=None, csharp_format=None,
                                   csharp_diagnostics=None, csharp_symbols=None, csharp_references=None)
                    session['output'].set_text('')
                    session['info'] = out['workspace']
                    self.refresh(pid)
                    available = {row['path'] for row in session['info'].get('files', [])}
                    for path in paths:
                        if path in available:
                            self.open_file(pid, path)
            def failed(error):
                session['history_restoring'] = False
                for tab in session['tabs'].values():
                    tab['editor'].set_read_only_enabled(self.debug.active(pid))
                self.app.jobs.message = tr('Git project history') + ': ' + tr(error)
                self.error(pid, tr(error))
            self.submit(pid, 'workspace_history', parameters, done, failed)
        if action in ('snapshot', 'compare'):
            self.save_all(pid, submit)
        else:
            submit()

    def draw_history(self, pid, session, busy):
        if not session['info'].get('available'):
            imgui.text_wrapped(tr('Create a reconstructed project or open an existing source folder.'))
            return
        imgui.text_wrapped(tr('Git keeps local versions of sources, resources and dependencies. Restore saves the current version first.'))
        imgui.begin_disabled(busy)
        if imgui.button(label('Refresh history')):
            self.history_request(pid, 'status')
        _, session['history_message'] = imgui.input_text(label('Version description'), session['history_message'])
        imgui.begin_disabled(not session['history_message'].strip())
        if imgui.button(label('Save Git version')):
            self.history_request(pid, 'snapshot')
        imgui.end_disabled()
        history = session['history'] or {}
        if history.get('head'):
            imgui.text(tr('Current commit: ') + history['head'][:12])
            imgui.text(tr('Changes since saved version') if history['dirty'] else tr('Sources match saved version'))
        commits = history.get('commits', [])
        if commits:
            ids = [row['commit'] for row in commits]
            current = ids.index(session['history_commit']) if session['history_commit'] in ids else 0
            changed, current = imgui.combo(label('Saved version'), current,
                                           [row['commit'][:8] + ' | ' + row['message'] for row in commits])
            if changed or not session['history_commit']:
                session['history_commit'] = ids[current]
                session['history_preview'] = None
            if imgui.button(label('Compare with saved sources')):
                self.history_request(pid, 'compare')
            imgui.same_line()
            imgui.begin_disabled(not session['history_preview'] or any(self.dirty(t) for t in session['tabs'].values()))
            if imgui.button(label('Restore this version')):
                self.history_request(pid, 'restore')
            imgui.end_disabled()
        imgui.end_disabled()
        if session['history_preview']:
            editor = session['history_preview_editor']
            editor.set_read_only_enabled(True)
            self.palette(editor)
            self.render(editor, '###git-preview', imgui.ImVec2(-1, max(100, imgui.get_content_region_avail().y - 180)))
        self.draw_output(pid, session)

    def draw_output(self, pid, session):
        result = session['result']
        if session['output_busy']:
            imgui.text(tr('Running'))
        elif result.get('status'):
            imgui.text(tr('Result: ') + tr(result['status']))
        if imgui.begin_tab_bar('###build-results'):
            opened, _ = imgui.begin_tab_item(label('Build output'))
            if opened:
                self.palette(session['output'])
                self.render(session['output'], '###build-output', imgui.ImVec2(-1, max(90, imgui.get_content_region_avail().y)))
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Problems'))
            if opened:
                imgui.begin_child('###build-problems', imgui.ImVec2(-1, max(90, imgui.get_content_region_avail().y)))
                for index, item in enumerate(result.get('diagnostics', [])):
                    caption = '%s:%s: %s' % (Path(item['file']).name, item['line'], item['message'])
                    if imgui.selectable(caption + '###problem-' + str(index), False)[0]:
                        root = Path(session['info']['directory']).resolve()
                        path = Path(item['file'])
                        resolved = (path if path.is_absolute() else root / path).resolve()
                        if resolved.is_relative_to(root):
                            self.open_file(pid, resolved.relative_to(root).as_posix(), item['line'], item['column'])
                imgui.end_child()
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Search source project'), None,
                    imgui.TabItemFlags_.set_selected if session.pop('force_search', False) else 0)
            if opened:
                self.draw_search(pid, session)
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('C# assistance'), None,
                    imgui.TabItemFlags_.set_selected if session.pop('force_assistance', False) else 0)
            if opened:
                self.draw_csharp(pid, session)
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Debugger'), None,
                    imgui.TabItemFlags_.set_selected if session.pop('force_debug', False) else 0)
            if opened:
                self.debug.draw(pid, session)
                imgui.end_tab_item()
            imgui.end_tab_bar()

    def draw_file_actions(self, pid, session, busy, editor):
        path = session['active']
        imgui.begin_disabled(busy)
        if imgui.small_button(label('Reload file')):
            if self.dirty(session['tabs'][path]):
                session['reload_path'] = path
                imgui.open_popup('###reload-source')
            else:
                self.reload_file(pid, path)
        imgui.same_line()
        if imgui.small_button(label('Go to line')):
            imgui.open_popup('###goto-line')
        if path.endswith('.cs'):
            for action, caption in [('complete', 'Complete (Ctrl+Space)'), ('definition', 'Go to definition (F12)'), ('symbols', 'C# symbols')]:
                imgui.same_line()
                if imgui.small_button(label(caption)):
                    self.csharp_request(pid, action)
            if not busy:
                if imgui.shortcut(int(imgui.Key.mod_ctrl) | int(imgui.Key.space)):
                    self.csharp_request(pid, 'complete')
                elif imgui.shortcut(int(imgui.Key.f12)):
                    self.csharp_request(pid, 'definition')
        imgui.end_disabled()
        opened, _ = imgui.begin_popup_modal(label('Reload file') + '###reload-source', None,
                                             imgui.WindowFlags_.always_auto_resize)
        if opened:
            imgui.text_wrapped(tr('Reload file from disk? Unsaved edits will be discarded.'))
            imgui.begin_disabled(busy)
            if imgui.button(label('Reload file')):
                self.reload_file(pid, session['reload_path'])
                imgui.close_current_popup()
            imgui.end_disabled()
            imgui.same_line()
            if imgui.button(label('Cancel##reload')):
                imgui.close_current_popup()
            imgui.end_popup()
        if imgui.begin_popup('###goto-line'):
            _, session['goto_line'] = imgui.input_int(label('Go to line'), session['goto_line'])
            if imgui.button(label('Go')):
                line = min(max(1, session['goto_line']), editor.get_text().count('\n') + 1)
                editor.set_cursor(ed.TextEditor.DocPos(line - 1, 0))
                imgui.close_current_popup()
            imgui.end_popup()

    def draw_csharp(self, pid, session):
        busy = self.app.jobs.busy('ide-' + pid)
        changed, session['csharp_auto'] = imgui.checkbox(label('Analyze C# while editing'), session['csharp_auto'])
        if changed:
            session['csharp_seen'] = None
        imgui.same_line()
        imgui.begin_disabled(busy or not session['active'].endswith('.cs'))
        if imgui.button(label('Analyze C# now')):
            self.csharp_request(pid, 'diagnostics')
        imgui.end_disabled()
        imgui.begin_disabled(busy or self.debug.active(pid) or not session['active'].endswith('.cs'))
        _, session['csharp_name'] = imgui.input_text(label('New symbol name'), session['csharp_name'])
        for action, caption in [('rename', 'Preview semantic rename'), ('references', 'Find symbol references'), ('format', 'Preview C# formatting')]:
            if imgui.button(label(caption)):
                self.csharp_request(pid, action)
            imgui.same_line()
        imgui.new_line()
        for action in ('rename', 'format'):
            result = session['csharp_' + action]
            if result:
                imgui.text(tr('Refactoring changes %d files') % len(result['edits']))
                for edit in result['edits']:
                    if imgui.collapsing_header(edit['path'] + '##refactoring-' + action):
                        import difflib
                        imgui.text_unformatted('\n'.join(difflib.unified_diff(edit['before'].splitlines(), edit['text'].splitlines(), lineterm='')))
                if imgui.button(label('Apply preview to editor buffers') + '##' + action):
                    self.apply_refactoring(pid, action)
        imgui.end_disabled()
        imgui.text_wrapped(tr('Generated files and custom build steps require a build for complete diagnostics.'))
        imgui.begin_disabled(busy or self.debug.active(pid))
        if imgui.button(label('Evaluate project with MSBuild')):
            self.save_all(pid, lambda: self.submit(pid, 'workspace_evaluate',
                {'configuration': ['Debug', 'Release'][session['configuration']]},
                lambda out: session.update(csharp_seen=None, csharp_notes=[], csharp_error='')))
        imgui.end_disabled()
        if session['csharp_error']:
            imgui.text_wrapped(session['csharp_error'])
        imgui.begin_child('###csharp-results', imgui.ImVec2(-1, max(80, imgui.get_content_region_avail().y)))
        completion = session['csharp_completion']
        if completion:
            imgui.text(tr('Completion suggestions: %d') % len(completion['items']))
            for index, item in enumerate(completion['items']):
                if imgui.selectable(item['label'] + '###completion-' + str(index), False)[0]:
                    self.apply_completion(pid, item)
                    break
                if imgui.is_item_hovered():
                    imgui.set_tooltip(item['detail'])
        definition = session['csharp_definition']
        if definition:
            imgui.text_wrapped(definition['symbol'])
            if definition['symbol'] and not definition['definitions']:
                imgui.text_wrapped(tr('This definition belongs to a referenced assembly.'))
            for index, row in enumerate(definition['definitions']):
                caption = '%s:%d' % (row['path'], row['point']['line'])
                if imgui.selectable(caption + '###definition-' + str(index), False)[0]:
                    self.open_file(pid, row['path'], row['point']['line'], row['point']['column'])
        references = session['csharp_references']
        if references:
            for index, row in enumerate(references['references']):
                if imgui.selectable('%s:%d###reference-%d' % (row['path'], row['point']['line'], index), False)[0]:
                    self.open_file(pid, row['path'], row['point']['line'], row['point']['column'])
        symbols = session['csharp_symbols']
        if symbols:
            for index, row in enumerate(symbols['symbols']):
                location = row['location']
                if imgui.selectable(row['name'] + '###symbol-' + str(index), False)[0]:
                    self.open_file(pid, location['path'], location['point']['line'], location['point']['column'])
        diagnostics = session['csharp_diagnostics']
        if diagnostics:
            imgui.text(tr('C# diagnostics: %d') % len(diagnostics['diagnostics']))
            for index, row in enumerate(diagnostics['diagnostics']):
                location = row['location']
                caption = '%s:%d %s: %s' % (location['path'], location['point']['line'], row['code'], row['message'])
                if imgui.selectable(caption + '###csharp-issue-' + str(index), False)[0]:
                    self.open_file(pid, location['path'], location['point']['line'], location['point']['column'])
        for note in session['csharp_notes']:
            imgui.text_wrapped(tr(note))
        imgui.end_child()

    def draw_search(self, pid, session):
        busy = self.app.jobs.busy('ide-' + pid)
        imgui.text_wrapped(tr('Search saved source files. Save edits to include them.'))
        _, session['search_query'] = imgui.input_text(label('Search text'), session['search_query'])
        _, session['search_case'] = imgui.checkbox(label('Match case'), session['search_case'])
        imgui.same_line()
        _, session['search_word'] = imgui.checkbox(label('Whole word'), session['search_word'])
        imgui.same_line()
        imgui.begin_disabled(busy or not session['search_query'] or not session['info'].get('available'))
        if imgui.button(label('Search##source')):
            self.submit(pid, 'workspace_search', {'query': session['search_query'],
                'caseSensitive': session['search_case'], 'wholeWord': session['search_word']},
                lambda out: session.update(search_result=out))
        imgui.end_disabled()
        result = session['search_result']
        if result:
            imgui.text(tr('Source matches: %d') % len(result['matches']))
            if result['truncated']:
                imgui.text_wrapped(tr('Search limit reached. Narrow the search.'))
            if result['skippedFiles']:
                imgui.text(tr('Skipped files: %d') % len(result['skippedFiles']))
            imgui.begin_child('###source-search-results', imgui.ImVec2(-1, max(80, imgui.get_content_region_avail().y)))
            for index, row in enumerate(result['matches']):
                caption = '%s:%d: %s' % (row['path'], row['line'], row['text'])
                if imgui.selectable(caption + '###source-match-' + str(index), False)[0]:
                    self.open_file(pid, row['path'], row['line'], row['column'])
                    session['force_editor'] = True
            imgui.end_child()

    def draw_patch(self, pid, session, busy):
        if self.app.project['format']['format'] == 'pe-dotnet':
            self.draw_managed_patch(pid, session, busy)
            return
        imgui.text_wrapped(tr('Native x86/x64 PE: edit one autonomous C function, preserve its signature and calling convention, then compile and review before writing a modified copy.'))
        imgui.begin_disabled(busy or not self.app.selected)
        if imgui.button(label('Edit selected function')):
            self.start_patch()
        imgui.end_disabled()
        patch = session['patch']
        if not patch:
            imgui.text_wrapped(tr('Select a native function in Workspace, then choose Edit selected function.'))
            self.draw_output(pid, session)
            return
        imgui.text('%s | %s' % (patch['name'], patch['function']))
        _, session['patch_symbol'] = imgui.input_text(label('Replacement function name'), session['patch_symbol'])
        source = session['patch_editor'].get_text()
        plan = session['patch_plan']
        if plan and (plan['source'] != source or plan['symbol'] != session['patch_symbol']):
            session['patch_plan'] = plan = None
        imgui.begin_disabled(busy)
        changed, session['native_extended'] = imgui.checkbox(label('Link larger native function with calls and unwind data'), session['native_extended'])
        if changed:
            session.update(patch_plan=None, patch_receipt=None)
        if session['native_extended']:
            changed, session['native_bindings'] = imgui.input_text(label('Native symbol bindings (JSON)'), session['native_bindings'])
            if changed:
                session.update(patch_plan=None, patch_receipt=None)
        if imgui.button(label('Compile and verify patch')):
            try:
                import json
                bindings = json.loads(session['native_bindings']) if session['native_extended'] else {}
            except ValueError:
                self.error(pid, tr('Invalid native binding JSON.'))
            else:
                self.submit(pid, 'patch_prepare', {'function': patch['function'], 'engine': patch['engine'],
                    'source': source, 'symbol': session['patch_symbol'], 'extended': session['native_extended'], 'bindings': bindings},
                    lambda out: session.update(patch_plan=out, patch_receipt=None))
        imgui.end_disabled()
        _, session['patch_destination'] = imgui.input_text(label('Modified copy path (optional)'), session['patch_destination'])
        if plan:
            if plan.get('kind') == 'native-linked':
                imgui.text(tr('Appended native section: %d bytes; redirected entry: %d bytes') % (plan['size'], plan['redirectedBytes']))
            else:
                imgui.text(tr('Replacement size: %d / %d bytes') % (plan['size'], plan['capacity']))
            imgui.text_wrapped(tr(plan['note']))
            if imgui.collapsing_header(label('Compiled instructions')):
                imgui.text_unformatted(plan['disassembly'])
            imgui.begin_disabled(busy)
            if imgui.button(label('Write modified copy')):
                self.submit(pid, 'patch_apply', {'planId': plan['planId'], 'destination': session['patch_destination']},
                            lambda out: session.update(patch_receipt=out))
            imgui.end_disabled()
        self.draw_modified_copy(pid, session, busy)
        self.palette(session['patch_editor'])
        self.render(session['patch_editor'], '###patch-source', imgui.ImVec2(-1, max(100, imgui.get_content_region_avail().y - 150)))
        self.draw_output(pid, session)

    def draw_managed_patch(self, pid, session, busy):
        imgui.text_wrapped(tr('.NET: edit the C# project, select one method, then build and verify its replacement in the original assembly.'))
        imgui.begin_disabled(busy)
        if imgui.button(label('Load .NET methods')):
            self.load_managed_methods(pid)
        imgui.end_disabled()
        listing = session['managed']
        if not listing:
            self.draw_output(pid, session)
            return
        methods = listing['methods']
        if not methods:
            imgui.text_wrapped(tr('No methods found for this type. Load all .NET methods.'))
            return
        imgui.text(tr('Method to replace'))
        imgui.set_next_item_width(-1)
        imgui.begin_disabled(busy)
        changed, session['managed_index'] = imgui.combo('##managed-method', session['managed_index'],
                                                       [m['signature'] for m in methods])
        imgui.end_disabled()
        if changed:
            session.update(patch_plan=None, patch_receipt=None)
        method = methods[session['managed_index']]
        imgui.text(method['id'])
        if method.get('generatedKind') == 'helper':
            imgui.text_wrapped(tr('Generated helper: select its owning source method.'))
        imgui.begin_disabled(busy)
        if imgui.button(label('Edit declaring type')):
            self.edit_managed_type(pid, method)
        imgui.end_disabled()
        imgui.begin_disabled(busy)
        changed, session['managed_donor'] = imgui.input_text(label('Rebuilt assembly relative to project (optional)'), session['managed_donor'])
        if changed:
            session.update(patch_plan=None, patch_receipt=None)
        if listing.get('signed'):
            changed, session['remove_strong_name'] = imgui.checkbox(label('Allow removing the strong-name signature'), session['remove_strong_name'])
            if changed:
                session.update(patch_plan=None, patch_receipt=None)
            imgui.text_wrapped(tr('Removing a strong-name signature can break dependent assemblies. Re-sign with the original key when required.'))
        imgui.end_disabled()
        imgui.begin_disabled(busy)
        for key, caption in [('allow_new_members', 'Import new referenced .NET members'), ('patch_symbols', 'Generate symbols for the modified copy')]:
            changed, session[key] = imgui.checkbox(label(caption), session[key])
            if changed:
                session.update(patch_plan=None, patch_receipt=None)
        imgui.end_disabled()
        imgui.begin_disabled(busy or not method['editable'] or not session['info'].get('available'))
        if imgui.button(label('Build and verify method patch')):
            def prepare():
                self.submit(pid, 'managed_patch_prepare', {'methodId': method['id'], 'donor': session['managed_donor'],
                    'configuration': ['Debug', 'Release'][session['configuration']],
                    'removeStrongName': session['remove_strong_name'], 'targetProject': session['target_project'],
                    'allowNewMembers': session['allow_new_members'], 'symbols': session['patch_symbols']},
                    lambda out: session.update(patch_plan=out, patch_receipt=None))
            self.save_all(pid, prepare)
        imgui.end_disabled()
        plan = session['patch_plan']
        dirty = any(self.dirty(tab) for tab in session['tabs'].values())
        _, session['patch_destination'] = imgui.input_text(label('Modified copy path (optional)'), session['patch_destination'])
        if plan:
            imgui.text(tr('IL size: %d -> %d bytes; %d other methods verified unchanged') %
                       (plan['capacity'], plan['size'], plan['unchangedMethods']))
            if plan.get('generatedTypes') or plan.get('generatedMethods'):
                imgui.text(tr('Generated helpers: %d types, %d methods') %
                           (len(plan.get('generatedTypes', [])), len(plan.get('generatedMethods', []))))
                if imgui.collapsing_header(label('Added generated dependencies')):
                    for name in plan.get('generatedTypes', []) + plan.get('generatedMethods', []):
                        imgui.text_wrapped(name)
            if plan.get('addedTypes') or plan.get('addedMethods') or plan.get('addedFields'):
                if imgui.collapsing_header(label('All added .NET dependencies')):
                    for name in plan.get('addedTypes', []) + plan.get('addedMethods', []) + plan.get('addedFields', []):
                        imgui.text_wrapped(name)
            imgui.text_wrapped(tr(plan['note']))
            if imgui.collapsing_header(label('Compiled instructions')):
                imgui.text_unformatted(plan['disassembly'])
            imgui.begin_disabled(busy or dirty)
            if imgui.button(label('Write modified copy')):
                self.submit(pid, 'patch_apply', {'planId': plan['planId'], 'destination': session['patch_destination']},
                            lambda out: session.update(patch_receipt=out))
            imgui.end_disabled()
            if dirty:
                imgui.text_wrapped(tr('Save and prepare the patch again after source changes.'))
        self.draw_modified_copy(pid, session, busy)
        self.draw_output(pid, session)

    def draw_modified_copy(self, pid, session, busy):
        receipt = session['patch_receipt']
        copies = session['copies']
        if copies:
            ids = [row['receiptId'] for row in copies]
            current = ids.index(receipt['receiptId']) if receipt and receipt.get('receiptId') in ids else 0
            imgui.begin_disabled(busy)
            changed, current = imgui.combo(label('Saved modified copies'), current,
                [Path(row['path']).name + ' | ' + row['receiptId'][:8] for row in copies])
            imgui.end_disabled()
            if changed or receipt is None:
                session['patch_receipt'] = receipt = copies[current]
        if not receipt:
            return
        imgui.text_wrapped(tr('Modified copy: ') + receipt['path'])
        if receipt.get('sourceCommit'):
            imgui.text(tr('Source commit: ') + receipt['sourceCommit'][:12])
        if receipt.get('symbols'):
            imgui.begin_disabled(busy or self.debug.active(pid))
            if imgui.button(label('Debug modified copy')):
                self.debug.start(pid, receipt['receiptId'])
            imgui.end_disabled()
        imgui.begin_disabled(busy)
        if imgui.button(label('Analyze modified copy')):
            self.app.open_path(receipt['path'])
        if receipt.get('launchKind') == 'library':
            imgui.end_disabled()
            imgui.text_wrapped(tr('This copy is a library. Run it through a source project test harness.'))
            return
        _, session['copy_arguments'] = imgui.input_text(label('Run arguments'), session['copy_arguments'])
        imgui.set_next_item_width(120)
        _, session['copy_timeout'] = imgui.input_int(label('Run timeout (seconds)'), session['copy_timeout'])
        session['copy_timeout'] = min(900, max(1, session['copy_timeout']))
        if imgui.button(label('Run modified copy')):
            from cydec.workspace import parse_arguments
            try:
                arguments = parse_arguments(session['copy_arguments'])
            except ValueError:
                self.error(pid, tr('Invalid run arguments.'))
            else:
                self.submit(pid, 'patch_run', {'receiptId': receipt['receiptId'], 'arguments': arguments,
                                             'timeout': session['copy_timeout']})
        imgui.end_disabled()
