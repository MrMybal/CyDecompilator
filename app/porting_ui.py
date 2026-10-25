"""CyUI frontend for the same porting operations exposed through MCP."""
import json
import os
from pathlib import Path

import cyui
from imgui_bundle import portable_file_dialogs as pfd
from ui_common import imgui, label, tr

STATUSES = {'prepared':'Input prepared', 'ready':'Ready', 'blocked':'Blocked',
            'converted-unverified':'Converted; behavior unverified', 'conversion-failed':'Conversion failed',
            'executed-unverified':'Executed; behavior unverified', 'scenarios-passed':'Test scenarios passed',
            'execution-failed':'Execution failed','analysis-complete':'Analysis complete'}
FINDINGS={'syscall':'Guest syscall instruction','converter-syscall':'AnyPS5 syscall rejection',
          'import':'Console import reference','runtime-import':'Observed import trace',
          'dependency-error':'Dependency error','host-instruction-error':'Host instruction error'}


class PortingUI:
    def __init__(self,app):
        self.app=app
        self.path=''
        self.entry=''
        self.target=0 if os.name=='nt' else 1
        self.to_intel=False
        self.standalone=False
        self.diagnostics=False
        self.trace_imports=False
        self.analyze_on_failure=True
        self.trace_libraries=''
        self.analysis_module=''
        self.analysis_engine=0
        self.diagnosis={}
        self.max_gib=256
        self.build_pkg_helper=True
        self.scenarios='[{"expectedExitCode": 0}]'
        self.report={}
        self.converted={}
        self.tool_settings={}
        self.dialog=None
        self.dialog_kind=''
        self.loaded_project=''

    def submit(self,operation,parameters,done=None):
        def completed(out):
            self.report=out
            if done: done(out)
        self.app.jobs.submit(operation,parameters,tag='porting',done=completed,timeout=7200)

    def import_input(self):
        path=Path(self.path.strip().strip('"')).expanduser()
        params={'directory' if path.is_dir() else 'file':str(path),'entry':self.entry.strip(),
                'maxBytes':max(1,min(1024,self.max_gib))*1024**3}
        def done(out):
            self.loaded_project=out['projectId']
            self.converted={}
            self.diagnosis={}
            self.app.load_project(out['projectId'])
            self.app.refresh_projects()
        self.submit('porting_open',params,done)

    def refresh(self):
        if not self.app.project:return
        pid=self.app.project['projectId']
        if self.loaded_project!=pid:self.diagnosis={}
        self.loaded_project=pid
        self.app.jobs.submit('porting_info',{'projectId':pid},tag='porting-info',done=lambda out:setattr(self,'report',out))
        self.app.jobs.submit('porting_conversion',{'projectId':pid},tag='porting-conversion',done=lambda out:setattr(self,'converted',out))

    def browse(self,kind):
        self.dialog_kind=kind
        if kind=='directory' or kind.endswith('Libraries'):
            self.dialog=pfd.select_folder(tr('Choose application folder') if kind=='directory' else tr('Compatibility libraries'))
        else:
            self.dialog=pfd.open_file(tr('Choose application input') if kind=='file' else tr('Choose tool'),'', ['All files','*'])

    def draw(self):
        if self.dialog and self.dialog.ready():
            value=self.dialog.result()
            if isinstance(value,list):value=value[0] if value else ''
            if value:
                if self.dialog_kind in ('file','directory'):self.path=value
                else:self.tool_settings[self.dialog_kind]=value
            self.dialog=None
        busy=self.app.jobs.busy('porting')
        cyui.panel_header(tr('PS5 porting'),tr('Prepare an application, convert it for desktop, then test recorded scenarios.'))
        cyui.callout('info',tr('Conversion alone does not prove that a game works.'))
        if cyui.begin_section(label('Application input'),True):
            if cyui.begin_properties('###porting-input-properties',220):
                cyui.property(tr('Application file or folder'))
                imgui.set_next_item_width(-1)
                _,self.path=imgui.input_text('###porting-path',self.path)
                cyui.property(tr('Entry executable (optional)'))
                _,self.entry=imgui.input_text_with_hint('###porting-entry',tr('Relative path when several applications are present'),self.entry)
                cyui.property(tr('Maximum application size (GiB)'))
                _,self.max_gib=imgui.input_int('###porting-size',self.max_gib)
                cyui.end_properties()
            with cyui.scoped_disabled(busy):
                if cyui.button(label('Choose application input')):self.browse('file')
                imgui.same_line()
                if cyui.button(label('Choose application folder')):self.browse('directory')
                with cyui.scoped_disabled(not self.path.strip()):
                    if cyui.button(label('Prepare input')):self.import_input()
            imgui.text_wrapped(tr('ELF, plaintext SELF and ZIP are prepared internally. PKG, PFS, RAR and 7z require the UltraPack backend.'))
            cyui.end_section()
        with cyui.scoped_disabled(busy):
            if cyui.begin_properties('###porting-target-properties',220):
                cyui.property(tr('Target operating system'))
                _,self.target=imgui.combo('###porting-target',self.target,['Windows','Linux'])
                cyui.property(tr('Adapt supported AMD instructions for Intel'))
                _,self.to_intel=cyui.toggle_switch('###porting-intel',self.to_intel)
                cyui.property(tr('Standalone homebrew without bundled modules'))
                _,self.standalone=cyui.toggle_switch('###porting-standalone',self.standalone)
                cyui.property(tr('Analyze conversion failures automatically'))
                _,self.analyze_on_failure=cyui.toggle_switch('###porting-auto-diagnosis',self.analyze_on_failure)
                with cyui.scoped_disabled(self.target!=0):
                    cyui.property(tr('AnyPS5 startup diagnostics'))
                    _,self.diagnostics=cyui.toggle_switch('###porting-diagnostics',self.diagnostics)
                    cyui.property(tr('Instrument console imports'))
                    _,self.trace_imports=cyui.toggle_switch('###porting-trace-imports',self.trace_imports)
                cyui.end_properties()
        target=['windows','linux'][self.target]
        if self.app.project:
            pid=self.app.project['projectId']
            if self.loaded_project!=pid:self.refresh()
            with cyui.scoped_disabled(busy):
                if cyui.button(label('Check porting prerequisites')):
                    self.submit('porting_plan',{'projectId':pid,'target':target})
                imgui.same_line()
                if cyui.primary_button(label('Convert for desktop')):
                    def converted(out):
                        self.converted=out
                        if out.get('diagnosis'):self.diagnosis=out['diagnosis']
                    self.submit('porting_convert',{'projectId':pid,'target':target,'toIntel':self.to_intel,'standalone':self.standalone,
                        'diagnostics':self.diagnostics if self.target==0 else False,
                        'traceImports':self.trace_imports if self.target==0 else False,
                        'analyzeOnFailure':self.analyze_on_failure},converted)
                imgui.same_line()
                if cyui.button(label('Refresh')):self.refresh()
            if cyui.begin_section(label('Test scenarios'),False):
                imgui.text_wrapped(tr('Each scenario may specify arguments, stdin, expectedExitCode and exact expectedStdout.'))
                _,self.scenarios=imgui.input_text_multiline('###porting-scenarios',self.scenarios,cyui.dp2(-1,120))
                imgui.text_wrapped(tr('Trace libraries: all or comma-separated names; requires instrumented conversion.'))
                imgui.set_next_item_width(-1)
                _,self.trace_libraries=imgui.input_text('###porting-trace-libraries',self.trace_libraries)
                with cyui.scoped_disabled(busy or not self.converted.get('conversionId')):
                    if cyui.button(label('Run converted application')):
                        try:cases=json.loads(self.scenarios)
                        except ValueError as error:self.app.jobs.message=str(error)
                        else:self.submit('porting_run',{'projectId':pid,'conversionId':self.converted['conversionId'],
                            'scenarios':cases,'traceLibraries':self.trace_libraries.strip()})
                cyui.end_section()
            if cyui.begin_section(label('CyDecompilator analysis'),True):
                if cyui.begin_properties('###porting-analysis-properties',220):
                    cyui.property(tr('Analysis module (optional)'))
                    _,self.analysis_module=imgui.input_text('###porting-analysis-module',self.analysis_module)
                    cyui.property(tr('Analysis engine'))
                    _,self.analysis_engine=imgui.combo('###porting-analysis-engine',self.analysis_engine,['cdec','native','ghidra'])
                    cyui.end_properties()
                with cyui.scoped_disabled(busy):
                    if cyui.button(label('Analyze port and failures')):
                        self.submit('porting_diagnose',{'projectId':pid,'module':self.analysis_module.strip(),
                            'engine':['cdec','native','ghidra'][self.analysis_engine]},lambda out:setattr(self,'diagnosis',out))
                imgui.text_wrapped(tr('Link AnyPS5 evidence to guest instructions and decompiled functions.'))
                self.draw_diagnosis()
                cyui.end_section()
        else:
            cyui.empty_state(tr('No application selected'),tr('Prepare input to start the porting workflow.'),cyui.icon.code)
        if cyui.begin_section(label('Porting tools'),False):
            with cyui.scoped_disabled(busy):
                if cyui.button(label('Install official AnyPS5 tools')):
                    self.submit('porting_install',{'target':target},lambda out:setattr(self,'tool_settings',dict(out['settings'])))
                _,self.build_pkg_helper=imgui.checkbox(label('Build package helper (.NET SDK 9+)'),self.build_pkg_helper)
                if cyui.button(label('Install official UltraPack backend')):
                    self.submit('porting_install',{'backend':'ultrapack','buildPkgHelper':self.build_pkg_helper},
                                lambda out:setattr(self,'tool_settings',dict(out['settings'])))
                imgui.same_line()
                if cyui.button(label('Read tool settings')):
                    self.submit('porting_tools',{},lambda out:setattr(self,'tool_settings',dict(out['settings'])))
                if cyui.begin_properties('###porting-tool-properties',220):
                    for key,caption in [('relinker','AnyPS5 converter'),('windowsLibraries','Windows compatibility libraries'),
                                        ('linuxLibraries','Linux compatibility libraries'),('ultrapackCli','UltraPack backend cli.py'),
                                        ('ultrapackPython','UltraPack Python (optional)'),
                                        ('ultrapackPkgTool','UltraPack package helper (optional)')]:
                        cyui.property(tr(caption))
                        with cyui.scoped_id(key):
                            room=imgui.get_content_region_avail().x-cyui.dp(35)
                            imgui.set_next_item_width(max(cyui.dp(80),room))
                            _,self.tool_settings[key]=imgui.input_text('###path',self.tool_settings.get(key,''))
                            imgui.same_line()
                            if cyui.icon_button(cyui.icon.open_file,tr('Browse')):self.browse(key)
                    cyui.end_properties()
                if cyui.button(label('Save tool settings')):self.submit('porting_tools',{'settings':self.tool_settings})
            imgui.text_wrapped(tr('AnyPS5 conversion is an optional external backend. UltraPack is used only to extract application containers.'))
            cyui.end_section()
        self.app.jobs.progress_widget('porting')
        if self.app.jobs.message:cyui.callout('warning',self.app.jobs.message)
        report=self.report
        if report.get('status'):
            status=report['status']
            cyui.status_text('error' if status.endswith('failed') else ('warning' if 'unverified' in status or status=='blocked' else 'neutral'),
                             tr(STATUSES.get(status,status)))
        for blocker in report.get('blockers',[]):cyui.callout('warning',tr(blocker['message']))
        for row in report.get('scenarios',[]):
            cyui.callout('success' if row['passed'] else 'error',tr('Scenario')+' '+str(row['index']+1)+': '+str(row['exitCode']))
            if row.get('stdout'):imgui.text_unformatted(row['stdout'])
            if row.get('stderr'):imgui.text_unformatted(row['stderr'])
        imported=report if report.get('entry') else {}
        if imported:
            cyui.text_dim(imported['entry']+' · '+str(len(imported['files']))+' '+tr('files'))
            for unresolved in imported.get('unpreparedSelf',[]):
                cyui.callout('warning',unresolved['path']+': '+unresolved['reason'])
            if cyui.button(label('Open in Workspace')):self.app.force_tab='workspace'
            imgui.same_line()
            if cyui.button(label('Open Project IDE')):self.app.force_tab='project'
        if self.converted.get('directory'):imgui.text_wrapped(self.converted['directory'])
        if report.get('output'):
            imgui.begin_child('###porting-log',cyui.dp2(-1,180))
            imgui.text_unformatted(report['output'])
            imgui.end_child()

    def draw_diagnosis(self):
        report=self.diagnosis
        if not report:return
        cyui.text_dim(report['source']+' · '+report['engine']+' · '+report['sourceSha256'][:16])
        coverage=report['coverage']
        imgui.text_unformatted(tr('Functions inspected')+': '+str(coverage['inspectedFunctions'])+'/'+str(coverage['discoveredFunctions']))
        if cyui.button(label('Open analyzed executable')):
            self.app.load_project(report['analysisProjectId'],report['engine'])
            self.app.force_tab='workspace'
        if imgui.tree_node(label('Findings')+'###porting-findings'):
            for index,row in enumerate(report['findings'][:100]):
                title=tr(FINDINGS.get(row['kind'],row['kind']))
                if row.get('library'):title+=' · '+row['library']+' · '+row.get('nid','')
                if imgui.tree_node(title+'###porting-finding-'+str(index)):
                    for loc in [row.get('location',{}),*row.get('callSites',[])]:
                        if loc:
                            imgui.text_wrapped(loc.get('source','')+' '+loc.get('fileOffset','')+' → '+
                                loc.get('functionId',tr('Unresolved address'))+' '+loc.get('instruction',''))
                    if row.get('hostAddress'):
                        imgui.text_wrapped(tr('Unmapped host address')+': '+row['hostAddress'])
                    evidence=row.get('evidence',{})
                    if evidence.get('text'):imgui.text_wrapped(evidence['text'])
                    cyui.text_dim(str(evidence.get('origin',''))+' · '+str(evidence.get('sha256',''))[:16])
                    imgui.tree_pop()
            imgui.tree_pop()
        if imgui.tree_node(label('Affected functions')+'###porting-samples'):
            for sample in report['samples']:
                function=sample['function']
                if imgui.tree_node(function['name']+' '+function['address']+'###porting-function-'+function['id']):
                    for view in ('decompiled','disassembly'):
                        code=sample.get(view,{})
                        if code.get('code'):
                            if code.get('hasUnmodeledInstructions'):
                                cyui.callout('warning',tr('Decompiled C is incomplete; unsupported instructions remain.'))
                            imgui.text_unformatted(code['language'])
                            imgui.begin_child('###porting-code-'+view+'-'+function['id'],cyui.dp2(-1,180))
                            imgui.text_unformatted(code['code'])
                            imgui.end_child()
                        elif code.get('error'):cyui.callout('warning',code['error']['message'])
                    imgui.tree_pop()
            imgui.tree_pop()
        if imgui.tree_node(label('Unknowns and limits')+'###porting-unknowns'):
            for text in report['unknowns']+report['limits']:imgui.text_wrapped(text)
            imgui.tree_pop()
