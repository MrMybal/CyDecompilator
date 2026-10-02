"""Provider API keys, kept out of argv, parameters, jobs, configurations and logs.

A key reaches a provider through an environment variable of the request subprocess or an
HTTP header built at call time. It is never a job parameter, so it never lands in the job
history, in a saved generation configuration, in an event or in the application log.

On Windows the value is sealed with DPAPI for the current user account, so the file on disk
is not readable by another account and copying it to another machine does not reveal it.
Everywhere else no OS secret store is wired in: the value is stored in a file with
owner-only permissions and `encrypted` is reported as false, because calling an unprotected
file encrypted would be a lie the user might rely on.
"""
import base64
import os
import stat
from pathlib import Path

from cytools_core import CyToolError

from ..paths import SETTINGS, read_json, write_json

STORE = SETTINGS / 'credentials.json'
# An environment variable the user already exports wins over the stored value: it lets a
# workstation keep its keys in its own vault without ever writing them into this Tool.
ENVIRONMENT = {'openai': 'OPENAI_API_KEY', 'openrouter': 'OPENROUTER_API_KEY',
               'anthropic': 'ANTHROPIC_API_KEY', 'mistral': 'MISTRAL_API_KEY',
               'groq': 'GROQ_API_KEY', 'deepseek': 'DEEPSEEK_API_KEY',
               'openai-compatible': 'CYDEC_OPENAI_COMPATIBLE_KEY',
               # Read access to a private release repository (application updates).
               'github': 'GITHUB_TOKEN'}


def _dpapi():
    if os.name != 'nt':
        return None
    try:
        import win32crypt  # noqa: F401  (pywin32, declared in requirements.txt)
        return win32crypt
    except ImportError:
        return None


def protected():
    return _dpapi() is not None


def _seal(value):
    api = _dpapi()
    if api is None:
        return {'encrypted': False, 'value': base64.b64encode(value.encode('utf-8')).decode('ascii')}
    blob = api.CryptProtectData(value.encode('utf-8'), 'CyDecompilator', None, None, None, 0)
    return {'encrypted': True, 'scheme': 'dpapi-user',
            'value': base64.b64encode(blob).decode('ascii')}


def _open(record):
    raw = base64.b64decode(record['value'])
    if not record.get('encrypted'):
        return raw.decode('utf-8')
    api = _dpapi()
    if api is None:
        raise CyToolError('MissingDependency',
                          'This key was sealed with DPAPI and can only be read on the Windows '
                          'account that stored it.')
    return api.CryptUnprotectData(raw, None, None, None, 0)[1].decode('utf-8')


def _restrict(path):
    try:
        Path(path).chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def store(provider_id, value):
    """Store a key. The caller must have read it from stdin or a masked field, never argv."""
    value = str(value or '').strip()
    if not value:
        raise CyToolError('InvalidParameters', 'An empty key cannot be stored.')
    records = read_json(STORE, {})
    records[str(provider_id)] = _seal(value)
    write_json(STORE, records)
    _restrict(STORE)
    return status(provider_id)


def clear(provider_id):
    records = read_json(STORE, {})
    removed = records.pop(str(provider_id), None) is not None
    write_json(STORE, records)
    _restrict(STORE)
    return {'providerId': provider_id, 'removed': removed}


def resolve(provider_id):
    """Return the key or an empty string. Never log, echo or return this value to a client."""
    variable = ENVIRONMENT.get(provider_id)
    if variable and os.environ.get(variable, '').strip():
        return os.environ[variable].strip()
    record = read_json(STORE, {}).get(str(provider_id))
    if not isinstance(record, dict) or not record.get('value'):
        return ''
    return _open(record)


def status(provider_id):
    """Everything a caller may know about a key: that it exists, and how it is protected."""
    variable = ENVIRONMENT.get(provider_id)
    from_environment = bool(variable and os.environ.get(variable, '').strip())
    record = read_json(STORE, {}).get(str(provider_id))
    stored = isinstance(record, dict) and bool(record.get('value'))
    return {'providerId': provider_id, 'configured': from_environment or stored,
            'source': 'environment' if from_environment else ('stored' if stored else 'none'),
            'environmentVariable': variable or '',
            'encrypted': bool(stored and record.get('encrypted')),
            'protection': 'dpapi-user' if stored and record.get('encrypted') else
                          ('environment' if from_environment else
                           ('file-permissions-only' if stored else 'none'))}


def statuses(provider_ids):
    return [status(provider_id) for provider_id in provider_ids]
