"""Local discovery and an account-protected identity for external assistant clients."""
from dataclasses import dataclass,field
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from .errors import CyToolError

MARKER='mcp-instance.json'
VAULT='mcp-automation-credentials.json'
KEY='external-assistant'


def local_url(value,path):
    if not isinstance(value,str):raise CyToolError('AccessDenied','A local instance URL must be a string.')
    try:
        url=urlsplit(value)
        valid=(url.scheme=='http' and url.hostname in ('127.0.0.1','localhost','::1')
               and url.port is not None and 1<=url.port<=65535 and url.path==path
               and not (url.username or url.password or url.query or url.fragment))
    except (ValueError,TypeError):valid=False
    if not valid:raise CyToolError('AccessDenied','Use an explicit authenticated loopback '+path+' URL without credentials or query parameters.')
    return value


def automation_identity(runtime):
    if runtime.options['accessProfile'] in ('free','local_controlled'):return runtime.local_actor(),''
    from ..ai import credentials
    path=runtime.root/VAULT
    with runtime._cv:
        token=credentials.resolve(KEY,file=path)
        if token:
            # Revoked or replaced credentials must not silently regain permissions.
            return runtime.authenticate(token),token
        permissions=sorted({p for o in runtime.descriptor['operations'] for p in o.get('permissions',[])})
        client=runtime.create_client('External assistant',permissions)
        credentials.store(KEY,client['token'],file=path)
        return runtime.authenticate(client['token']),client['token']


def publish(runtime,server,*,require_token=False):
    from ..paths import write_json
    automation_identity(runtime)
    row={'schemaVersion':1,'instanceId':runtime.instance_id,'pid':os.getpid(),
         'mcpUrl':'http://127.0.0.1:'+str(server.server_port)+'/mcp',
         'credentialRequired':bool(require_token),'accessProfile':runtime.options['accessProfile']}
    path=runtime.root/MARKER;write_json(path,row);path.chmod(0o600)
    return row


def unpublish(runtime,row):
    path=runtime.root/MARKER
    try:
        if json.loads(path.read_text('utf-8'))==row:path.unlink()
    except (FileNotFoundError,ValueError):pass


@dataclass(frozen=True)
class Connection:
    url:str
    instance_id:str
    token:str=field(repr=False)


def discover(directory,token=''):
    from ..ai import credentials
    from .transport import HTTPClient
    directory=Path(directory).resolve()
    try:row=json.loads((directory/MARKER).read_text('utf-8'))
    except FileNotFoundError:return None
    except (ValueError,UnicodeError):raise CyToolError('InvalidState','The local MCP instance descriptor is invalid.') from None
    if not isinstance(row,dict) or row.get('schemaVersion')!=1 or not isinstance(row.get('instanceId'),str):raise CyToolError('InvalidState','Unsupported local MCP instance descriptor.')
    endpoint=local_url(row.get('mcpUrl'),'/mcp')
    selected=token or (credentials.resolve(KEY,file=directory/VAULT) if row.get('accessProfile') not in ('free','local_controlled') else '')
    if not selected and row.get('credentialRequired'):raise CyToolError('AuthenticationRequired','This instance requires its configured CYMCP_TOKEN credential.')
    try:status=HTTPClient(endpoint.removesuffix('/mcp')+'/v1',selected,timeout=2).call('GetRuntimeStatus')
    except CyToolError as exc:
        if exc.code in ('AuthenticationRequired','AccessDenied'):raise
        return None
    except OSError:return None
    if status.get('instanceId')!=row['instanceId']:return None
    return Connection(endpoint,row['instanceId'],selected)


def client_configuration(directory=None):
    import sys
    root=Path(__file__).resolve().parents[3]
    executable=root/'CyDecompilatorCLI.exe'
    if os.name=='nt' and executable.is_file():command=str(executable);arguments=[]
    else:command=sys.executable;arguments=[str(root/'app/tool.py')]
    arguments+=['--data-dir',str(Path(directory or root/'data/jobs').resolve()),'mcp','--auto']
    return {'mcpServers':{'cydecompilator':{'command':command,'args':arguments}}}
