"""Exact-image biped physics wrapper and thread-local force scaling."""
from pathlib import Path
import json
import re

def apply(project):
    header=(Path(__file__).resolve().parents[1]/'native/rex_physics.h').as_posix()
    found=[]
    for path in (project/'generated/default').glob('*_recomp.*.cpp'):
        text=path.read_text(encoding='utf-8')
        needle='DEFINE_REX_FUNC(sub_82D36520) {\n\tREX_FUNC_PROLOGUE();'
        if needle not in text: continue
        before=text
        start=text.index(needle);end=text.find('\nDEFINE_REX_FUNC(',start+len(needle))
        if end<0:end=len(text)
        body=text[start:end]
        marker='\n\tif (XboxNativeBipedSubsteps(ctx, base)) return; // PC physics substeps'
        if needle+marker not in body:body=body.replace(needle,needle+marker)
        for site,offset in [('gravity',-23968),('ground force',3312)]:
            load=f'\t// lfs f0,{offset}(r11)\n'
            tail=f'\ttemp.u32 = REX_LOAD_U32(ctx.r11.u32 + {offset});\n\tctx.f0.f64 = double(temp.f32);'
            pattern=re.escape(load)+r'(?:\tctx\.fpscr\.disableFlushMode\(\);\n)?'+re.escape(tail)
            loads=[m.group() for m in re.finditer(pattern,body)]
            count=2 if site=='gravity' else 1
            if len(loads)!=count:raise ValueError(f'Changed verified biped {site} sites')
            hook='\n\tXboxNativeBipedForce(ctx); // thread-local substep acceleration'
            for load in set(loads):
                if (load+hook) not in body:body=body.replace(load,load+hook)
        if body.count('XboxNativeBipedForce(ctx);')!=3:raise ValueError('Expected three biped force hooks')
        text=text[:start]+body+text[end:]
        if text!=before:
            if f'#include "{header}"' not in text:text=f'#include "{header}"\n'+text
            path.write_text(text,encoding='utf-8',newline='\n')
        found.append(path.name)
    if len(found)!=1:raise ValueError('Expected exact biped physics kernel')
    (project/'physics-hooks.json').write_text(json.dumps(dict(function='0x82D36520',force_sites=['0x82D367A8','0x82D36C54','0x82D36C9C'],files=found),indent=2)+'\n',encoding='utf-8')
