"""Bind AnyPS5 evidence to CyDecompilator analysis of verified guest bytes.

AnyPS5 offset fields can hold guest addresses depending on the release. Only a
unique mapping into the verified guest image is used. Runtime host addresses remain
unmapped; matching an import name alone does not locate its caller.
"""
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from cytools_core import CyToolError

from . import porting,service
from .engines import native
from .paths import read_json,write_json
from .project import sha256_file


def _number(value):
    if type(value) is int and 0<=value<1<<64:return value
    if isinstance(value,str) and re.fullmatch(r'0x[0-9a-fA-F]{1,16}',value):return int(value,16)
    return None


def _saved(project,kind,identifier=''):
    if not identifier:identifier=read_json(project.dir/('porting/latest-'+kind+'.json'),{}).get(kind+'Id','')
    if not identifier:return {}
    collection={'attempt':'attempts','run':'runs'}[kind]
    record=read_json(project.dir/'porting'/collection/(porting._id(identifier)+'.json'),{})
    if not record:porting.fail('Saved porting evidence is unavailable.','NotFound')
    return record


def _evidence(text,origin,identifier):
    digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
    rows=[]
    for index,line in enumerate(text.splitlines()):
        if line.strip():rows.append({'origin':origin,'id':identifier,'line':index+1,'text':line[:8192],'sha256':digest})
        if len(rows)>=1000:break
    return rows


def _registries(record,source,context,unknowns):
    result=[]
    files={row['path']:row for row in record.get('files',[])}
    mappings=record.get('registries')
    if mappings is None:
        # Previous receipts emitted the main registry without an explicit mapping.
        main=Path(record.get('executable','')).stem+'.registry.json'
        mappings=[{'path':main,'source':source}] if main in files else []
    for mapping in mappings:
        if mapping.get('source')!=source:continue
        relative=porting._relative(mapping['path'])
        expected=files.get(relative)
        if not expected:porting.fail('Registry is not part of the conversion receipt.','IntegrityFailure')
        path=Path(record['directory'])/relative
        if expected['size']>4*1024**2:
            unknowns.append('A registry exceeds the 4 MiB diagnostic limit.');continue
        if (not path.is_file() or porting._is_link(path) or path.stat().st_size!=expected['size']
                or sha256_file(path,context.cancellation)!=expected['sha256']):
            porting.fail('Conversion registry changed. Convert the application again.','Conflict')
        try:data=json.loads(path.read_text('utf-8-sig'))
        except (ValueError,UnicodeError):
            unknowns.append('A registry is not valid JSON.');continue
        if not isinstance(data,list) or len(data)>20000:
            unknowns.append('A registry has an unsupported shape or size.');continue
        for index,row in enumerate(data):
            context.check()
            if (not isinstance(row,dict) or not isinstance(row.get('nid'),str)
                    or not isinstance(row.get('library'),str) or len(row['nid'])>512 or len(row['library'])>512
                    or not isinstance(row.get('callSites'),list) or len(row['callSites'])>5000):
                unknowns.append('An unsupported registry entry was skipped.');continue
            result.append({'nid':row['nid'],'library':row['library'],'callSites':row['callSites'],
                           'resolved':row.get('callSitesResolved') is True,
                           'evidence':{'origin':'registry','path':relative,'index':index,'sha256':expected['sha256']}})
            if len(result)>=500:
                unknowns.append('Registry inspection stopped at 500 imports.');return result
    return result


def diagnose(project,context,engine='cdec',import_id='',attempt_id='',conversion_id='',module='',max_functions=128):
    if engine not in ('native','cdec','ghidra'):porting.fail('Choose native, cdec or ghidra for porting analysis.')
    imported=porting.info(project,import_id)
    if not imported.get('available'):porting.fail('Prepare a porting input first.','NotFound')
    source=porting._relative(module or imported['entry'])
    manifest={row['path']:row for row in imported['files']}
    expected=manifest.get(source)
    if not expected:porting.fail('Choose an executable from the prepared input manifest.')
    path=Path(imported['directory'])/source
    if (not path.is_file() or porting._is_link(path) or path.stat().st_size!=expected['size']
            or sha256_file(path,context.cancellation)!=expected['sha256']):
        porting.fail('The prepared executable changed. Import it again.','Conflict')
    elf=porting.elf_info(path,require_entry=False)
    unknowns=['Static discovery may miss indirect calls, callbacks and unreachable code.',
              'A registry import is not proof that its API is fully implemented.',
              'Runtime host addresses are not guest virtual addresses.']
    attempt=_saved(project,'attempt',attempt_id) if not conversion_id else {}
    if attempt and attempt.get('importId')!=imported['importId']:
        if attempt_id:porting.fail('The attempt belongs to another prepared input.','Conflict')
        attempt={}
    chosen=conversion_id or attempt.get('conversionId','')
    converted=porting.conversion(project,chosen) if chosen or not attempt else {}
    if converted.get('available') and converted.get('importId')!=imported['importId']:
        if conversion_id:porting.fail('The conversion belongs to another prepared input.','Conflict')
        converted={}
    registry=_registries(converted,source,context,unknowns) if converted.get('available') else []
    run=_saved(project,'run')
    if run.get('conversionId')!=converted.get('conversionId'):run={}
    lines=_evidence(attempt.get('output',converted.get('output','')),'conversion',attempt.get('attemptId',converted.get('conversionId','')))
    conversion_record=attempt or converted
    primary_only=(conversion_record.get('options',{}).get('standalone') is True or imported.get('executables')==[imported['entry']])
    for case in run.get('scenarios',[]):
        lines+=_evidence((case.get('stdout','')+'\n'+case.get('stderr',''))[-2*1024**2:],
                         'scenario-'+str(case['index']),run['runId'])
    analysis_project=project
    if source!=imported['entry']:
        analysis_project,_=service.store.open(path,source_path=str(path),cancellation=context.cancellation)
    if analysis_project.meta()['sha256']!=expected['sha256']:
        porting.fail('The analysis project does not match the prepared executable.','Conflict')
    force=analysis_project.has_analysis(engine) and not analysis_project.analysis(engine).get('functions')
    service.analyze(analysis_project.id,engine,context,force=force)
    analysis=analysis_project.analysis(engine)
    functions=analysis['functions']
    image=native.load_elf(analysis_project.binary)
    walker=native.Walker(image,native.disassembler(image))
    starts={int(row['address'],16) for row in functions}
    interested=set()
    for row in registry:
        interested.update(n for v in row['callSites'] if (n:=_number(v)) is not None)
    for line in lines:
        interested.update(int(n,16) for n in re.findall(r'code offset (0x[0-9a-fA-F]+)',line['text']))
    def addresses(offset):
        return [s['address']+offset-s['offset'] for s in elf['segments']
                if s['type']==1 and s['flags']&1 and s['offset']<=offset<s['offset']+s['fileSize']]
    interested_va={a for offset in interested for a in addresses(offset)}|{a for a in interested if image.executable(a)}
    def priority(row):
        start=int(row['address'],16)
        return (not any(start<=a<start+row.get('size',0) for a in interested_va),start!=image.entry,start)
    selected=sorted(functions,key=priority)[:min(512,max(1,int(max_functions)))]
    decoded={}
    owners={}
    scanned=0
    inspected=0
    for function in selected:
        context.check()
        instructions,*_=walker.walk(int(function['address'],16),starts)
        for insn in instructions:
            decoded[insn.address]=insn
            owners.setdefault(insn.address,[]).append(function['id'])
        scanned+=len(instructions)
        inspected+=1
        if scanned>=200000:
            unknowns.append('Instruction inspection stopped at 200,000 decoded instructions.');break
    findings=[]
    def location(offset,call=False):
        vas=set(addresses(offset))
        if image.executable(offset):vas.add(offset)
        loc={'source':source,'reportedValue':hex(offset),'mapping':'unresolved'}
        if len(vas)>1:
            loc.update(mapping='ambiguous-guest-address',candidates=[hex(a) for a in sorted(vas)])
            return loc
        if len(vas)==1:
            va=next(iter(vas));loc['virtualAddress']=hex(va)
            loc['addressInterpretations']=(['source-file-offset'] if va in addresses(offset) else [])+(['guest-virtual-address'] if va==offset else [])
            file_offsets={s['offset']+va-s['address'] for s in elf['segments']
                          if s['type']==1 and s['flags']&1 and s['address']<=va<s['address']+s['fileSize']}
            if len(file_offsets)==1:loc['fileOffset']=hex(next(iter(file_offsets)))
            insn=decoded.get(va)
            if insn and (not call or insn.mnemonic in ('call','jmp')):
                ids=list(dict.fromkeys(owners.get(va,[])))
                if len(ids)==1:
                    loc.update(functionId=ids[0],mapping='decoded-instruction',instruction=insn.mnemonic+' '+insn.op_str)
        return loc
    for address,insn in sorted(decoded.items()):
        if insn.mnemonic not in ('syscall','sysenter') and not (insn.mnemonic=='int' and insn.op_str in ('0x80','0x2e')):continue
        offsets={s['offset']+address-s['address'] for s in elf['segments']
                 if s['type']==1 and s['address']<=address<s['address']+s['fileSize']}
        if len(offsets)==1:
            findings.append({'kind':'syscall','severity':'warning','location':location(offsets.pop()),
                             'evidence':{'origin':'guest-instruction','sha256':expected['sha256'],'bytes':bytes(insn.bytes).hex()}})
    for row in registry:
        sites=[location(n,call=True) for v in row['callSites'][:128] if (n:=_number(v)) is not None]
        findings.append({'kind':'import','severity':'info','nid':row['nid'],'library':row['library'],
                         'callSites':sites,'callSitesResolved':row['resolved'],'evidence':row['evidence']})
    for line in lines:
        text=line['text']
        match=re.search(r'Forbidden syscall instruction at code offset (0x[0-9a-fA-F]+)',text)
        if match:
            loc=location(int(match[1],16))
            if source!=imported['entry'] or not primary_only:
                loc={'mapping':'module-unattributed','reportedValue':match[1],'selectedModuleCandidate':loc}
                unknowns.append('A converter error has no proven module attribution; the selected module is only a candidate.')
            findings.append({'kind':'converter-syscall','severity':'error','location':loc,'evidence':line})
        elif re.search(r'unresolved import|undefined symbol|missing (?:library|import|symbol)|failed to (?:load|resolve)|not implemented|requires libc\.prx|not a shared module',text,re.I):
            findings.append({'kind':'dependency-error','severity':'error','evidence':line})
        elif re.search(r'missing (?:CPU )?(?:extensions|features)|unsupported (?:CPU|instruction)',text,re.I):
            findings.append({'kind':'host-instruction-error','severity':'error','evidence':line})
        trace=re.search(r'#(\d+) thread (\d+) (\S+\.prx) (\S+) from (0x[0-9a-fA-F]+)',text)
        if trace:
            # NID matches give candidate SOURCE call sites. ASLR/return-address
            # translation is deliberately not guessed from a host pointer.
            candidates=[r for r in findings if r['kind']=='import' and r['nid'].split('#')[0]==trace[4].split('#')[0]
                        and r['library'].removesuffix('.prx')==trace[3].removesuffix('.prx')]
            findings.append({'kind':'runtime-import','severity':'info','nid':trace[4],'library':trace[3],
                'thread':int(trace[2]),'sequence':int(trace[1]),'hostAddress':trace[5],
                'mapping':'runtime-address-unmapped','sourceCandidates':[s for r in candidates for s in r['callSites']],
                'evidence':line})
        if len(findings)>=1000:
            unknowns.append('Findings were truncated at 1,000 entries.');break
    function_ids=[]
    for finding in findings:
        for loc in [finding.get('location',{}),*finding.get('callSites',[])]:
            if loc.get('functionId') and loc['functionId'] not in function_ids:function_ids.append(loc['functionId'])
    if not function_ids and functions:function_ids=[min(functions,key=lambda f:int(f['address'],16)!=image.entry)['id']]
    samples=[]
    for identifier in function_ids[:5]:
        function=analysis_project.find_function(engine,identifier)
        sample={'function':{k:function[k] for k in ('id','name','address','size') if k in function},
                'projectId':analysis_project.id,'engine':engine}
        for view in ('disassembly','decompiled') if engine!='native' else ('disassembly',):
            try:
                code=service.decompile(analysis_project.id,identifier,engine,context,view=view)
                sample[view]={'code':code['code'][:20000],'language':code['language'],'truncated':len(code['code'])>20000}
                if view=='decompiled':
                    incomplete=bool(re.search(r'instruction\(s\) not modelled|/\* unsupported:',code['code']))
                    sample[view]['hasUnmodeledInstructions']=incomplete
                    if incomplete:unknowns.append('Generated C contains unmodeled instructions and must not replace guest code as-is.')
            except CyToolError as error:sample[view]={'error':error.to_dict()}
        samples.append(sample)
    if sha256_file(analysis_project.binary,context.cancellation)!=expected['sha256']:
        porting.fail('The analysis input changed during diagnosis.','Conflict')
    if inspected<len(functions):unknowns.append('Only a bounded subset of discovered functions was inspected.')
    unknowns+=['Console NID imports without ELF section symbols may remain unresolved in generated C.',
               'AnyPS5 offset fields are interpreted against guest load mappings; ambiguous interpretations stay unresolved.']
    result={'projectId':project.id,'diagnosisId':uuid.uuid4().hex,'importId':imported['importId'],
            'analysisProjectId':analysis_project.id,'source':source,'sourceSha256':expected['sha256'],'engine':engine,
            'attemptId':attempt.get('attemptId'),'conversionId':converted.get('conversionId'),'runId':run.get('runId'),
            'status':'analysis-complete','findings':findings[:1000],'samples':samples,
            'coverage':{'discoveredFunctions':len(functions),'inspectedFunctions':inspected,
                        'decodedInstructions':scanned,'registryImports':len(registry)},
            'unknowns':list(dict.fromkeys(unknowns)),'createdAt':time.time(),
            'limits':['Diagnosis does not modify guest code or prove behavioral equivalence.',
                      'Opaque, indirect and module mappings must not be guessed.']}
    write_json(project.dir/'porting/diagnoses'/(result['diagnosisId']+'.json'),result)
    write_json(project.dir/'porting/latest-diagnosis.json',{'diagnosisId':result['diagnosisId']})
    return result
