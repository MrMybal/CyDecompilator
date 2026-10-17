"""Downloadable engine components: discovery, installation, location and removal.

Every component comes from its official source, resolved at install time:

    jdk          Eclipse Temurin JDK 21 (Adoptium API)          GPL-2.0 + Classpath Exception
    ghidra       NSA Ghidra (GitHub releases)                    Apache-2.0
    dotnet       .NET runtime (Microsoft release metadata)       MIT
    ilspycmd     ILSpy command line (NuGet)                       MIT
    vineflower   Vineflower Java decompiler (GitHub releases)    Apache-2.0
    jadx         JADX Dex/APK decompiler (GitHub releases)       Apache-2.0
    pydecompile  xdis + uncompyle6 + decompyle3 (PyPI, private)  GPL-2.0 / GPL-3.0

A download is verified against the SHA256 its source publishes when there is one, then
extracted into runtime/engines/<id>/<version>/ with path traversal and links refused. The
previous version stays on disk until removed, so an update can be rolled back by
selecting it. A component already installed on the system (java >= 21 on PATH, a dotnet
runtime, a Ghidra folder chosen in the settings) is used without downloading anything.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from cytools_core import CyToolError

from .paths import DOWNLOADS, ENGINES, SETTINGS, read_json, write_json

WINDOWS = os.name == 'nt'
EXE = '.exe' if WINDOWS else ''
OVERRIDES = SETTINGS / 'components.json'
USER_AGENT = 'CyDecompilator/0.1 (+https://github.com/)'
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0

CATALOG = {
    'electron':{'name':'Electron','license':'MIT','url':'https://github.com/electron/electron',
        'approxBytes':100_000_000,'requires':[],'usedBy':['reconstruction'],
        'description':'Runtime for rebuilt Electron applications. Native modules require a matching version and architecture.'},
    'typescript': {'name': 'TypeScript parser', 'license': 'Apache-2.0',
                   'url': 'https://github.com/microsoft/TypeScript', 'approxBytes': 4_400_000,
                   'requires': [], 'usedBy': ['javascript'],
                   'description': 'Static JavaScript and TypeScript parser for Electron and web investigations. Requires Node.js on PATH.'},
    'netcoredbg': {'name': 'NetCoreDbg', 'license': 'MIT',
                  'url': 'https://github.com/Samsung/netcoredbg', 'approxBytes': 4_000_000,
                  'requires': [], 'usedBy': ['debugger'],
                  'description': 'Debugger for reconstructed .NET projects: breakpoints, stepping, stack frames and variables.'},
    'jdk': {'name': 'Eclipse Temurin JDK 21', 'license': 'GPL-2.0-with-classpath-exception',
            'url': 'https://adoptium.net/', 'approxBytes': 205_000_000, 'requires': [],
            'usedBy': ['ghidra', 'vineflower', 'jadx'],
            'description': 'Java runtime for Ghidra, Vineflower and JADX. A system Java 21+ is used if present.'},
    'ghidra': {'name': 'Ghidra', 'license': 'Apache-2.0',
               'url': 'https://github.com/NationalSecurityAgency/ghidra', 'approxBytes': 570_000_000,
               'requires': ['jdk'], 'usedBy': ['ghidra'],
               'description': 'NSA reverse engineering suite, used headless: native C decompiler for PE, ELF, Mach-O and raw firmware on many CPUs.'},
    'dotnet': {'name': '.NET runtime', 'license': 'MIT', 'url': 'https://dotnet.microsoft.com/',
               'approxBytes': 32_000_000, 'requires': [], 'usedBy': ['ilspy'],
               'description': 'Runtime for ILSpy. The version matches what ilspycmd targets.'},
    'ilspycmd': {'name': 'ILSpy (ilspycmd)', 'license': 'MIT',
                 'url': 'https://github.com/icsharpcode/ILSpy', 'approxBytes': 5_000_000,
                 'requires': ['dotnet'], 'usedBy': ['ilspy'],
                 'description': '.NET decompiler: C# source and IL for managed assemblies.'},
    'vineflower': {'name': 'Vineflower', 'license': 'Apache-2.0',
                   'url': 'https://github.com/Vineflower/vineflower', 'approxBytes': 2_000_000,
                   'requires': ['jdk'], 'usedBy': ['vineflower'],
                   'description': 'Modern Java decompiler (Fernflower fork) for .class and .jar.'},
    'jadx': {'name': 'JADX', 'license': 'Apache-2.0', 'url': 'https://github.com/skylot/jadx',
             'approxBytes': 73_000_000, 'requires': ['jdk'], 'usedBy': ['jadx'],
             'description': 'Dex to Java decompiler for APK, DEX, JAR and class files.'},
    'upx': {'name': 'UPX', 'license': 'GPL-2.0-or-later with UPX exception',
            'url': 'https://github.com/upx/upx', 'approxBytes': 700_000, 'requires': [], 'usedBy': ['unpack'],
            'description': 'Executable packer; used to unpack UPX-compressed EXE/DLL files before analysis.'},
    'pydecompile': {'name': 'Python decompilers (xdis, uncompyle6, decompyle3)',
                    'license': 'GPL-2.0-or-later (xdis), GPL-3.0 (uncompyle6, decompyle3)',
                    'url': 'https://github.com/rocky/python-uncompyle6', 'approxBytes': 15_000_000,
                    'requires': [], 'usedBy': ['python'],
                    'description': 'Cross-version bytecode reader and decompilers (source for Python up to 3.8, disassembly for every version).'},
}

PIP_PACKAGES = ['xdis', 'uncompyle6', 'decompyle3']

_cache = {}
_cache_lock = threading.Lock()
_install_lock = threading.Lock()


# ---------------------------------------------------------------------- helpers

def _http_json(url, timeout=30):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT,
                                                   'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise CyToolError('DownloadFailed', 'HTTP %d from %s' % (exc.code, url.split('?')[0]),
                          recoverable=True)
    except (OSError, ValueError) as exc:
        raise CyToolError('DownloadFailed', 'Cannot reach %s: %s' % (url.split('?')[0], exc),
                          recoverable=True)


def _github_asset(repository, pattern):
    release = _http_json('https://api.github.com/repos/%s/releases/latest' % repository)
    for asset in release.get('assets', []):
        if re.fullmatch(pattern, asset['name']):
            digest = asset.get('digest') or ''
            return {'version': release['tag_name'].lstrip('v').replace('Ghidra_', '').replace('_build', ''),
                    'url': asset['browser_download_url'], 'fileName': asset['name'],
                    'size': asset.get('size'),
                    'sha256': digest[7:] if digest.startswith('sha256:') else None}
    raise CyToolError('DownloadFailed', 'No asset matching %s in the latest %s release.'
                      % (pattern, repository), recoverable=True)


def _platform():
    if WINDOWS:
        return 'windows'
    return 'mac' if sys.platform == 'darwin' else 'linux'


def _arch():
    import platform
    machine = platform.machine().lower()
    return 'aarch64' if machine in ('arm64', 'aarch64') else 'x64'


def overrides():
    value = read_json(OVERRIDES, {})
    return value if isinstance(value, dict) else {}


def set_override(component_id, path):
    if component_id not in CATALOG:
        raise CyToolError('NotFound', 'Unknown component ' + component_id)
    values = overrides()
    if path:
        if not Path(path).exists():
            raise CyToolError('NotFound', 'Path does not exist: %s' % path)
        values[component_id] = {'path': str(Path(path).resolve())}
    else:
        values.pop(component_id, None)
    write_json(OVERRIDES, values)
    invalidate()
    return status(component_id)


def invalidate():
    with _cache_lock:
        _cache.clear()


def _run(command, timeout=20):
    try:
        result = subprocess.run([str(c) for c in command], capture_output=True, timeout=timeout,
                                creationflags=CREATE_NO_WINDOW)
        return result.returncode, result.stdout.decode('utf-8', 'replace'), result.stderr.decode('utf-8', 'replace')
    except (OSError, subprocess.TimeoutExpired):
        return -1, '', ''


def _installed_versions(component_id):
    """Private installs, newest first, read from runtime/engines/<id>/installed.json."""
    record = read_json(ENGINES / component_id / 'installed.json', {})
    versions = record.get('versions', []) if isinstance(record, dict) else []
    active = record.get('active') if isinstance(record, dict) else None
    result = [v for v in versions if isinstance(v, dict) and Path(v.get('path', '')).exists()]
    result.sort(key=lambda v: (v.get('version') != active, -float(v.get('installedAt', 0))))
    return result


# ---------------------------------------------------------------------- locators

def _java_version(java):
    code, out, err = _run([java, '-version'])
    match = re.search(r'version "(\d+)(?:\.(\d+))?', out + err)
    if not match:
        return 0, ''
    major = int(match.group(1))
    if major == 1 and match.group(2):
        major = int(match.group(2))
    full = re.search(r'version "([^"]+)"', out + err)
    return major, full.group(1) if full else str(major)


def _locate_jdk():
    candidates = []
    override = overrides().get('jdk', {}).get('path')
    if override:
        candidates.append(('override', Path(override)))
    for item in _installed_versions('jdk'):
        candidates.append(('private', Path(item['path'])))
    if os.environ.get('JAVA_HOME'):
        candidates.append(('system', Path(os.environ['JAVA_HOME'])))
    which = shutil.which('java')
    if which:
        resolved = Path(which).resolve()
        candidates.append(('system', resolved.parent.parent))
    for source, home in candidates:
        java = home / 'bin' / ('java' + EXE)
        if not java.is_file():
            if home.is_file() and home.name.lower().startswith('java'):
                java, home = home, home.parent.parent
            else:
                continue
        major, full = _java_version(java)
        if major >= 21:
            return {'path': str(home), 'java': str(java), 'version': full, 'source': source,
                    'javac': (home / 'bin' / ('javac' + EXE)).is_file()}
    return None


def _find(root, relative_glob):
    matches = sorted(Path(root).glob(relative_glob))
    return matches[0] if matches else None


def _locate_ghidra():
    candidates = []
    override = overrides().get('ghidra', {}).get('path')
    if override:
        candidates.append(('override', Path(override)))
    for item in _installed_versions('ghidra'):
        candidates.append(('private', Path(item['path'])))
    for source, root in candidates:
        script = 'analyzeHeadless.bat' if WINDOWS else 'analyzeHeadless'
        for base in (root, *sorted(root.glob('ghidra_*'))):
            headless = base / 'support' / script
            if headless.is_file():
                props = (base / 'Ghidra' / 'application.properties')
                version = ''
                if props.is_file():
                    match = re.search(r'application\.version=(.+)', props.read_text('utf-8', 'replace'))
                    version = match.group(1).strip() if match else ''
                return {'path': str(base), 'headless': str(headless), 'version': version,
                        'source': source}
    return None


def _dotnet_runtimes(dotnet):
    code, out, _ = _run([dotnet, '--list-runtimes'])
    versions = []
    for line in out.splitlines():
        match = re.match(r'Microsoft\.NETCore\.App (\d+)\.(\d+)\.(\d+)', line)
        if match:
            versions.append(tuple(int(x) for x in match.groups()))
    return sorted(versions, reverse=True)


def required_dotnet_major():
    ilspy = _locate_ilspycmd(check_runtime=False)
    if ilspy and ilspy.get('requiresDotnet'):
        return ilspy['requiresDotnet']
    return 10


def _locate_dotnet():
    need = required_dotnet_major()
    candidates = []
    override = overrides().get('dotnet', {}).get('path')
    if override:
        candidates.append(('override', Path(override)))
    for item in _installed_versions('dotnet'):
        candidates.append(('private', Path(item['path'])))
    which = shutil.which('dotnet')
    if which:
        candidates.append(('system', Path(which).resolve().parent))
    for source, root in candidates:
        dotnet = root / ('dotnet' + EXE) if root.is_dir() else root
        if not dotnet.is_file():
            continue
        runtimes = _dotnet_runtimes(dotnet)
        usable = [v for v in runtimes if v[0] >= need]
        if usable:
            return {'path': str(dotnet.parent), 'dotnet': str(dotnet),
                    'version': '.'.join(map(str, usable[0])), 'source': source,
                    'requiresMajor': need}
    return None


def _locate_ilspycmd(check_runtime=True):
    candidates = []
    override = overrides().get('ilspycmd', {}).get('path')
    if override:
        candidates.append(('override', Path(override)))
    for item in _installed_versions('ilspycmd'):
        candidates.append(('private', Path(item['path'])))
    for source, root in candidates:
        dll = root if root.suffix == '.dll' else _find(root, 'tools/*/any/ilspycmd.dll') or _find(root, '**/ilspycmd.dll')
        if dll is None or not dll.is_file():
            continue
        config = read_json(dll.with_name('ilspycmd.runtimeconfig.json'), {})
        framework = config.get('runtimeOptions', {}).get('framework', {}).get('version', '10.0.0')
        version = dll.parent.parent.parent.parent.name if source == 'private' else ''
        return {'path': str(dll.parent), 'dll': str(dll), 'version': version, 'source': source,
                'requiresDotnet': int(framework.split('.')[0])}
    return None


def _locate_vineflower():
    candidates = []
    override = overrides().get('vineflower', {}).get('path')
    if override:
        candidates.append(('override', Path(override)))
    for item in _installed_versions('vineflower'):
        candidates.append(('private', Path(item['path'])))
    for source, root in candidates:
        jar = root if root.suffix == '.jar' else _find(root, 'vineflower*.jar')
        if jar is not None and jar.is_file():
            match = re.search(r'vineflower-(\d+(?:\.\d+)*)', jar.name)
            return {'path': str(jar.parent), 'jar': str(jar), 'source': source,
                    'version': match.group(1) if match else ''}
    return None


def _locate_jadx():
    candidates = []
    override = overrides().get('jadx', {}).get('path')
    if override:
        candidates.append(('override', Path(override)))
    for item in _installed_versions('jadx'):
        candidates.append(('private', Path(item['path'])))
    for source, root in candidates:
        lib = root / 'lib'
        jars = sorted(lib.glob('jadx-*-all.jar')) or sorted(lib.glob('*.jar'))
        if jars:
            match = re.search(r'jadx-([\d.]+)', jars[0].name)
            return {'path': str(root), 'classpath': str(lib / '*'), 'jars': [str(j) for j in jars],
                    'source': source, 'version': match.group(1) if match else ''}
    return None


def _locate_upx():
    candidates = []
    override = overrides().get('upx', {}).get('path')
    if override:
        candidates.append(('override', Path(override)))
    for item in _installed_versions('upx'):
        candidates.append(('private', Path(item['path'])))
    which = shutil.which('upx')
    if which:
        candidates.append(('system', Path(which)))
    for source, root in candidates:
        exe = root if root.is_file() else _find(root, '**/upx' + EXE)
        if exe is not None and exe.is_file():
            code, out, _ = _run([exe, '--version'])
            match = re.search(r'upx ([\d.]+)', out)
            return {'path': str(exe.parent), 'exe': str(exe), 'source': source,
                    'version': match.group(1) if match else ''}
    return None


def _locate_pydecompile():
    for item in _installed_versions('pydecompile'):
        root = Path(item['path'])
        if (root / 'xdis').is_dir():
            return {'path': str(root), 'version': item.get('version', ''), 'source': 'private',
                    'packages': item.get('packages', {})}
    return None


def _locate_netcoredbg():
    candidates = []
    override = overrides().get('netcoredbg', {}).get('path')
    if override:
        candidates.append(('override', Path(override)))
    candidates.extend(('private', Path(v['path'])) for v in _installed_versions('netcoredbg'))
    which = shutil.which('netcoredbg')
    if which:
        candidates.append(('system', Path(which)))
    for source, root in candidates:
        exe = root if root.is_file() else _find(root, '**/netcoredbg' + EXE)
        if exe and exe.is_file():
            return {'path': str(exe.parent), 'exe': str(exe), 'source': source}
    return None


def _locate_typescript():
    candidates = [('override', Path(overrides()['typescript']['path']))] if overrides().get('typescript', {}).get('path') else []
    candidates.extend(('private', Path(v['path'])) for v in _installed_versions('typescript'))
    for source, root in candidates:
        parser = root if root.is_file() else _find(root, '**/lib/typescript.js')
        if parser and parser.is_file():
            return {'path': str(parser.parent.parent), 'parser': str(parser), 'source': source}
    return None


def _locate_electron():
    candidates=[]
    override=overrides().get('electron',{}).get('path')
    if override:candidates.append(('override',Path(override)))
    candidates.extend(('private',Path(v['path'])) for v in _installed_versions('electron'))
    for source,root in candidates:
        exe=root if root.is_file() else _find(root,'**/Electron.app/Contents/MacOS/Electron' if sys.platform=='darwin' else '**/electron'+EXE)
        if exe and exe.is_file():return {'path':str(exe.parent),'exe':str(exe),'source':source}
    return None


LOCATORS = {'electron':_locate_electron,'typescript': _locate_typescript, 'netcoredbg': _locate_netcoredbg, 'jdk': _locate_jdk, 'ghidra': _locate_ghidra, 'dotnet': _locate_dotnet,
            'ilspycmd': _locate_ilspycmd, 'vineflower': _locate_vineflower,
            'jadx': _locate_jadx, 'pydecompile': _locate_pydecompile, 'upx': _locate_upx}


def locate(component_id, refresh=False):
    """Where the component is, or None. Cached because probing runs subprocesses."""
    if component_id not in LOCATORS:
        raise CyToolError('NotFound', 'Unknown component ' + str(component_id))
    with _cache_lock:
        cached = _cache.get(component_id)
        if cached is not None and not refresh and time.monotonic() - cached[0] < 300:
            return cached[1]
    value = LOCATORS[component_id]()
    with _cache_lock:
        _cache[component_id] = (time.monotonic(), value)
    return value


def status(component_id=None, refresh=False):
    if component_id is None:
        return [status(key, refresh) for key in CATALOG]
    entry = CATALOG.get(component_id)
    if entry is None:
        raise CyToolError('NotFound', 'Unknown component ' + str(component_id))
    found = locate(component_id, refresh)
    return {'id': component_id, 'name': entry['name'], 'license': entry['license'],
            'url': entry['url'], 'description': entry['description'],
            'requires': entry['requires'], 'usedBy': entry['usedBy'],
            'approxBytes': entry['approxBytes'], 'installed': found is not None,
            'location': found or {},
            'privateVersions': [{k: v.get(k) for k in ('version', 'path', 'installedAt', 'sha256Verified')}
                                for v in _installed_versions(component_id)],
            'override': overrides().get(component_id, {}).get('path', '')}


# ---------------------------------------------------------------------- resolvers

def resolve(component_id):
    """Ask the official source for the current release: url, version, size, sha256."""
    plat, arch = _platform(), _arch()
    if component_id=='electron':
        target={'windows':'win32','mac':'darwin','linux':'linux'}[plat]+'-'+('arm64' if arch=='aarch64' else 'x64')
        release=_github_asset('electron/electron',r'electron-v[\d.]+-'+re.escape(target)+r'\.zip')
        if not release.get('sha256'):
            url='https://github.com/electron/electron/releases/download/v'+release['version']+'/SHASUMS256.txt'
            request=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
            try:
                with urllib.request.urlopen(request,timeout=30) as response:sums=response.read(1024*1024).decode('ascii')
            except (OSError,UnicodeError) as error:raise CyToolError('DownloadFailed','Cannot read official Electron checksums: '+str(error))
            for line in sums.splitlines():
                parts=line.split()
                if len(parts)==2 and parts[1].lstrip('*')==release['fileName'] and re.fullmatch(r'[a-fA-F0-9]{64}',parts[0]):
                    release['sha256']=parts[0];break
        if not release.get('sha256'):raise CyToolError('IntegrityFailure','The official Electron archive has no verified checksum.')
        return release
    if component_id == 'typescript':
        import base64
        version = '5.9.3'
        metadata = _http_json('https://registry.npmjs.org/typescript/' + version)
        dist = metadata['dist']
        integrity = dist['integrity']
        if not integrity.startswith('sha512-') or not dist['tarball'].startswith('https://registry.npmjs.org/typescript/-/'):
            raise CyToolError('IntegrityFailure', 'Invalid official parser release metadata.')
        return {'version': version, 'url': dist['tarball'], 'fileName': 'typescript-' + version + '.tgz',
                'sha512': base64.b64decode(integrity[7:], validate=True).hex()}
    if component_id == 'netcoredbg':
        target = 'win64.zip' if plat == 'windows' and arch == 'x64' else \
            ('osx-arm64.zip' if plat == 'mac' and arch == 'aarch64' else
             'linux-%s.tar.gz' % ('arm64' if arch == 'aarch64' else 'amd64') if plat == 'linux' else '')
        if not target:
            raise CyToolError('Unsupported', 'No official NetCoreDbg binary is available for this platform.')
        return _github_asset('Samsung/netcoredbg', re.escape('netcoredbg-' + target))
    if component_id == 'jdk':
        os_name = {'windows': 'windows', 'linux': 'linux', 'mac': 'mac'}[plat]
        data = _http_json('https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=%s'
                          '&image_type=jdk&os=%s&vendor=eclipse' % (arch, os_name))
        if not data:
            raise CyToolError('DownloadFailed', 'Adoptium returned no JDK 21 build for this platform.')
        package = data[0]['binary']['package']
        return {'version': data[0]['version']['semver'], 'url': package['link'],
                'fileName': package['name'], 'size': package['size'], 'sha256': package['checksum']}
    if component_id == 'ghidra':
        return _github_asset('NationalSecurityAgency/ghidra', r'ghidra_.*_PUBLIC_.*\.zip')
    if component_id == 'vineflower':
        return _github_asset('Vineflower/vineflower', r'vineflower-[\d.]+\.jar')
    if component_id == 'jadx':
        return _github_asset('skylot/jadx', r'jadx-[\d.]+\.zip')
    if component_id == 'upx':
        pattern = r'upx-[\d.]+-win64\.zip' if plat == 'windows' else \
            r'upx-[\d.]+-%s_linux\.tar\.xz' % ('arm64' if arch == 'aarch64' else 'amd64')
        return _github_asset('upx/upx', pattern)
    if component_id == 'ilspycmd':
        versions = _http_json('https://api.nuget.org/v3-flatcontainer/ilspycmd/index.json')['versions']
        stable = [v for v in versions if '-' not in v]
        version = stable[-1]
        return {'version': version, 'fileName': 'ilspycmd.%s.nupkg' % version, 'size': None,
                'sha256': None,
                'url': 'https://api.nuget.org/v3-flatcontainer/ilspycmd/%s/ilspycmd.%s.nupkg' % (version, version)}
    if component_id == 'dotnet':
        major = required_dotnet_major()
        data = _http_json('https://builds.dotnet.microsoft.com/dotnet/release-metadata/%d.0/releases.json' % major)
        rid = {'windows': 'win', 'linux': 'linux', 'mac': 'osx'}[plat] + '-' + ('arm64' if arch == 'aarch64' else 'x64')
        suffix = '.zip' if plat == 'windows' else '.tar.gz'
        for release in data['releases']:
            runtime = release.get('runtime') or {}
            for item in runtime.get('files', []):
                if item['name'] == 'dotnet-runtime-%s%s' % (rid, suffix):
                    return {'version': runtime['version'], 'url': item['url'],
                            'fileName': Path(item['url']).name, 'size': None, 'sha256': None,
                            'sha512': item.get('hash')}
        raise CyToolError('DownloadFailed', 'No .NET %d runtime for %s.' % (major, rid))
    if component_id == 'pydecompile':
        return {'version': 'pypi-latest', 'packages': PIP_PACKAGES}
    raise CyToolError('NotFound', 'Unknown component ' + str(component_id))


# ---------------------------------------------------------------------- extraction

def _safe_target(root, name):
    name = name.replace('\\', '/')
    if name.startswith('/') or re.match(r'^[A-Za-z]:', name) or any(p == '..' for p in name.split('/')):
        raise CyToolError('IntegrityFailure', 'Archive entry escapes the destination: %s' % name)
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise CyToolError('IntegrityFailure', 'Archive entry escapes the destination: %s' % name)
    return target


def extract(archive, destination, context=None):
    archive, destination = Path(archive), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(('.zip', '.nupkg')):
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            for index, member in enumerate(members):
                if context is not None and index % 200 == 0:
                    context.check()
                    context.progress(80 + 18 * index / max(len(members), 1), 'Extracting')
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:  # symbolic link: refused
                    continue
                target = _safe_target(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, open(target, 'wb') as sink:
                    shutil.copyfileobj(source, sink, 1 << 20)
                if not WINDOWS and (member.external_attr >> 16) & 0o111:
                    target.chmod(0o755)
    elif name.endswith(('.tar.gz', '.tgz', '.tar.xz')):
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                _safe_target(destination, member.name)
            bundle.extractall(destination, filter='data')
    else:
        shutil.copyfile(archive, destination / archive.name)


# ---------------------------------------------------------------------- install

def _record_install(component_id, version, path, extra):
    record = read_json(ENGINES / component_id / 'installed.json', {})
    versions = [v for v in record.get('versions', []) if v.get('version') != version]
    versions.append({'version': version, 'path': str(path), 'installedAt': time.time(), **extra})
    write_json(ENGINES / component_id / 'installed.json', {'active': version, 'versions': versions})
    invalidate()


def install(component_id, context=None, include_requirements=True):
    """Install the latest release of a component (and what it requires). Returns status."""
    if component_id not in CATALOG:
        raise CyToolError('NotFound', 'Unknown component ' + str(component_id))
    if not _install_lock.acquire(timeout=1):
        raise CyToolError('Busy', 'Another component installation is running.', recoverable=True)
    try:
        installed = []
        if include_requirements:
            for requirement in CATALOG[component_id]['requires']:
                if locate(requirement, refresh=True) is None:
                    installed.append(_install_one(requirement, context))
        installed.append(_install_one(component_id, context))
        return {'installed': installed, 'status': status(component_id, refresh=True)}
    finally:
        _install_lock.release()


def _progress(context, base, span):
    def report(done, total):
        if context is None:
            return
        if total:
            context.progress(base + span * done / total, 'Downloading %.1f / %.1f MB' % (done / 1e6, total / 1e6))
        else:
            context.progress(base, 'Downloading %.1f MB' % (done / 1e6))
    return report


def _install_one(component_id, context):
    if context is not None:
        context.log('Resolving the current %s release from its official source' % CATALOG[component_id]['name'])
        context.progress(1, 'Resolving ' + component_id)
    release = resolve(component_id)
    if component_id == 'pydecompile':
        return _install_pip(context)
    from cytools_core.downloads import DownloadManager
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    manager = DownloadManager(DOWNLOADS, timeout=60, use_shared_cache=False)
    file_name = re.sub(r'[^A-Za-z0-9_.-]', '_', release['fileName'])
    if context is not None:
        context.log('Downloading %s %s from %s%s' % (component_id, release['version'], release['url'],
                                                     ' (SHA256 published)' if release.get('sha256') else ''))
    result = manager.download(file_name, release['url'], sha256=release.get('sha256'),
                              size=release.get('size'),
                              cancellation=getattr(context, 'cancellation', None),
                              progress=_progress(context, 3, 75))
    if result.get('state') != 'Completed':
        raise CyToolError('DownloadFailed', 'Download did not complete: %s' % result.get('state'),
                          recoverable=True)
    archive = Path(result['path'])
    if release.get('sha512'):
        import hashlib
        digest = hashlib.sha512()
        with open(archive, 'rb') as handle:
            for block in iter(lambda: handle.read(1 << 20), b''):
                digest.update(block)
        if digest.hexdigest().lower() != release['sha512'].lower():
            manager.remove(file_name)
            raise CyToolError('IntegrityFailure', 'SHA512 of the downloaded component does not match the published value.')
    version = re.sub(r'[^A-Za-z0-9_.+-]', '_', release['version'])
    final = ENGINES / component_id / version
    staging = ENGINES / component_id / (version + '.staging')
    shutil.rmtree(staging, ignore_errors=True)
    extract(archive, staging, context)
    if final.exists():
        shutil.rmtree(final)
    os.replace(staging, final)
    home = final
    if component_id == 'jdk':
        found = _find(final, '*/bin/java' + EXE)
        home = found.parent.parent if found else final
    if component_id == 'jadx' and not (final / 'lib').is_dir():
        nested = _find(final, '*/lib')
        home = nested.parent if nested else final
    _record_install(component_id, release['version'], home,
                    {'url': release['url'], 'sha256': result.get('sha256Verified') and release.get('sha256'),
                     'sha512': release.get('sha512'),
                     'sha256Verified': bool(release.get('sha256') or release.get('sha512'))})
    if context is not None:
        context.log('%s %s installed in %s' % (component_id, release['version'], home))
    return {'id': component_id, 'version': release['version'], 'path': str(home)}


def _install_pip(context):
    target_root = ENGINES / 'pydecompile'
    version = time.strftime('%Y%m%d-%H%M%S')
    staging = target_root / (version + '.staging')
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    from . import process
    if context is not None:
        context.progress(10, 'pip install ' + ' '.join(PIP_PACKAGES))
    code, out, err = process.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
                                  '--no-input', '--target', str(staging)] + PIP_PACKAGES,
                                 context=context, timeout=900, log_name='pip')
    if code != 0:
        shutil.rmtree(staging, ignore_errors=True)
        raise CyToolError('DownloadFailed', 'pip failed: ' + process.tail(err or out, 8), recoverable=True)
    packages = {}
    for info in staging.glob('*.dist-info'):
        match = re.match(r'(.+)-([^-]+)\.dist-info', info.name)
        if match:
            packages[match.group(1)] = match.group(2)
    final = target_root / version
    os.replace(staging, final)
    _record_install('pydecompile', version, final, {'packages': packages, 'sha256Verified': False,
                                                     'url': 'https://pypi.org/'})
    return {'id': 'pydecompile', 'version': version, 'path': str(final), 'packages': packages}


def remove(component_id, version=''):
    """Remove one private version (or all). System or overridden installs are never touched."""
    record = read_json(ENGINES / component_id / 'installed.json', {})
    kept = []
    removed = []
    for item in record.get('versions', []):
        if not version or item.get('version') == version:
            base = ENGINES / component_id
            path = Path(item['path']).resolve()
            # Remove the version folder directly under runtime/engines/<id>/ only.
            while path.parent.resolve() != base.resolve() and path != path.parent:
                path = path.parent
            if path.parent.resolve() == base.resolve():
                shutil.rmtree(path, ignore_errors=True)
            removed.append(item.get('version'))
        else:
            kept.append(item)
    write_json(ENGINES / component_id / 'installed.json',
               {'active': kept[-1]['version'] if kept else None, 'versions': kept})
    invalidate()
    return {'id': component_id, 'removed': removed, 'status': status(component_id, refresh=True)}


def java_env():
    """Environment for a Java engine: JAVA_HOME of the located JDK, or an error."""
    jdk = locate('jdk')
    if jdk is None:
        raise CyToolError('MissingDependency', 'Java 21+ is required. Install the jdk component.',
                          recoverable=True)
    return jdk, {'JAVA_HOME': jdk['path']}
