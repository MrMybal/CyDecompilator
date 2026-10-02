"""Entry point: decompile one function (or a set of functions) of a loaded native image to C."""
from pathlib import Path

from cytools_core import CyToolError

from .cgen import HEADER, Generator
from .dataflow import Program
from .lifter import Image, lift_function


def convention_for(native_image, file_format):
    if native_image.arch == 'arm64':
        return 'aapcs64'
    if native_image.bits == 32:
        return 'x86'
    return 'win64' if file_format in ('pe', 'pe-dotnet') else 'sysv'


def decompile_detail(native_image, start, name, names, function_starts, file_format, cache=None, strict=False,
                     refs=None, arity=None, loose_calls=()):
    """(C text, called function addresses, globals {address: bytes used}).

    strict: module output (see Generator). refs, when given, collects what the text refers to:
    'imports' (set of names), 'globals' and 'code' ({address: C name})."""
    convention = convention_for(native_image, file_format)
    image = Image(native_image, names, function_starts)
    if cache is None:
        # Callee prototypes are facts of the binary: keep them with the loaded image so the next
        # function does not lift the same callees again.
        cache = native_image.__dict__.setdefault('cdec_signatures', {})
    image.signatures = cache
    lifted = lift_function(image, start, convention)
    program = Program(lifted).run()
    generator = Generator(program, name, lifted.word, names, strict=strict, arity=arity, loose_calls=loose_calls)
    note = 'CyDecompilator C (%s, %s)' % (native_image.arch, convention)
    if lifted.unsupported:
        note += '; %d instruction(s) not modelled, see comments' % len(lifted.unsupported)
    text = generator.generate(note)
    if cache is not None:
        # The prototype just printed is the one callers must use.
        from .lifter import signature_of
        cache[start] = signature_of(generator)
    if refs is not None:
        refs.setdefault('imports', set()).update(generator.imports)
        refs.setdefault('globals', {}).update(generator.global_names)
        refs.setdefault('code', {}).update(generator.code_refs)
    callees = sorted({c.target.address for c in lifted.calls
                      if getattr(c.target, 'kind', '') == 'code' and image.executable(getattr(c.target, 'address', 0))})
    return text, callees, dict(generator.globals)


def decompile(native_image, start, name, names, function_starts, file_format):
    return decompile_detail(native_image, start, name, names, function_starts, file_format)[0]


def global_definitions(native_image, globals_used, global_names=None):
    """`byte DAT_x[n] = {...};` initialised from the image; overlapping ranges are merged and
    inner addresses become macros on the enclosing array so aliasing is preserved."""
    ranges = []
    for address, size in sorted(globals_used.items()):
        size = max(size, 1)
        if ranges and address <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], address + size)
            ranges[-1][2].append(address)
        else:
            ranges.append([address, address + size, [address]])
    lines = []
    for start, end, members in ranges:
        length = end - start
        seg = native_image.data_segment(start)
        raw = native_image.read(start, length) if seg is not None else b''
        raw = raw + b'\0' * (length - len(raw))
        body = ', '.join('0x%02x' % b for b in raw) if any(raw) else '0'
        name_of = (global_names or {}).get
        lines.append('byte %s[%d] = {%s};' % (name_of(start, 'DAT_%x' % start), length, body))
        for member in members:
            if member != start:
                lines.append('#define %s (%s + %d)' % (name_of(member, 'DAT_%x' % member),
                                                       name_of(start, 'DAT_%x' % start), member - start))
    return lines


_RESERVED = []


def reserved_names():
    """Names the included headers already declare: module functions and globals must avoid them."""
    if not _RESERVED:
        path = Path(__file__).with_name('reserved_names.txt')
        _RESERVED.append({line.strip() for line in path.read_text(encoding='utf-8').splitlines()
                          if line.strip() and not line.startswith('#')})
    return _RESERVED[0]


def module_source(native_image, entries, names, function_starts, file_format, export_prefix='', include_callees=True):
    """A compilable C file: header, globals, prototypes, then every function (and its callees).

    entries: list of (address, name). Callees without a name are named FUN_<address>.
    """
    reserved = reserved_names()
    names = {address: name + '_' if name in reserved else name for address, name in names.items()}
    entries = [(address, name + '_' if name in reserved else name) for address, name in entries]
    function_starts = set(function_starts)
    cache = {}
    # Calls are lifted against callee prototypes; a callee's final prototype can differ from the
    # one inferred while lifting its callers, so passes repeat until the prototypes are stable.
    def arity_of(address):
        entry = cache.get(address)
        if not entry:
            return None
        return len(entry[1]) + (len(entry[5]) if len(entry) > 5 else entry[0])
    arity, unstable = {}, set()
    for attempt in range(8):
        done, order, globals_used, refs, failed = _module_pass(native_image, entries, names, function_starts,
                                                               file_format, include_callees, cache, arity, unstable)
        final = {address: arity_of(address) for address in order if arity_of(address) is not None}
        # Calls of this pass used `arity`; the printed prototypes have `final`.
        changed = {address for address, count in final.items() if arity.get(address, count) != count}
        if attempt and not changed - unstable:
            break
        # Prototypes that still move from pass to pass are called unprototyped, so the module
        # compiles whatever their final parameter count.
        if attempt >= 2:
            unstable |= changed
        arity = final
    prototypes = []
    bodies = []
    for address in order:
        text = done[address]
        lines = text.split('\n')
        signature = next(line for line in lines if not line.startswith('/*'))
        prototypes.append(export_prefix + signature + ';')
        bodies.append(text.replace(signature, export_prefix + signature, 1))
    # Imported functions are reached through their import pointer (__imp_X, resolved by the
    # import library at link time), which never clashes with a header declaration.
    externs = ['extern code *__imp_%s;' % name for name in sorted(refs.get('imports', ()))]
    # Functions referenced but not decompiled here (outside the module, or not decodable).
    externs += ['extern code %s;' % name for address, name in sorted(refs.get('code', {}).items())
                if address not in done]
    notes = ['/* not decompiled: %s */' % ', '.join('%s (%s)' % item for item in failed)] if failed else []
    parts = [HEADER] + notes + global_definitions(native_image, globals_used, refs.get('globals')) + [''] + \
        externs + prototypes + [''] + bodies
    return '\n'.join(parts)


def _module_pass(native_image, entries, names, function_starts, file_format, include_callees, cache, arity,
                 unstable=()):
    pending = list(entries)
    done = {}
    order = []
    globals_used = {}
    refs = {}
    failed = []
    while pending:
        address, name = pending.pop(0)
        if address in done or any(address == f[2] for f in failed):
            continue
        try:
            text, callees, used = decompile_detail(native_image, address, name, names, function_starts, file_format,
                                                   cache, strict=True, refs=refs, arity=arity,
                                                   loose_calls=unstable)
        except CyToolError as exc:
            failed.append((name, exc.message if hasattr(exc, 'message') else str(exc), address))
            continue
        done[address] = text
        order.append(address)
        for key, size in used.items():
            globals_used[key] = max(globals_used.get(key, 0), size)
        if include_callees:
            for callee in callees:
                if callee not in done:
                    names.setdefault(callee, 'FUN_%x' % callee)
                    function_starts.add(callee)
                    pending.append((callee, names[callee]))
    return done, order, globals_used, refs, [(name, message) for name, message, _ in failed]
