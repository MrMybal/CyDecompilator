"""Exact-image hooks on Halo's render-only matrix exports."""
import hashlib
import json
from pathlib import Path


def apply(project):
    header = (Path(__file__).resolve().parents[1] / 'native/rex_animation.h').as_posix()
    hooks = {'82C54908': 'XboxNativePoseExport native_pose_export{ctx, base, false};',
             '82C547F0': 'XboxNativePoseExport native_pose_export{ctx, base, true};',
             '82D14D80': 'XboxNativeFirstPersonPose native_fp_pose{ctx, base};',
             '82CB5688': 'XboxNativeClassicDraw native_classic_draw{ctx};',
             '822DFBF0': 'XboxNativeClassicNodes native_classic_nodes{ctx, base};',
             '822CAB58': 'XboxNativeCinematicCamera native_cinematic_camera{ctx, base};'}
    counts = dict.fromkeys(hooks, 0)
    files = []
    for path in (project / 'generated/default').glob('*_recomp.*.cpp'):
        text = path.read_text(encoding='utf-8'); before = text
        for address, call in hooks.items():
            needle = f'DEFINE_REX_FUNC(sub_{address}) {{\n\tREX_FUNC_PROLOGUE();'
            if needle not in text: continue
            counts[address] += 1
            hook = '\n\t' + call
            if needle + hook not in text: text = text.replace(needle, needle + hook)
        if text != before:
            if f'#include "{header}"' not in text: text = f'#include "{header}"\n' + text
            path.write_text(text, encoding='utf-8', newline='\n')
        if any(call in text for call in hooks.values()):
            files.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if any(n != 1 for n in counts.values()): raise ValueError('Missing verified Halo pose export')
    (project / 'animation-hooks.json').write_text(json.dumps(dict(hooks=hooks, files=files), indent=2)+'\n', encoding='utf-8')
