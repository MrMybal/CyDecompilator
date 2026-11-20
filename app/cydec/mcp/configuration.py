"""Validated host choices; neither provider messages nor MCP tools can write these."""
from pathlib import Path
import re
from urllib.parse import urlsplit
from .errors import CyToolError
from .native import DEFAULTS

ACCESS_PROFILES={'free':(False,False),'local_controlled':(False,True),
                 'token_only':(True,False),'protected_access':(True,True)}

def validate_options(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise CyToolError('InvalidParameters','Unknown SDK option.')
    result={**DEFAULTS,**value}
    if not isinstance(result['accessProfile'],str) or result['accessProfile'] not in ACCESS_PROFILES:
        raise CyToolError('InvalidParameters','Unknown local access profile.')
    for key in ('compactDiscovery','cache','notifications','diskSpool','telemetry','ripgrep'):
        if type(result[key])is not bool:raise CyToolError('InvalidParameters',key+' must be boolean.')
    bounds={'cacheTtlMs':(0,300000),'diskBytes':(1024*1024,1024**3),'memoryBytes':(1024*1024,256*1024**2),'retentionSeconds':(1,86400),'chunkBytes':(1024,65536),'inlineBytes':(1024,1024**2),'contextBytes':(0,64*1024**2),'recentTurns':(1,1000)}
    for key,(minimum,maximum) in bounds.items():
        if type(result[key])is not int or not minimum<=result[key]<=maximum:raise CyToolError('InvalidParameters',key+' is outside its supported range.')
    if not isinstance(result['workspaceRoot'],str):raise CyToolError('InvalidParameters','workspaceRoot must be a path string.')
    if result['ripgrep'] and (not Path(result['workspaceRoot']).is_absolute() or not Path(result['workspaceRoot']).is_dir()):raise CyToolError('InvalidParameters','Ripgrep requires an explicit existing absolute workspace root.')
    spool=result['spoolRoot']
    if not isinstance(spool,str) or spool and (not Path(spool).is_absolute() or Path(spool).is_symlink() or Path(spool).exists() and not Path(spool).is_dir()):raise CyToolError('InvalidParameters','spoolRoot must be empty or an explicit absolute directory.')
    return result

def load_options(path):
    """Persist the new default only for configurations without an explicit choice."""
    import json
    from ..paths import write_json
    try:value=json.loads(Path(path).read_text('utf-8'))
    except FileNotFoundError:value={}
    result=validate_options(value)
    if 'accessProfile' not in value:write_json(Path(path),result)
    return result

def validate_servers(value):
    if not isinstance(value,dict) or set(value)-{'servers'} or not isinstance(value.get('servers',{}),dict):raise CyToolError('InvalidParameters','Expected a servers object.')
    for name,config in value.get('servers',{}).items():
        if not re.fullmatch('[a-zA-Z0-9_-]{1,64}',name):raise CyToolError('InvalidParameters','Invalid server identifier.')
        if not isinstance(config,dict) or set(config)-{'url','executable','arguments','workingDirectory','allowedTools','allowedResources'}:raise CyToolError('InvalidParameters','Unknown external server setting; credentials belong in the vault.')
        if bool(config.get('url'))==bool(config.get('executable')):raise CyToolError('InvalidParameters','Choose one HTTP URL or one executable.')
        if config.get('url'):
            url=urlsplit(config['url'])
            if url.username or url.password or url.scheme not in ('http','https') or url.query or url.fragment:raise CyToolError('InvalidParameters','Use an HTTP(S) endpoint without credentials or query secrets.')
            if url.scheme=='http' and url.hostname not in ('127.0.0.1','localhost','::1'):raise CyToolError('InvalidParameters','Remote MCP servers require HTTPS.')
        if config.get('executable') and (not Path(config['executable']).is_absolute() or not Path(config['executable']).is_file()):raise CyToolError('InvalidParameters','Choose an explicit existing server executable.')
        for key in ('arguments','allowedTools','allowedResources'):
            if not isinstance(config.get(key,[]),list) or not all(isinstance(v,str) for v in config.get(key,[])):raise CyToolError('InvalidParameters',key+' must be a string array.')
    return value
