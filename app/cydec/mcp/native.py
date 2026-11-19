"""Ownership-safe ctypes boundary to the compiled CyMCPSDK C++20 bridge."""
import ctypes
import json
import os
from pathlib import Path
import threading
import time
from .errors import CyToolError

ROOT=Path(__file__).resolve().parents[3]
CALLBACK=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_char_p)
def sdk_schema(value):
    # Historical host input-staging annotation, not a JSON Schema assertion.
    if isinstance(value,dict):return {k:sdk_schema(v) for k,v in value.items() if k!='x-cy-kind'}
    if isinstance(value,list):return [sdk_schema(v) for v in value]
    return value
DEFAULTS={'compactDiscovery':True,'cache':True,'cacheTtlMs':30000,'notifications':True,
          'diskSpool':True,'diskBytes':128*1024**2,'memoryBytes':16*1024**2,
          'retentionSeconds':900,'chunkBytes':32768,'inlineBytes':16384,'telemetry':False,
          'contextBytes':256*1024,'recentTurns':8,'ripgrep':False,'workspaceRoot':'','spoolRoot':''}

class Native:
    def __init__(self,callback=None,*,directory=None,options=None):
        self._lifetime=threading.Condition(threading.RLock());self._calls=0;self._closing=False
        suffix='cydec_mcp.dll' if os.name=='nt' else 'libcydec_mcp.so'
        binary=Path(os.environ.get('CYDEC_MCP_LIBRARY',ROOT/'runtime/native/CyMCPSDK'/suffix))
        if not binary.is_file():
            binary=ROOT/'app/native/bin'/suffix
        if not binary.is_file():raise CyToolError('MissingDependency','Build CyMCPSDK first: python app/scripts/build_mcp_sdk.py')
        self.library=ctypes.CDLL(str(binary))
        self.library.cydec_create.argtypes=[CALLBACK,ctypes.c_char_p];self.library.cydec_create.restype=ctypes.c_void_p
        self.library.cydec_call.argtypes=[ctypes.c_void_p,ctypes.c_char_p];self.library.cydec_call.restype=ctypes.c_void_p
        self.library.cydec_free.argtypes=[ctypes.c_void_p]
        self.library.cydec_destroy.argtypes=[ctypes.c_void_p]
        # Native transport callbacks may arrive on foreign threads. ctypes creates
        # transient Python thread states there, so threading.local cannot own a
        # returned buffer: it can be collected before C++ copies the response.
        self.buffers={};self.buffer_lock=threading.Lock();self.callback=callback
        self._callback=CALLBACK(self._host)
        self.options={**DEFAULTS,**(options or {})}
        directory=Path(directory or ROOT/'data/mcp').resolve();directory.mkdir(parents=True,exist_ok=True)
        spool=Path(self.options.get('spoolRoot') or directory/'spool').expanduser().resolve()
        self.options.update(spoolDirectory=str(spool),metricsFile=str(directory/'metrics.jsonl'))
        if not self.options['cache']: self.options['cacheTtlMs']=0
        self.handle=self.library.cydec_create(self._callback,self.encode(self.options))
        if not self.handle:raise CyToolError('ConfigurationError','Cannot initialize CyMCPSDK; verify private storage and optimization options.')
    @staticmethod
    def encode(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
    def _host(self,raw):
        try:
            result=self.callback(json.loads(raw)) if self.callback else {}
            response={'result':result}
        except CyToolError as exc: response={'error':exc.to_dict()}
        except Exception as exc: response={'error':{'code':'HostError','message':str(exc)}}
        # The SDK copies this buffer before the callback returns to another invocation.
        buffer=ctypes.create_string_buffer(self.encode(response))
        with self.buffer_lock:self.buffers[threading.get_ident()]=buffer
        return ctypes.addressof(buffer)
    def call(self,command,**parameters):
        with self._lifetime:
            if not self.handle or self._closing:raise CyToolError('InvalidState','SDK bridge is closed or stopping.')
            handle=self.handle;self._calls+=1
        try:
            if 'schema' in parameters:parameters['schema']=sdk_schema(parameters['schema'])
            if 'operation' in parameters:parameters['operation']=sdk_schema(parameters['operation'])
            pointer=self.library.cydec_call(handle,self.encode({'command':command,**parameters}))
            if not pointer:raise CyToolError('NativeError','SDK returned no data.')
            try:response=json.loads(ctypes.string_at(pointer))
            finally:self.library.cydec_free(pointer)
            if 'error' in response:
                e=response['error'];raise CyToolError(e['code'],e['message'])
            return response['result']
        finally:
            with self._lifetime:self._calls-=1;self._lifetime.notify_all()
    def close(self,timeout=10):
        deadline=time.monotonic()+timeout
        with self._lifetime:
            if not self.handle:return
            self._closing=True
            while self._calls:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise CyToolError('Busy','Native SDK calls are still stopping; the library remains owned.')
                self._lifetime.wait(remaining)
            handle=self.handle;self.handle=None
        self.library.cydec_destroy(handle)

_validator=None
_lock=threading.Lock()
def validate_parameters(value,schema):
    global _validator
    with _lock:
        if _validator is None:_validator=Native()
    _validator.call('validate',value=value,schema=schema)
    # Match the historical CLI's default insertion without changing SDK validation semantics.
    if isinstance(value,dict):
        value=dict(value)
        for key,spec in schema.get('properties',{}).items():
            if key not in value and 'default' in spec:value[key]=spec['default']
    return value
