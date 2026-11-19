"""Compatibility wire methods and MCP control schemas, backed by the real host."""
import copy
import json
import uuid
from .errors import CyToolError

def schema(properties=None,required=()):return {'type':'object','properties':properties or {},'required':list(required),'additionalProperties':False}
S={'type':'string'};B={'type':'boolean'};N={'type':'number','minimum':0};O={'type':'object'}
CONTROL_SCHEMAS={
 'cy_describe':('DescribeTool',schema()),'cy_status':('GetRuntimeStatus',schema()),
 'cy_list_operations':('ListOperations',schema()),'cy_describe_operation':('DescribeOperation',schema({'operationId':S},['operationId'])),
 'cy_list_backends':('ListBackends',schema()),'cy_list_models':('ListModels',schema({'backendId':S})),
 'cy_capabilities':('GetCapabilities',schema()),'cy_system_resources':('GetSystemResources',schema()),'cy_diagnose':('Diagnose',schema()),
 'cy_list_jobs':('ListJobs',schema()),'cy_get_job':('GetJob',schema({'jobId':S},['jobId'])),'cy_cancel_job':('CancelJob',schema({'jobId':S},['jobId'])),
 'cy_events':('GetEvents',schema({'after':{'type':'integer','minimum':0}})),
 'cy_can_run':('CanRun',schema({'operationId':S,'parameters':O,'backendId':S,'modelId':S},['operationId'])),
 'cy_estimate':('EstimateResources',schema({'operationId':S,'parameters':O,'backendId':S,'modelId':S},['operationId'])),
 'cy_begin_task':('CreateSession',schema({'temporary':B,'retentionSeconds':{'type':'number','minimum':1,'maximum':86400}})),
 'cy_finish_task':('FinishTask',schema({'sessionId':S,'cancelRunning':B})),
 'cy_keep_task_alive':('KeepTaskAlive',schema({'sessionId':S})),
 'cy_import_file':('ImportFile',schema({'sessionId':S,'source':S,'companions':{'type':'array','items':S}},['source'])),
 'cy_export_job':('ExportJob',schema({'jobId':S,'destination':S},['jobId','destination'])),
 'cy_release_resources':('ReleaseResources',schema({'level':S},['level'])),
 'cy_read_result':('ReadResult',schema({'jobId':S,'offset':{'type':'integer','minimum':0},'length':{'type':'integer','minimum':1,'maximum':65536}},['jobId'])),
 'cy_sdk_info':('SDKInfo',schema()),
}

class LocalClient:
    def __init__(self,runtime,principal,*,scope=None):self.runtime,self.principal=runtime,principal;self.scope=scope or 'sdk-cli:'+uuid.uuid4().hex
    def call(self,method,**p):
        r,actor=self.runtime,self.principal;r.actor(actor.client_id)
        if method=='DescribeTool':return copy.deepcopy(r.descriptor)
        if method=='GetCapabilities':return copy.deepcopy(r.descriptor.get('capabilities',[]))
        if method=='ListOperations':return copy.deepcopy(r.descriptor['operations'])
        if method=='DescribeOperation':return r.operation(p['operationId'])
        if method=='ListBackends':return copy.deepcopy(r.descriptor.get('backends',[]))
        if method=='ListModels':return [dict(m,backendId=b['id']) for b in r.descriptor.get('backends',[]) for m in b.get('models',[]) if not p.get('backendId') or b['id']==p['backendId']]
        if method in ('GetRuntimeStatus','Diagnose'):return r.status()
        if method=='SDKInfo':return r.native.call('info')
        if method=='SDKDispatch':return r.native.call('app',request=p['request'],principal=actor.client_id,scope=self.scope)
        if method=='GetSystemResources':
            import shutil,os
            return {'cpuThreads':os.cpu_count(),'diskFreeBytes':shutil.disk_usage(r.root).free,**r.system}
        if method in ('EstimateResources','CanRun'):
            r.authorize(actor,p['operationId'],p.get('parameters',{}))
            return (r.estimate_resources if method=='EstimateResources' else r.can_run)(p['operationId'],p.get('parameters',{}),p.get('backendId',''),p.get('modelId',''))
        if method=='CreateSession':return r.create_session(actor,temporary=p.get('temporary',True),retention_seconds=p.get('retentionSeconds',3600))
        if method in ('CloseSession','FinishTask'):return r.finish_task(actor,p['sessionId'],cancel_running=p.get('cancelRunning',False))
        if method=='KeepTaskAlive':return r.keep_task_alive(actor,p['sessionId'])
        if method=='SubmitJob':return r.submit(actor,p['sessionId'],p['operationId'],p.get('parameters',{}),backend_id=p.get('backendId',''),model_id=p.get('modelId',''),priority=p.get('priority','Normal'),queue_timeout=p.get('queueTimeout'),execution_timeout=p.get('executionTimeout'),confirmed=p.get('confirmed',False))
        if method=='GetJob':return r.get_job(actor,p['jobId'])
        if method=='ListJobs':return r.list_jobs(actor)
        if method=='CancelJob':return r.cancel(actor,p['jobId'])
        if method=='GetEvents':return r.events(actor,p.get('after',0))
        if method=='ShareJob':return r.share_job(actor,p['jobId'],p.get('visibility','Owner'),p.get('sharedWith',[]))
        if method=='ImportFile':return r.import_file(actor,p['sessionId'],p['source'],companions=p.get('companions',[]))
        if method=='ExportJob':return r.export_job(actor,p['jobId'],p['destination'])
        if method=='ReleaseResources':return r.release_resources(actor,p['level'])
        if method=='ReadResult':
            import base64
            data=json.dumps(r.get_job(actor,p['jobId']).get('outputs'),ensure_ascii=False).encode('utf-8')
            offset=p.get('offset',0);length=p.get('length',32768)
            if type(offset)is not int or offset<0 or type(length)is not int or not 1<=length<=65536:raise CyToolError('InvalidParameters','Invalid byte range.')
            chunk=data[offset:offset+length]
            return {'data':base64.b64encode(chunk).decode(),'encoding':'base64','mimeType':'application/json','offset':offset,'totalBytes':len(data),'nextOffset':offset+len(chunk) if offset+len(chunk)<len(data) else None}
        raise CyToolError('UnknownMethod','Unknown application method: '+method)
    def dispatch(self,request):
        response={'protocolVersion':'1.0','id':request.get('id') if isinstance(request,dict) else None}
        try:
            if not isinstance(request,dict) or not isinstance(request.get('method'),str) or not isinstance(request.get('params',{}),dict):raise CyToolError('InvalidRequest','Expected method and params object.')
            response['result']=self.call(request['method'],**request.get('params',{}))
        except CyToolError as exc:response['error']=exc.to_dict()
        except (ValueError,KeyError,TypeError) as exc:response['error']=CyToolError('InvalidParameters',str(exc)).to_dict()
        return response
