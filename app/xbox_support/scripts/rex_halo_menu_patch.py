"""Route native mouse events through Halo's existing GFx UI thread."""
import hashlib
import json
from pathlib import Path


def apply(project):
    header = (Path(__file__).resolve().parents[1] / 'native/rex_menu_bridge.h').as_posix()
    target = 'DEFINE_REX_FUNC(sub_822CB8C8) {\n\tREX_FUNC_PROLOGUE();'
    patched = target + '\n\tXboxNativeGfxAdvance(ctx, base); // local mouse bridge before GFx Advance'
    found = []
    for path in (project / 'generated/default').glob('*_recomp.*.cpp'):
        text = path.read_text(encoding='utf-8')
        if target not in text:
            continue
        if patched not in text:
            if text.count(target) != 1:
                raise ValueError('Expected one verified GFx Advance')
            text = f'#include "{header}"\n' + text.replace(target, patched)
            path.write_text(text, encoding='utf-8', newline='\n')
        guard = '\n\tXboxNativeMapAdvance native_map_advance{ctx, base}; // after GFx Advance, outside Blam update'
        if guard not in text:
            text = text.replace(patched, patched + guard)
            path.write_text(text, encoding='utf-8', newline='\n')
        found.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if len(found) != 1:
        raise ValueError('Expected one GFx Advance hook')
    # The normal game code has already applied the controller curve and time
    # step here. Add relative mouse angles only on its two enabled-input paths.
    look_sites = ('\t// b 0x82c6eaac\n\tgoto loc_82C6EAAC;',)
    look_files = []
    for path in (project / 'generated/default').glob('*_recomp.*.cpp'):
        text = path.read_text(encoding='utf-8')
        if 'DEFINE_REX_FUNC(sub_82C6E3F8)' not in text:
            continue
        marker = '\tXboxNativePlayerLook(ctx, base); // direct PC mouse angles\n'
        needle = look_sites[0]
        if text.count(needle) != 2:
            raise ValueError('Expected exactly two enabled Halo look paths')
        if marker not in text:
            text = f'#include "{header}"\n' + text.replace(needle, marker + needle)
            path.write_text(text, encoding='utf-8', newline='\n')
        if text.count(marker) != 2:
            raise ValueError('Expected exactly two native look hooks')
        look_files.append(path.name)
    if len(look_files) != 1:
        raise ValueError('Expected one Halo player-control function')
    sprint_counts = []
    for path in (project / 'generated/default').glob('*_recomp.*.cpp'):
        text = path.read_text(encoding='utf-8'); before = text
        for address in ('82D38B68', '82D39F10'):
            start = text.find(f'DEFINE_REX_FUNC(sub_{address}) {{')
            if start < 0: continue
            end = text.find('\nDEFINE_REX_FUNC(', start + 1)
            if end < 0: end = len(text)
            body = text[start:end]
            needle = '\t// lfs f31,108(r8)\n\tctx.fpscr.disableFlushMode();\n\ttemp.u32 = REX_LOAD_U32(ctx.r8.u32 + 108);\n\tctx.f31.f64 = double(temp.f32);'
            marker = '\n\tXboxNativeSprintSpeed(ctx, base); // local biped desired velocity only'
            if body.count(needle) != 1: raise ValueError('Changed verified biped speed load')
            if needle + marker not in body: body = body.replace(needle, needle + marker)
            text = text[:start] + body + text[end:]
            sprint_counts.append(address)
        if text != before:
            if f'#include "{header}"' not in text: text = f'#include "{header}"\n' + text
            path.write_text(text, encoding='utf-8', newline='\n')
    if len(sprint_counts) != 2: raise ValueError('Missing verified biped speed functions')
    hooks = {
        '8234E3D8': 'XboxNativeObserveCampaignLaunch(ctx, base);',
        '8247B1C8': 'XboxNativeSaberMapArgument(ctx, base);',
        '822CD790': 'XboxNativeSkipTick(ctx, base);',
        '823309A8': 'XboxNativeSleepProbe(ctx, base);',
        '826B24A0': 'XboxNativeVideoSettingsGuard native_video{ctx.r3.u32, base};',
        '82ADA198': 'XboxNativeGfxProcessMouse(ctx, base);',
        '82ACEE48': 'if (XboxNativeMenuOwnsMouse(ctx, base)) return; // reserve physical PC cursor',
        '82ACE988': 'if (XboxNativeIgnoreGuestMouse(ctx, base)) { ctx.r3.u64 = 3; return; } // PC mouse owns menus',
    }
    counts = dict.fromkeys(hooks, 0)
    pacing_files = []
    for path in (project / 'generated/default').glob('*_recomp.*.cpp'):
        text = path.read_text(encoding='utf-8'); before = text
        text = text.replace('\tXboxNativeUiTick(ctx, base);\n', '')
        for address, call in hooks.items():
            target = f'DEFINE_REX_FUNC(sub_{address}) {{\n\tREX_FUNC_PROLOGUE();'
            if target not in text: continue
            counts[address] += 1
            if target + '\n\t' + call not in text:
                text = text.replace(target, target + '\n\t' + call)
        if 'DEFINE_REX_FUNC(sub_823D7150)' in text:
            pacing_files.append(path.name)
            start = text.index('DEFINE_REX_FUNC(sub_823D7150)')
            end = text.find('\nDEFINE_REX_FUNC(', start + 1)
            if end < 0: end = len(text)
            body = text[start:end]
            for needle in ('\t// fcmpu cr6,f13,f0\n\tctx.cr6.compare(ctx.f13.f64, ctx.f0.f64);\n\t// bge cr6,0x823d7204', '\t// stfs f0,23660(r10)\n'):
                marker = '\tXboxNativeFramePacing(ctx); // PC presentation wait only\n'
                if marker + needle not in body:
                    if body.count(needle) != 1: raise ValueError('Changed Halo frame pacer')
                    body = body.replace(needle, marker + needle)
            if body.count('XboxNativeFramePacing(ctx);') != 2:
                raise ValueError('Expected exactly two presentation wait hooks')
            text = text[:start] + body + text[end:]
        if text != before:
            if f'#include "{header}"' not in text: text = f'#include "{header}"\n' + text
            path.write_text(text, encoding='utf-8', newline='\n')
    if any(n != 1 for n in counts.values()): raise ValueError('Missing verified PC hook')
    if len(pacing_files) != 1: raise ValueError('Expected one Halo presentation limiter')
    for item in found:
        item['sha256'] = hashlib.sha256((project / 'generated/default' / item['file']).read_bytes()).hexdigest()
    (project / 'menu-bridge.json').write_text(json.dumps(dict(
        advance='0x822CB8C8', handle_event='0x82ACE988', root_vtable='0x82006680',
        input_record_bytes=24, files=found, look_sites=['0x82C6E9A4', '0x82C6EAA0'],
        look_files=look_files, frame_pacer='0x823D7150', pacing_files=pacing_files,
        virtual_mouse_filters=['0x82ACEE48', '0x82ACE988']), indent=2) + '\n', encoding='utf-8')
