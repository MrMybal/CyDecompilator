"""Investigation frontend. Analysis, reads and captures are Runtime jobs."""
import json
import cyui
from imgui_bundle import portable_file_dialogs as pfd, hello_imgui
from ui_common import imgui, label, tr

STEP_CAPTIONS={'click':'Click control','fill':'Fill text','waitFor':'Wait for control','assertText':'Check text',
    'snapshot':'Take screenshot','wait':'Wait','toggle':'Toggle control','select':'Select control','press':'Press key','navigate':'Navigate'}

LIMIT_MESSAGES = {
    'external-files-not-observed': 'Files outside the working directory are not observed.',
    'network-and-gui-observation-disabled': 'Network and graphical recording were disabled.',
    'tcp-sampling-can-miss-short-connections': 'TCP sampling can miss short connections; UDP and payloads are not recorded.',
    'http-capture-selected-renderer-only': 'HTTP recording covers the selected renderer; other processes and pages are outside its scope.',
    'renderer-startup-before-attachment-not-observed': 'Electron activity before renderer attachment is not observed.',
    'native-screenshots-provider-dependent': 'Windows screenshots depend on the application window provider.',
    'network-observation-denied': 'The operating system denied network observation.',
    'network-connection-limit': 'The TCP connection recording reached its limit.',
    'network-request-limit': 'The HTTP request recording reached its limit.',
    'network-requests-unfinished': 'Some HTTP requests were still pending at the end of the scenario.',
    'dom-element-limit': 'The DOM snapshot reached its element limit.',
    'dom-text-limit': 'The page text snapshot reached its character limit.',
    'console-entry-limit': 'The renderer console recording reached its entry limit.',
    'uia-element-limit': 'The Windows control snapshot reached its element limit.',
    'window-count-limit': 'The window snapshot reached its window limit.',
    'screenshot-unavailable': 'A screenshot could not be captured.',
    'static-analysis-does-not-prove-execution': 'Static relationships do not prove execution.',
    'dynamic-code-and-framework-routing-not-resolved': 'Dynamic code and framework routing are not fully resolved.',
    'native-types-are-analysis-results': 'Native types come from Ghidra analysis and may need correction.',
    'aliasing-indirect-calls-and-cross-function-values-not-resolved': 'Aliases, indirect calls and values across functions remain unresolved.',
    'external-files-network-and-gui-not-observed': 'External files, network traffic and GUI interactions are not captured.',
    'batch-stdin-not-timed-interaction': 'Input is a finite stdin batch; timed interactions are not captured.',
    'matching-observations-do-not-prove-equivalence': 'Matching observations do not prove application equivalence.',
    'har-does-not-prove-handler-execution': 'HAR correlations do not prove handler execution.',
    'excluded-directory': 'Directory excluded from the snapshot.',
    'excluded-link': 'Link excluded from the snapshot.',
    'snapshot-limit': 'Artifact omitted because the snapshot limit was reached.',
    'source-parser-limit': 'Source omitted because the parser limit was reached.',
    'graph-node-limit': 'The evidence graph reached its node limit.',
    'graph-edge-limit': 'The evidence graph reached its relationship limit.',
    'ast-fact-limit': 'The source reached its AST fact limit.',
    'native-dossier-limit': 'The native dossier reached its instruction or value limit.',
    'native-values-unavailable': 'Ghidra could not recover value dependencies.',
    'unresolved-artifact': 'Artifact reference could not be resolved uniquely.',
    'ambiguous-or-missing-ipc-handler': 'The IPC handler is missing or ambiguous.',
    'ambiguous-receiver-binding': 'A shadowed receiver cannot be attributed reliably.',
    'ambiguous-bridge-api': 'The exposed bridge API is ambiguous.',
    'dynamic-module': 'Dynamic module reference remains unresolved.',
    'dynamic-ipc': 'Dynamic IPC channel remains unresolved.',
    'dynamic-preload': 'Dynamic preload path remains unresolved.',
    'dynamic-endpoint': 'Dynamic route or endpoint remains unresolved.',
    'syntax-error': 'The source contains a syntax error.',
    'invalid-source-map': 'The source map could not be decoded.',
    'indexed-source-map-not-supported': 'Indexed source maps are not supported.',
    'unresolved-source-map': 'Source map is absent or external; it was not fetched.',
    'missing-unpacked-file': 'An ASAR unpacked file is missing.',
    'har-entry-limit': 'The HAR recording reached its entry limit.',
    'capture-file-not-observed': 'A capture file could not be observed within the limits.',
    'capture-link-not-followed': 'A capture link was not followed.',
    'executable-changed-during-capture': 'The executable changed during capture.',
    'argument-file-changed-during-capture': 'An argument file changed during capture.',
    'snapshot-exclusion-limit': 'The snapshot reached its exclusion reporting limit.',
}


class InvestigationUI:
    def __init__(self, app, make_editor, set_language, palette, render):
        self.app = app
        self.make_editor, self.set_language, self.palette, self.render = make_editor, set_language, palette, render
        self.sessions, self.application_path, self.dialog = {}, '', None
        self.force_mode = ''
        self.force_results = ''

    def state(self):
        pid = self.app.project['projectId']
        if pid not in self.sessions:
            self.sessions[pid] = {'query': '', 'depth': 2, 'report': {}, 'selected': None,
                'source': self.make_editor(), 'source_path': '', 'error': '', 'har': '', 'dossier': {},
                'executables': ['', ''], 'arguments': ['[]', '[]'], 'stdin': '', 'assets': '',
                'seeds': '{}', 'timeout': 60, 'captures': [], 'chosen': ['', ''], 'comparison': {},
                'driver':0,'network':False,'headless':False,'url':'','target_url':'','steps':'[]',
                'settle':500,'evidence':{},'frame':0,
                'step_edit':-1,'step_action':0,'step_selector':'','step_id':'','step_name':'','step_type':'',
                'step_text':'','step_url':'','step_ms':500,'step_timeout':5000,'step_key':0,
                'comparison_editor': self.make_editor()}
        return pid, self.sessions[pid]

    def submit(self, pid, state, operation, parameters, done):
        state['error'] = ''
        return self.app.jobs.submit(operation, {'projectId': pid, **parameters}, tag='investigation-' + pid,
            done=done, failed=lambda message: state.update(error=message), timeout=1200)

    def query(self, pid, state):
        self.submit(pid, state, 'investigation_query', {'query': state['query'], 'depth': state['depth'], 'limit': 300},
                    lambda result: state.update(report=result, selected=None))

    def open_application(self):
        path = self.application_path.strip().strip('"')
        if not path:
            return
        def done(result):
            self.app.refresh_projects()
            self.app.load_project(result['projectId'], 'javascript')
            self.app.force_tab = 'investigation'
        self.app.jobs.submit('application_open', {'path': path}, tag='application-open', done=done, timeout=1200)

    def select(self, pid, state, row):
        state['selected'] = row
        location = row['location']
        path = location.get('path')
        if path and self.app.engine == 'javascript' and row['kind'] not in ('original-source', 'original-position'):
            def loaded(out):
                if state['selected'] and state['selected']['id'] == row['id']:
                    state['source_path'] = out['path']
                    state['source'].set_text(out['text'])
                    self.set_language(state['source'], 'javascript')
                    self.palette(state['source'])
                    # Keep source locations one-based in the contract; editor coordinates are zero-based.
                    from imgui_bundle import imgui_color_text_edit as ed
                    state['source'].set_cursor_position(ed.TextEditor.Coordinates(max(0,location.get('line',1)-1), max(0,location.get('column',1)-1)))
            self.submit(pid, state, 'investigation_source', {'path': path}, loaded)

    def draw(self):
        if self.dialog is not None and self.dialog.ready():
            self.application_path = self.dialog.result() or self.application_path
            self.dialog = None
        cyui.panel_header(tr('Investigation'))
        if cyui.begin_properties('###application-properties', 220):
            cyui.property(tr('Application folder or ASAR'))
            _, self.application_path = imgui.input_text('###application-path', self.application_path)
            cyui.end_properties()
        if imgui.button(label('Choose application folder')):
            self.dialog = pfd.select_folder(tr('Choose application folder'), self.application_path)
        imgui.same_line()
        imgui.begin_disabled(self.app.jobs.busy('application-open'))
        if cyui.primary_button(label('Analyze application')):
            self.open_application()
        imgui.end_disabled()
        imgui.same_line()
        if imgui.button(label('Install JS parser')):
            self.app.jobs.submit('install_component', {'component': 'typescript'}, tag='install-js-parser',
                                 done=lambda out: self.app.refresh_components(True), timeout=1200)
        if not self.app.project:
            imgui.text_wrapped(tr('Open an application or a binary to investigate features and compare versions.'))
            return
        pid, state = self.state()
        imgui.text(self.app.project['name'])
        if state['error']:
            imgui.text_wrapped(tr(state['error']))
        if self.app.jobs.busy('investigation-' + pid):
            imgui.same_line()
            if imgui.button(label('Cancel investigation')):
                self.app.jobs.cancel('investigation-' + pid)
        requested, self.force_mode = self.force_mode, ''
        if imgui.begin_tab_bar('###investigation-modes'):
            for key, caption, draw in (('evidence', 'Feature evidence', self.evidence), ('behavior', 'Version behavior', self.behavior)):
                opened, _ = imgui.begin_tab_item(label(caption), None,
                    imgui.TabItemFlags_.set_selected if requested == key else 0)
                if opened:
                    draw(pid, state)
                    imgui.end_tab_item()
            imgui.end_tab_bar()

    def limits(self, rows):
        opened = imgui.collapsing_header(label('Limits and unknowns') + ' (%d)' % len(rows))
        if opened:
            for row in rows[:80]:
                imgui.bullet_text(tr(LIMIT_MESSAGES.get(row['code'], row['code'])) +
                    (' — ' + str(row.get('path') or row.get('channel') or row.get('value') or row.get('receiver') or '')
                     if any(k in row for k in ('path','channel','value','receiver')) else ''))

    def evidence(self, pid, state):
        imgui.set_next_item_width(cyui.dp(300))
        _, state['query'] = imgui.input_text(label('Feature, symbol or endpoint'), state['query'])
        imgui.same_line()
        imgui.set_next_item_width(cyui.dp(130))
        _, state['depth'] = imgui.slider_int(label('Relation depth'), state['depth'], 0, 4)
        imgui.same_line()
        busy = self.app.jobs.busy('investigation-' + pid)
        imgui.begin_disabled(busy)
        if imgui.button(label('Trace evidence')):
            self.query(pid, state)
        if self.app.selected and self.app.engine == 'ghidra':
            imgui.same_line()
            if imgui.button(label('Inspect selected native function')):
                def inspected(out):
                    state['dossier'] = out['dossier']
                    state['query'] = out['dossier']['name']
                    state['depth'] = 3
                    self.query(pid, state)
                self.submit(pid, state, 'investigation_native', {'function': self.app.selected['id']}, inspected)
        imgui.end_disabled()
        imgui.set_next_item_width(cyui.dp(470))
        _, state['har'] = imgui.input_text(label('HAR recording path'), state['har'])
        imgui.same_line()
        imgui.begin_disabled(busy or not state['har'])
        if imgui.button(label('Correlate HAR')):
            self.submit(pid, state, 'investigation_har', {'path': state['har']}, lambda out: state.update(report=out))
        imgui.end_disabled()
        report = state['report']
        if not report:
            imgui.text_wrapped(tr('Analyze JavaScript artifacts or inspect a function from a Ghidra analysis, then trace a feature.'))
            return
        imgui.text(tr('Evidence nodes: %d | Matching nodes: %d') % (len(report['nodes']), report['matches']))
        if report.get('truncated'):
            imgui.text_wrapped(tr('Partial result: a query or analysis limit was reached.'))
        self.limits(report['unknowns'])
        if imgui.begin_table('###evidence-layout', 2, imgui.TableFlags_.resizable):
            imgui.table_setup_column('###facts', imgui.TableColumnFlags_.width_fixed, 570)
            imgui.table_setup_column('###proof')
            imgui.table_next_row()
            imgui.table_set_column_index(0)
            imgui.begin_child('###evidence-list', imgui.ImVec2(0, max(200,imgui.get_content_region_avail().y)), True)
            for row in report['nodes']:
                location = row['location']
                suffix = location.get('address') or (location.get('path','') + (':%s' % location['line'] if 'line' in location else ''))
                caption = '%s · %s' % (row['kind'], row['label'].replace('\n', ' ')[:95])
                clicked, _ = imgui.selectable(caption + '###fact-' + row['id'], state['selected'] is not None and state['selected']['id'] == row['id'])
                if clicked:
                    self.select(pid, state, row)
                if imgui.is_item_hovered():
                    imgui.set_tooltip(suffix)
            imgui.end_child()
            imgui.table_set_column_index(1)
            imgui.begin_child('###evidence-details', imgui.ImVec2(0, max(200,imgui.get_content_region_avail().y)), False)
            selected = state['selected']
            if selected:
                imgui.text_wrapped(selected['label'])
                imgui.text(tr('Evidence status: ') + tr({'static':'Static analysis', 'inferred':'Inference', 'observed':'Runtime observation'}[selected['status']]))
                imgui.text_wrapped(tr('Source evidence: ') + json.dumps(selected['evidence'], ensure_ascii=False))
                paths = report['paths'].get(selected['id'], []) or [r for r in report['edges']
                    if selected['id'] in (r['source'],r['target'])][:12]
                if paths:
                    imgui.text(tr('Relationship path'))
                    names = {r['id']:r['label'] for r in report['nodes']}
                    for relation in paths:
                        status={'static':'Static analysis','inferred':'Inference','observed':'Runtime observation'}[relation['status']]
                        imgui.text_wrapped('%s → %s → %s [%s]' % (names.get(relation['source'],''),relation['kind'],names.get(relation['target'],''),tr(status)))
                if selected['details']:
                    opened = imgui.collapsing_header(label('Analysis details'))
                    if opened:
                        imgui.text_wrapped(json.dumps(selected['details'], ensure_ascii=False, indent=2))
                if selected['kind'] == 'function' and selected['details'].get('functionId'):
                    if imgui.button(label('Open function')):
                        target = next((f for f in self.app.functions if f['id']==selected['details']['functionId']),None)
                        if target:
                            self.app.open_function(target)
                            self.app.force_tab = 'workspace'
                if state['source_path'] == selected['location'].get('path'):
                    imgui.separator()
                    self.render(state['source'], '###investigation-source', imgui.ImVec2(0, max(180,imgui.get_content_region_avail().y)))
            imgui.end_child()
            imgui.end_table()

    def capture(self, pid, state, index):
        try:
            arguments, seeds, steps = json.loads(state['arguments'][index]), json.loads(state['seeds']), json.loads(state['steps'])
            if not isinstance(arguments, list) or not isinstance(seeds, dict) or not isinstance(steps,list):
                raise ValueError()
        except (ValueError, TypeError):
            state['error'] = tr('Use JSON arrays for arguments and steps, and a JSON object for seed files.')
            return
        def recorded(out):
            state['chosen'][index] = out['captureId']
            self.refresh_captures(pid, state)
        self.submit(pid, state, 'behavior_capture', {'executable':state['executables'][index], 'arguments':arguments,
            'stdin':state['stdin'], 'seedFiles':seeds, 'assetsDirectory':state['assets'], 'timeout':state['timeout'],
            'observation':{'driver':('none','windows','chromium','electron')[state['driver']],
                'network':state['network'],'headless':state['headless'] if state['driver']==2 else False,
                'url':state['url'] if state['driver'] in (2,3) else '',
                'targetUrl':state['target_url'] if state['driver'] in (2,3) else '',
                'steps':steps if state['driver'] else [],'settleMs':state['settle']}}, recorded)

    def refresh_captures(self, pid, state):
        self.submit(pid, state, 'behavior_captures', {}, lambda out: state.update(captures=out['captures']))

    def comparison_ready(self, state, out):
        state['comparison'] = out
        text = '\n\n'.join(tr(key) + '\n' + row['diff'] for key,row in out['streams'].items())
        for row in out['fileChanges']:
            text += '\n%s · %s\n%s\n' % (row['kind'],row['path'],json.dumps(row, ensure_ascii=False, indent=2))
        text+='\n\n'+tr('Network and console differences')+'\n'+out.get('network',{}).get('diff','')
        for row in out.get('graphics',{}).get('states',[]):
            text+='\n\n'+(tr('Graphical step %d') % row['step'])+' · '+str(row['label'])+'\n'+row['diff']
        state['comparison_editor'].set_text(text)

    def scenario_controls(self,state):
        if not imgui.collapsing_header(label('Network and graphical scenario')):
            return
        imgui.set_next_item_width(cyui.dp(280))
        _,state['driver']=imgui.combo(label('Graphical driver'),state['driver'],
            [tr('No graphical scenario'),tr('Windows controls'),tr('Chromium browser'),tr('Electron renderer')])
        imgui.same_line()
        _,state['network']=imgui.checkbox(label('Record network'),state['network'])
        if state['driver']==2:
            imgui.same_line()
            _,state['headless']=imgui.checkbox(label('Headless browser'),state['headless'])
        if state['driver'] in (2,3):
            imgui.set_next_item_width(cyui.dp(500))
            _,state['url']=imgui.input_text(label('Scenario URL'),state['url'])
            imgui.same_line()
            imgui.set_next_item_width(cyui.dp(350))
            _,state['target_url']=imgui.input_text(label('Renderer target URL'),state['target_url'])
        if state['driver']:
            if imgui.button(label('Insert scenario example')):
                selector={'automationId':'go'} if state['driver']==1 else '#go'
                state['steps']=json.dumps([{'action':'click','selector':selector},{'action':'snapshot','label':'result'}],indent=2)
            imgui.same_line()
            imgui.set_next_item_width(cyui.dp(170))
            _,state['settle']=imgui.slider_int(label('Settle delay (ms)'),state['settle'],0,3000)
            self.step_builder(state)
            if imgui.collapsing_header(label('Advanced scenario JSON')):
                _,state['steps']=imgui.input_text_multiline(label('Graphical steps (JSON)'),state['steps'],imgui.ImVec2(cyui.dp(800),cyui.dp(115)))
            imgui.text_wrapped(tr('Steps: click, fill, waitFor, assertText, snapshot, wait. Use CSS selectors for web or automationId/name/controlType for Windows. The application stops after the scenario.'))

    def step_builder(self,state):
        actions=('click','fill','waitFor','assertText','snapshot','wait','toggle','select') if state['driver']==1 else (
            'click','fill','waitFor','assertText','snapshot','wait','press','navigate')
        state['step_action']=min(state['step_action'],len(actions)-1)
        try:
            steps=json.loads(state['steps'])
            if not isinstance(steps,list):raise ValueError()
        except (ValueError,TypeError):
            imgui.text_wrapped(tr('Use JSON arrays for arguments and steps, and a JSON object for seed files.'))
            return
        imgui.set_next_item_width(cyui.dp(180))
        _,state['step_action']=imgui.combo(label('Step action'),state['step_action'],[tr(STEP_CAPTIONS[a]) for a in actions])
        action=actions[state['step_action']]
        if action in ('click','fill','waitFor','assertText','toggle','select','press'):
            if state['driver']==1:
                for field,caption in (('step_id','Automation ID'),('step_name','Control name'),('step_type','Control type')):
                    imgui.same_line();imgui.set_next_item_width(cyui.dp(190))
                    _,state[field]=imgui.input_text(label(caption),state[field])
            else:
                imgui.same_line();imgui.set_next_item_width(cyui.dp(330))
                _,state['step_selector']=imgui.input_text(label('CSS selector'),state['step_selector'])
        if action in ('fill','assertText'):
            imgui.set_next_item_width(cyui.dp(500))
            _,state['step_text']=imgui.input_text(label('Step text'),state['step_text'])
        elif action=='wait':
            imgui.set_next_item_width(cyui.dp(200))
            _,state['step_ms']=imgui.slider_int(label('Wait duration (ms)'),state['step_ms'],0,10000)
        elif action=='navigate':
            imgui.set_next_item_width(cyui.dp(500))
            _,state['step_url']=imgui.input_text(label('Navigation URL'),state['step_url'])
        elif action=='press':
            imgui.set_next_item_width(cyui.dp(200))
            _,state['step_key']=imgui.combo(label('Scenario key'),state['step_key'],['Enter','Tab','Escape','ArrowDown','ArrowUp','Space'])
        imgui.set_next_item_width(cyui.dp(200))
        _,state['step_timeout']=imgui.slider_int(label('Step timeout (ms)'),state['step_timeout'],100,10000)
        imgui.same_line()
        if imgui.button(label('Apply step' if state['step_edit']>=0 else 'Add step')):
            step={'action':action,'timeoutMs':state['step_timeout']}
            if action in ('click','fill','waitFor','assertText','toggle','select','press'):
                step['selector']={k:state[v] for k,v in (('automationId','step_id'),('name','step_name'),('controlType','step_type')) if state[v]} if state['driver']==1 else state['step_selector']
            if action in ('fill','assertText'):step['text']=state['step_text']
            if action=='wait':step['ms']=state['step_ms']
            if action=='navigate':step['url']=state['step_url']
            if action=='press':step['key']=('Enter','Tab','Escape','ArrowDown','ArrowUp','Space')[state['step_key']]
            if 0<=state['step_edit']<len(steps):
                if 'label' in steps[state['step_edit']]:step['label']=steps[state['step_edit']]['label']
                steps[state['step_edit']]=step
            elif len(steps)<30:steps.append(step)
            state['steps']=json.dumps(steps,ensure_ascii=False,indent=2)
            state['step_edit']=-1
        imgui.same_line()
        if imgui.button(label('New step')):state['step_edit']=-1
        imgui.begin_child('###scenario-step-list',imgui.ImVec2(0,cyui.dp(80)),True)
        for index,step in enumerate(steps):
            if not isinstance(step,dict):continue
            imgui.push_id(index)
            clicked,_=imgui.selectable('%d · %s · %s' % (index,tr(STEP_CAPTIONS.get(step.get('action'),step.get('action',''))),str(step.get('selector',step.get('text','')))),state['step_edit']==index)
            if clicked and step.get('action') in actions:
                selector=step.get('selector',{})
                state.update(step_edit=index,step_action=actions.index(step['action']),step_text=step.get('text',''),
                    step_url=step.get('url',''),step_ms=step.get('ms',500),step_timeout=step.get('timeoutMs',5000),
                    step_selector=selector if isinstance(selector,str) else '',
                    step_id=selector.get('automationId','') if isinstance(selector,dict) else '',
                    step_name=selector.get('name','') if isinstance(selector,dict) else '',
                    step_type=selector.get('controlType','') if isinstance(selector,dict) else '')
                keys=('Enter','Tab','Escape','ArrowDown','ArrowUp','Space')
                state['step_key']=keys.index(step.get('key')) if step.get('key') in keys else 0
            imgui.pop_id()
        imgui.end_child()
        if 0<=state['step_edit']<len(steps):
            if imgui.button(label('Remove step')):
                steps.pop(state['step_edit']);state['step_edit']=-1
                state['steps']=json.dumps(steps,ensure_ascii=False,indent=2)

    def screens(self,pid,state):
        self.load_evidence_button(pid,state)
        evidence=[state['evidence'].get(k,{}) for k in state['chosen']]
        count=max([len(r.get('runtime',{}).get('gui',{}).get('states',[])) for r in evidence]+[0])
        if not count:
            imgui.text_wrapped(tr('Load recordings to view the retained screenshots and step results.'))
            return
        state['frame']=min(state['frame'],count-1)
        imgui.set_next_item_width(cyui.dp(250))
        _,state['frame']=imgui.slider_int(label('Captured state'),state['frame'],0,count-1)
        if imgui.begin_table('###captured-screens',2,imgui.TableFlags_.resizable):
            imgui.table_next_row()
            for index,out in enumerate(evidence):
                imgui.table_set_column_index(index)
                imgui.begin_child('###screen-'+str(index),imgui.ImVec2(0,max(180,imgui.get_content_region_avail().y)),False)
                imgui.text(tr('Recording %d') % (index+1))
                gui=out.get('runtime',{}).get('gui',{})
                imgui.text(tr('HTTP requests: %d | TCP observations: %d') % (len(gui.get('requests',[])),len(out.get('runtime',{}).get('connections',[]))))
                states=gui.get('states',[])
                if state['frame']<len(states):
                    frame=states[state['frame']]
                    imgui.text(tr('Graphical step %d') % frame['step'])
                    for image in out.get('images',[]):
                        if image['step']==frame['step']:
                            width=max(100,imgui.get_content_region_avail().x)
                            size=hello_imgui.image_size_from_asset(image['path'])
                            if size.x>0:
                                hello_imgui.image_from_asset(image['path'],imgui.ImVec2(width,width*size.y/size.x))
                    imgui.text_wrapped(json.dumps(frame['state'],ensure_ascii=False,indent=2)[:12000])
                if gui.get('error'):imgui.text_wrapped(tr(gui['error']))
                imgui.end_child()
            imgui.end_table()

    def load_evidence_button(self,pid,state):
        busy=self.app.jobs.busy('investigation-'+pid)
        imgui.begin_disabled(busy or not all(state['chosen']))
        if imgui.button(label('Load captured screens')):
            for capture_id in state['chosen']:
                self.submit(pid,state,'behavior_evidence',{'captureId':capture_id},
                    lambda out:state['evidence'].update({out['captureId']:out}))
        imgui.end_disabled()

    def network_recordings(self,pid,state):
        self.load_evidence_button(pid,state)
        if imgui.begin_table('###network-recordings',2,imgui.TableFlags_.resizable):
            imgui.table_next_row()
            for index,capture_id in enumerate(state['chosen']):
                imgui.table_set_column_index(index)
                imgui.begin_child('###network-'+str(index),imgui.ImVec2(0,max(180,imgui.get_content_region_avail().y)),False)
                imgui.text(tr('Recording %d') % (index+1))
                runtime=state['evidence'].get(capture_id,{}).get('runtime',{})
                imgui.push_id(index)
                for row in runtime.get('gui',{}).get('requests',[]):
                    if imgui.tree_node('%s %s · %s###request-%s' % (row.get('status'),row.get('method'),row.get('url'),row['index'])):
                        imgui.text_wrapped(json.dumps(row,ensure_ascii=False,indent=2))
                        imgui.tree_pop()
                if imgui.collapsing_header(label('TCP connections')):
                    for row in runtime.get('connections',[]):
                        imgui.text_wrapped('%s:%s → %s:%s [%s]' % (row['localAddress'],row['localPort'],row['remoteAddress'],row['remotePort'],row['status']))
                if imgui.collapsing_header(label('Renderer console')):
                    for row in runtime.get('gui',{}).get('console',[]):
                        imgui.text_wrapped('[%s] %s' % (row['type'],row['text']))
                imgui.pop_id()
                imgui.end_child()
            imgui.end_table()

    def behavior(self, pid, state):
        imgui.text_wrapped(tr('Captures use a fresh working directory. Enable network recording and replay the same graphical scenario for both versions.'))
        busy = self.app.jobs.busy('investigation-' + pid)
        imgui.begin_disabled(busy)
        self.scenario_controls(state)
        for index in range(2):
            imgui.push_id(index)
            imgui.set_next_item_width(cyui.dp(420))
            _, state['executables'][index] = imgui.input_text(label('Version executable'), state['executables'][index])
            imgui.same_line()
            imgui.set_next_item_width(cyui.dp(400))
            _, state['arguments'][index] = imgui.input_text(label('Arguments (JSON)'), state['arguments'][index])
            imgui.same_line()
            if imgui.button((tr('Capture version %d') % (index + 1)) + '###capture-version'):
                self.capture(pid, state, index)
            imgui.pop_id()
        imgui.set_next_item_width(cyui.dp(650))
        _, state['stdin'] = imgui.input_text_multiline(label('Scenario input (stdin)'), state['stdin'], imgui.ImVec2(cyui.dp(650),cyui.dp(65)))
        imgui.set_next_item_width(cyui.dp(500))
        _, state['assets'] = imgui.input_text(label('Scenario assets folder'), state['assets'])
        imgui.same_line()
        imgui.set_next_item_width(cyui.dp(480))
        _, state['seeds'] = imgui.input_text(label('Seed files (JSON)'), state['seeds'])
        imgui.set_next_item_width(cyui.dp(170))
        _, state['timeout'] = imgui.slider_int(label('Capture timeout'), state['timeout'], 1, 300)
        if imgui.button(label('Refresh captures')):
            self.refresh_captures(pid, state)
        for index in range(2):
            imgui.same_line()
            imgui.push_id('capture-select-' + str(index))
            imgui.set_next_item_width(cyui.dp(350))
            if imgui.begin_combo((tr('Recording %d') % (index+1)) + '###recording',state['chosen'][index][:16]):
                for row in state['captures']:
                    clicked, _ = imgui.selectable('%s · %s' % (row['captureId'][:16],row['exitCode']), row['captureId'] == state['chosen'][index])
                    if clicked:
                        state['chosen'][index] = row['captureId']
                imgui.end_combo()
            imgui.pop_id()
        imgui.same_line()
        imgui.begin_disabled(not all(state['chosen']))
        if imgui.button(label('Compare recordings')):
            self.submit(pid, state, 'behavior_compare', {'left':state['chosen'][0], 'right':state['chosen'][1]},
                        lambda out: self.comparison_ready(state,out))
        imgui.end_disabled()
        imgui.end_disabled()
        result = state['comparison']
        if result:
            imgui.text(tr('Same scenario: %s | Complete captures: %s | Matching observations: %s') %
                tuple(tr('Yes') if result[k] else tr('No') for k in ('sameScenario','complete','observationsMatch')))
            imgui.text(tr('Exit codes: %s / %s') % tuple(result['exitCodes']))
            imgui.text(tr('Network match: %s | Graphical match: %s') % tuple(tr('Yes') if result.get(k,{}).get('same',True) else tr('No') for k in ('network','graphics')))
            self.limits(result['unknowns'])
        if imgui.begin_tab_bar('###behavior-results'):
            requested,self.force_results=self.force_results,''
            opened,_=imgui.begin_tab_item(label('Observed differences'),None,imgui.TabItemFlags_.set_selected if requested=='diff' else 0)
            if opened:
                if result:self.render(state['comparison_editor'],'###behavior-diff',imgui.ImVec2(0,max(180,imgui.get_content_region_avail().y)))
                imgui.end_tab_item()
            opened,_=imgui.begin_tab_item(label('Captured screens'),None,imgui.TabItemFlags_.set_selected if requested=='screens' else 0)
            if opened:
                self.screens(pid,state)
                imgui.end_tab_item()
            opened,_=imgui.begin_tab_item(label('Network recordings'),None,imgui.TabItemFlags_.set_selected if requested=='network' else 0)
            if opened:
                self.network_recordings(pid,state)
                imgui.end_tab_item()
            imgui.end_tab_bar()
