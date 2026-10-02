"""Build (and optionally publish) the application release that cydec/updates.py installs.

    runtime/python/Scripts/python.exe app/scripts/make_release.py            # build dist/*.zip
    runtime/python/Scripts/python.exe app/scripts/make_release.py --publish  # + GitHub release

The archive is `git archive HEAD` (only committed files: never runtime/ or data/) with an added
app/release.json (version, runtime ABI, commit). The version comes from app/CyTool.json; the
tag is v<version>. Publishing needs a GitHub token with write access to the repository, read
from GITHUB_TOKEN or the credential store ('github'); the commit must already be pushed.
GitHub records the asset's SHA-256 digest, which the updater checks before installing.
"""
import hashlib
import io
import json
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
DIST = ROOT / 'dist'
sys.path.insert(0, str(APP))


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def build():
    from cydec.updates import DEFAULT_REPOSITORY, RUNTIME_ABI
    manifest = json.loads((APP / 'CyTool.json').read_text(encoding='utf-8'))
    version = manifest['version']
    if git('status', '--porcelain', '--untracked-files=no'):
        raise SystemExit('Commit your changes first: the release is built from HEAD.')
    commit = git('rev-parse', 'HEAD')
    archive = subprocess.run(['git', 'archive', '--format=zip', '--prefix=CyDecompilator/', 'HEAD'], cwd=ROOT,
                             capture_output=True, check=True).stdout
    DIST.mkdir(exist_ok=True)
    target = DIST / ('CyDecompilator-%s.zip' % version)
    with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as out:
        for item in source.infolist():
            if item.filename != 'CyDecompilator/app/release.json':     # replaced by the generated one
                out.writestr(item, source.read(item))
        out.writestr('CyDecompilator/app/release.json', json.dumps(
            {'version': version, 'runtimeAbi': RUNTIME_ABI, 'commit': commit, 'repository': DEFAULT_REPOSITORY},
            indent=2) + '\n')
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (DIST / (target.name + '.sha256')).write_text('%s  %s\n' % (digest, target.name), encoding='ascii')
    print('Built %s (%d bytes)\nSHA-256 %s' % (target, target.stat().st_size, digest))
    return target, version, commit, digest


def api(method, url, token, data=None, content_type='application/json'):
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'CyDecompilator-release'}
    if data is not None:
        headers['Content-Type'] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit('GitHub %s %s failed: HTTP %d %s' % (method, url, exc.code, exc.read()[:400]))


def publish(target, version, commit, digest):
    from cydec.ai import credentials
    from cydec.updates import DEFAULT_REPOSITORY
    token = credentials.resolve('github')
    if not token:
        raise SystemExit('No GitHub token: set GITHUB_TOKEN or store one in the Updates section.')
    tag = 'v' + version
    base = 'https://api.github.com/repos/' + DEFAULT_REPOSITORY
    notes = 'CyDecompilator %s\n\nCommit %s\n\nSHA-256 of %s: %s\n' % (version, commit, target.name, digest)
    release = api('POST', base + '/releases', token, json.dumps(
        {'tag_name': tag, 'target_commitish': commit, 'name': 'CyDecompilator ' + version, 'body': notes}).encode())
    upload = release['upload_url'].split('{')[0] + '?name=' + target.name
    asset = api('POST', upload, token, target.read_bytes(), 'application/zip')
    published = str(asset.get('digest', '')).removeprefix('sha256:')
    if published and published != digest:
        raise SystemExit('GitHub reports another digest for the asset (%s): delete the release.' % published)
    print('Published %s: %s' % (tag, release.get('html_url')))


if __name__ == '__main__':
    built = build()
    if '--publish' in sys.argv[1:]:
        publish(*built)
