"""ILSpy engine: C# source and IL for .NET assemblies through ilspycmd.

Units are types (classes, interfaces, structs, delegates, enums) as listed by `-l cisde`.
Each type is decompiled on demand with `-t` and cached; `-il` gives its IL listing.
The ilspycmd package targets a specific .NET major version; DOTNET_ROLL_FORWARD=Major
lets a newer installed runtime run it.
"""
import re
import time
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from cytools_core import CyToolError

from .. import components, process
from .base import Engine

KINDS = {'Class': 'class', 'Interface': 'interface', 'Struct': 'struct', 'Delegate': 'delegate',
         'Enum': 'enum'}


class IlspyEngine(Engine):
    id = 'ilspy'
    name = 'ILSpy'
    license = 'MIT'
    url = 'https://github.com/icsharpcode/ILSpy'
    description = '.NET decompiler: readable C# for every type of a managed assembly, plus IL.'
    formats = ('pe-dotnet',)
    components = ('ilspycmd', 'dotnet')
    language = 'csharp'
    supports_decompile = True
    supports_disassemble = True

    def _command(self, *arguments):
        dotnet = components.locate('dotnet')
        ilspy = components.locate('ilspycmd')
        return [dotnet['dotnet'], ilspy['dll'], '--disable-updatecheck', *arguments]

    @staticmethod
    def _env():
        return {'DOTNET_ROLL_FORWARD': 'Major', 'DOTNET_CLI_TELEMETRY_OPTOUT': '1',
                'DOTNET_NOLOGO': '1'}

    def analyze(self, project, context):
        self.require()
        started = time.monotonic()
        context.progress(10, 'Listing types')
        code, out, err = process.run(self._command('-l', 'cisde', str(project.binary)),
                                     context=context, env=self._env(), timeout=600,
                                     log_name='ilspy-list')
        if code != 0:
            raise CyToolError('EngineFailed', 'ilspycmd failed (exit %s): %s'
                              % (code, process.tail(err or out, 10)))
        functions = []
        for line in out.splitlines():
            match = re.match(r'(\w+)\s+(.+)$', line.strip())
            if not match or match.group(1) not in KINDS:
                continue
            full = match.group(2).strip()
            if full == '<Module>':
                continue
            namespace, _, short = full.rpartition('.')
            functions.append({'id': full, 'name': full, 'kind': KINDS[match.group(1)],
                              'parent': namespace, 'shortName': short})
        context.progress(60, 'Listing resources')
        code, out, _ = process.run(self._command('--list-resources', str(project.binary)),
                                   context=context, env=self._env(), timeout=300,
                                   log_name='ilspy-resources')
        resources = [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []
        return {'functions': functions, 'resources': resources, 'strings': [], 'imports': [],
                'seconds': round(time.monotonic() - started, 3),
                'message': '%d types' % len(functions)}

    def decompile(self, project, analysis, function, context):
        self.require()
        code, out, err = process.run(self._command('-t', function['id'], str(project.binary)),
                                     context=context, env=self._env(), timeout=600,
                                     log_name='ilspy-type')
        if code != 0 and not out.strip():
            raise CyToolError('EngineFailed', 'ilspycmd could not decompile %s: %s'
                              % (function['id'], process.tail(err, 10)))
        return {'code': out, 'language': 'csharp'}

    def disassemble(self, project, analysis, function, context):
        self.require()
        code, out, err = process.run(self._command('-il', '-t', function['id'], str(project.binary)),
                                     context=context, env=self._env(), timeout=600,
                                     log_name='ilspy-il')
        if code != 0 and not out.strip():
            raise CyToolError('EngineFailed', 'ilspycmd could not produce IL for %s: %s'
                              % (function['id'], process.tail(err, 10)))
        return {'code': out, 'language': 'il'}

    def export_project(self, project, destination, context, language_version=''):
        """Write a compilable C# project (csproj + one file per type) into `destination`."""
        self.require()
        arguments = ['-p', '-o', str(destination)]
        if language_version:
            arguments += ['--languageversion', language_version]
        original_folder = Path(project.meta().get('sourcePath') or str(project.binary)).parent
        if original_folder.is_dir() and original_folder.resolve() != project.binary.parent.resolve():
            arguments += ['--referencepath', str(original_folder)]
        code, out, err = process.run(self._command(*arguments, str(project.binary)),
                                     context=context, env=self._env(), timeout=3600,
                                     log_name='ilspy-project')
        if code != 0:
            raise CyToolError('EngineFailed', 'ilspycmd project export failed: %s'
                              % process.tail(err or out, 10))
        # ILSpy resolves metadata through --referencepath but does not always emit
        # usable HintPaths. Keep local dependencies with the reconstructed project.
        for csproj in Path(destination).glob('*.csproj'):
            tree = ET.parse(csproj)
            for reference in tree.getroot().iter('Reference'):
                name = reference.get('Include', '').split(',')[0]
                if Path(name).name != name or not name:
                    continue
                dependency = original_folder / (name + '.dll')
                if not dependency.is_file() or dependency.resolve() == Path(project.meta().get('sourcePath', '')).resolve():
                    continue
                folder = Path(destination) / 'references'
                folder.mkdir(exist_ok=True)
                shutil.copyfile(dependency, folder / dependency.name)
                hint = reference.find('HintPath')
                if hint is None:
                    hint = ET.SubElement(reference, 'HintPath')
                hint.text = 'references/' + dependency.name
                private = reference.find('Private')
                if private is None:
                    private = ET.SubElement(reference, 'Private')
                private.text = 'true'
            tree.write(csproj, encoding='utf-8', xml_declaration=True)
        return destination
