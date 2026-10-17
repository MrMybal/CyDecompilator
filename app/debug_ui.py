"""Debugger controls and presentation; filesystem/process work stays in Runtime jobs."""
import time
from pathlib import Path

import cyui
from ui_common import imgui, label, tr


class DebugUI:
    def __init__(self, ide):
        self.ide, self.app = ide, ide.app

    def init(self, session):
        session.update(debug={'status': 'idle', 'sessionId': ''}, debug_rows=[], debug_children={},
                       debug_poll=0, debug_inspected=None, debug_stop_entry=False, debug_executable='',
                       debug_error='', debug_console=self.ide.make_editor(), debug_marker=None)

    def active(self, pid):
        state = self.ide.sessions[pid]['debug']
        return self.app.jobs.busy('debug-launch-' + pid) or state['status'] in ('building', 'starting', 'paused', 'running')

    def accept(self, pid, out):
        session = self.ide.sessions[pid]
        if out.get('status') == 'idle' and self.app.jobs.busy('debug-launch-' + pid):
            return
        previous = session['debug']
        if out.get('sessionId') and previous.get('sessionId'):
            if out.get('startedAt', 0) < previous.get('startedAt', 0):
                return
            if out['sessionId'] == previous['sessionId'] and out.get('snapshotSequence', 0) < previous.get('snapshotSequence', 0):
                return
        changed = (previous.get('sessionId'), previous.get('stopId')) != (out.get('sessionId'), out.get('stopId'))
        if changed or out['status'] != 'paused':
            session['debug_children'] = {}
        # The lightweight status snapshot does not carry the source-check field.
        if not changed and previous.get('sourceChanged'):
            out['sourceChanged'] = True
        session['debug'] = out
        if 'output' in out:
            session['debug_console'].set_text(out['output'])
        if out['status'] == 'idle':
            session['debug_rows'] = out.get('breakpoints', [])
        if out['status'] in ('terminated', 'failed', 'cancelled'):
            session['debug_inspected'] = None
        if out['status'] == 'paused' and not self.app.jobs.busy('debug-control-' + pid):
            stamp = (out['sessionId'], out['stopId'])
            if session['debug_inspected'] != stamp:
                session['debug_inspected'] = stamp
                self.command(pid, 'inspect', navigate=True)

    def tick(self):
        now = time.monotonic()
        for pid, session in list(self.ide.sessions.items()):
            if not session['info'].get('available'):
                continue
            if now < session['debug_poll'] or self.app.jobs.busy('debug-status-' + pid):
                continue
            session['debug_poll'] = now + (.4 if self.active(pid) else 3)
            self.app.jobs.submit('debug_status', {'projectId': pid}, tag='debug-status-' + pid,
                done=lambda out, pid=pid: self.accept(pid, out),
                failed=lambda error, session=session: session.update(debug_error=error), timeout=30)

    def start(self, pid, receipt_id=''):
        session = self.ide.sessions[pid]
        from cydec.workspace import parse_arguments
        try:
            args = parse_arguments(session['arguments'])
        except ValueError as exc:
            session['debug_error'] = str(exc)
            return
        def saved():
            session.update(debug={'status': 'building', 'sessionId': ''}, debug_error='',
                           debug_inspected=None, debug_children={}, force_debug=True)
            session['debug_console'].set_text('')
            def failed(error):
                session['debug_error'] = error
                session['debug'] = dict(session['debug'], status='failed')
                session['force_debug'] = True
            self.app.jobs.submit('debug_start', {'projectId': pid, 'targetProject': session['target_project'],
                'executable': session['debug_executable'], 'arguments': args, 'receiptId': receipt_id,
                'breakpoints': session['debug_rows'], 'stopAtEntry': session['debug_stop_entry'], 'timeout': 1800},
                tag='debug-launch-' + pid, done=lambda out: self.accept(pid, out), failed=failed,
                streamed=lambda text: session['debug_console'].set_text(text), timeout=None)
        self.ide.save_all(pid, saved)

    def command(self, pid, action, navigate=False, **parameters):
        session = self.ide.sessions[pid]
        state = session['debug']
        if self.app.jobs.busy('debug-control-' + pid):
            return
        session['debug_error'] = ''
        def done(out):
            self.accept(pid, out)
            current = session['debug']
            if (out['sessionId'], out.get('stopId')) != (current['sessionId'], current.get('stopId')):
                return
            if action == 'variables':
                session['debug_children'][out['variablesReference']] = out.get('children', [])
            if navigate and out.get('frames') and not out.get('sourceChanged'):
                frame = next((f for f in out['frames'] if f['id'] == out.get('frameId')), out['frames'][0])
                if frame.get('path'):
                    self.ide.open_file(pid, frame['path'], frame['line'], frame.get('column', 1))
            session['force_debug'] = True
        self.app.jobs.submit('debug_control', dict(parameters, projectId=pid,
            sessionId=state['sessionId'], stopId=state.get('stopId', 0), action=action),
            tag='debug-control-' + pid, done=done,
            failed=lambda error: session.update(debug_error=error), timeout=30)

    def stop(self, pid):
        # Cancellation remains available even during compilation, protocol setup or a stuck request.
        if self.app.jobs.busy('debug-launch-' + pid):
            self.app.jobs.cancel('debug-launch-' + pid)
        elif self.ide.sessions[pid]['debug'].get('sessionId'):
            self.command(pid, 'stop')

    def toggle(self, pid, path=None, line=None):
        session = self.ide.sessions[pid]
        path = path or session['active']
        if path not in session['tabs'] or Path(path).suffix.lower() != '.cs':
            return
        if self.ide.dirty(session['tabs'][path]):
            session['debug_error'] = tr('Save this file before setting a breakpoint.')
            session['force_debug'] = True
            return
        line = line or session['tabs'][path]['editor'].get_main_cursor_position().line + 1
        row = {'path': path, 'line': line}
        rows = list(session['debug_rows'])
        if row in rows:
            rows.remove(row)
        else:
            rows.append(row)
        self.set_rows(pid, rows)

    def set_rows(self, pid, rows):
        session = self.ide.sessions[pid]
        if self.app.jobs.busy('debug-control-' + pid):
            return
        if self.active(pid):
            if session['debug'].get('sessionId') and session['debug']['status'] in ('paused', 'running'):
                def done(out):
                    session['debug_rows'] = rows
                    self.accept(pid, out)
                self.app.jobs.submit('debug_control', {'projectId': pid, 'sessionId': session['debug']['sessionId'],
                    'action': 'breakpoints', 'breakpoints': rows}, tag='debug-control-' + pid,
                    done=done, failed=lambda error: session.update(debug_error=error), timeout=30)
        else:
            self.app.jobs.submit('debug_breakpoints', {'projectId': pid, 'breakpoints': rows}, tag='debug-control-' + pid,
                done=lambda out: session.update(debug_rows=out['breakpoints'], debug_marker=None),
                failed=lambda error: session.update(debug_error=error), timeout=30)

    def markers(self, pid, path, editor):
        session = self.ide.sessions[pid]
        state = session['debug']
        active = self.active(pid)
        editor.set_read_only_enabled(active)
        current = next((f for f in state.get('frames', []) if f['id'] == state.get('frameId')
                        and f.get('path') == path), None) if state['status'] == 'paused' and not state.get('sourceChanged') else None
        stamp = (path, repr(session['debug_rows']), state.get('stopId'), state['status'], state.get('frameId'),
                 session['tabs'][path]['revision'], repr(current))
        if session['debug_marker'] == stamp:
            return
        session['debug_marker'] = stamp
        editor.clear_markers()
        lines = {row['line'] for row in session['debug_rows'] if row['path'] == path}
        for line in sorted(lines | ({current['line']} if current else set())):
            here = current and current['line'] == line
            tooltip = tr('Current instruction') if here else tr('Breakpoint')
            editor.add_marker(max(0, line - 1), 0xFF5050EE if line in lines else 0xFF40CCFF,
                              0x4040CCFF if here else 0, tooltip, tr('Current instruction') if here else '')

    def shortcuts(self, pid):
        session = self.ide.sessions[pid]
        state = session['debug']
        active = self.active(pid)
        busy = self.app.jobs.busy('debug-control-' + pid)
        if imgui.shortcut(int(imgui.Key.mod_shift) | int(imgui.Key.f5)) and active:
            self.stop(pid)
        elif imgui.shortcut(int(imgui.Key.f5)) and not busy:
            if state['status'] == 'paused':
                self.command(pid, 'continue')
            elif not active and not self.app.jobs.busy('ide-' + pid):
                if Path(session['target_project'] or session['info'].get('entry', '')).suffix == '.csproj':
                    self.start(pid)
        if state['status'] == 'paused' and not busy:
            if imgui.shortcut(int(imgui.Key.f10)):
                self.command(pid, 'next')
            elif imgui.shortcut(int(imgui.Key.mod_shift) | int(imgui.Key.f11)):
                self.command(pid, 'stepOut')
            elif imgui.shortcut(int(imgui.Key.f11)):
                self.command(pid, 'stepIn')
        if not busy and state['status'] not in ('building', 'starting'):
            if imgui.shortcut(int(imgui.Key.f9)):
                self.toggle(pid)

    def draw(self, pid, session):
        state = session['debug']
        active, paused = self.active(pid), state['status'] == 'paused'
        busy = self.app.jobs.busy('debug-control-' + pid)
        installed = any(c['id'] == 'netcoredbg' and c['installed'] for c in self.app.components)
        if not installed:
            imgui.text_wrapped(tr('Install NetCoreDbg to debug reconstructed .NET projects.'))
            imgui.begin_disabled(self.app.jobs.busy('install'))
            if imgui.small_button(label('Install debugger')):
                self.app.jobs.submit('install_component', {'component': 'netcoredbg'}, tag='install',
                    done=lambda out: self.app.refresh_components(),
                    failed=lambda error: session.update(debug_error=error), timeout=None)
            imgui.end_disabled()
            self.app.jobs.progress_widget('install')
        imgui.text(tr('Debugger: ') + tr(state['status']))
        imgui.same_line()
        imgui.begin_disabled(not active)
        if imgui.small_button(label('Stop debugging')):
            self.stop(pid)
        imgui.end_disabled()
        imgui.begin_disabled(busy or not active or state['status'] in ('building', 'starting'))
        if imgui.small_button(label('Continue (F5)' if paused else 'Pause')):
            self.command(pid, 'continue' if paused else 'pause')
        imgui.end_disabled()
        imgui.same_line()
        imgui.begin_disabled(busy or not paused)
        for action, caption in [('next', 'Step over (F10)'), ('stepIn', 'Step into (F11)'), ('stepOut', 'Step out (Shift+F11)')]:
            if imgui.small_button(label(caption)):
                self.command(pid, action)
            imgui.same_line()
        imgui.end_disabled()
        imgui.new_line()
        imgui.begin_disabled(busy or state['status'] in ('building', 'starting'))
        if imgui.small_button(label('Toggle breakpoint (F9)')):
            self.toggle(pid)
        imgui.end_disabled()
        if session['debug_error'] or state.get('error'):
            imgui.text_wrapped(session['debug_error'] or state['error'])
        if state.get('sourceChanged'):
            imgui.text_wrapped(tr('Sources changed on disk. Restart debugging to restore source correspondence.'))
        if active:
            imgui.text_wrapped(tr('Source files are read-only during debugging. Stop to edit and rebuild.'))
        if state.get('exitCode') is not None:
            imgui.text(tr('Exit code: %d') % state['exitCode'])
        if imgui.begin_tab_bar('###debug-details'):
            opened, _ = imgui.begin_tab_item(label('Stack and variables'))
            if opened:
                self.stack_and_variables(pid, session, busy)
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Breakpoints'))
            if opened:
                for index, row in enumerate(session['debug_rows']):
                    imgui.push_id(index)
                    imgui.begin_disabled(busy or state['status'] in ('building', 'starting'))
                    if imgui.small_button(label('Remove')):
                        self.set_rows(pid, [r for r in session['debug_rows'] if r != row])
                    imgui.end_disabled()
                    imgui.same_line()
                    bound = next((b for b in state.get('breakpoints', []) if b['path'] == row['path'] and b.get('line') == row['line']), {})
                    text = '%s:%d' % (row['path'], row['line'])
                    if active:
                        text += ' — ' + tr('Verified' if bound.get('verified') else 'Pending')
                    if imgui.selectable(text, False)[0]:
                        self.ide.open_file(pid, row['path'], row['line'])
                    if bound.get('message'):
                        imgui.text_wrapped(bound['message'])
                    imgui.pop_id()
                imgui.end_tab_item()
            opened, _ = imgui.begin_tab_item(label('Debug console'))
            if opened:
                self.ide.palette(session['debug_console'])
                self.ide.render(session['debug_console'], '###debug-console', imgui.ImVec2(-1, max(70, imgui.get_content_region_avail().y)))
                imgui.end_tab_item()
            imgui.end_tab_bar()

    def stack_and_variables(self, pid, session, busy):
        state = session['debug']
        if not state.get('frames'):
            imgui.text_wrapped(tr('Pause at a breakpoint to inspect the stack and local variables.'))
            return
        threads = state.get('threads', [])
        if len(threads) > 1:
            current = next((i for i, t in enumerate(threads) if t['id'] == state.get('threadId')), 0)
            imgui.begin_disabled(busy)
            changed, current = imgui.combo(label('Thread'), current, [t['name'] for t in threads])
            if changed:
                self.command(pid, 'inspect', threadId=threads[current]['id'], navigate=True)
            imgui.end_disabled()
        if imgui.begin_table('###debug-layout', 2, imgui.TableFlags_.resizable | imgui.TableFlags_.borders_inner_v):
            imgui.table_setup_column(tr('Call stack'), imgui.TableColumnFlags_.width_stretch, .45)
            imgui.table_setup_column(tr('Local variables'), imgui.TableColumnFlags_.width_stretch, .55)
            imgui.table_headers_row()
            imgui.table_next_row()
            imgui.table_next_column()
            imgui.begin_child('###debug-stack', imgui.ImVec2(0, max(70, imgui.get_content_region_avail().y)))
            for frame in state['frames']:
                caption = frame['name'] + (' — %s:%d' % (Path(frame['path']).name, frame['line']) if frame.get('path') else '')
                imgui.begin_disabled(busy)
                if imgui.selectable(caption + '###frame-' + str(frame['id']), frame['id'] == state.get('frameId'))[0]:
                    self.command(pid, 'inspect', frameId=frame['id'], navigate=True)
                imgui.end_disabled()
            imgui.end_child()
            imgui.table_next_column()
            imgui.begin_child('###debug-variables', imgui.ImVec2(0, max(70, imgui.get_content_region_avail().y)))
            def variable(row, key, depth=0):
                caption = '%s = %s' % (row['name'], row.get('value', ''))
                reference = row.get('variablesReference', 0)
                if reference and depth < 8:
                    opened = imgui.tree_node(caption + '###' + key)
                    if opened:
                        if reference not in session['debug_children'] and not busy:
                            self.command(pid, 'variables', variablesReference=reference)
                        for index, child in enumerate(session['debug_children'].get(reference, [])):
                            variable(child, key + '-' + str(index), depth + 1)
                        imgui.tree_pop()
                else:
                    imgui.text(caption)
                if imgui.is_item_hovered() and row.get('type'):
                    imgui.set_tooltip(row['type'])
            for index, row in enumerate(state.get('variables', [])):
                variable(row, str(index))
            imgui.end_child()
            imgui.end_table()
