"""CyMCPSDK native services with CyDecompilator's durable application jobs."""
import json
from pathlib import Path
from .errors import CyToolError, AppError
from .native import Native, validate_parameters

def load_manifest(path):
    descriptor=json.loads(Path(path).read_text('utf-8-sig'))
    if not isinstance(descriptor,dict) or not isinstance(descriptor.get('operations'),list):raise CyToolError('InvalidManifest','Missing operation registry.')
    names=[o['id'] for o in descriptor['operations']]
    if len(set(names))!=len(names):raise CyToolError('InvalidManifest','Duplicate operation ID.')
    return descriptor

from .runtime import Runtime, Principal, TERMINAL
