"""Runtime-only reconstruction frontend integrated with the project editor."""
import json
from ui_common import imgui,label,tr

STATUS={'scenarios-matched':'Recorded scenarios match','compiled-unverified':'Compiled; behavior unverified',
        'compilation-failed':'Compilation failed','behavior-differs':'Behavior differs','blocked':'Reconstruction blocked',
        'cancelled':'Cancelled','running':'Running','not-started':'Not started'}
STATUS['tests-failed']='Project tests failed'


class ReconstructionUI:
    def __init__(self,ide):self.ide=ide

    def init(self,state):
        state.update(reconstruction_rounds=3,reconstruction_repair=False,reconstruction_tests=False,
                     reconstruction_verify=True,reconstruction_runtime='',reconstruction_scenarios='[]',
                     reconstruction_report={},reconstruction_busy=False)

    def import_scenario(self,pid,state):
        investigation=getattr(self.ide.app,'investigation',None)
        source=investigation.sessions.get(pid) if investigation else None
        if not source and investigation:_,source=investigation.state()
        if not source:return
        try:
            scenario={'stdin':source['stdin'],'seedFiles':json.loads(source['seeds']),
                'timeout':source['timeout'],'assetsDirectory':source['assets'],
                'observation':{'driver':('none','windows','chromium','electron')[source['driver']],
                    'network':source['network'],'headless':source['headless'],'url':source['url'],
                    'targetUrl':source['target_url'],'settleMs':source['settle'],'steps':json.loads(source['steps'])}}
            if source['executables'][0]:
                scenario.update(originalExecutable=source['executables'][0],originalArguments=json.loads(source['arguments'][0]))
            state['reconstruction_scenarios']=json.dumps([scenario],ensure_ascii=False,indent=2)
        except (ValueError,TypeError):self.ide.error(pid,tr('Invalid comparison scenarios.'))

    def start(self,pid,state):
        try:
            scenarios=json.loads(state['reconstruction_scenarios'])
            if not isinstance(scenarios,list):raise ValueError()
            scenarios=scenarios or [{}]
            from cydec.workspace import parse_arguments
            for scenario in scenarios:
                if not isinstance(scenario,dict):raise ValueError()
                if state['reconstruction_runtime']:scenario['runtimeExecutable']=state['reconstruction_runtime']
                scenario.setdefault('arguments',parse_arguments(state['arguments']))
        except (ValueError,TypeError):
            self.ide.error(pid,tr('Invalid comparison scenarios.'));return
        params={'destination':self.ide.destination,'nativeTarget':('auto','executable','shared','library')[self.ide.native_target],
            'entryFunction':self.ide.native_entry,'configuration':('Debug','Release')[state['configuration']],
            'targetProject':state['target_project'],'maxRounds':state['reconstruction_rounds'],
            'repair':state['reconstruction_repair'],'runTests':state['reconstruction_tests'],
            'verifyBehavior':state['reconstruction_verify'],'scenarios':scenarios}
        def submit():
            state['reconstruction_busy']=True
            def finished(out):
                state['reconstruction_busy']=False;state['reconstruction_report']=out
                # Buffers were saved and frozen for the job; reopen fresh revisions.
                state.update(tabs={},active='',history_preview=None,history=None)
                self.ide.refresh(pid)
            def failed(error):
                state['reconstruction_busy']=False
                state.update(tabs={},active='',history_preview=None,history=None)
                self.ide.error(pid,error)
                self.ide.submit(pid,'reconstruction_status',{},lambda out:state.update(reconstruction_report=out))
                self.ide.refresh(pid)
            self.ide.submit(pid,'reconstruction_run',params,finished,failed)
        self.ide.save_all(pid,submit)

    def show_comparison(self,pid,comparison):
        investigation=getattr(self.ide.app,'investigation',None)
        if not investigation:return
        investigation.state()
        state=investigation.sessions[pid]
        state.update(chosen=[comparison['left'],comparison['right']])
        investigation.comparison_ready(state,comparison)
        investigation.refresh_captures(pid,state)
        investigation.force_mode='behavior'
        self.ide.app.force_tab='investigation'

    def draw(self,pid,state,busy):
        imgui.text_wrapped(tr('Reconstruct, build, repair and compare the recorded behavior.'))
        imgui.text_wrapped(tr('Matching scenarios validate only the recorded interactions.'))
        imgui.begin_disabled(busy)
        _,state['reconstruction_rounds']=imgui.slider_int(label('Maximum build rounds'),state['reconstruction_rounds'],1,10)
        _,state['reconstruction_repair']=imgui.checkbox(label('Automatic AI repairs with Git history'),state['reconstruction_repair'])
        _,state['reconstruction_tests']=imgui.checkbox(label('Run project tests'),state['reconstruction_tests'])
        _,state['reconstruction_verify']=imgui.checkbox(label('Compare with the original application'),state['reconstruction_verify'])
        _,state['reconstruction_runtime']=imgui.input_text(label('Electron / browser runtime'),state['reconstruction_runtime'])
        if imgui.button(label('Use investigation scenario')):self.import_scenario(pid,state)
        if imgui.collapsing_header(label('Comparison scenarios (JSON)')):
            _,state['reconstruction_scenarios']=imgui.input_text_multiline('###reconstruction-scenarios',state['reconstruction_scenarios'],imgui.ImVec2(-1,140))
        if imgui.button(label('Reconstruct and validate')):self.start(pid,state)
        imgui.same_line()
        if imgui.button(label('Refresh reconstruction report')):
            self.ide.submit(pid,'reconstruction_status',{},lambda out:state.update(reconstruction_report=out))
        if state['info'].get('kind') in ('node','web','electron'):
            imgui.same_line()
            if imgui.button(label('Install locked npm dependencies')):
                self.ide.submit(pid,'workspace_dependencies',{})
        imgui.end_disabled()
        report=state['reconstruction_report']
        if report:
            imgui.separator();imgui.text(tr(STATUS.get(report['status'],report['status'])))
            if report.get('error'):imgui.text_wrapped(report['error']['message'])
            for attempt in report.get('attempts',[]):
                imgui.text(tr('Round %d')%attempt['round'])
                if attempt.get('tests'):imgui.text(tr('Test')+' : '+tr(attempt['tests']['status']))
                if attempt.get('repair'):
                    imgui.text_wrapped(attempt['repair']['reason'])
                    for path in attempt['repair']['changedFiles']:imgui.bullet_text(path)
                for comparison in attempt.get('comparisons',[]):
                    imgui.push_id(comparison['left'])
                    if imgui.small_button(label('Inspect recorded comparison')):self.show_comparison(pid,comparison)
                    omitted=[k for k,v in comparison.get('validatedChecks',{}).items() if not v]
                    if omitted:imgui.text_wrapped(tr('Excluded comparison checks: ')+', '.join(omitted))
                    if comparison.get('applicationPathsNormalized'):
                        imgui.text_wrapped(tr('Application file URLs are compared relative to each version.'))
                    imgui.pop_id()
            for row in report.get('unknowns',[]):
                if row.get('message'):imgui.text_wrapped(row['message'])
        self.ide.draw_output(pid,state)
