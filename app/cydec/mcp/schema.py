"""Host configuration validation. Operation validation belongs to CyMCPSDK."""
from .errors import CyToolError

def validate_manifest(value):
    identifiers=[x['id'] for x in value['operations']]
    if len(identifiers)!=len(set(identifiers)):raise CyToolError('InvalidManifest','Duplicate operation.')
    return value

def validate_document(value,kind):
    if not isinstance(value,dict):raise CyToolError('InvalidParameters','Expected a configuration object.')
    if kind=='installation-storage':
        if value.get('schemaVersion')!=1:raise CyToolError('InvalidParameters','Unsupported installation storage format.')
        if set(value)-{'schemaVersion','downloadMode','sharedRoot','cudaComponent'}:raise CyToolError('InvalidParameters','Unknown installation storage field.')
        for key in ('downloadMode','sharedRoot','cudaComponent'):
            if key in value and not isinstance(value[key],str):raise CyToolError('InvalidParameters','Storage fields must be strings.')
    return value
