"""ImGui adapter for the SDK conversation service; all work is submitted as jobs."""
import json
from pathlib import Path
import uuid
from imgui_bundle import portable_file_dialogs as pfd
import cyui
from ui_common import imgui,label,tr
from ui_views import ConversationView

class AssistantPanel:
    def __init__(self,app):
        self.app=app;self.text='';self.identifier='';self.view=ConversationView();self.message='';self.attachments=[];self.dialog=None;self.allow_edits=True;self.sessions=[];self.selected=0
        self.settings_editor=None;self.settings_text='';self.settings_loaded=False
        self.sdk_version=app.runtime.native.call('info')['version'];self.loaded=False
    def refresh(self):
        self.app.jobs.submit('assistant_history',{},tag='sdk-history',done=lambda out:setattr(self,'sessions',out.get('conversations',[])))
    def restore(self,identifier):
        def done(out):
            self.identifier=identifier;self.view.clear()
            for message in out.get('history',[]):
                if message['role'] in ('user','assistant'):
                    content=message.get('content','')
                    if isinstance(content,list):content='\n'.join(b.get('text','') for b in content if b.get('type')=='text')
                    if content:self.view.append('You' if message['role']=='user' else 'Assistant',str(content))
        self.app.jobs.submit('assistant_history',{'conversationId':identifier},tag='sdk-history',done=done,failed=lambda error:setattr(self,'message',error))
    def send(self):
        text=self.text.strip()
        if not text or self.app.jobs.busy('sdk-chat'):return
        self.view.append('You',text);self.text='';self.message=''
        def done(out):
            self.identifier=out['conversationId'];self.view.append('Assistant',out['answer']);self.attachments=[];self.refresh()
        def failed(error):self.message=error;self.view.append('Error',error)
        self.app.jobs.submit('assistant_send',{'text':text,'conversationId':self.identifier,'allowEdits':self.allow_edits,'attachments':list(self.attachments)},tag='sdk-chat',done=done,failed=failed)
    def panel(self):
        jobs=self.app.jobs;job_id,_=jobs.active('sdk-chat');busy=bool(job_id)
        settings=(getattr(self.app,'ai_status',None) or {}).get('settings',{})
        cyui.panel_header(tr('Application assistant'),'CyMCPSDK '+self.sdk_version+' · '+settings.get('provider',''))
        if not self.loaded:self.refresh();self.loaded=True
        imgui.text_wrapped(tr('The assistant uses the same operations and permissions as the CLI and MCP.'))
        if imgui.button(label('Refresh conversations')):self.refresh()
        imgui.same_line()
        with cyui.scoped_disabled(busy):
            if imgui.button(label('New conversation')):self.identifier='';self.view.clear();self.attachments=[];self.message=''
        if self.sessions:
            _,self.selected=imgui.combo(label('Conversation'),min(self.selected,len(self.sessions)-1),[str(s.get('title') or s['conversationId']) for s in self.sessions])
            with cyui.scoped_disabled(busy):
                if imgui.button(label('Restore conversation')):self.restore(self.sessions[self.selected]['conversationId'])
        with cyui.scoped_disabled(busy):
            _,self.allow_edits=imgui.checkbox(label('Allow application changes'),self.allow_edits)
            _,self.text=imgui.input_text_multiline('##sdk-message',self.text,cyui.dp2(-1,85))
            if imgui.button(label('Attach files')):self.dialog=pfd.open_file(tr('Attach files'),'',[],pfd.opt.multiselect)
            imgui.same_line()
            if imgui.button(label('Clear attachments')):self.attachments=[]
            if self.dialog and self.dialog.ready():self.attachments=self.dialog.result();self.dialog=None
            if self.attachments:imgui.text_wrapped(', '.join(Path(p).name for p in self.attachments))
            imgui.same_line()
            with cyui.scoped_disabled(not self.text.strip()):
                if cyui.primary_button(label('Send')):
                    self.send()
        if busy:jobs.progress_widget('sdk-chat')
        if self.message:imgui.text_wrapped(self.message)
        self.view.render('###sdk-transcript',jobs.deltas.get(job_id,'') if job_id else '')

def settings_panel(app):
    """Explicit host configuration, never an assistant-callable operation."""
    if not imgui.collapsing_header(label('CyMCPSDK options and external tools')):return
    panel=app.sdk_chat
    path=app.runtime.root.parent/'settings/mcp.json'
    remote=app.runtime.assistant.config_file
    if not panel.settings_loaded:
        panel.settings_text=json.dumps({'optimizations':{k:v for k,v in app.runtime.options.items()},'external':app.runtime.assistant.configuration()},indent=2,ensure_ascii=False)
        from cyui_modules.code import CodeEditor
        panel.settings_editor=CodeEditor(panel.settings_text,'json');panel.settings_loaded=True
    imgui.text_wrapped(tr('Options are independent. Save and restart to apply. External tools require an explicit allowedTools list.'))
    panel.settings_editor.draw('##sdk-options',(-1,cyui.dp(260)))
    if imgui.button(label('Save SDK options')):
        try:
            from cydec.mcp.configuration import validate_options,validate_servers
            values=json.loads(panel.settings_editor.text);optimizations=validate_options(values['optimizations']);external=validate_servers(values.get('external',{}))
            from cydec.paths import write_json
            write_json(path,optimizations);write_json(remote,external);panel.message=tr('Saved. Restart the Tool after current jobs finish.')
        except Exception as exc:panel.message=str(exc)
    if panel.message:imgui.text_wrapped(panel.message)
