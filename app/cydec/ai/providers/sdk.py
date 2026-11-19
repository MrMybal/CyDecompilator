"""Native conversation adapters for existing function assistance and workflows."""
import threading
import time
import uuid
from pathlib import Path
from cydec.mcp import Native,CyToolError
from .base import Provider,ChatResult,Delta,SESSION,STATELESS

class SDKProvider(Provider):
    def __init__(self,registry,spec,settings):
        super().__init__(settings);self.registry=registry;self.spec=spec;self.id=spec['id'];self.name=spec['name']
        self.transports=(spec['transport'],);caps=spec['available_capabilities']
        self.kind=SESSION if caps.get('resume') or caps.get('persistent_process') else STATELESS
        self.supports_streaming=caps.get('streaming',False);self.supports_model_list=caps.get('model_catalogue',False)
        self.requires_api_key=spec.get('authentication')=='api-key';self._active=set();self._lock=threading.Lock()
    def descriptor(self):return {**super().descriptor(),'capabilities':self.spec['available_capabilities'],'sdk':'CyMCPSDK'}
    def transport_for(self,transport):
        if transport in ('app-server','cli-jsonl'):
            if self.id=='codex' and transport=='cli-jsonl':return 'cli-exec-json'
            return self.transports[0]
        return super().transport_for(transport)
    def detect(self):return next(p for p in self.registry.detect() if p['id']==self.id)
    def parameters(self):
        from .. import credentials
        settings=dict(self.settings);executable=settings.pop('executable','')
        if 'timeout_seconds' in settings:settings['timeout_ms']=int(settings.pop('timeout_seconds')*1000)
        return {'provider':self.id,'settings':settings,'executable':executable,'apiKey':credentials.resolve(self.id)}
    def list_models(self,transport=''):
        self.transport_for(transport);result=self.registry.native.call('models',**self.parameters())
        return result.get('models',result.get('data',[])) if isinstance(result,dict) else result
    def chat(self,request,on_delta):
        request.check();identifier=uuid.uuid4().hex;request_id='model-'+identifier;finished=threading.Event();opened=False
        p=self.parameters();p['settings'].update(max_output_tokens=request.settings.get('max_tokens',8192),deferred_tools=True)
        if self.id=='codex' and request.transport in ('cli-jsonl','cli-exec-json'):p['provider']='codex-exec'
        if self.id=='opencode' and request.transport in ('cli-jsonl','cli-jsonl-v1'):p['provider']='opencode-cli'
        if request.settings.get('temperature') is not None:p['settings']['temperature']=request.settings['temperature']
        if request.workspace:p['workingDirectory']=str(request.workspace)
        p.update(id=identifier,model=request.model,system=request.system_prompt,nativeId=request.native_id,tools=False,requestId=request_id,contextBytes=self.registry.context_bytes,recentTurns=self.registry.recent_turns)
        if self.kind!=SESSION and request.messages:p['history']=list(request.messages)
        def receive(event):
            if event['payload']['type']=='TextDelta':on_delta(Delta.TEXT,event['payload']['data'].get('text',''))
            elif event['payload']['type'] in ('ToolStarted','ToolCompleted'):on_delta(Delta.TOOL,event['payload']['data'])
        with self.registry.lock:self.registry.callbacks[request_id]=receive
        with self._lock:self._active.add(identifier)
        def watch():
            while not finished.wait(.05):
                try:request.check()
                except CyToolError:
                    self.registry.native.call('cancel',id=request_id);return
        watcher=threading.Thread(target=watch,daemon=True);watcher.start();started=time.monotonic()
        try:
            self.registry.native.call('conversationOpen',**p);opened=True
            result=self.registry.native.call('conversationSend',id=identifier,content=request.prompt,requestId=request_id)
            request.check()
            return ChatResult(result['text'],native_id=result.get('nativeId',''),model=result.get('model',request.model),usage=result.get('usage',{}),transport=self.transports[0],seconds=time.monotonic()-started)
        finally:
            finished.set();watcher.join(1)
            if opened:self.registry.native.call('conversationClose',id=identifier)
            self.registry.native.call('releaseRequest',id=request_id)
            with self.registry.lock:self.registry.callbacks.pop(request_id,None)
            with self._lock:self._active.discard(identifier)
    def cancel(self):
        with self._lock:
            for identifier in self._active:self.registry.native.call('conversationCancel',id=identifier)
    def close(self):self.cancel()

class Registry:
    def __init__(self,settings=None,workspace=None,options=None):
        self.settings=dict(settings or {});self.lock=threading.Lock();self.callbacks={}
        self.native=Native(self._callback,directory=Path(workspace or '.')/'sdk',options=options)
        self.context_bytes=self.native.options['contextBytes'];self.recent_turns=self.native.options['recentTurns']
        self.providers={p['id']:SDKProvider(self,p,{**(self.settings.get('agents',{}) if p['available_capabilities'].get('resume') or p['available_capabilities'].get('persistent_process') else {}),**self.settings.get(p['id'],{})}) for p in self.native.call('providers')}
    def _callback(self,event):
        if event['type']=='event':
            with self.lock:callback=self.callbacks.get(event['requestId'])
            if callback:callback(event)
        return {}
    def get(self,identifier):
        if identifier not in self.providers:raise CyToolError('NotFound','Unknown SDK provider: '+str(identifier))
        return self.providers[identifier]
    def descriptors(self):return [p.descriptor() for p in self.providers.values()]
    def detect(self,provider_id=''):
        configured={k:p.parameters() for k,p in self.providers.items()}
        connections={p['id']:p for p in self.native.call('discover',configured=configured)}
        result=[]
        for provider in self.providers.values():
            if provider_id and provider.id!=provider_id:continue
            row=connections.get(provider.id,{})
            result.append({**provider.descriptor(),'available':row.get('state')=='available','status':row.get('state','not-configured'),'detail':row.get('errorCode','') or row.get('source',''),'models':row.get('models',[])})
        return result
    def close(self):
        for provider in self.providers.values():provider.close()
        self.native.close()
