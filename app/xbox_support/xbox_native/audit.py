"""Evidence from emitted C++ and the original mapped image. No reachability guesses."""
from __future__ import annotations

import bisect
from collections import Counter
import json
from pathlib import Path
import re
import struct
import uuid

from .backend import workspace
from .disc import sha256, write_json
from .formats import FormatError, span


class FunctionIndex:
    def __init__(self, image: bytes, metadata: dict):
        self.functions=[]
        for section in metadata['sections']:
            if section['name']!='.pdata':
                continue
            data=span(image,section['address']-metadata['image_base'],section['size'])
            if len(data)%8:
                raise FormatError('Malformed .pdata table')
            for address,packed in struct.iter_unpack('>II',data):
                length=((packed>>8)&0x3FFFFF)*4
                if length:
                    self.functions.append(dict(address=address,size=length,exception_flag=bool(packed>>31)))
        self.functions.sort(key=lambda f:f['address'])
        self.starts=[f['address'] for f in self.functions]

    def find(self,address):
        index=bisect.bisect_right(self.starts,address)-1
        if index>=0:
            fn=self.functions[index]
            if address<fn['address']+fn['size']:
                return fn
        return None


def read_word(image: bytes, metadata: dict, address: int) -> int | None:
    for s in metadata['sections']:
        if s['executable'] and s['address']<=address and address+4<=s['address']+s['size']:
            offset=address-metadata['image_base']
            return struct.unpack('>I',span(image,offset,4))[0]
    return None


def scan_sources(generated: Path):
    guards=[]
    direct_traps=[]
    definitions=[]
    for path in sorted(generated.glob('*.cpp')):
        function, instruction=None,None
        for line_number,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
            match=re.search(r'PPC_FUNC_IMPL\((\w+)\)',line)
            if match:
                function=match[1]
                definitions.append(dict(name=function,file=path.name,line=line_number))
            if line.lstrip().startswith('// '):
                instruction=line.strip()[3:]
            for macro,kind in (('PPC_UNSUPPORTED_INSTRUCTION','unsupported-instruction'),('PPC_UNRESOLVED_BRANCH','unresolved-branch')):
                match=re.search(macro+r'\(0x([0-9A-Fa-f]+)u,\s*0x([0-9A-Fa-f]+)u\)',line)
                if match:
                    a,b=(int(x,16) for x in match.groups())
                    guards.append(dict(kind=kind,pc=a,value=b,function=function,file=path.name,line=line_number,instruction=instruction))
            if re.search(r'__builtin_(?:debugtrap|trap)\s*\(|__debugbreak\s*\(',line):
                direct_traps.append(dict(function=function,file=path.name,line=line_number,instruction=instruction))
    return guards,direct_traps,definitions


def audit(path: Path) -> dict:
    root,_,report=workspace(path,'xbox360')
    translation=json.loads((root/'latest-translation.json').read_text(encoding='utf-8'))
    probe=json.loads((root/'latest-probe.json').read_text(encoding='utf-8'))
    if any(r['executable_sha256']!=report['sha256'] for r in (translation,probe)):
        raise FormatError('Analysis artifacts do not match the executable')
    generated=Path(translation['generated_directory']).resolve(strict=True)
    image_path=Path(probe['image']).resolve(strict=True)
    metadata_path=Path(probe['metadata']).resolve(strict=True)
    if any(root not in p.parents for p in (generated,image_path,metadata_path)):
        raise FormatError('Analysis artifacts must be inside the workspace')
    if sha256(image_path)!=probe['image_sha256']:
        raise FormatError('Mapped image changed since the probe')
    image=image_path.read_bytes()
    metadata=json.loads(metadata_path.read_text(encoding='utf-8'))
    index=FunctionIndex(image,metadata)
    guards,traps,definitions=scan_sources(generated)
    branches,unsupported=[],[]
    for guard in guards:
        source_fn=index.find(guard['pc'])
        item=dict(**guard,source_pdata=source_fn)
        if guard['kind']=='unresolved-branch':
            target_fn=index.find(guard['value'])
            item.update(target_pdata=target_fn,target_word=read_word(image,metadata,guard['value']))
            item['category']='same-pdata' if source_fn and source_fn==target_fn else 'other-pdata' if target_fn else 'no-target-pdata'
            branches.append(item)
        else:
            item['category']='zero-word' if guard['value']==0 else 'nonzero-word'
            item['matches_image']=read_word(image,metadata,guard['pc'])==guard['value']
            unsupported.append(item)
    result=dict(schema_version=1,status='audited',native_game_ready=False,executable_sha256=report['sha256'],
                generated_directory=str(generated),function_definitions=len(definitions),
                unresolved_branch_count=len(branches),unresolved_unique_targets=len({b['value'] for b in branches}),
                branch_categories=dict(Counter(b['category'] for b in branches)),
                branches_in_exception_functions=sum(bool(b['source_pdata'] and b['source_pdata']['exception_flag']) for b in branches),
                unsupported_instruction_count=len(unsupported),unsupported_categories=dict(Counter(i['category'] for i in unsupported)),
                direct_trap_count=len(traps),direct_trap_mnemonics=dict(Counter((i['instruction'] or '').split(' ')[0] for i in traps)),
                branches=branches,unsupported_instructions=unsupported,direct_traps=traps,
                note='Static sites, including padding and embedded data. Counts do not prove runtime reachability; exception flags describe original .pdata records.')
    out=root/'runs'/('audit-'+uuid.uuid4().hex[:12]);out.mkdir(parents=True)
    write_json(out/'receipt.json',result)
    summary={k:v for k,v in result.items() if k not in ('branches','unsupported_instructions','direct_traps')}
    summary['detail_file']=str(out/'receipt.json')
    write_json(root/'latest-audit.json',summary)
    return summary
