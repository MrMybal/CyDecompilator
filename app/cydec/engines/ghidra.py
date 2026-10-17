"""Ghidra engine: headless analysis and C decompilation through a Java export script.

`analyze` imports the file into a Ghidra project kept inside the CyDecompilator project,
runs the full auto-analysis, then CyExport.java writes the function list, call graph,
imports, strings and sections, and decompiles up to `maxDecompile` functions in the same
run. Functions beyond that limit (or whose decompilation timed out) are decompiled on
demand later with `-process -noanalysis`, which reuses the stored analysis.
"""
import os
import re
import shutil
import time
from pathlib import Path

from cytools_core import CyToolError

from .. import components, process
from ..paths import read_json
from .base import Engine

SCRIPTS = Path(__file__).with_name('ghidra_scripts')


def ghidra_name(display):
    """A symbol name Ghidra accepts: no whitespace or quotes; '::' keeps the namespace split."""
    if not display or display.startswith('`string'):
        return ''
    text = display.replace('{', '').replace('}', '').replace('`', '').replace("'", '')
    text = re.sub(r'\s+', '_', text.strip())
    return text


class GhidraEngine(Engine):
    id = 'ghidra'
    name = 'Ghidra'
    license = 'Apache-2.0'
    url = 'https://github.com/NationalSecurityAgency/ghidra'
    description = ('Full native decompiler (C pseudo-code) for PE, ELF, Mach-O and raw binaries '
                   'on x86, ARM, MIPS, PowerPC, RISC-V and more. Runs headless; needs Java 21+.')
    formats = ('pe', 'pe-dotnet', 'elf', 'macho', 'raw')
    components = ('ghidra', 'jdk')
    language = 'c'
    supports_decompile = True

    def availability(self):
        state = super().availability()
        jdk = components.locate('jdk')
        if jdk is not None and not jdk.get('javac'):
            state.update(available=False, missing=['jdk'],
                         detail='Ghidra compiles its scripts and needs a full JDK (javac); the '
                                'Java found is a runtime only. Install the jdk component.')
        return state

    def _environment(self):
        jdk = components.locate('jdk')
        java_bin = str(Path(jdk['java']).parent)
        return {'JAVA_HOME': jdk['path'], 'PATH': java_bin + os.pathsep + os.environ.get('PATH', ''),
}

    def _headless(self):
        return components.locate('ghidra')['headless']

    def _progress_parser(self, context, base, span):
        pattern = re.compile(r'CYPROGRESS (\w+) (\d+) (\d+)')

        def on_line(line):
            match = pattern.search(line)
            if match:
                phase, done, total = match.group(1), int(match.group(2)), max(int(match.group(3)), 1)
                if phase == 'decompile':
                    context.progress(base + span * done / total, 'Decompiling %d / %d' % (done, total))
                else:
                    context.progress(base, 'Exporting functions')
            elif 'ANALYZING all memory and code' in line or 'Analysis' in line and 'INFO' in line:
                context.progress(max(base - 30, 5), 'Ghidra auto-analysis')
        return on_line

    def analyze(self, project, context):
        self.require()
        started = time.monotonic()
        directory = project.engine_dir(self.id)
        gproj = directory / 'gproj'
        export = Path(context.workdir) / 'ghidra-export'
        shutil.rmtree(export, ignore_errors=True)
        export.mkdir(parents=True, exist_ok=True)
        gproj.mkdir(parents=True, exist_ok=True)
        max_decompile = int(context.options.get('maxDecompile', 2000))
        timeout = int(context.options.get('functionTimeout', 60))
        analysis_timeout = int(context.options.get('analysisTimeout', 3600))
        threads = max(1, (os.cpu_count() or 2) - 1)
        command = [self._headless(), str(gproj), 'cydec', '-import', str(project.binary), '-overwrite',
                   '-scriptPath', str(SCRIPTS), '-postScript', 'CyExport.java', str(export), 'all',
                   str(max_decompile), str(timeout), '-analysisTimeoutPerFile', str(analysis_timeout),
                   '-max-cpu', str(threads)]
        processor = context.options.get('processor')
        if processor:
            command += ['-processor', processor]
        symbol_status = ''
        if project.meta()['detect']['format'] in ('pe', 'pe-dotnet') and context.options.get('symbols', True):
            from .. import symbols as symbol_store
            context.progress(3, 'Debug symbols')
            loaded = symbol_store.for_project(project, context)
            symbol_status = loaded.get('status', '')
            if loaded.get('symbols'):
                names_file = Path(context.workdir) / 'symbols.tsv'
                with open(names_file, 'w', encoding='utf-8') as handle:
                    for symbol in loaded['symbols']:
                        name = ghidra_name(symbol.get('display') or symbol['name'])
                        if not name:
                            continue
                        handle.write('0x%x\t%s\t%s\n' % (symbol['va'], 'f' if symbol['kind'] == 'function' else 'd', name))
                command += ['-preScript', 'CyApplyNames.java', str(names_file)]
        context.progress(5, 'Ghidra import and auto-analysis')
        code, out, err = process.run(command, context=context, env=self._environment(),
                                     timeout=analysis_timeout + 3600, log_name='ghidra-analyze',
                                     on_line=self._progress_parser(context, 60, 35))
        program = read_json(export / 'program.json', None)
        if not isinstance(program, dict) or not isinstance(program.get('functions'), list) or not program.get('program'):
            hint = process.tail(out + '\n' + err, 30)
            raise CyToolError('EngineFailed', 'Ghidra did not produce an export (exit %s).\n%s' % (code, hint))
        context.progress(96, 'Storing results')
        functions = [f for f in program.get('functions', []) if not f.get('external')]
        code_dir = export / 'code'
        decompiled = 0
        for item in functions:
            item['hasCode'] = (code_dir / (item['id'] + '.c')).is_file()
            decompiled += item['hasCode']
        analysis = {'arch': program.get('program', {}).get('language', ''),
                    'program': program.get('program', {}), 'functions': functions,
                    'strings': program.get('strings', []), 'imports': program.get('imports', []),
                    'sections': program.get('sections', []), 'decompiledAtAnalysis': decompiled}
        messages = []
        if decompiled < len(functions):
            messages.append('%d of %d functions decompiled during analysis; the others are decompiled when '
                            'opened.' % (decompiled, len(functions)))
        if symbol_status:
            messages.append('Symbols: ' + symbol_status)
        analysis['message'] = ' '.join(messages)
        if project.meta()['detect']['format'] in ('pe', 'pe-dotnet'):
            try:
                from .. import pe_info
                analysis['pe'] = pe_info.analyse(project.binary)
            except Exception as exc:
                context.log('PE details unavailable: %s' % exc, 'Warning')
        analysis['_code'] = [(item['id'], (code_dir / (item['id'] + '.c')).read_text('utf-8', 'replace'))
                             for item in functions if item['hasCode']]
        return analysis

    def decompile(self, project, analysis, function, context):
        self.require()
        gproj = project.engine_dir(self.id) / 'gproj'
        if not (gproj / 'cydec.gpr').is_file():
            raise CyToolError('NotAnalyzed', 'The Ghidra project is missing; run analyze again.',
                              recoverable=True)
        export = Path(context.workdir) / 'ghidra-decompile'
        shutil.rmtree(export, ignore_errors=True)
        export.mkdir(parents=True, exist_ok=True)
        timeout = int(context.options.get('functionTimeout', 120))
        command = [self._headless(), str(gproj), 'cydec', '-process', project.binary.name,
                   '-noanalysis', '-readOnly', '-scriptPath', str(SCRIPTS),
                   '-postScript', 'CyExport.java', str(export), 'decompile', '0', str(timeout),
                   function['address']]
        context.progress(10, 'Ghidra decompiler')
        code, out, err = process.run(command, context=context, env=self._environment(),
                                     timeout=timeout + 600, log_name='ghidra-decompile')
        path = export / 'code' / (function['address'] + '.c')
        if path.is_file():
            return {'code': path.read_text('utf-8', 'replace'), 'language': 'c'}
        error = export / 'code' / (function['address'] + '.error.txt')
        if error.is_file():
            raise CyToolError('EngineFailed', 'Ghidra could not decompile %s: %s'
                              % (function['name'], error.read_text('utf-8', 'replace')))
        raise CyToolError('EngineFailed', 'Ghidra produced no output (exit %s).\n%s'
                          % (code, process.tail(out + '\n' + err, 20)))
