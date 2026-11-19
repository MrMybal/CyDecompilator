"""Thin authenticated framing around the native SDK's MCP dispatcher."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import urllib.request
import uuid
from .errors import CyToolError
from .api import LocalClient

MAX_MESSAGE=16*1024**2
def token_environment():return os.environ.get('CYMCP_TOKEN') or os.environ.get('CYTOOLS_TOKEN','')

class LiveServer:
    def __init__(self,runtime,port=None,*,advertise=False,require_token=False):
        self.runtime,self.port=runtime,port;self.server=None;self.advertise=advertise;self.require_token=require_token;self.marker=None
    def __enter__(self):
        if self.port is not None:
            self.server=make_server(self.runtime,self.port)
            try:
                if self.advertise:
                    from .instance import publish
                    self.marker=publish(self.runtime,self.server,require_token=self.require_token)
            except BaseException:self.server.server_close();raise
            self.thread=threading.Thread(target=self.server.serve_forever,name='CyDecompilatorInstance',daemon=True);self.thread.start()
            print('CyDecompilator instance: http://127.0.0.1:%d/v1; MCP: /mcp; bearer authentication required.'%self.server.server_port,file=sys.stderr,flush=True)
        return self
    def __exit__(self,*args):
        if self.server:
            if self.marker:
                from .instance import unpublish
                unpublish(self.runtime,self.marker)
            self.server.shutdown();self.server.server_close();self.thread.join(5)

class HTTPClient:
    def __init__(self,url,token,*,timeout=120):
        from .instance import local_url
        local_url(url.rstrip('/'),'/v1')
        self.url=url.rstrip('/');self.token=token;self.timeout=timeout;self.connection_id=uuid.uuid4().hex
    def call(self,method,**parameters):
        payload=json.dumps({'protocolVersion':'1.0','id':1,'method':method,'params':parameters}).encode()
        request=urllib.request.Request(self.url,data=payload,headers={'Content-Type':'application/json','Authorization':'Bearer '+self.token,'X-CyDecompilator-Connection':self.connection_id})
        try:
            with urllib.request.urlopen(request,timeout=self.timeout) as response:result=json.load(response)
        except urllib.error.HTTPError as exc:raise CyToolError('AuthenticationRequired' if exc.code==401 else 'AccessDenied' if exc.code==403 else 'ConnectionFailed','Instance refused the request: HTTP '+str(exc.code)) from None
        if 'error' in result:raise CyToolError(result['error']['code'],result['error']['message'])
        return result['result']


def serve_proxy(url,token,*,compact=True):
    """Forward framing to the owning instance's native MCP server; never replay calls."""
    from .instance import local_url
    local_url(url,'/mcp');lock=threading.Lock();connection=uuid.uuid4().hex
    def emit(value):
        if value is not None:
            with lock:print(json.dumps(value,ensure_ascii=False,allow_nan=False),flush=True)
    def handle(request):
        try:
            payload=json.dumps(request,ensure_ascii=False,allow_nan=False).encode('utf-8')
            headers={'Content-Type':'application/json','Authorization':'Bearer '+token,
                     'X-CyDecompilator-Connection':connection,'X-CyDecompilator-Discovery':'compact' if compact else 'full'}
            message=urllib.request.Request(url,data=payload,headers=headers)
            with urllib.request.urlopen(message,timeout=None) as response:
                raw=response.read(MAX_MESSAGE+1)
                if len(raw)>MAX_MESSAGE:raise CyToolError('ProtocolError','The instance returned an oversized MCP response. Use asynchronous jobs and chunked result reads.')
                if raw:emit(json.loads(raw))
        except (OSError,ValueError,CyToolError):
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

def make_server(runtime,port=0):
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def handle(self):
            try:super().handle()
            except (ConnectionResetError,BrokenPipeError):pass
        def log_message(self,*args):pass
        def do_POST(self):
            status=200;result=None
            try:
                if self.path not in ('/v1','/mcp'):raise CyToolError('NotFound','Unknown endpoint.')
                if self.headers.get('Origin') and self.headers['Origin'] not in ('http://127.0.0.1','http://localhost'):raise CyToolError('AccessDenied','Browser origin is not permitted.')
                bearer=self.headers.get('Authorization','')
                if not bearer.startswith('Bearer '):raise CyToolError('AuthenticationRequired','Bearer token required.')
                actor=runtime.authenticate(bearer[7:]);length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=MAX_MESSAGE:raise CyToolError('InvalidRequest','Invalid message length.')
                request=json.loads(self.rfile.read(length))
                connection=self.headers.get('X-CyDecompilator-Connection','')
                if connection and (len(connection)!=32 or any(c not in '0123456789abcdef' for c in connection)):raise CyToolError('InvalidRequest','Invalid local connection identifier.')
                if self.path=='/mcp':
                    discovery=self.headers.get('X-CyDecompilator-Discovery','')
                    if discovery not in ('','compact','full'):raise CyToolError('InvalidRequest','Invalid MCP discovery mode.')
                    result=runtime.native.call('mcp',request=request,principal=actor.client_id,scope='http:'+actor.client_id+(':'+connection if connection else ''),compact=discovery=='compact' if discovery else runtime.options['compactDiscovery'],notifications=False)
                else:result=LocalClient(runtime,actor,scope='sdk-http:'+actor.client_id+(':'+connection if connection else '')).dispatch(request)
            except CyToolError as exc:
                status=401 if exc.code=='AuthenticationRequired' else 403 if exc.code=='AccessDenied' else 400;result={'error':exc.to_dict()}
            except (ValueError,TypeError,KeyError):status=400;result={'error':{'code':'InvalidRequest','message':'Invalid request.'}}
            payload=json.dumps(result,ensure_ascii=False,allow_nan=False).encode('utf-8') if result is not None else b''
            self.send_response(status if result is not None else 202);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def do_DELETE(self):
            self.send_response(204);self.send_header('Content-Length','0');self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    return server
