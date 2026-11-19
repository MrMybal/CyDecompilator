"""Durable application jobs around CyMCPSDK's validated, permission-gated registry.

This is host lifecycle/storage, not a replacement MCP implementation. Native SDK
Registry, McpServer, Conversation, ToolGateway and McpClient do protocol work.
"""
import copy
from contextlib import ExitStack
from collections import deque
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import threading
import time
import uuid
from .errors import CyToolError
from .native import Native, validate_parameters, DEFAULTS
from .storage import Store,RuntimeLock

TERMINAL={'Completed','Failed','Cancelled'}
CONFIRM={'delete_project','remove_component','update_apply','update_rollback'}
def uid():return uuid.uuid4().hex
def now():return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class Principal:
    client_id:str
    permissions:frozenset

class Cancellation:
    def __init__(self,deadline=None):self.flag=threading.Event();self.event=self.flag;self.deadline=deadline;self.reason='Cancelled';self.code='Cancelled'
    def cancel(self,reason='Cancelled',code='Cancelled'):self.reason=reason;self.code=code;self.flag.set()
    def check(self):
        if self.flag.is_set():raise CyToolError(self.code,self.reason)
        if self.deadline and time.monotonic()>self.deadline:raise CyToolError('Timeout','Execution deadline exceeded.')
    def sleep(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.check();self.flag.wait(min(.05,max(0,end-time.monotonic())))

class JobContext:
    def __init__(self,runtime,job_id,token):self.runtime,self.job_id,self.cancellation=runtime,job_id,token
    def path(self,relative):
        base=Path(self.runtime._jobs[self.job_id]['workspace']).resolve();target=(base/relative).resolve()
        if Path(relative).is_absolute() or not target.is_relative_to(base):raise CyToolError('AccessDenied','Job path escapes its workspace.')
        target.parent.mkdir(parents=True,exist_ok=True);return target
    def progress(self,percent,**fields):
        with self.runtime._cv:
            job=self.runtime._jobs[self.job_id];job['progress']={'percent':min(100,max(0,float(percent))),**fields}
            self.runtime._emit('JobProgress',job,job['progress'])
    def emit(self,event_type,data):self.runtime._emit(event_type,self.runtime._jobs[self.job_id],data)
    def log(self,message,level='Info'):self.emit('Log',{'message':str(message),'level':level})
    def import_input(self,source,*,base_dir=None,suffixes=(),max_bytes=8*1024**3,keep=False):
        return self.runtime._snapshot(Path(source),self.path('inputs/.keep').parent,max_bytes)
    def observe_resources(self,*args,**kwargs):pass

def read_only(name):
    return name.startswith(('list_','get_','describe','project_info','function_info','strings','xrefs','search','installation_','unreal_rules','unreal_guide')) or name in {'workspace_info','workspace_read','workspace_search','workspace_grep_native','workspace_read_native','debug_status','porting_info','porting_plan','patch_outputs','ai_conversations','reconstruction_status'}

class Runtime:
    def __init__(self,descriptor,data_dir,*,capacity=None,system=None,event_limit=20000):
        self.descriptor=copy.deepcopy(descriptor);self.root=Path(data_dir).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.instance_id=uid()
        self._ownership=RuntimeLock(self.root/'runtime.lock.sqlite3');self.store=Store(self.root/'state.sqlite3')
        identity=self.store.all('settings').get('identity')
        if identity and identity['toolId']!=descriptor['id']:
            self.store.close();self._ownership.close();raise CyToolError('InvalidState','Data directory belongs to another application.')
        self.store.put('settings','identity',{'toolId':descriptor['id'],'protocolVersion':'1.0'})
        self._clients=self.store.all('clients');self._sessions=self.store.all('sessions');self._jobs=self.store.all('jobs')
        self._cv=threading.Condition(threading.RLock());self._handlers={};self._tokens={};self._threads={};self._queue=[];self._running=set()
        self._events=deque(maxlen=event_limit);self._sequence=0;self._closed=False;self._started=False;self._transport_sessions={};self._notification_sinks={}
        self._chat_grants={}
        self._delegations={}
        self.input_root=self.root/'inputs';self.input_root.mkdir(exist_ok=True);self.input_fields={};self.input_max_bytes=1024**4
        self.max_workers=descriptor.get('concurrency',{}).get('maxWorkers',6)
        self.capacity=capacity or {};self.system=system or {};self._active_groups=set()
        self._business_locks={}
        options_path=self.root.parent/'settings/mcp.json'
        from .configuration import validate_options
        try:self.options=validate_options(json.loads(options_path.read_text('utf-8')))
        except FileNotFoundError:self.options=validate_options({})
        self.native=Native(self._native_callback,directory=self.root/'sdk',options=self.options)
        from .assistant import Assistant
        self.assistant=Assistant(self)
        for job in self._jobs.values():
            if job['state'] not in TERMINAL:
                job.update(state='Failed',finishedAt=now(),error=CyToolError('Interrupted','Application stopped before completion; inspect results before explicitly retrying.',recoverable=True).to_dict());self._save(job)
        self._emit('ToolStarted',data={})
    def register(self,operation_id,handler,*,estimate=None):
        if self._started:raise CyToolError('InvalidState','Register before starting the runtime.')
        self.operation(operation_id)
        if operation_id in self._handlers:raise CyToolError('Conflict','Duplicate handler.')
        self._handlers[operation_id]=handler
    def operation(self,name):
        for o in self.descriptor['operations']:
            if o['id']==name:return copy.deepcopy(o)
        raise CyToolError('UnknownOperation','Unknown operation: '+name)
    def start(self):
        with self._cv:
            if self._started:return self
            if set(o['id'] for o in self.descriptor['operations'])!=set(self._handlers):raise CyToolError('MissingImplementation','Operation handlers and registry differ.')
            for o in self.descriptor['operations']:
                self.native.call('register',operation={'name':o['id'],'description':o['description'],'inputSchema':o['inputSchema'],'outputSchema':o.get('outputSchema',{'type':'object'}),'readOnly':read_only(o['id'])})
                # Compatibility: old MCP clients submit a durable job and poll cy_get_job.
                props={'parameters':o['inputSchema'],'sessionId':{'type':'string'},'backendId':{'type':'string'},'modelId':{'type':'string'},'priority':{'type':'string','enum':['Interactive','Critical','High','Normal','Background','Low']},'queueTimeout':{'type':'number','minimum':.001},'executionTimeout':{'type':'number','minimum':.001},'confirmed':{'type':'boolean'}}
                self.native.call('register',operation={'name':'op_'+o['id'],'description':o['description']+' Start an asynchronous job; poll cy_get_job. Existing clients remain supported.','inputSchema':{'type':'object','properties':props,'required':['parameters'],'additionalProperties':False},'outputSchema':{'type':'object'},'readOnly':False})
            from .api import CONTROL_SCHEMAS
            for name,(method,schema) in CONTROL_SCHEMAS.items():
                self.native.call('register',operation={'name':name,'description':method+' on this application instance. Job results are durable; expired transient references never repeat operations.','inputSchema':schema,'outputSchema':{'type':'object'},'readOnly':name not in {'cy_cancel_job','cy_finish_task','cy_begin_task','cy_import_file','cy_export_job','cy_release_resources','cy_keep_task_alive'}})
            self.native.call('resource',uri='cydec://operations',name='Operation catalogue',description='Stable application operations and their schemas.',text=json.dumps(self.descriptor['operations']),mimeType='application/json')
            self._started=True
            self._scheduler=threading.Thread(target=self._schedule,name='CyDecompilatorJobs',daemon=True);self._scheduler.start()
        return self
    def __enter__(self):return self.start()
    def __exit__(self,*args):self.close()
    def create_client(self,name='local',permissions=()):
        token=secrets.token_urlsafe(32);identifier=uid()
        row={'clientId':identifier,'name':name,'permissions':list(permissions),'tokenHash':hashlib.sha256(token.encode()).hexdigest()}
        with self._cv:self._clients[identifier]=row;self.store.put('clients',identifier,row)
        return {'clientId':identifier,'token':token}
    def authenticate(self,token):
        digest=hashlib.sha256(str(token).encode()).hexdigest()
        for value in self._clients.values():
            if secrets.compare_digest(digest,value['tokenHash']):return Principal(value['clientId'],frozenset(value['permissions']))
        raise CyToolError('AuthenticationRequired','Invalid application credential.')
    def actor(self,identifier):
        row=self._clients.get(identifier)
        if row is None:raise CyToolError('AccessDenied','Unknown authenticated identity.')
        if row.get('delegated') and identifier not in self._delegations:raise CyToolError('AccessDenied','Conversation delegation is no longer active.')
        return Principal(identifier,frozenset(row['permissions']))
    def authorize(self,actor,name,parameters,*,confirmed=False):
        actual=self.actor(actor.client_id);operation=self.operation(name)
        if not set(operation.get('permissions',[]))<=actual.permissions:raise CyToolError('AccessDenied','The client lacks required application permissions.')
        if name in CONFIRM and not confirmed:raise CyToolError('ConfirmationRequired','Review the action, then explicitly confirm it. Noninteractive calls require --confirm or confirmed=true.')
        if name=='remote_call':
            from generation_config import secret_key
            def secret_fields(value):
                if isinstance(value,dict):return any(secret_key(k) or secret_fields(v) for k,v in value.items())
                if isinstance(value,list):return any(secret_fields(v) for v in value)
                return False
            if secret_fields(parameters.get('arguments',{})):raise CyToolError('InvalidParameters','External service credentials belong in the application vault, never business arguments or job records.')
        return validate_parameters(parameters,operation['inputSchema'])
    def create_session(self,principal,*,temporary=True,retention_seconds=3600):
        self.actor(principal.client_id)
        if type(temporary) is not bool or not 1<=retention_seconds<=86400:raise CyToolError('InvalidParameters','Invalid task retention.')
        row={'sessionId':uid(),'clientId':principal.client_id,'createdAt':now(),'closed':False,'temporary':temporary,'retentionSeconds':retention_seconds,'expiresAt':time.time()+retention_seconds}
        with self._cv:self._sessions[row['sessionId']]=row;self.store.put('sessions',row['sessionId'],row)
        return copy.deepcopy(row)
    def _session(self,actor,identifier,*,allow_closed=False):
        row=self._sessions.get(identifier)
        if not row or row['clientId']!=actor.client_id or (row['closed'] and not allow_closed):raise CyToolError('AccessDenied','Task belongs to another client or is closed.')
        return row
    def keep_task_alive(self,actor,identifier):
        with self._cv:
            row=self._session(actor,identifier);row['expiresAt']=time.time()+row['retentionSeconds'];self.store.put('sessions',identifier,row);return copy.deepcopy(row)
    def finish_task(self,actor,identifier,*,cancel_running=False):
        with self._cv:
            row=self._session(actor,identifier,allow_closed=True)
            jobs=[j for j in self._jobs.values() if j['sessionId']==identifier]
            active=[j for j in jobs if j['state'] not in TERMINAL]
            if active and not cancel_running:raise CyToolError('Busy','Stop running jobs before finishing this task.')
            for job in active:self.cancel(actor,job['jobId'])
        for job in active:self.wait(actor,job['jobId'],30)
        with self._cv:
            if any(j['state'] not in TERMINAL for j in jobs):raise CyToolError('Busy','Task workers are still stopping.')
            if row.get('temporary'):
                for job in jobs:
                    workspace=Path(job['workspace']).resolve()
                    if workspace.is_relative_to(self.root/'workspaces') and workspace.exists():shutil.rmtree(workspace)
                imported=self.root/'workspaces'/('task-'+identifier)
                if imported.exists():shutil.rmtree(imported)
            row.update(closed=True,cleanedAt=now());self.store.put('sessions',identifier,row)
        return {'sessionId':identifier,'finished':True,'cleaned':bool(row.get('temporary')),'resultsDurable':True}
    def close_session(self,actor,identifier):return self.finish_task(actor,identifier)
    def configure_inputs(self,root,*,max_bytes=1024**4,fields=None):
        self.input_root=Path(root).resolve();self.input_root.mkdir(parents=True,exist_ok=True);self.input_max_bytes=max_bytes;self.input_fields=fields or {}
    def _snapshot(self,source,destination,limit):
        source=Path(source).expanduser()
        if not source.is_absolute():
            source=(self.input_root/source).resolve()
            if not source.is_relative_to(self.input_root):raise CyToolError('AccessDenied','Relative input escapes input root.')
        if source.is_symlink() or getattr(source,'is_junction',lambda:False)():raise CyToolError('AccessDenied','Linked input is not supported.')
        if not source.is_file():raise CyToolError('NotFound','Input file is missing.')
        if source.stat().st_size>limit:raise CyToolError('InvalidParameters','Input exceeds its byte limit.')
        destination.mkdir(parents=True,exist_ok=True);target=destination/source.name;partial=target.with_name(target.name+'.'+uid()+'.partial')
        before=source.stat()
        with source.open('rb') as reader,partial.open('xb') as writer:
            total=0
            while data:=reader.read(1024*1024):
                total+=len(data)
                if total>limit:raise CyToolError('InvalidParameters','Input grew beyond its byte limit.')
                writer.write(data)
        after=source.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            partial.unlink(missing_ok=True);raise CyToolError('Conflict','Input changed during its snapshot; use a stable file.')
        partial.replace(target)
        return target
    def import_file(self,actor,session_id,source,*,companions=()):
        self._session(actor,session_id)
        original=Path(source).expanduser()
        if not original.is_absolute():raise CyToolError('InvalidParameters','Provide an absolute import source.')
        if 'filesystemExternal' not in actor.permissions and not original.resolve().is_relative_to(self.input_root):raise CyToolError('AccessDenied','Importing external files requires filesystemExternal.')
        for job in self._jobs.values():
            if original.resolve().is_relative_to(Path(job['workspace']).resolve()):self._allowed(actor,job)
        for session in self._sessions.values():
            other=self.root/'workspaces'/('task-'+session['sessionId'])
            if original.resolve().is_relative_to(other) and session['clientId']!=actor.client_id:raise CyToolError('AccessDenied','Source belongs to another task.')
        bundle=self.root/'workspaces'/('task-'+session_id)/'imports'/uid();files=[];total=0
        for name in [original.name,*dict.fromkeys(companions)]:
            relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts or not (original.parent/relative).resolve().is_relative_to(original.parent.resolve()):raise CyToolError('AccessDenied','Companion escapes source directory.')
            incoming=original.parent/relative
            target=self._snapshot(incoming,bundle/relative.parent,self.input_max_bytes-total)
            total+=target.stat().st_size;files.append({'path':str(target),'relativePath':relative.as_posix(),'sizeBytes':target.stat().st_size,'sha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest()})
        self.keep_task_alive(actor,session_id)
        return {'path':str(bundle/original.name),'source':str(source),'sizeBytes':total,'sessionId':session_id,'files':files,'temporary':True}
    def _save(self,job):self.store.put('jobs',job['jobId'],job)
    def _emit(self,kind,job=None,data=None,client_id=None):
        with self._cv:
            self._sequence+=1;self._events.append({'sequence':self._sequence,'type':kind,'jobId':job['jobId'] if job else '', 'clientId':client_id or (job['clientId'] if job else ''),'data':data or {},'timestamp':now()});self._cv.notify_all()
    def events(self,actor,after=0):
        with self._cv:return {'cursor':self._sequence,'gap':bool(self._events and after and after<self._events[0]['sequence']-1),'events':[copy.deepcopy(e) for e in self._events if e['sequence']>after and e['clientId'] in ('',actor.client_id)]}
    def submit(self,principal,session_id,operation_id,parameters,*,backend_id='',model_id='',priority='Normal',queue_timeout=None,execution_timeout=None,confirmed=False,**options):
        parameters=self.authorize(principal,operation_id,parameters,confirmed=confirmed)
        if priority not in ('Interactive','Critical','High','Normal','Background','Low'):raise CyToolError('InvalidParameters','Unknown priority.')
        if any(t is not None and (type(t) not in (int,float) or t<=0) for t in (queue_timeout,execution_timeout)):raise CyToolError('InvalidParameters','Timeouts must be positive.')
        with self._cv:
            if self._closed:raise CyToolError('InvalidState','Application runtime is closing.')
            self._session(principal,session_id);identifier=uid();workspace=self.root/'workspaces'/identifier;workspace.mkdir(parents=True)
            job={'jobId':identifier,'clientId':principal.client_id,'sessionId':session_id,'operationId':operation_id,'parameters':copy.deepcopy(parameters),'state':'Queued','createdAt':now(),'workspace':str(workspace),'outputs':None,'error':None,'progress':{'percent':0},'priority':priority,'backendId':backend_id,'modelId':model_id,'confirmed':confirmed,'queueTimeout':queue_timeout,'executionTimeout':execution_timeout,'visibility':'Owner','sharedWith':[],'queuedMonotonic':time.monotonic()}
            self._jobs[identifier]=job;self._tokens[identifier]=Cancellation();self._queue.append(identifier);self._save(job);self._emit('JobQueued',job)
            return copy.deepcopy(job)
    def _allowed(self,actor,job,write=False):
        if job['clientId']!=actor.client_id and (write or not (job.get('visibility')=='Public' or actor.client_id in job.get('sharedWith',[]))):raise CyToolError('AccessDenied','Job is private to its owner.')
    def get_job(self,actor,job_id):
        with self._cv:
            job=self._jobs.get(job_id)
            if job is None:raise CyToolError('NotFound','Job does not exist.')
            self._allowed(actor,job);return copy.deepcopy(job)
    def list_jobs(self,actor):
        with self._cv:return [copy.deepcopy(j) for j in self._jobs.values() if j['clientId']==actor.client_id or j.get('visibility')=='Public' or actor.client_id in j.get('sharedWith',[])]
    def share_job(self,actor,job_id,visibility='Owner',shared_with=None):
        with self._cv:
            job=self._jobs[job_id];self._allowed(actor,job,True)
            if visibility not in ('Owner','Shared','Public'):raise CyToolError('InvalidParameters','Unknown visibility.')
            job.update(visibility=visibility,sharedWith=list(shared_with or []));self._save(job);return copy.deepcopy(job)
    def cancel(self,actor,job_id):
        with self._cv:
            job=self._jobs.get(job_id)
            if job is None:raise CyToolError('NotFound','Job not found.')
            self._allowed(actor,job,True)
            if job_id in self._tokens:self._tokens[job_id].cancel()
            self.native.call('cancel',id=job_id)
            for child in list(self._jobs.values()):
                if child.get('parentJobId')==job_id and child['state'] not in TERMINAL:self.cancel(actor,child['jobId'])
            if job['state']=='Queued':job.update(state='Cancelled',finishedAt=now(),error=CyToolError('Cancelled','Cancelled before execution.').to_dict());self._save(job)
            self._emit('JobCancelled' if job['state']=='Cancelled' else 'JobCancelRequested',job);return copy.deepcopy(job)
    def _schedule(self):
        while True:
            with self._cv:
                if self._closed:return
                priorities={name:i for i,name in enumerate(('Interactive','Critical','High','Normal','Background','Low'))}
                self._queue.sort(key=lambda identifier:priorities.get(self._jobs[identifier]['priority'],3))
                for identifier in list(self._queue):
                    job=self._jobs[identifier]
                    if job['state']!='Queued':self._queue.remove(identifier);continue
                    if job['queueTimeout'] and time.monotonic()-job['queuedMonotonic']>job['queueTimeout']:
                        self._queue.remove(identifier);self._finish(job,'Failed',error=CyToolError('Timeout','Queue deadline exceeded.').to_dict());continue
                    groups=set(self.operation(job['operationId']).get('exclusiveGroups',[]))
                    if len(self._running)>=self.max_workers or groups & self._active_groups:continue
                    self._queue.remove(identifier);self._running.add(identifier);self._active_groups|=groups
                    thread=threading.Thread(target=self._execute,args=(identifier,groups),name='CyDec-'+job['operationId'],daemon=True);self._threads[identifier]=thread;thread.start()
                self._cv.wait(.05)
    def _execute(self,identifier,groups):
        job=self._jobs[identifier];token=self._tokens[identifier]
        try:
            token.deadline=time.monotonic()+job['executionTimeout'] if job['executionTimeout'] else None
            with self._cv:job.update(state='Running',startedAt=now());self._save(job);self._emit('JobStarted',job)
            result=self.native.call('invoke',name=job['operationId'],arguments=job['parameters'],principal=job['clientId'],requestId=identifier)
            token.check();self._finish(job,'Completed',outputs=result)
        except CyToolError as exc:self._finish(job,'Cancelled' if exc.code=='Cancelled' else 'Failed',error=exc.to_dict())
        except Exception as exc:self._finish(job,'Failed',error=CyToolError('InternalError',str(exc)).to_dict())
        finally:
            with self._cv:self._running.discard(identifier);self._active_groups-=groups;self._cv.notify_all()
            self.native.call('releaseRequest',id=identifier)
    def _finish(self,job,state,outputs=None,error=None):
        with self._cv:
            job.update(state=state,outputs=outputs,error=error,finishedAt=now());self._save(job);self._emit('Job'+state,job)
        if state=='Completed':self.native.call('publishChange',topic='resources')
    def wait(self,actor,identifier,timeout=30):
        deadline=time.monotonic()+timeout
        with self._cv:
            while True:
                job=self.get_job(actor,identifier)
                if job['state'] in TERMINAL:return job
                remaining=deadline-time.monotonic()
                if remaining<=0:raise CyToolError('Timeout','Job still exists; inspect it before explicitly retrying.')
                self._cv.wait(min(.1,remaining))
    def _connection_session(self,actor,scope='mcp'):
        key=(actor.client_id,scope)
        with self._cv:
            identifier=self._transport_sessions.get(key)
            if not identifier or self._sessions[identifier]['closed']:
                identifier=self.create_session(actor,temporary=True)['sessionId'];self._transport_sessions[key]=identifier
            return identifier
    def _native_callback(self,request):
        kind=request['type'];p=request['payload'];identifier=request.get('requestId','')
        if kind=='notification':
            sink=self._notification_sinks.get(request['principal'])
            if sink:sink(p)
            return {}
        if kind=='event':
            job=self._jobs.get(identifier)
            if job:
                event=p['type'];data=p['data']
                if event=='TextDelta':self._emit('AiDelta',job,{'text':data.get('text','')})
                elif event in ('ToolStarted','ToolCompleted'):self._emit('AiTool',job,{'event':event,'tool':data.get('name',data.get('tool','')),**data})
                else:self._emit(event,job,data)
            return {}
        actor=self.actor(request['principal'])
        name=p.get('name','');arguments=p.get('arguments',{})
        delegation=self._delegations.get(actor.client_id)
        if kind=='authorize':
            if delegation and not delegation.get('parentJobId'):raise CyToolError('AccessDenied','The conversation has no active user turn.')
            if name.startswith('cydec://') or name.startswith('cyresult:') or name.startswith('cymcp:') or name.startswith('resource') or name.startswith('resources.'):
                return {'allowed':True} # SDK retained handles enforce their own principal ownership.
            if name.startswith('cy_'):
                if delegation and name not in {'cy_get_job','cy_list_jobs','cy_cancel_job','cy_events','cy_read_result','cy_sdk_info','cy_finish_task','cy_keep_task_alive','cy_begin_task'}:raise CyToolError('AccessDenied','Control is outside this conversation delegation.')
                return {'allowed':True} # Control handlers enforce owner checks.
            original=name.removeprefix('op_');params=arguments.get('parameters',{}) if name.startswith('op_') else arguments
            grant=self._chat_grants.get(identifier) or delegation
            if grant is not None:
                if delegation and not delegation.get('parentJobId'):raise CyToolError('AccessDenied','The conversation has no active user turn.')
                if original not in grant['allowed']:raise CyToolError('AccessDenied','This tool is not granted to the conversation.')
                project=grant.get('projectId')
                if project and 'projectId' in params and params['projectId']!=project:raise CyToolError('AccessDenied','The conversation is scoped to its selected project.')
            job=self._jobs.get(identifier)
            confirmed=bool(job and job['clientId']==actor.client_id and job.get('confirmed')) or (name.startswith('op_') and arguments.get('confirmed') is True)
            self.authorize(actor,original,params,confirmed=confirmed);return {'allowed':True}
        if kind!='invoke':return {}
        scope=request.get('scope','host')+':'+request['principal']
        if delegation:
            actor=self.actor(delegation['ownerId']);identifier=delegation.get('parentJobId') or ''
        if name.startswith('cy_'):
            from .api import LocalClient,CONTROL_SCHEMAS
            method=CONTROL_SCHEMAS[name][0];params=dict(arguments)
            if delegation and method in ('GetJob','CancelJob','ReadResult') and params['jobId'] not in delegation['jobs']:raise CyToolError('AccessDenied','Job is outside this conversation.')
            direct_grant=self._chat_grants.get(identifier)
            if direct_grant and direct_grant.get('projectId'):
                selected=direct_grant['projectId']
                def within_project(job):return job.get('parameters',{}).get('projectId')==selected or (job.get('outputs') or {}).get('projectId')==selected
                if method in ('GetJob','ReadResult') and not within_project(self.get_job(actor,params['jobId'])):raise CyToolError('AccessDenied','Job is outside this selected project.')
                if method=='ListJobs':return {'result':[j for j in self.list_jobs(actor) if within_project(j)]}
            if delegation and method=='ListJobs':return {'result':[self.get_job(actor,j) for j in delegation['jobs']]}
            if delegation and method=='GetEvents':
                result=self.events(actor,params.get('after',0));result['events']=[e for e in result['events'] if e.get('jobId') in delegation['jobs']];return result
            if method in ('FinishTask','KeepTaskAlive','ImportFile'):params.setdefault('sessionId',self._connection_session(actor,scope))
            if delegation and params.get('sessionId') and params['sessionId']!=self._connection_session(actor,scope):raise CyToolError('AccessDenied','Task is outside this conversation.')
            result=LocalClient(self,actor).call(method,**params)
            return result if isinstance(result,dict) else {'result':result}
        if name.startswith('op_'):
            p=dict(arguments);session=p.pop('sessionId',None) or self._connection_session(actor,scope)
            if delegation and session!=self._connection_session(actor,scope):raise CyToolError('AccessDenied','Task is outside this conversation.')
            result=self.submit(actor,session,name[3:],p.pop('parameters'),backend_id=p.pop('backendId',''),model_id=p.pop('modelId',''),queue_timeout=p.pop('queueTimeout',None),execution_timeout=p.pop('executionTimeout',None),**p)
            if delegation:delegation['jobs'].add(result['jobId'])
            return result
        job=self._jobs.get(identifier)
        if not job or job['operationId']!=name:
            # Direct tools and tool calls inside a conversation execute synchronously,
            # still recording a durable child job. They do not wait on a saturated worker pool.
            session=job['sessionId'] if job and job['clientId']==actor.client_id else self._connection_session(actor,scope)
            parameters=self.authorize(actor,name,arguments)
            if name=='debug_start':
                started=self.submit(actor,session,name,parameters)
                with self._cv:self._jobs[started['jobId']]['parentJobId']=identifier;self._save(self._jobs[started['jobId']])
                if delegation:delegation['jobs'].add(started['jobId'])
                return {**started,'async':True,'projectId':parameters['projectId'],'next':'Use debug_status and debug_control while this job runs; wait for terminal state only after stopping the session.'}
            child=uid();work=self.root/'workspaces'/child;work.mkdir(parents=True)
            nested={'jobId':child,'clientId':actor.client_id,'sessionId':session,'operationId':name,'parameters':parameters,'state':'Running','createdAt':now(),'startedAt':now(),'workspace':str(work),'outputs':None,'error':None,'confirmed':False,'parentJobId':identifier}
            with self._cv:self._jobs[child]=nested;self._save(nested);self._tokens[child]=self._tokens.get(identifier,Cancellation());self._emit('JobStarted',nested)
            if delegation:delegation['jobs'].add(child)
            try:
                result=self._business(nested,parameters,request.get('cancellationId',''));result.setdefault('_jobId',child);self._finish(nested,'Completed',result);return result
            except CyToolError as exc:self._finish(nested,'Cancelled' if exc.code=='Cancelled' else 'Failed',error=exc.to_dict());raise
            except Exception as exc:
                error=CyToolError('InternalError',str(exc));self._finish(nested,'Failed',error=error.to_dict());raise error from exc
        return self._business(job,arguments,request.get('cancellationId',''))
    def _business(self,job,arguments,native_cancellation=''):
        finished=threading.Event();watcher=None
        if native_cancellation:
            def watch():
                while not finished.wait(.05):
                    try:self.native.call('checkCancellation',id=native_cancellation)
                    except CyToolError as exc:
                        if exc.code in ('Cancelled','Timeout'):self._tokens[job['jobId']].cancel(exc.message,exc.code)
                        return
            watcher=threading.Thread(target=watch,name='CyDecCancellation',daemon=True);watcher.start()
        try:return self._business_handler(job,arguments)
        finally:
            finished.set()
            if watcher:watcher.join(1)
    def _business_handler(self,job,arguments):
        context=JobContext(self,job['jobId'],self._tokens[job['jobId']]);context.cancellation.check();params=copy.deepcopy(arguments)
        for field in self.input_fields.get(job['operationId'],[]):
            if params.get(field):params[field]=str(self._snapshot(Path(params[field]),context.path('inputs/.keep').parent,self.input_max_bytes))
        groups=self.operation(job['operationId']).get('exclusiveGroups',[])
        with self._cv:locks=[self._business_locks.setdefault(g,threading.RLock()) for g in sorted(groups)]
        with ExitStack() as held:
            for lock in locks:
                while not lock.acquire(timeout=.1):context.cancellation.check()
                held.callback(lock.release)
            result=self._handlers[job['operationId']](context,params)
        return result if isinstance(result,dict) else {'result':result}
    def export_job(self,actor,job_id,destination):
        job=self.get_job(actor,job_id)
        if job['state'] not in TERMINAL:raise CyToolError('Busy','Wait for the job before exporting it.')
        target=Path(destination).expanduser().resolve()
        if not Path(destination).is_absolute() or target.exists() or target.is_relative_to(self.root):raise CyToolError('InvalidParameters','Choose a new absolute export folder outside runtime storage.')
        if Path(job['workspace']).is_dir():shutil.copytree(job['workspace'],target)
        else:target.mkdir(parents=True)
        previous=job['workspace']
        def moved(value):
            if isinstance(value,dict):return {k:moved(v) for k,v in value.items()}
            if isinstance(value,list):return [moved(v) for v in value]
            if isinstance(value,str) and (value==previous or value.startswith(previous+os.sep)):return str(target)+value[len(previous):]
            return value
        saved=moved(job);(target/'result.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2),'utf-8');return {'path':str(target),'jobId':job_id,'outputs':saved['outputs']}
    def estimate_resources(self,name,parameters,backend_id='',model_id=''):
        validate_parameters(parameters,self.operation(name)['inputSchema']);return self.operation(name).get('resourceRequirements',{})
    def can_run(self,name,parameters,backend_id='',model_id=''):
        estimate=self.estimate_resources(name,parameters,backend_id,model_id);return {'canRun':name in self._handlers,'requirements':estimate,'reasons':[]}
    def release_resources(self,actor,level):return {'released':True,'level':level,'note':'Business engines own their resources; durable job outputs are retained.'}
    def status(self):return {'instanceId':self.instance_id,'running':len(self._running),'queued':len(self._queue),'resources':{},'sdk':self.native.call('info')}
    def close(self,timeout=10):
        if self._closed:return
        with self._cv:
            self._closed=True
            for token in self._tokens.values():token.cancel('Application is stopping.')
            for identifier in self._running:self.native.call('cancel',id=identifier)
            self._cv.notify_all()
        deadline=time.monotonic()+timeout
        if self._started:self._scheduler.join(max(0,deadline-time.monotonic()))
        for thread in list(self._threads.values()):thread.join(max(0,deadline-time.monotonic()))
        if any(t.is_alive() for t in self._threads.values()):raise CyToolError('Busy','Workers are still stopping; native services and storage remain owned.')
        self.assistant.close();self.native.close();self.store.close();self._ownership.close()
