"""CyDecompilator's own x86 / x86-64 / ARM64 C decompiler (see cydec/cdec).

Function discovery, call graph, strings and disassembly come from the built-in Capstone engine;
decompile() lifts the function to an IR, runs data flow, structures the control flow and prints C.
Ghidra stays first in the engine order when it is installed; this engine is the dependency-free
alternative and the source of module_c (recompilable C for a set of functions).
"""
from cytools_core import CyToolError

from .native import NativeEngine

SUPPORTED_ARCHES = ('x86', 'x86_64', 'arm64')
INLINE_GLOBAL_LIMIT = 256


class CDecompilerEngine(NativeEngine):
    id = 'cdec'
    name = 'CyDecompilator C (built-in)'
    license = 'GPL-3.0-only (CyDecompilator), BSD-3-Clause (Capstone)'
    url = ''
    description = ('Always available. In-house x86 / x86-64 / ARM64 decompiler for PE and ELF: data flow, '
                   'structured if/while/switch, SSE intrinsics, inlined constants. Output aims to '
                   'recompile; Ghidra remains the default when installed.')
    formats = ('pe', 'pe-dotnet', 'elf', 'raw')
    language = 'c'
    supports_decompile = True
    supports_disassemble = True

    _images = {}

    def _image(self, project):
        """The loaded binary, kept between requests (it carries the callee signature cache)."""
        try:
            key = (str(project.binary), project.binary.stat().st_mtime_ns)
        except OSError:
            return super()._image(project)
        image = self._images.get(key)
        if image is None:
            if len(self._images) >= 4:
                self._images.pop(next(iter(self._images)))
            image = self._images[key] = super()._image(project)
        return image

    def accepts(self, detect_record):
        return super().accepts(detect_record) and detect_record.get('arch') in SUPPORTED_ARCHES

    @staticmethod
    def _tables(analysis):
        functions = analysis.get('functions', [])
        names = {int(f['address'], 16): f['name'] for f in functions}
        return names, set(names)

    def _check(self, image):
        if image.arch not in SUPPORTED_ARCHES:
            raise CyToolError('Unsupported', 'The built-in C decompiler handles x86, x86-64 and ARM64 only '
                              '(this image is %s). Use Ghidra.' % image.arch)

    def decompile(self, project, analysis, function, context):
        from ..cdec.decompiler import decompile_detail, global_definitions
        image = self._image(project)
        self._check(image)
        names, starts = self._tables(analysis)
        if context is not None:
            context.progress(20, 'Lifting')
        text, callees, globals_used = decompile_detail(
            image, int(function['address'], 16), function['name'], names, starts,
            project.meta()['detect']['format'])
        header = []
        if globals_used:
            header.append('/* Globals read from the image */')
            small = {a: s for a, s in globals_used.items() if s <= INLINE_GLOBAL_LIMIT}
            header.extend(global_definitions(image, small))
            for address, size in sorted(globals_used.items()):
                if size > INLINE_GLOBAL_LIMIT:
                    header.append('extern byte DAT_%x[%d];' % (address, size))
            header.append('')
        return {'code': '\n'.join(header) + text, 'language': 'c'}

    def module_c(self, project, analysis, functions, include_callees=True, context=None):
        """One compilable C file for the given function records (and, optionally, their callees)."""
        from ..cdec.decompiler import module_source
        image = self._image(project)
        self._check(image)
        names, starts = self._tables(analysis)
        entries = [(int(f['address'], 16), f['name']) for f in functions]
        if context is not None:
            context.progress(10, 'Decompiling %d function(s)' % len(entries))
        return module_source(image, entries, names, starts, project.meta()['detect']['format'],
                             include_callees=include_callees)
