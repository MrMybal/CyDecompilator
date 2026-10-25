"""Opt-in, real backend smoke test on a generated, owned PS5 ELF fixture.

Uses configured engines; --install-anyps5 / --install-ultrapack download official
tools first. Does not test commercial games, GPU translation or console APIs.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cydec import porting,porting_analysis,process,service
from cydec.paths import REPORTS,write_json
from cydec.project import ProjectStore
from cydec.engines.base import EngineContext


def own_elf():
    image=bytearray(0x4000)
    struct.pack_into('<16sHHIQQQIHHHHHH',image,0,b'\x7fELF\x02\x01\x01'+bytes(9),0xfe10,62,1,
                     0x401000,64,0,0,64,56,3,0,0,0)
    dynamic=[(5,0x403000),(10,1),(6,0x403010),(11,24),(4,0x403100),
             (7,0x403080),(8,0),(9,24),(23,0x403080),(2,0),(20,7),(3,0x403180),(0x6100003F,24),(0,0)]
    for i,values in enumerate([(1,7,0,0x400000,0x400000,len(image),len(image),0x1000),
                              (2,6,0x2000,0x402000,0x402000,len(dynamic)*16,len(dynamic)*16,8),
                              (0x61000000,4,0x3000,0,0,512,512,1)]):
        struct.pack_into('<IIQQQQQQ',image,64+i*56,*values)
    for i,values in enumerate(dynamic):struct.pack_into('<QQ',image,0x2000+i*16,*values)
    struct.pack_into('<IIII',image,0x3100,1,1,0,0)
    image[0x1000:0x1003]=b'\x31\xc0\xc3'  # return 0, no imported APIs
    return bytes(image)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-anyps5',action='store_true')
    parser.add_argument('--install-ultrapack',action='store_true')
    parser.add_argument('--build-pkg-helper',action='store_true')
    parser.add_argument('--pfs',action='store_true',help='Build and import an owned, unencrypted PFS container.')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--diagnostics',action='store_true',help='Enable Windows startup diagnostics.')
    parser.add_argument('--trace-imports',action='store_true',help='Instrument imports; requires libc.prx among guest library dependencies.')
    parser.add_argument('--syscall-check',action='store_true',help='Verify a real converter rejection and map it to guest C/assembly; never run the syscall fixture.')
    args=parser.parse_args()
    base=REPORTS/'porting-verification'/uuid.uuid4().hex[:12]
    base.mkdir(parents=True)
    context=EngineContext(workdir=base/'work',log=lambda message,*a:print(message,flush=True))
    target='windows' if os.name=='nt' else 'linux'
    if args.install_anyps5:porting.install_anyps5(target,context)
    if args.install_ultrapack:porting.install_ultrapack(context,args.build_pkg_helper)
    source=base/'original';source.mkdir()
    fixture=own_elf()
    if args.syscall_check:
        fixture=bytearray(fixture)
        fixture[0x1000:0x1008]=b'\xb8\x3c\0\0\0\x0f\x05\xc3'
        fixture=bytes(fixture)
    (source/'eboot.bin').write_bytes(fixture)
    (source/'resource.txt').write_text('owned resource\n',encoding='utf-8')
    input_path=source
    if args.pfs:
        config=porting.tools()['settings']
        cli=Path(config['ultrapackCli'])
        code,out,err=process.run([config['ultrapackPython'],'-m','mkpfs','pack','folder',str(source),
            str(base/'own.ffpfsc'),'--raw','--no-compress'],cwd=cli.parent,context=context,
            timeout=60,own_children=True,log_name='pfs-fixture')
        if code:raise RuntimeError(out+'\n'+err)
        input_path=base/'own.ffpfsc'
    store=ProjectStore(base/'projects')
    service.store=store
    opened=porting.open_input(store,input_path,context)
    assert (Path(opened['directory'])/opened['entry']).read_bytes()==fixture
    assert (Path(opened['directory'])/'resource.txt').read_text()=='owned resource\n'
    write_json(base/'input.json',opened)
    if args.prepare_only:
        print(json.dumps({'status':'prepared','report':str(base/'input.json')}))
        return
    project=store.get(opened['projectId'])
    converted=porting.convert(project,target,context,standalone=True,
        diagnostics=args.diagnostics,trace_imports=args.trace_imports)
    write_json(base/'conversion.json',converted)
    if args.syscall_check:
        assert converted['status']=='conversion-failed',converted
        diagnosis=converted['diagnosis']
        write_json(base/'diagnosis.json',diagnosis)
        errors=[r for r in diagnosis['findings'] if r['kind']=='converter-syscall']
        assert errors and errors[0]['location']['functionId']=='0x401000',diagnosis
        print(json.dumps({'status':'expected-conversion-rejection-mapped','report':str(base/'diagnosis.json'),
                          'location':errors[0]['location']}))
        return
    if converted['status']!='converted-unverified':raise RuntimeError(converted.get('output',str(converted)))
    result=porting.run(project,context,scenarios=[{'expectedExitCode':0}],trace_libraries='all' if args.trace_imports else '')
    write_json(base/'execution.json',result)
    assert result['status']=='scenarios-passed',result
    assert (source/'eboot.bin').read_bytes()==fixture
    print(json.dumps({'status':result['status'],'report':str(base/'execution.json'),
                      'limit':'Owned standalone CPU fixture only; no game or GPU compatibility claim.'}))


if __name__=='__main__':main()
