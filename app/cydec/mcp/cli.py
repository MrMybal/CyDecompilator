"""Compatible headless CLI plus native SDK discovery and live-instance connection."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from .api import LocalClient
from .errors import CyToolError
from .transport import HTTPClient,LiveServer,make_server,serve_proxy,serve_stdio,token_environment

def run_cli(factory,argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='CyDecompilator — CyMCPSDK CLI and MCP server')
    parser.add_argument('--data-dir',default='.cytools')  # Keep existing CLI databases discoverable.
    parser.add_argument('--connect',help='Running instance URL, e.g. http://127.0.0.1:8766/v1; CYMCP_TOKEN authenticates the client.')
    parser.add_argument('--auto',dest='auto_instance',action='store_true',help='Use the live local instance when available, otherwise run without a window, with a stable local assistant identity.')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('describe','list-operations','list-backends','list-models','diagnose','stdio','jsonl','sdk-info','mcp-config'):commands.add_parser(name)
    mcp=commands.add_parser('mcp');mcp.add_argument('--compact',action='store_true');mcp.add_argument('--full',action='store_true')
    mcp.add_argument('--auto',action='store_true',help='Attach to the owning local instance, or run headless when it is closed; credentials stay in the application vault.')
    sdk=commands.add_parser('sdk',help='CyMCPSDK dispatch_app protocol: describe, invoke or persistent JSONL stdio.')
    sdk.add_argument('method',choices=('describe','invoke','stdio'));sdk.add_argument('operation',nargs='?')
    sdk.add_argument('--params',default='{}');sdk.add_argument('--params-file')
    commands.add_parser('jobs')
    for name in ('job','result','cancel','wait'):
        job=commands.add_parser(name);job.add_argument('job_id')
        if name=='wait':job.add_argument('--timeout',type=float,default=30)
        if name=='result':job.add_argument('--offset',type=int,default=0);job.add_argument('--length',type=int,default=32768)
    describe=commands.add_parser('describe-operation');describe.add_argument('operation')
    for name in ('invoke','estimate','can-run'):
        p=commands.add_parser(name);p.add_argument('operation');p.add_argument('--params',default='{}');p.add_argument('--params-file');p.add_argument('--backend',default='');p.add_argument('--model',default='')
        if name=='invoke':
            p.add_argument('arguments_file',nargs='?',help='Optional JSON input file, as in the SDK CLI example.')
            p.add_argument('--timeout',type=float,default=300);p.add_argument('--confirm',action='store_true',help='Explicitly confirm this reviewed destructive action.')
    serve=commands.add_parser('serve');serve.add_argument('--port',type=int,default=8766)
    create=commands.add_parser('create-client');create.add_argument('--name',required=True);create.add_argument('--permission',action='append',default=[])
    args=parser.parse_args(argv);runtime=None;live=None;initial_token=token_environment()
    try:
        if args.command=='mcp-config':
            from .instance import client_configuration
            print(json.dumps(client_configuration(args.data_dir),ensure_ascii=False,indent=2));return 0
        if args.command=='mcp' and (args.auto or args.auto_instance):
            if args.connect:raise CyToolError('InvalidParameters','Choose mcp --auto or an explicit --connect URL.')
            from .instance import automation_identity,discover
            explicit_token=token_environment();connection=discover(args.data_dir,explicit_token)
            compact=not args.full
            if connection:
                print('CyDecompilator MCP: connected to the running local instance.',file=sys.stderr,flush=True)
                serve_proxy(connection.url,connection.token,compact=compact);return 0
            try:runtime=factory(args.data_dir)
            except CyToolError as exc:
                if exc.code!='Busy':raise
                # A window or another chat can be between locking and publishing.
                for _ in range(30):
                    time.sleep(.1);connection=discover(args.data_dir,explicit_token)
                    if connection:
                        serve_proxy(connection.url,connection.token,compact=compact);return 0
                raise CyToolError('Busy','The owning instance has not published its MCP endpoint. Start the updated application with MCP enabled or choose another --data-dir.') from None
            runtime.start()
            actor=runtime.authenticate(explicit_token) if explicit_token else automation_identity(runtime)[0]
            with LiveServer(runtime,0,advertise=True,require_token=bool(explicit_token)):
                print('CyDecompilator MCP: running headless; the integrated chat is not required.',file=sys.stderr,flush=True)
                serve_stdio(runtime,actor,compact=compact)
            return 0
        connection=None
        if args.auto_instance:
            if args.connect or args.command in ('serve','create-client'):raise CyToolError('InvalidParameters','Choose --auto for business commands or explicit connection/administration options.')
            from .instance import discover
            connection=discover(args.data_dir,initial_token)
        if connection:
            client=HTTPClient(connection.url.removesuffix('/mcp')+'/v1',connection.token)
        elif args.connect:
            if args.command in ('serve','create-client'):raise CyToolError('InvalidParameters','Use a local data directory for this command.')
            token=token_environment()
            if not token:raise CyToolError('AuthenticationRequired','Set CYMCP_TOKEN for the selected instance (CYTOOLS_TOKEN remains accepted).')
            if args.command=='mcp':
                endpoint=args.connect.rstrip('/').removesuffix('/v1').removesuffix('/mcp')+'/mcp'
                serve_proxy(endpoint,token,compact=args.compact and not args.full);return 0
            client=HTTPClient(args.connect,token)
        else:
            runtime=factory(args.data_dir);runtime.start()
            if args.command=='create-client':print(json.dumps(runtime.create_client(args.name,args.permission)));return 0
            if args.command=='serve':
                server=make_server(runtime,args.port)
                print('CyDecompilator instance: http://127.0.0.1:%d/v1; MCP: /mcp; bearer authentication required.'%server.server_port,file=sys.stderr,flush=True)
                try:server.serve_forever()
                except KeyboardInterrupt:pass
                finally:server.server_close()
                return 0
            if args.auto_instance and not initial_token:
                from .instance import automation_identity
                actor=automation_identity(runtime)[0]
            else:actor=runtime.authenticate(token_environment())
            client=LocalClient(runtime,actor)
            if args.auto_instance:
                owned=LiveServer(runtime,0,advertise=True,require_token=bool(initial_token))
                owned.__enter__();live=owned
        if args.command=='mcp':serve_stdio(runtime,actor,compact=args.compact and not args.full)
        elif args.command=='stdio':
            for raw in sys.stdin:
                try:
                    request=json.loads(raw)
                    result=client.dispatch(request) if isinstance(client,LocalClient) else {'protocolVersion':'1.0','id':request.get('id'),'result':client.call(request['method'],**request.get('params',{}))}
                except (ValueError,CyToolError) as exc:result={'protocolVersion':'1.0','id':None,'error':{'code':getattr(exc,'code','InvalidRequest'),'message':str(exc)}}
                print(json.dumps(result,ensure_ascii=False),flush=True)
        elif args.command in ('sdk','jsonl'):
            if args.command=='jsonl' or args.method=='stdio':
                failed=False
                for raw in sys.stdin:
                    try:result=client.call('SDKDispatch',request=json.loads(raw))
                    except (CyToolError,ValueError) as exc:
                        failed=True;result={'error':{'code':getattr(exc,'code','InvalidRequest'),'message':str(exc)}}
                    print(json.dumps(result,ensure_ascii=False),flush=True)
                return 1 if failed else 0
            request={'method':args.method}
            if args.method=='invoke':
                if not args.operation:raise CyToolError('InvalidParameters','sdk invoke requires an operation name.')
                request.update(name=args.operation,arguments=json.loads(Path(args.params_file).read_text('utf-8-sig') if args.params_file else args.params))
            print(json.dumps(client.call('SDKDispatch',request=request),ensure_ascii=False));return 0
        elif args.command in ('jobs','job','cancel','result','wait'):
            if args.command=='jobs':result=client.call('ListJobs')
            elif args.command=='result':result=client.call('ReadResult',jobId=args.job_id,offset=args.offset,length=args.length)
            elif args.command=='cancel':result=client.call('CancelJob',jobId=args.job_id)
            else:
                result=client.call('GetJob',jobId=args.job_id)
                if args.command=='wait':
                    if args.timeout<=0:raise CyToolError('InvalidParameters','Wait timeout must be positive.')
                    deadline=time.monotonic()+args.timeout
                    while result['state'] not in ('Completed','Failed','Cancelled'):
                        if time.monotonic()>=deadline:raise CyToolError('Timeout','Job remains stored; inspect it before retrying.')
                        time.sleep(.05);result=client.call('GetJob',jobId=args.job_id)
            print(json.dumps(result,ensure_ascii=False))
            return 1 if args.command=='wait' and result['state']!='Completed' else 0
        elif args.command=='invoke':
            params_path=args.params_file or args.arguments_file
            if args.params_file and args.arguments_file:raise CyToolError('InvalidParameters','Choose one JSON input file.')
            parameters=json.loads(Path(params_path).read_text('utf-8-sig') if params_path else args.params)
            session=client.call('CreateSession',temporary=False)
            job=client.call('SubmitJob',sessionId=session['sessionId'],operationId=args.operation,parameters=parameters,backendId=args.backend,modelId=args.model,executionTimeout=args.timeout,queueTimeout=args.timeout,confirmed=args.confirm)
            deadline=time.monotonic()+args.timeout+5
            while job['state'] not in ('Completed','Cancelled','Failed'):
                if time.monotonic()>deadline:raise CyToolError('Timeout','Job remains stored. Inspect GetJob before retrying.')
                time.sleep(.03);job=client.call('GetJob',jobId=job['jobId'])
            print(json.dumps(job,ensure_ascii=False))
            client.call('CloseSession',sessionId=session['sessionId'])
            if job['state']!='Completed':print(json.dumps({'error':job.get('error')}),file=sys.stderr)
            return 0 if job['state']=='Completed' else 1
        elif args.command in ('describe-operation','estimate','can-run'):
            method={'describe-operation':'DescribeOperation','estimate':'EstimateResources','can-run':'CanRun'}[args.command];parameters={'operationId':args.operation}
            if args.command!='describe-operation':parameters.update(parameters=json.loads(Path(args.params_file).read_text('utf-8-sig') if args.params_file else args.params),backendId=args.backend,modelId=args.model)
            print(json.dumps(client.call(method,**parameters),ensure_ascii=False,indent=2))
        else:
            method={'describe':'DescribeTool','list-operations':'ListOperations','list-backends':'ListBackends','list-models':'ListModels','diagnose':'Diagnose','sdk-info':'SDKInfo'}[args.command]
            print(json.dumps(client.call(method),ensure_ascii=False,indent=2))
        return 0
    except (CyToolError,ValueError,OSError,ImportError) as exc:
        print(json.dumps({'error':{'code':getattr(exc,'code','ConfigurationError'),'message':str(exc)}},ensure_ascii=False),file=sys.stderr);return 1
    finally:
        try:
            if live:live.__exit__(None,None,None)
        finally:
            if runtime:runtime.close()
