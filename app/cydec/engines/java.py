"""Java and Android engines: Vineflower for .class/.jar, JADX for .apk/.dex (and jars).

Both decompile the whole input once during analysis (they need the full class path to
resolve types), then every top-level class is a unit whose source is read from the
cache. `javap` from the JDK provides the bytecode view for Vineflower units.
"""
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from cytools_core import CyToolError

from .. import components, process
from .base import Engine


def _java(context):
    jdk, env = components.java_env()
    env['PATH'] = str(Path(jdk['java']).parent) + os.pathsep + os.environ.get('PATH', '')
    return jdk, env


def _collect_sources(root, project, engine_id, context, base=None):
    """Turn every .java file under `root` into a unit and cache its source."""
    files = sorted(Path(root).rglob('*.java'))
    functions = []
    contents = []
    for index, path in enumerate(files):
        if index % 200 == 0:
            context.check()
        relative = path.relative_to(base or root).as_posix()
        class_name = relative[:-5].replace('/', '.')
        package, _, short = class_name.rpartition('.')
        text = path.read_text('utf-8', 'replace')
        functions.append({'id': class_name, 'name': class_name, 'kind': 'class', 'parent': package,
                          'shortName': short, 'lines': text.count('\n') + 1, 'file': relative})
        contents.append((class_name, text))
    return functions, contents


class VineflowerEngine(Engine):
    id = 'vineflower'
    name = 'Vineflower'
    license = 'Apache-2.0'
    url = 'https://github.com/Vineflower/vineflower'
    description = 'Modern Java decompiler for .class files and .jar archives (Java 1.0 to 21+).'
    formats = ('java-class', 'jar')
    components = ('vineflower', 'jdk')
    language = 'java'
    supports_disassemble = True

    def analyze(self, project, context):
        self.require()
        started = time.monotonic()
        jdk, env = _java(context)
        jar = components.locate('vineflower')['jar']
        work = Path(context.workdir) / 'vineflower'
        shutil.rmtree(work, ignore_errors=True)
        source = work / 'input'
        source.mkdir(parents=True)
        binary = project.binary
        fmt = project.meta()['detect']['format']
        if fmt == 'java-class':
            # Vineflower needs the .class extension to recognise a lone class file.
            target = source / (binary.stem + '.class')
            shutil.copyfile(binary, target)
        else:
            target = source / (binary.stem + '.jar')
            shutil.copyfile(binary, target)
        output = work / 'output'
        output.mkdir()
        total = 1
        if fmt == 'jar':
            with zipfile.ZipFile(target) as archive:
                total = max(1, sum(1 for n in archive.namelist() if n.endswith('.class') and '$' not in n))
        counter = {'done': 0}

        def on_line(line):
            if 'Decompiling class' in line or 'Done: ' in line:
                counter['done'] += 1
                context.progress(5 + 85 * min(counter['done'], total) / total,
                                 'Decompiling %d / %d classes' % (min(counter['done'], total), total))

        threads = str(max(1, (os.cpu_count() or 2) - 1))
        code, out, err = process.run([jdk['java'], '-jar', jar, '--folder', '--log-level=info',
                                      '--thread-count=' + threads, str(target), str(output)],
                                     context=context, env=env, timeout=7200, log_name='vineflower',
                                     on_line=on_line)
        if code != 0:
            raise CyToolError('EngineFailed', 'Vineflower failed (exit %s): %s' % (code, process.tail(err or out, 10)))
        functions, contents = _collect_sources(output, project, self.id, context)
        if not functions:
            raise CyToolError('EngineFailed', 'Vineflower produced no Java source. %s' % process.tail(err or out, 10))
        analysis = {'functions': functions, 'strings': [], 'imports': [],
                    'message': '%d classes' % len(functions),
                    'seconds': round(time.monotonic() - started, 3)}
        analysis['_code'] = contents
        return analysis

    def decompile(self, project, analysis, function, context):
        text = project.cached_code(self.id, function['id'])
        if text is None:
            raise CyToolError('NotAnalyzed', 'Source of %s is missing; analyze again.' % function['id'],
                              recoverable=True)
        return {'code': text, 'language': 'java'}

    def disassemble(self, project, analysis, function, context):
        jdk, env = _java(context)
        javap = Path(jdk['java']).with_name('javap' + ('.exe' if os.name == 'nt' else ''))
        if not javap.is_file():
            raise CyToolError('MissingDependency', 'javap was not found next to java; install the jdk component.')
        fmt = project.meta()['detect']['format']
        if fmt == 'java-class':
            command = [javap, '-c', '-p', '-v', str(project.binary)]
        else:
            command = [javap, '-c', '-p', '-classpath', str(project.binary), function['id']]
        code, out, err = process.run(command, context=context, env=env, timeout=300, log_name='javap')
        if code != 0:
            raise CyToolError('EngineFailed', 'javap failed: ' + process.tail(err or out, 10))
        return {'code': out, 'language': 'jvm'}


class JadxEngine(Engine):
    id = 'jadx'
    name = 'JADX'
    license = 'Apache-2.0'
    url = 'https://github.com/skylot/jadx'
    description = 'Dex to Java decompiler: Android APK and DEX, also JAR/class. Decodes AndroidManifest.xml.'
    formats = ('apk', 'dex', 'jar', 'java-class')
    components = ('jadx', 'jdk')
    language = 'java'

    def analyze(self, project, context):
        self.require()
        started = time.monotonic()
        jdk, env = _java(context)
        jadx = components.locate('jadx')
        work = Path(context.workdir) / 'jadx'
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        fmt = project.meta()['detect']['format']
        extension = {'apk': '.apk', 'dex': '.dex', 'jar': '.jar', 'java-class': '.class'}[fmt]
        target = work / ('input' + extension)
        shutil.copyfile(project.binary, target)
        output = work / 'output'
        decode = bool(context.options.get('decodeResources', True)) and fmt == 'apk'
        threads = str(max(1, (os.cpu_count() or 2) - 1))
        command = [jdk['java'], '-Xmx' + str(context.options.get('javaHeapMb', 4096)) + 'm',
                   '-cp', jadx['classpath'], 'jadx.cli.JadxCLI', '-d', str(output),
                   '--show-bad-code', '-j', threads, '--log-level', 'progress']
        if not decode:
            command.append('--no-res')
        if context.options.get('deobfuscate'):
            command.append('--deobf')
        command.append(str(target))
        progress = re.compile(r'progress: (\d+) of (\d+)')

        def on_line(line):
            match = progress.search(line)
            if match:
                done, total = int(match.group(1)), max(int(match.group(2)), 1)
                context.progress(5 + 85 * done / total, 'Decompiling %d / %d classes' % (done, total))

        code, out, err = process.run(command, context=context, env=env, timeout=7200,
                                     log_name='jadx', on_line=on_line)
        sources = output / 'sources'
        if not sources.is_dir():
            raise CyToolError('EngineFailed', 'JADX produced no sources (exit %s): %s'
                              % (code, process.tail(err or out, 12)))
        functions, contents = _collect_sources(sources, project, self.id, context)
        manifest = output / 'resources' / 'AndroidManifest.xml'
        if manifest.is_file():
            text = manifest.read_text('utf-8', 'replace')
            functions.insert(0, {'id': 'AndroidManifest.xml', 'name': 'AndroidManifest.xml',
                                 'kind': 'resource', 'parent': '', 'lines': text.count('\n') + 1})
            contents.insert(0, ('AndroidManifest.xml', text))
        message = '%d classes' % len(functions)
        if code != 0:
            message += ' (JADX reported errors; some methods may be shown as bad code)'
        analysis = {'functions': functions, 'strings': [], 'imports': [], 'message': message,
                    'seconds': round(time.monotonic() - started, 3)}
        analysis['_code'] = contents
        return analysis

    def decompile(self, project, analysis, function, context):
        text = project.cached_code(self.id, function['id'])
        if text is None:
            raise CyToolError('NotAnalyzed', 'Source of %s is missing; analyze again.' % function['id'],
                              recoverable=True)
        return {'code': text, 'language': 'xml' if function['id'].endswith('.xml') else 'java'}
