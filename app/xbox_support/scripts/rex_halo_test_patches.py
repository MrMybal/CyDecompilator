"""Optional local mission-selection unlock for the exact Halo recompile.

The IsMapUnlocked callback reads a ten-bit mask at this+0x14 after looking up a
map name in the ten-entry table at 0x8343339C. Only that mask is overridden.
Campaign completion, achievements, original XEX and original archive are untouched.
"""
import hashlib
import json
from pathlib import Path

from rex_guard_branches import HALO_SHA


def apply(project, executable_sha256):
    if executable_sha256 != HALO_SHA:
        raise ValueError('Mission patch requires the exact supported Halo executable')
    old = 'ctx.r11.u64 = REX_LOAD_U16(ctx.r28.u32 + 20);'
    new = ('ctx.r11.u64 = REX_LOAD_U16(ctx.r28.u32 + 20);\n'
           '\t// Local test option: ten selectable maps, independent of completion records.\n'
           '\tif (rex::cvar::GetFlagByName("halo_test_unlock_missions") == "true") ctx.r11.u64 |= 0x3FF;')
    hits = []
    for path in (project / 'generated/default').glob('*_recomp.*.cpp'):
        content = path.read_text(encoding='utf-8')
        start = content.find('DEFINE_REX_FUNC(sub_8236A380) {')
        if start < 0:
            continue
        end = content.find('\nDEFINE_REX_FUNC(', start + 1)
        if end < 0:
            end = len(content)
        function = content[start:end]
        if new not in function:
            if function.count(old) != 1:
                raise ValueError('IsMapUnlocked instruction context changed')
            content = content[:start] + function.replace(old, new) + content[end:]
            content = '#include <rex/cvar.h>\n' + content
            path.write_text(content, encoding='utf-8', newline='\n')
        hits.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if len(hits) != 1:
        raise ValueError('Expected exactly one IsMapUnlocked callback')
    (project / 'test-patches.json').write_text(json.dumps(dict(
        executable_sha256=HALO_SHA, callback='0x8236A380', mask='0x3FF',
        option='halo_test_unlock_missions', files=hits), indent=2) + '\n', encoding='utf-8')
