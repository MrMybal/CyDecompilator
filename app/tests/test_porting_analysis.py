"""Guest analysis and evidence bindings; controlled registries are schema fixtures,
not a claim that AnyPS5 converted an application with those particular imports.
"""
import json
from pathlib import Path
import struct
import sys
import uuid

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cytools_core import CyToolError
from cydec import porting,porting_analysis,service
from cydec.engines import native
from cydec.paths import write_json
from test_porting import setup,elf_bytes  # noqa: F401 (shared fixture)


def two_functions():
    # Entry calls a helper at +0x10; helper contains a real decoded syscall.
    return elf_bytes(b'\xe8\x0b\0\0\0\x31\xc0\xc3'+b'\x90'*8+b'\xb8\x3c\0\0\0\x0f\x05\xc3')


def test_sectionless_loader_and_cdec_find_real_functions(setup):
    store,ctx,source=setup
    (source/'eboot.bin').write_bytes(two_functions())
    opened=porting.open_input(store,source,ctx)
    project=store.get(opened['projectId'])
    for engine in ('native','cdec'):
        service.analyze(project.id,engine,ctx)
        analysis=project.analysis(engine)
        assert {f['address'] for f in analysis['functions']}=={'0x401000','0x401010'}
        assert analysis['sections'][0]['source']=='program-header'
        code=service.decompile(project.id,'0x401000',engine,ctx)['code']
        assert code and ('call' in code if engine=='native' else 'sub_401010' in code)


def test_sectionless_loader_rejects_bad_ranges_and_overlapping_mappings(tmp_path):
    source=tmp_path/'bad.elf'
    image=bytearray(elf_bytes())
    struct.pack_into('<Q',image,64+32,1<<40)
    source.write_bytes(image)
    with pytest.raises(CyToolError):native.load_elf(source)
    image=bytearray(elf_bytes())
    struct.pack_into('<H',image,56,2)
    image[120:176]=image[64:120]
    source.write_bytes(image)
    with pytest.raises(CyToolError):native.load_elf(source)


def test_converter_error_is_bound_to_source_instruction_and_c_samples(setup):
    store,ctx,source=setup
    (source/'eboot.bin').write_bytes(two_functions())
    imported=porting.open_input(store,source,ctx)
    project=store.get(imported['projectId'])
    attempt={'projectId':project.id,'importId':imported['importId'],'status':'conversion-failed',
             'output':'Forbidden syscall instruction at code offset 0x1015: syscall number 60'}
    porting._save_attempt(project,attempt)
    report=porting_analysis.diagnose(project,ctx)
    error=next(f for f in report['findings'] if f['kind']=='converter-syscall')
    assert error['location']['functionId']=='0x401010'
    assert error['location']['virtualAddress']=='0x401015'
    assert error['evidence']['id']==attempt['attemptId']
    assert any(f['kind']=='syscall' for f in report['findings'])
    assert report['samples'][0]['function']['id']=='0x401010'
    assert 'syscall' in report['samples'][0]['disassembly']['code']
    assert 'decompiled' in report['samples'][0]
    assert report['samples'][0]['decompiled']['hasUnmodeledInstructions'] is True
    assert report['sourceSha256']==project.meta()['sha256']
    assert (source/'eboot.bin').read_bytes()==two_functions()
    assert (project.dir/'porting/diagnoses'/(report['diagnosisId']+'.json')).is_file()


def test_registry_offsets_and_runtime_candidates_never_guess_host_addresses(setup):
    store,ctx,source=setup
    (source/'eboot.bin').write_bytes(two_functions())
    imported=porting.open_input(store,source,ctx)
    project=store.get(imported['projectId'])
    receipt=uuid.uuid4().hex
    output=project.dir/'porting/conversions'/receipt;output.mkdir(parents=True)
    registry=output/'application.registry.json'
    write_json(registry,[{'nid':'k+AXqu2-eBc','library':'libkernel','callSitesResolved':True,
                         'callSites':['0x1000','0x1001','0x401000']}])
    converted={'projectId':project.id,'conversionId':receipt,'importId':imported['importId'],
               'directory':str(output),'executable':'application.exe','files':porting.inventory(output,ctx),
               'status':'converted-unverified'}
    write_json(output.parent/(receipt+'.json'),converted)
    write_json(project.dir/'porting/latest-conversion.json',{'conversionId':receipt})
    run_id=uuid.uuid4().hex
    write_json(project.dir/'porting/runs'/(run_id+'.json'),{'runId':run_id,'conversionId':receipt,
        'scenarios':[{'index':0,'stderr':'#1 thread 9384 libkernel.prx k+AXqu2-eBc from 0x140010006 app.exe+0x10006'}]})
    write_json(project.dir/'porting/latest-run.json',{'runId':run_id})
    report=porting_analysis.diagnose(project,ctx)
    imported_call=next(r for r in report['findings'] if r['kind']=='import')
    sites=imported_call['callSites']
    assert sites[0]['functionId']=='0x401000' and sites[0]['virtualAddress']=='0x401000'
    assert sites[1]['mapping']=='unresolved'
    assert sites[2]['functionId']=='0x401000' and sites[2]['addressInterpretations']==['guest-virtual-address']
    runtime=next(r for r in report['findings'] if r['kind']=='runtime-import')
    assert runtime['mapping']=='runtime-address-unmapped' and 'virtualAddress' not in runtime
    assert runtime['sourceCandidates'][0]['functionId']=='0x401000'
    registry.write_text('[]')
    with pytest.raises(CyToolError,match='registry changed'):porting_analysis.diagnose(project,ctx)


def test_module_analysis_is_hash_bound_and_stale_attempts_are_rejected(setup):
    store,ctx,source=setup
    modules=source/'sce_module';modules.mkdir()
    (modules/'helper.prx').write_bytes(elf_bytes(b'\xb8\x07\0\0\0\xc3'))
    imported=porting.open_input(store,source,ctx)
    project=store.get(imported['projectId'])
    report=porting_analysis.diagnose(project,ctx,module='sce_module/helper.prx')
    assert report['analysisProjectId']!=project.id and report['samples'][0]['decompiled']['code']
    assert report['source']=='sce_module/helper.prx'
    porting._save_attempt(project,{'importId':imported['importId'],'options':{'standalone':False},
        'output':'Forbidden syscall instruction at code offset 0x401000'})
    uncertain=porting_analysis.diagnose(project,ctx)
    error=next(r for r in uncertain['findings'] if r['kind']=='converter-syscall')
    assert error['location']['mapping']=='module-unattributed' and 'functionId' not in error['location']
    attempt={'importId':uuid.uuid4().hex,'status':'conversion-failed','output':'old failure'}
    porting._save_attempt(project,attempt)
    with pytest.raises(CyToolError,match='another prepared input'):
        porting_analysis.diagnose(project,ctx,attempt_id=attempt['attemptId'])
    assert porting_analysis.diagnose(project,ctx)['attemptId'] is None
    (Path(imported['directory'])/'sce_module/helper.prx').write_bytes(elf_bytes())
    with pytest.raises(CyToolError,match='executable changed'):
        porting_analysis.diagnose(project,ctx,module='sce_module/helper.prx')


def test_ambiguous_virtual_address_and_file_offset_are_not_assigned_to_a_function(setup):
    store,ctx,source=setup
    image=bytearray(0x2001)
    header=elf_bytes()[:120];image[:120]=header
    struct.pack_into('<Q',image,24,0x2000)
    struct.pack_into('<H',image,56,2)
    struct.pack_into('<IIQQQQQQ',image,64,1,5,0x1000,0x2000,0x2000,6,6,0x1000)
    struct.pack_into('<IIQQQQQQ',image,120,1,5,0x2000,0x3000,0x3000,1,1,0x1000)
    image[0x1000:0x1006]=b'\xe8\xfb\x0f\0\0\xc3';image[0x2000]=0xc3
    (source/'eboot.bin').write_bytes(image)
    imported=porting.open_input(store,source,ctx)
    project=store.get(imported['projectId'])
    porting._save_attempt(project,{'importId':imported['importId'],'output':'Forbidden syscall instruction at code offset 0x2000'})
    report=porting_analysis.diagnose(project,ctx)
    loc=next(r['location'] for r in report['findings'] if r['kind']=='converter-syscall')
    assert loc['mapping']=='ambiguous-guest-address' and 'functionId' not in loc
    assert loc['candidates']==['0x2000','0x3000']
