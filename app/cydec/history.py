"""Local Git source snapshots, reviewed differences and reversible restoration.

Each attached folder gets its own private bare repository. Plumbing commands avoid
the user's index, hooks, attributes, ignore rules and remote configuration.
"""
import difflib
import hashlib
import os
import re
import shutil
import stat
import uuid
import zipfile
from pathlib import Path

from cytools_core import CyToolError

from . import process, workspace
from .paths import read_json, write_json

MAX_FILES = 4000
MAX_BYTES = 128 * 1024 * 1024
MAX_FILE = 32 * 1024 * 1024
EXCLUDED = workspace.EXCLUDED | {'.hg', '.svn', 'node_modules', '.idea'}
REF = 'refs/heads/history'


def _folder(project, root):
    key = hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:24]
    return project.dir / 'history' / key


def _path(root, relative):
    path = workspace.confined(root, relative)
    parts = Path(relative).parts
    if any(p.casefold() in {x.casefold() for x in EXCLUDED} for p in parts):
        raise CyToolError('InvalidParameters', 'History cannot include reserved folders.')
    prefixes = [root / Path(*parts[:i]) for i in range(1, len(parts) + 1)]
    if any(c in relative for c in '\r\n\t\0') or any(p.is_symlink() or (p.exists() and getattr(p.lstat(), 'st_file_attributes', 0) & 0x400)
                                                   for p in prefixes):
        raise CyToolError('InvalidParameters', 'History requires regular files and paths.')
    return path


def _capture(root, context):
    files, total = {}, 0
    for directory, folders, names in os.walk(root, followlinks=False):
        if context:
            context.check()
        folders[:] = sorted(f for f in folders if f.casefold() not in {x.casefold() for x in EXCLUDED})
        for folder in folders:
            _path(root, (Path(directory) / folder).relative_to(root).as_posix())
        for name in sorted(names):
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if name.casefold() in {x.casefold() for x in EXCLUDED}:
                continue
            path = _path(root, relative)
            if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > MAX_FILE:
                raise CyToolError('Unsupported', 'History supports regular files up to 32 MiB.')
            raw = path.read_bytes()
            total += len(raw)
            if len(files) >= MAX_FILES or total > MAX_BYTES:
                raise CyToolError('Unsupported', 'History supports up to 4000 files and 128 MiB per snapshot.')
            files[relative] = raw
    return files


def _revision(files):
    digest = hashlib.sha256()
    for name, raw in sorted(files.items()):
        digest.update(name.encode('utf-8') + b'\0' + hashlib.sha256(raw).digest())
    return digest.hexdigest()


def _source_revision(files):
    # Same directory-first order as managed_patching.source_stamp, from saved bytes.
    digest = hashlib.sha256()
    ordered = sorted(files, key=lambda name: (Path(name).parts[:-1], Path(name).name))
    for name in ordered:
        if Path(name).suffix.lower() in workspace.TEXT_EXTENSIONS:
            digest.update(name.encode('utf-8'))
            digest.update(hashlib.sha256(files[name]).digest())
    return digest.hexdigest()


class Git:
    def __init__(self, project, root, context, create=False):
        self.folder = _folder(project, root)
        self.repo = self.folder / 'repository.git'
        self.context = context
        self.git = shutil.which('git')
        if not self.git:
            raise CyToolError('MissingDependency', 'Install Git and add it to PATH to use project history.')
        if context is None or not context.workdir:
            raise CyToolError('InvalidParameters', 'Git history requires a job workdir.')
        self.work = Path(context.workdir) / ('git-history-' + uuid.uuid4().hex)
        self.work.mkdir(parents=True)
        self.env = {key: None for key in os.environ if key.upper().startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_COUNT='0',
                        GIT_ATTR_NOSYSTEM='1', GIT_INDEX_FILE=str(self.work / 'index'),
                        GIT_AUTHOR_NAME='CyDecompilator', GIT_AUTHOR_EMAIL='local@cydecompilator.invalid',
                        GIT_COMMITTER_NAME='CyDecompilator', GIT_COMMITTER_EMAIL='local@cydecompilator.invalid')
        if create and not self.repo.exists():
            self.folder.mkdir(parents=True, exist_ok=True)
            self.run('init', '--bare', '--template=', str(self.repo), bare=False)
            # Highest-precedence attributes: preserve exact bytes during archive export.
            (self.repo / 'info').mkdir(exist_ok=True)
            (self.repo / 'info/attributes').write_text('* -text -filter -ident -working-tree-encoding -export-ignore -export-subst\n', encoding='utf-8')

    def run(self, *args, stdin=None, bare=True, optional=False):
        command = [self.git, '-c', 'core.hooksPath=' + str(self.work / 'no-hooks'),
                   '-c', 'core.autocrlf=false', '-c', 'core.longpaths=true', '-c', 'commit.gpgSign=false', '-c', 'core.quotePath=false']
        if bare:
            command += ['--git-dir=repository.git']
        code, out, err = process.run(command + list(args), context=self.context, cwd=self.folder if bare else self.work,
                                     env=self.env, stdin_text=stdin, timeout=120, log_name='git-history')
        if code and not optional:
            raise CyToolError('EngineFailed', 'Git history failed: ' + process.tail(err or out))
        return out.strip() if not code else ''

    def head(self):
        return self.run('rev-parse', '--verify', REF, optional=True) if self.repo.is_dir() else ''

    def validate(self, commit):
        if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise CyToolError('InvalidParameters', 'Choose a full commit id from project history.')
        if not self.repo.is_dir():
            raise CyToolError('NotFound', 'History commit not found.')
        reachable = self.run('rev-list', REF).splitlines()
        if commit not in reachable:
            raise CyToolError('NotFound', 'History commit not found.')

    def files(self, commit, root):
        self.validate(commit)
        archive = self.work / 'snapshot.zip'
        self.run('archive', '--format=zip', '--output=' + str(archive), commit)
        files, total = {}, 0
        with zipfile.ZipFile(archive) as zipped:
            for row in zipped.infolist():
                if row.is_dir():
                    continue
                _path(root, row.filename)
                total += row.file_size
                if len(files) >= MAX_FILES or row.file_size > MAX_FILE or total > MAX_BYTES:
                    raise CyToolError('Unsupported', 'History snapshot exceeds supported limits.')
                files[row.filename] = zipped.read(row)
        return files


def _commit(git, root, files, message):
    if not isinstance(message, str) or not message.strip() or len(message) > 500 or '\0' in message:
        raise CyToolError('InvalidParameters', 'Use a version description up to 500 characters.')
    head = git.head()
    staged = git.work / 'files'
    paths = []
    for name, raw in sorted(files.items()):
        path = staged / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        paths.append(str(path).replace('\\', '/'))
    hashes = git.run('hash-object', '--no-filters', '-w', '--stdin-paths', stdin='\n'.join(paths) + '\n').splitlines() if paths else []
    if len(hashes) != len(paths):
        raise CyToolError('EngineFailed', 'Git did not save every source file.')
    git.run('read-tree', '--empty')
    if hashes:
        git.run('update-index', '--index-info', stdin=''.join('100644 %s\t%s\n' % (oid, name) for oid, name in zip(hashes, sorted(files))))
    tree = git.run('write-tree')
    if _revision(_capture(root, git.context)) != _revision(files):
        raise CyToolError('Conflict', 'Sources changed while saving history. Save a version again.')
    if head and tree == git.run('rev-parse', head + '^{tree}'):
        return head, False
    commit = git.run('commit-tree', tree, *(['-p', head] if head else []), '-m', message.strip())
    git.run('update-ref', REF, commit, head or '0' * 40)
    write_json(git.folder / 'commits' / (commit + '.json'),
               {'revision': _revision(files), 'sourceRevision': _source_revision(files), 'directory': str(root)})
    return commit, True


def _info(project, root, git, files):
    head = git.head()
    commits = []
    if head:
        for line in git.run('log', '-100', '--format=%H%x09%ct%x09%s', REF).splitlines():
            oid, timestamp, message = line.split('\t', 2)
            commits.append({'commit': oid, 'timestamp': int(timestamp), 'message': message})
    metadata = read_json(git.folder / 'commits' / (head + '.json'), {}) if head else {}
    revision = _revision(files)
    return {'projectId': project.id, 'directory': str(root), 'repository': str(git.repo),
            'head': head, 'revision': revision, 'dirty': revision != metadata.get('revision'), 'commits': commits}


def history(project, action, context, message='', commit='', revision=''):
    if action not in ('status', 'snapshot', 'compare', 'restore'):
        raise CyToolError('InvalidParameters', 'Unknown history action.')
    with project.lock:
        root, _ = workspace.root_for(project)
        if project.dir.resolve().is_relative_to(root):
            raise CyToolError('InvalidParameters', 'Choose a source folder separate from the persistent analysis store.')
        git = Git(project, root, context, create=action == 'snapshot')
        current = _capture(root, context)
        if action == 'status':
            return _info(project, root, git, current)
        if action == 'snapshot':
            oid, created = _commit(git, root, current, message)
            return dict(_info(project, root, git, current), commit=oid, created=created)
        selected = git.files(commit, root)
        if action == 'compare':
            changes, remaining = [], 200000
            for name in sorted(current.keys() | selected.keys()):
                before, after = selected.get(name), current.get(name)
                if before == after:
                    continue
                if context:
                    context.check()
                binary, diff, truncated = False, '', False
                try:
                    a, b = (before or b'').decode('utf-8-sig'), (after or b'').decode('utf-8-sig')
                    binary = '\0' in a or '\0' in b
                    if not binary:
                        left, right = a[:200000].splitlines(True), b[:200000].splitlines(True)
                        truncated = len(a) > 200000 or len(b) > 200000 or len(left) > 4000 or len(right) > 4000
                        diff = ''.join(difflib.unified_diff(left[:4000], right[:4000], fromfile=name + ' @ ' + commit[:8], tofile=name + ' @ workspace'))
                except UnicodeDecodeError:
                    binary = True
                visible = diff[:remaining]
                remaining -= len(visible)
                changes.append({'path': name, 'kind': 'added' if before is None else 'deleted' if after is None else 'modified',
                                'binary': binary, 'diff': visible, 'truncated': truncated or len(visible) < len(diff)})
            return dict(_info(project, root, git, current), commit=commit, changes=changes)
        if revision != _revision(current):
            raise CyToolError('Conflict', 'Sources changed since the history preview. Compare again before restoring.')
        changed = [name for name in current.keys() | selected.keys() if current.get(name) != selected.get(name)]
        protected = {project.binary.resolve(), Path(project.meta()['sourcePath']).resolve()}
        if any(_path(root, name) in protected for name in changed):
            raise CyToolError('InvalidParameters', 'History cannot overwrite the original application.')
        for name in selected:
            path = _path(root, name)
            if path.is_dir() or any(parent.is_file() for parent in path.parents if parent.is_relative_to(root)):
                raise CyToolError('Conflict', 'A file/directory layout conflicts with this version. Move it before restoring.')
        # All paths/bytes have been validated. Keep current bytes in Git before changing any file.
        backup, _ = _commit(git, root, current, 'Before restoring ' + commit[:8])
        if _revision(_capture(root, context)) != revision:
            raise CyToolError('Conflict', 'Sources changed while preparing restoration. Compare again.')
        def write(name, raw):
            path = _path(root, name)
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    temporary.write_bytes(raw)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
        try:
            for name in sorted(changed):
                write(name, selected.get(name))
            oid, created = _commit(git, root, selected, 'Restore ' + commit[:8])
        except BaseException:
            for name in changed:
                write(name, current.get(name))
            raise
        (project.dir / 'workspace-build.json').unlink(missing_ok=True)
        return dict(_info(project, root, git, selected), commit=oid, created=created, backupCommit=backup,
                    workspace=workspace.state(project))


def matching_commit(project, source_directory, source_revision):
    """Link a receipt to an already saved version without invoking Git during publication."""
    if not source_directory or not source_revision:
        return ''
    root = Path(source_directory).resolve()
    rows = sorted((_folder(project, root) / 'commits').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in rows:
        if read_json(path, {}).get('sourceRevision') == source_revision:
            return path.stem
    return ''
