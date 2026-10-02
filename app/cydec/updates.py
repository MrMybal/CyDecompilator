"""Application updates from GitHub releases, staged, verified, activated and reversible.

Ported from CyTools_AIChat (same author). Engines have their own stream in components.py
(each engine is updated from its official source and older versions stay side by side).

An update is staged under runtime/updates, verified there (configured provenance, Tool
identity, runtime ABI marker, asset size, published digest when present, archive
containment, compilation without import) and only then activated. data/ is never part of
a replacement; the previous app/ is kept under runtime/backups and can be restored.
The official repository is the default; another one can be configured (or none). A private
repository needs a GitHub token with read access: GITHUB_TOKEN, or the credential store
(provider 'github', DPAPI-sealed on Windows). The token is never a job parameter.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from cytools_core import CyToolError, load_manifest
from cytools_core.downloads import DownloadManager

from . import paths
from .paths import TOOL_ID, read_json, write_json

MAX_ASSET_BYTES = 512 * 1024 ** 2
# Bumped whenever the application stops being loadable by the runtime already installed here.
RUNTIME_ABI = 'python311-cytools010-imgui192-cydec01'
USER_AGENT = 'CyDecompilator'
DEFAULT_REPOSITORY = 'MrMybal/CyDecompilator'


def settings_file():
    return paths.SETTINGS / 'updates.json'


def updates_dir():
    return paths.RUNTIME / 'updates'


def backups_dir():
    return paths.RUNTIME / 'backups'


def state_file():
    return paths.SETTINGS / 'update-state.json'


def repository(value):
    value = str(value or '').strip()
    value = value.removeprefix('https://github.com/').removesuffix('.git').rstrip('/')
    if not value:
        return ''
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value) or '..' in value:
        raise CyToolError('InvalidParameters', 'Expected a GitHub repository as owner/name.')
    return value


def settings():
    stored = read_json(settings_file(), {})
    return {'applicationRepository': repository(stored.get('applicationRepository', DEFAULT_REPOSITORY)),
            'automaticCheck': bool(stored.get('automaticCheck', False)),
            'lastCheck': stored.get('lastCheck', ''), 'runtimeAbi': RUNTIME_ABI}


def configure(application_repository=None, automatic_check=None):
    current = settings()
    if application_repository is not None:
        current['applicationRepository'] = repository(application_repository)
    if automatic_check is not None:
        current['automaticCheck'] = bool(automatic_check)
    write_json(settings_file(), current)
    return settings()


def token():
    """GitHub token for a private repository, or ''. Never logged or returned to a client."""
    from .ai import credentials
    try:
        return credentials.resolve('github')
    except CyToolError:
        return ''


def token_status():
    from .ai import credentials
    return credentials.status('github')


def github(path, repo=''):
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    secret = token()
    if secret:
        headers['Authorization'] = 'Bearer ' + secret
    request = urllib.request.Request('https://api.github.com/' + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            hint = '' if secret else (' If the repository is private, set a GitHub token with read access '
                                      '(GITHUB_TOKEN or the token field of the Updates section).')
            raise CyToolError('NotFound', 'The repository or release was not found%s.%s'
                              % (' for ' + repo if repo else '', hint))
        if exc.code == 401:
            raise CyToolError('Unauthorized', 'GitHub rejected the token (HTTP 401): it is invalid or expired.')
        if exc.code in (403, 429):
            raise CyToolError('RateLimited', 'GitHub refused the request (HTTP %d); try again later.' % exc.code)
        raise CyToolError('NetworkError', 'GitHub returned HTTP %d.' % exc.code)
    except urllib.error.URLError as exc:
        raise CyToolError('NetworkError', 'Cannot reach GitHub: %s' % exc.reason)


def current_version():
    return load_manifest(paths.APP / 'CyTool.json')['version']


def parse_version(value):
    parts = re.findall(r'\d+', str(value or ''))
    return tuple(int(p) for p in parts[:4]) or (0,)


def check():
    current = settings()
    installed = current_version()
    row = {'stream': 'application', 'installed': installed, 'repository': current['applicationRepository'],
           'available': '', 'updateAvailable': False, 'asset': '', 'sizeBytes': 0, 'digest': '', 'notes': ''}
    if not current['applicationRepository']:
        row['notes'] = ('No application repository is configured. CyDecompilator does not invent one: set it '
                        'if you publish releases, otherwise the application stream stays unavailable. Engines '
                        'are updated from their own sources in the Engines tab.')
    else:
        release = github('repos/%s/releases/latest' % current['applicationRepository'], current['applicationRepository'])
        row['available'] = release.get('tag_name', '')
        assets = [a for a in release.get('assets', []) if str(a.get('name', '')).endswith('.zip')]
        if not assets:
            row['notes'] = 'The latest release publishes no .zip asset (expected: a zip holding app/ with CyTool.json).'
        else:
            asset = assets[0]
            row.update(asset=asset['name'], sizeBytes=int(asset.get('size', 0)), digest=str(asset.get('digest', '')),
                       updateAvailable=parse_version(row['available']) > parse_version(installed))
            if row['sizeBytes'] > MAX_ASSET_BYTES:
                row.update(updateAvailable=False, notes='The published asset is larger than this Tool will download.')
    write_json(settings_file(), {**current, 'lastCheck': time.strftime('%Y-%m-%dT%H:%M:%S')})
    return row


def staging_path():
    return updates_dir() / 'application'


def verify_application_tree(root):
    candidates = [p for p in Path(root).rglob('CyTool.json') if p.parent.name == 'app'] or list(Path(root).rglob('CyTool.json'))
    if len(candidates) != 1:
        raise CyToolError('InvalidArchive', 'The archive must contain exactly one app/CyTool.json, found %d.' % len(candidates))
    app_root = candidates[0].parent
    document = load_manifest(candidates[0])
    if document['id'] != TOOL_ID:
        raise CyToolError('InvalidArchive', 'This release belongs to another Tool (%s).' % document['id'])
    release = read_json(app_root / 'release.json', {})
    abi = release.get('runtimeAbi', '')
    if abi and abi != RUNTIME_ABI:
        raise CyToolError('IncompatibleRuntime', 'The release targets runtime %s; this installation is %s. Install '
                          'the matching full package instead.' % (abi, RUNTIME_ABI))
    if not (app_root / 'tool.py').is_file() or not (app_root / 'desktop.py').is_file():
        raise CyToolError('InvalidArchive', 'The staged application is missing its entry points.')
    compiled = subprocess.run([sys.executable, '-m', 'compileall', '-q', str(app_root)], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=300,
                              creationflags=0x08000000 if os.name == 'nt' else 0)
    if compiled.returncode:
        raise CyToolError('InvalidArchive', 'The staged application does not compile:\n' + (compiled.stdout or '')[-1500:])
    return {'path': str(app_root), 'version': document['version'], 'toolId': document['id'],
            'runtimeAbi': abi or 'not declared', 'operations': len(document['operations'])}


def download(context, version=''):
    from .components import extract
    current = settings()
    if not current['applicationRepository']:
        raise CyToolError('NotConfigured', 'Configure the application repository first. CyDecompilator will not '
                          'guess a repository to download code from.')
    path = ('repos/%s/releases/tags/%s' % (current['applicationRepository'], version) if version
            else 'repos/%s/releases/latest' % current['applicationRepository'])
    release = github(path, current['applicationRepository'])
    tag = release.get('tag_name', version)
    assets = [a for a in release.get('assets', []) if str(a.get('name', '')).endswith('.zip')]
    if not assets:
        raise CyToolError('NotFound', 'That release publishes no .zip asset.')
    asset = assets[0]
    size = int(asset.get('size', 0))
    if size > MAX_ASSET_BYTES:
        raise CyToolError('InvalidArchive', 'The published asset is larger than this Tool will download.')
    digest = str(asset.get('digest', '') or '').removeprefix('sha256:')
    context.progress(5, 'Downloading ' + asset['name'])
    secret = token()
    if secret:
        # Private repository: the asset is read through the API (the redirect to the storage
        # host drops the Authorization header).
        url, headers = asset['url'], {'Accept': 'application/octet-stream', 'Authorization': 'Bearer ' + secret,
                                      'User-Agent': USER_AGENT}
    else:
        url, headers = asset['browser_download_url'], {'User-Agent': USER_AGENT}
    receipt = DownloadManager(paths.RUNTIME / 'downloads/updates', use_shared_cache=False).download(
        re.sub(r'[^A-Za-z0-9_.-]', '_', asset['name']), url, sha256=digest or None, headers=headers,
        size=size or None, revision=tag, cancellation=context.cancellation,
        progress=lambda n, t: context.progress(min(70, 5 + 65 * n / max(t or 1, 1)), 'Downloading ' + asset['name']))
    target = staging_path()
    shutil.rmtree(target, ignore_errors=True)
    context.progress(75, 'Extracting into runtime/updates')
    extract(receipt['path'], target, context)
    context.progress(85, 'Verifying the staged application')
    report = verify_application_tree(target)
    if not digest:
        report['digestNote'] = ('The release published no digest: only size and contents were checked. A checksum '
                                'published beside a release is not an independent signature either.')
    write_json(target / 'staged.json', {'version': report['version'], 'tag': tag, 'asset': asset['name'],
                                        'sha256': digest, 'appRoot': report['path'], 'staged': time.time()})
    context.progress(100, 'Staged and verified')
    return {'staged': True, 'version': report['version'], 'path': str(target), 'report': report}


def busy(runtime, own_job=None):
    if runtime is None:
        return []
    return [job for job in runtime._jobs.values() if job['state'] in ('Queued', 'Running') and job['jobId'] != own_job]


def apply(context, runtime, job_id=None):
    target = staging_path()
    staged = read_json(target / 'staged.json', {})
    if not staged.get('appRoot'):
        raise CyToolError('NotFound', 'No verified application update is staged.')
    running = busy(runtime, job_id)
    if running:
        raise CyToolError('Busy', 'An update is never activated while a job is running (%d running).' % len(running))
    source = Path(staged['appRoot'])
    if not source.is_dir() or not source.resolve().is_relative_to(updates_dir().resolve()):
        raise CyToolError('InvalidState', 'The staged application is no longer where it was verified.')
    context.progress(20, 'Re-verifying the staged application')
    report = verify_application_tree(source.parent)
    backups_dir().mkdir(parents=True, exist_ok=True)
    backup = backups_dir() / ('app-%s-%d' % (current_version(), time.time_ns()))
    context.progress(50, 'Keeping the current version')
    shutil.copytree(paths.APP, backup, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    context.progress(70, 'Activating')
    incoming = paths.APP.parent / ('app.incoming-%d' % time.time_ns())
    shutil.copytree(source, incoming, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    previous = paths.APP.parent / ('app.previous-%d' % time.time_ns())
    try:
        paths.APP.rename(previous)
        incoming.rename(paths.APP)
    except OSError as exc:
        if previous.is_dir() and not paths.APP.is_dir():
            previous.rename(paths.APP)
        shutil.rmtree(incoming, ignore_errors=True)
        raise CyToolError('Busy', 'The application folder is in use and could not be replaced (%s). Close the window '
                          'and apply the update from the command line: tool.py invoke update_apply.' % exc)
    shutil.rmtree(previous, ignore_errors=True)
    write_json(state_file(), {'version': report['version'], 'backup': str(backup),
                              'applied': time.strftime('%Y-%m-%dT%H:%M:%S'), 'previousVersion': current_version()})
    context.progress(100, 'Applied; restart to run the new version')
    return {'applied': True, 'version': report['version'], 'backup': str(backup), 'restartRequired': True}


def rollback(context, runtime, job_id=None):
    state_value = read_json(state_file(), {})
    backup = state_value.get('backup', '')
    if not backup or not Path(backup).is_dir():
        raise CyToolError('NotFound', 'No kept version is available to restore.')
    if busy(runtime, job_id):
        raise CyToolError('Busy', 'Wait for running jobs to finish before restoring a version.')
    source = Path(backup).resolve()
    if not source.is_relative_to(backups_dir().resolve()):
        raise CyToolError('InvalidState', 'The kept version is outside runtime/backups.')
    context.progress(30, 'Restoring the kept version')
    incoming = paths.APP.parent / ('app.restore-%d' % time.time_ns())
    shutil.copytree(source, incoming, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    previous = paths.APP.parent / ('app.replaced-%d' % time.time_ns())
    try:
        paths.APP.rename(previous)
        incoming.rename(paths.APP)
    except OSError as exc:
        if previous.is_dir() and not paths.APP.is_dir():
            previous.rename(paths.APP)
        shutil.rmtree(incoming, ignore_errors=True)
        raise CyToolError('Busy', 'The application folder is in use (%s).' % exc)
    shutil.rmtree(previous, ignore_errors=True)
    restored = read_json(paths.APP / 'CyTool.json', {}).get('version', '')
    write_json(state_file(), {**state_value, 'rolledBackAt': time.strftime('%Y-%m-%dT%H:%M:%S'), 'version': restored})
    context.progress(100, 'Restored; restart to run it')
    return {'restored': True, 'version': restored, 'restartRequired': True}


def state():
    return {'settings': settings(), 'current': current_version(), 'token': token_status(),
            'staged': read_json(staging_path() / 'staged.json', {}), 'lastApplied': read_json(state_file(), {}),
            'backups': sorted(item.name for item in backups_dir().glob('app-*')) if backups_dir().is_dir() else [],
            'dataUntouched': str(paths.DATA)}
