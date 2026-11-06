"""Native Xbox page; all actions use the application's existing Runtime jobs."""
from pathlib import Path
import cyui
from ui_views import LogView
from imgui_bundle import portable_file_dialogs as pfd
from ui_common import imgui,label,tr

STATUS={'prepared':'Input prepared','native-project':'Native project created',
        'built':'Native build completed','build-failed':'Native build failed',
        'executed-unverified':'Executed; behavior unverified','execution-failed':'Execution failed'}


class XboxUI:
    def __init__(self,app):
        self.app=app
        self.path='';self.entry='';self.existing=''
        self.report={};self.native={};self.tool_settings={}
        self.coop=False;self.fullscreen=False;self.jobs=4
        self.loaded_project='';self.dialog=None;self.dialog_kind=''
        self.loaded_tools=False
        self.output_view=LogView()

    def submit(self,operation,parameters,done=None):
        def completed(out):
            self.report=out
            if done:done(out)
        self.app.jobs.submit(operation,parameters,tag='xbox',done=completed,
                             failed=lambda text:self.refresh(),timeout=30000)

    def select(self,out):
        self.loaded_project=out['projectId']
        if out.get('buildId'):self.native=out
        else:self.native={}
        self.app.load_project(out['projectId'])
        self.app.refresh_projects()
        self.refresh(out['projectId'])

    def refresh(self,pid=''):
        pid=pid or (self.app.project or {}).get('projectId','')
        if not pid:return
        self.loaded_project=pid
        def done(out):
            if self.loaded_project!=pid:return
            self.report=out;self.native=out.get('build',{})
        self.app.jobs.submit('xbox_info',{'projectId':pid},tag='xbox-info',done=done)

    def browse(self,kind):
        self.dialog_kind=kind
        self.dialog=(pfd.open_file(tr('Choose Xbox game input'),'', ['Xbox game','*.xex *.xbe *.iso *.zip','All files','*'])
                     if kind=='file' else pfd.select_folder(tr('Choose Xbox game folder') if kind=='directory' else tr('Choose native Xbox project')))

    def draw(self):
        if self.dialog and self.dialog.ready():
            selected=self.dialog.result()
            if isinstance(selected,list):selected=selected[0] if selected else ''
            if selected:
                if self.dialog_kind=='existing':self.existing=selected
                else:self.path=selected
            self.dialog=None
        if not self.loaded_tools:
            self.loaded_tools=True
            self.app.jobs.submit('xbox_tools',{},tag='xbox-tools-info',done=lambda out:setattr(self,'tool_settings',out['settings']))
        busy=self.app.jobs.busy('xbox')
        cyui.panel_header(tr('Xbox porting'),tr('Prepare a game, compile a native PC project and launch it.'))
        cyui.text_dim(tr('Xbox: inspection. Xbox 360: static recompilation with ReXGlue.'))
        projects=[p for p in self.app.projects if p.get('format',{}).get('format') in ('xbox-xbe','xbox-xex2')]
        current=(self.app.project or {}).get('projectId','')
        selected=next((i+1 for i,p in enumerate(projects) if p['projectId']==current),0)
        changed,choice=imgui.combo(label('Xbox projects'),selected,[tr('Select Xbox project')]+[p['name'] for p in projects])
        if changed and choice:self.app.load_project(projects[choice-1]['projectId'])
        if cyui.begin_section(label('Xbox game input'),True):
            imgui.set_next_item_width(-1)
            _,self.path=imgui.input_text_with_hint('###xbox-input',tr('Game file or extracted folder'),self.path)
            imgui.set_next_item_width(-1)
            _,self.entry=imgui.input_text_with_hint('###xbox-entry',tr('Entry executable (optional)'),self.entry)
            with cyui.scoped_disabled(busy):
                if cyui.button(label('Choose Xbox game input')):self.browse('file')
                imgui.same_line()
                if cyui.button(label('Choose Xbox game folder')):self.browse('directory')
                with cyui.scoped_disabled(not self.path.strip()):
                    if cyui.primary_button(label('Prepare Xbox game')):
                        path=Path(self.path.strip().strip('"')).expanduser()
                        self.submit('xbox_open',{'directory' if path.is_dir() else 'file':str(path),'entry':self.entry.strip()},self.select)
            imgui.text_wrapped(tr('Use a game folder or ISO to include resources. An XEX or XBE file alone only imports the executable.'))
            cyui.end_section()
        if cyui.begin_section(label('Existing Xbox native project'),False):
            imgui.set_next_item_width(-1)
            _,self.existing=imgui.input_text('###xbox-existing',self.existing)
            with cyui.scoped_disabled(busy):
                if cyui.button(label('Choose native Xbox project')):self.browse('existing')
                imgui.same_line()
                with cyui.scoped_disabled(not self.existing.strip()):
                    if cyui.button(label('Attach Xbox project')):self.submit('xbox_attach',{'directory':self.existing.strip().strip('"')},self.select)
            cyui.end_section()
        pid=(self.app.project or {}).get('projectId','')
        if pid and self.loaded_project!=pid:self.refresh(pid)
        if pid:
            if self.report.get('console'):
                imgui.text_unformatted(self.report['console']+' · '+self.report.get('sha256','')[:16])
            if self.report.get('available') and self.report.get('assetsComplete') is False:
                cyui.callout('warning',tr('Only the executable was imported. Prepare its game folder for a complete resource snapshot.'))
            with cyui.scoped_disabled(busy):
                if cyui.button(label('Refresh')):self.refresh(pid)
                imgui.same_line()
                with cyui.scoped_disabled(not self.report.get('importId') or self.report.get('console')!='xbox360'):
                    if cyui.button(label('Create Xbox native project')):
                        self.submit('xbox_create',{'projectId':pid},lambda out:setattr(self,'native',out))
                with cyui.scoped_disabled(not self.native.get('buildId')):
                    if cyui.primary_button(label('Compile Xbox project')):
                        self.submit('xbox_build',{'projectId':pid,'buildId':self.native['buildId'],'jobs':max(1,min(16,self.jobs))},
                                    lambda out:setattr(self,'native',out))
                    imgui.same_line()
                    if cyui.button(label('Edit native sources')):
                        self.app.jobs.submit('workspace_open',{'projectId':pid,'directory':self.native['directory']},tag='xbox-editor',
                            done=lambda out:setattr(self.app,'force_tab','project'))
                _,self.coop=imgui.checkbox(label('Local campaign coop (Halo profile)'),self.coop)
                _,self.fullscreen=imgui.checkbox(label('Fullscreen at launch'),self.fullscreen)
                with cyui.scoped_disabled(self.native.get('status')!='built'):
                    if cyui.primary_button(label('Launch native Xbox game')):
                        self.submit('xbox_run',{'projectId':pid,'buildId':self.native['buildId'],'coop':self.coop,'fullscreen':self.fullscreen})
            imgui.text_wrapped(tr('Cancel the running job to stop the game. Saved in-game settings may override fullscreen.'))
            status=self.native.get('status','')
            if status:cyui.status_text('error' if status.endswith('failed') else 'neutral',tr(STATUS.get(status,status)))
            if self.native.get('directory'):imgui.text_wrapped(self.native['directory'])
        self.draw_tools(busy)
        if cyui.begin_section(label('Xbox methods and pitfalls'),False):
            imgui.text_wrapped(tr('Keep original files unchanged. Apply patches only to an exact executable SHA-256.'))
            imgui.text_wrapped(tr('Unlocked FPS, simulation timing and animation interpolation require separate checks.'))
            imgui.text_wrapped(tr('Ray tracing and direct IP campaign networking remain experimental. Competitive multiplayer is excluded.'))
            if cyui.button(label('Read Xbox integration guide')):
                self.app.open_help('xbox-methods')
            cyui.end_section()
        self.app.jobs.progress_widget('xbox')
        if self.app.jobs.message:cyui.callout('warning',tr(self.app.jobs.message))
        output=self.report.get('output') or self.native.get('output')
        if output:
            imgui.text_unformatted(tr('Output'))
            self.output_view.set_text(output)
            self.output_view.render('###xbox-output',(-1,cyui.dp(180)))

    def draw_tools(self,busy):
        if not cyui.begin_section(label('Xbox native tools'),False):return
        with cyui.scoped_disabled(busy):
            if cyui.button(label('Install ReXGlue SDK')):
                self.submit('xbox_install',{},lambda out:setattr(self,'tool_settings',out['settings']))
            for key,caption in [('sdkRoot','ReXGlue SDK folder'),('gpuPlugin','Optional native GPU plugin')]:
                imgui.text_unformatted(tr(caption))
                imgui.set_next_item_width(-1)
                _,self.tool_settings[key]=imgui.input_text('###xbox-'+key,self.tool_settings.get(key,''))
            if cyui.button(label('Save Xbox tool settings')):
                self.submit('xbox_tools',{'settings':self.tool_settings},lambda out:setattr(self,'tool_settings',out['settings']))
            _,self.jobs=imgui.input_int(label('Compiler processes'),self.jobs)
        imgui.text_wrapped(tr('Native builds require Windows x64, CMake, Ninja and Visual Studio C++ with Clang.'))
        cyui.end_section()
