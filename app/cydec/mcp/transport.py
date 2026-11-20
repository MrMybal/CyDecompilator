"""SDK-owned loopback HTTP and stdio framing around the native dispatcher."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import threading
import urllib.request
import uuid
from .errors import CyToolError

MAX_MESSAGE=16*1024**2
def token_environment():return os.environ.get('CYMCP_TOKEN') or os.environ.get('CYTOOLS_TOKEN','')

class LiveServer:
    def __init__(self,runtime,port=None,*,advertise=False,require_token=None):
        from .configuration import ACCESS_PROFILES
        self.runtime,self.port=runtime,port;self.server=None;self.advertise=advertise;self.marker=None
        self.require_token=ACCESS_PROFILES[runtime.options['accessProfile']][0] or bool(require_token)
    def __enter__(self):
        if self.port is not None:
            self.server=make_server(self.runtime,self.port,require_token=self.require_token)
            try:
                if self.advertise:
                    from .instance import publish
                    self.marker=publish(self.runtime,self.server,require_token=self.require_token)
            except BaseException:self.server.server_close();raise
            self.thread=threading.Thread(target=self.server.serve_forever,name='CyDecompilatorInstance',daemon=True);self.thread.start()
            print('CyDecompilator instance: http://127.0.0.1:%d/v1; MCP: /mcp; profile %s; %s.'%(self.server.server_port,self.runtime.options['accessProfile'],'bearer authentication required' if self.require_token else 'address-only access'),file=sys.stderr,flush=True)
        return self
    def __exit__(self,*args):
        if self.server:
            if self.marker:
                from .instance import unpublish
                unpublish(self.runtime,self.marker)
            self.server.shutdown();self.server.server_close();self.thread.join(5)

class HTTPClient:
    def __init__(self,url,token='',*,timeout=120):
        from .instance import local_url
        local_url(url.rstrip('/'),'/v1')
        self.url=url.rstrip('/');self.token=token;self.timeout=timeout;self.connection_id=uuid.uuid4().hex
    def call(self,method,**parameters):
        payload=json.dumps({'protocolVersion':'1.0','id':1,'method':method,'params':parameters,'_cyConnection':self.connection_id}).encode()
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        request=urllib.request.Request(self.url,data=payload,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=self.timeout) as response:result=json.load(response)
        except urllib.error.HTTPError as exc:raise CyToolError('AuthenticationRequired' if exc.code==401 else 'AccessDenied' if exc.code==403 else 'ConnectionFailed','Instance refused the request: HTTP '+str(exc.code)) from None
        if 'error' in result:raise CyToolError(result['error']['code'],result['error']['message'])
        return result['result']


def serve_proxy(url,token,*,compact=True):
    """Forward framing to the owning instance's native MCP server; never replay calls."""
    from .instance import local_url
    local_url(url,'/mcp');lock=threading.Lock();connection=uuid.uuid4().hex;session={}
    def emit(value):
        if value is not None:
            with lock:print(json.dumps(value,ensure_ascii=False,allow_nan=False),flush=True)
    def handle(request):
        try:
            payload=json.dumps({**request,'_cyConnection':connection,'_cyDiscovery':'compact' if compact else 'full'},ensure_ascii=False,allow_nan=False).encode('utf-8')
            headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
            if token:headers['Authorization']='Bearer '+token
            if session.get('id'):headers['Mcp-Session-Id']=session['id']
            if session.get('protocol'):headers['MCP-Protocol-Version']=session['protocol']
            params=request.get('params',{})
            metadata=params.get('_meta',{}) if isinstance(params,dict) else {}
            if isinstance(metadata,dict) and 'io.modelcontextprotocol/protocolVersion' in metadata:
                headers['MCP-Protocol-Version']=metadata['io.modelcontextprotocol/protocolVersion']
                headers['Mcp-Method']=request.get('method','')
                field='name' if request.get('method') in ('tools/call','prompts/get') else 'uri' if request.get('method')=='resources/read' else None
                if field and isinstance(params.get(field),str):
                    import base64
                    name=params[field]
                    encoded=name!=name.strip(' \t') or name.startswith('=?base64?') and name.endswith('?=') or any(ord(c)>126 or ord(c)<32 and c!='\t' for c in name)
                    headers['Mcp-Name']='=?base64?'+base64.b64encode(name.encode('utf-8')).decode()+'?=' if encoded else name
            message=urllib.request.Request(url,data=payload,headers=headers)
            with urllib.request.urlopen(message,timeout=None) as response:
                raw=response.read(MAX_MESSAGE+1)
                if len(raw)>MAX_MESSAGE:raise CyToolError('ProtocolError','The instance returned an oversized MCP response. Use asynchronous jobs and chunked result reads.')
                if raw:
                    value=json.loads(raw)
                    if request.get('method')=='initialize' and response.headers.get('Mcp-Session-Id'):
                        session.update(id=response.headers['Mcp-Session-Id'],protocol=value['result']['protocolVersion'])
                    emit(value)
        except (OSError,ValueError,TypeError,CyToolError):
            # An uncertain response is not permission to repeat the operation.
            if 'id' in request:emit({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32603,'message':'The instance connection failed. The action may still be running; inspect its durable jobs before retrying.'}})
    with ThreadPoolExecutor(max_workers=8,thread_name_prefix='CyDecMCPProxy') as pool:
        for raw in sys.stdin.buffer:
            try:
                if len(raw)>MAX_MESSAGE:raise ValueError('Oversized message')
                request=json.loads(raw)
                if not isinstance(request,dict):raise ValueError('Expected object')
            except (ValueError,UnicodeError):emit({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Invalid MCP JSON message.'}});continue
            if request.get('method')=='notifications/cancelled':handle(request)
            else:pool.submit(handle,request)

def serve_stdio(runtime,actor,*,compact=False):
    lock=threading.Lock()
    def emit(value):
        if value is not None:
            with lock:print(json.dumps(value,ensure_ascii=False,allow_nan=False),flush=True)
    runtime._notification_sinks[actor.client_id]=emit
    def handle(request):
        try:emit(runtime.native.call('mcp',request=request,principal=actor.client_id,scope='stdio',compact=compact,notifications=True))
        except CyToolError as exc:emit({'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32603,'message':str(exc)}})
    try:
        with ThreadPoolExecutor(max_workers=8,thread_name_prefix='CyDecMCP') as pool:
            for raw in sys.stdin.buffer:
                if len(raw)>MAX_MESSAGE:
                    emit({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Message exceeds 16 MiB.'}});continue
                try:request=json.loads(raw)
                except (ValueError,UnicodeError):emit({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Invalid JSON.'}});continue
                if not isinstance(request,dict):emit({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Expected object.'}});continue
                # Cancellation must not wait behind the call it cancels.
                if request.get('method')=='notifications/cancelled':handle(request)
                else:pool.submit(handle,request)
    finally:
        runtime._notification_sinks.pop(actor.client_id,None)
        for key,identifier in list(runtime._transport_sessions.items()):
            if key[0]==actor.client_id:
                try:runtime.finish_task(actor,identifier,cancel_running=True)
                except CyToolError:pass

def make_server(runtime,port=0,*,require_token=None):
    """Compatibility lifecycle adapter; sockets, authentication and MCP HTTP are SDK-owned."""
    from .configuration import ACCESS_PROFILES
    required=ACCESS_PROFILES[runtime.options['accessProfile']][0] or bool(require_token)
    class Server:
        def __init__(self):
            self.server_port=runtime.native.call('httpStart',port=port,requireToken=required)['port']
            self.stopped=threading.Event();self.closed=False
        def serve_forever(self):self.stopped.wait()
        def shutdown(self):self.server_close()
        def server_close(self):
            if not self.closed:
                self.closed=True
                try:runtime.native.call('httpStop')
                finally:self.stopped.set()
    return Server()
