"""Native image project generation with exports, import bindings and PE resources."""
import hashlib
import json
import re
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

from cytools_core import CyToolError
from .paths import write_json


def resources(project,root,context):
    if project.meta()['detect']['format']!='pe':return []
    import pefile
    rows,lines,total=[],['#pragma code_page(65001)'],0
    with pefile.PE(str(project.binary)) as pe:
        directory=getattr(pe,'DIRECTORY_ENTRY_RESOURCE',None)
        if not directory:return []
        folder=root/'resources';folder.mkdir(exist_ok=True)
        def token(entry):
            if entry.name is not None:
                name=str(entry.name)
                if '\n' in name or '\r' in name:raise CyToolError('Unsupported','Resource names contain unsupported characters.')
                return '"'+name.replace('\\','\\\\').replace('"','\\"')+'"'
            return str(entry.id)
        for typ in directory.entries:
            for name in typ.directory.entries:
                for language in name.directory.entries:
                    context.check()
                    item=language.data.struct
                    if item.Size>16*1024*1024 or len(rows)>=4000 or total+item.Size>64*1024*1024:
                        raise CyToolError('Unsupported','Native resources exceed reconstruction limits.')
                    data=pe.get_data(item.OffsetToData,item.Size)
                    if len(data)!=item.Size:raise CyToolError('IntegrityFailure','A native resource is truncated.')
                    path='resources/resource-%04d.bin' % len(rows)
                    (root/path).write_bytes(data);total+=len(data)
                    lang=language.id or 0
                    lines+=['LANGUAGE %d, %d' % (lang&1023,lang>>10),
                            '%s %s "%s"' % (token(name),token(typ),path)]
                    rows.append({'type':token(typ),'name':token(name),'language':lang,'path':path,
                                 'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        (root/'resources/recovered.rc').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return rows


def create(project,root,context,functions=(),target='auto',entry_function=''):
    from . import service,workspace
    from .cdec.cgen import c_identifier
    from .cdec.decompiler import reserved_names
    if target not in ('auto','executable','shared','library'):
        raise CyToolError('InvalidParameters','Choose an automatic, executable, shared or static native target.')
    if not project.has_analysis('cdec'):service.analyze(project.id,'cdec',context)
    analysis=project.analysis('cdec')
    pe=analysis.get('pe',{})
    fmt=project.meta()['detect']['format']
    if target=='auto':target='shared' if pe.get('kind')=='DLL' or (not analysis.get('entryPoint') and analysis.get('exports')) else 'executable'
    name='recovered'
    selected=list(functions)
    entry=None
    if target=='executable':
        if entry_function:
            entry=project.find_function('cdec',entry_function)
        else:
            entries=[f for f in analysis['functions'] if f['name'] in ('main','_main','wmain','WinMain','wWinMain')]
            if len(entries)==1:entry=entries[0]
        if entry and entry['id'] not in selected:selected.append(entry['id'])
    code=service.c_module(project.id,selected,context=context)['code']
    (root/'src').mkdir()
    (root/'src/recovered.c').write_text(code,encoding='utf-8')
    blockers=[]
    notes=[{'code':'native-types-inferred','message':'Recovered calling conventions, types and pointer layouts require behavior validation.'}]
    if '/* not decompiled:' in code:
        blockers.append({'code':'native-functions-not-recovered','message':'Some native functions could not be decompiled.'})
    if pe.get('tlsCallbacks'):
        blockers.append({'code':'native-tls-initialization','message':'TLS callbacks require reconstruction.'})
    def symbol(record):
        original=record['name']
        return c_identifier(original+'_' if original in reserved_names() else original)
    sources=['src/recovered.c']
    imports=[]
    for imported in analysis.get('imports',[]):
        label=c_identifier(imported['name'])
        if not re.search(r'\b__imp_'+re.escape(label)+r'\b',code):continue
        if not imported.get('library'):
            blockers.append({'code':'native-import-library-unknown','message':'Resolve the library for '+imported['name']});continue
        imports.append(imported)
    if imports:
        # Own pointer variables avoid dependency on missing vendor import libraries.
        lines=['#include <windows.h>','typedef unsigned long long (*cydec_proc)();']
        for row in imports:lines.append('cydec_proc __imp_%s;' % c_identifier(row['name']))
        lines.append('int cydec_bind_imports(void) { HMODULE library;')
        for row in imports:
            library=json.dumps(row['library']);proc='MAKEINTRESOURCEA(%d)' % int(row['name'][4:]) if row['name'].startswith('ord_') else json.dumps(row['name'])
            lines+=['library=LoadLibraryA(%s); if (!library) return 0;' % library,
                    '__imp_%s=(cydec_proc)GetProcAddress(library,%s); if (!__imp_%s) return 0;' % (c_identifier(row['name']),proc,c_identifier(row['name']))]
        lines+=['return 1;','}']
        (root/'src/imports.c').write_text('\n'.join(lines)+'\n',encoding='utf-8');sources.append('src/imports.c')
    rc_rows=resources(project,root,context)
    if target=='shared':
        exports=[]
        by_address={r['address']:r for r in analysis['functions']}
        for row in pe.get('exports',analysis.get('exports',[])):
            if row.get('forwarder'):
                if not row.get('name') or re.search(r'[\s"=;]',row['name']+row['forwarder']):
                    blockers.append({'code':'native-export-name','message':'An export needs a manual definition.'});continue
                exports.append('%s=%s @%s' % (row['name'],row['forwarder'],row['ordinal']));continue
            record=by_address.get(row.get('address'))
            if not record:
                blockers.append({'code':'native-data-or-missing-export','message':'Export cannot be reconstructed: '+str(row.get('name',row.get('ordinal')))});continue
            emitted=symbol(record)
            if not re.search(r'^\w[\w *]*\b'+re.escape(emitted)+r'\([^\n]*\);$',code,re.M):
                blockers.append({'code':'native-missing-export-body','message':'Export body is absent: '+record['name']});continue
            original=row.get('name') or 'ordinal_'+str(row['ordinal'])
            ordinal=(' @%s' % row['ordinal']) if row.get('ordinal') else ''
            if re.search(r'[\s"=;]',original):
                blockers.append({'code':'native-export-name','message':'An export needs a manual definition.'});continue
            exports.append('%s=%s%s%s' % (original,emitted,ordinal,' NONAME' if not row.get('name') else ''))
        if not exports:blockers.append({'code':'native-missing-exports','message':'No complete native exports were recovered.'})
        (root/'exports.def').write_text('LIBRARY recovered\nEXPORTS\n'+ '\n'.join('    '+x for x in exports)+'\n',encoding='utf-8')
        if imports:
            (root/'src/startup.c').write_text('#include <windows.h>\nextern int cydec_bind_imports(void);\nBOOL WINAPI DllMain(HINSTANCE h,DWORD reason,LPVOID reserved){return reason!=DLL_PROCESS_ATTACH || cydec_bind_imports();}\n',encoding='utf-8')
            sources.append('src/startup.c')
        if analysis.get('entryPoint'):
            notes.append({'code':'native-initialization-unverified','message':'The original DLL initialization has not been verified.'})
    elif target=='executable':
        startup='#include <stdint.h>\n#include <stdlib.h>\n#include "recovered.c"\n'
        sources.remove('src/recovered.c')
        if imports:startup+='extern int cydec_bind_imports(void);\n'
        if not entry:
            startup+='#error CYDEC_APPLICATION_ENTRY_NOT_RECOVERED\n'
            blockers.append({'code':'native-entry-not-recovered','message':'Select or reconstruct the real application entry point.'})
        else:
            emitted=symbol(entry)
            prototype=re.search(r'^(\w[\w *]*\b'+re.escape(emitted)+r'\(([^\n]*)\));$',code,re.M)
            if not prototype or entry['name'] not in ('main','_main'):
                startup+='#error CYDEC_APPLICATION_ENTRY_ADAPTER_REQUIRED\n'
                blockers.append({'code':'native-entry-adapter','message':'Implement a startup adapter for the selected native entry.'})
            else:
                params=prototype.group(2).strip()
                count=0 if not params or params=='void' else len(params.split(','))
                args=[] if count==0 else ['argc','(intptr_t)argv'] if count==2 else ['argc','(intptr_t)argv','(intptr_t)environment'] if count==3 else None
                if args is None:
                    startup+='#error CYDEC_APPLICATION_ENTRY_ADAPTER_REQUIRED\n'
                    blockers.append({'code':'native-entry-adapter','message':'The recovered entry signature needs an adapter.'})
                else:
                    startup+='extern '+prototype.group(1)+';\nint main(int argc,char **argv,char **environment){\n'
                    if imports:startup+='if(!cydec_bind_imports())return 127;\n'
                    startup+='return (int)%s(%s);\n}\n' % (emitted,','.join(args))
        (root/'src/startup.c').write_text(startup,encoding='utf-8');sources.append('src/startup.c')
    if target!='library' and blockers:
        (root/'src/reconstruction_blockers.c').write_text('\n'.join('#error CYDEC_'+r['code'].upper().replace('-','_') for r in blockers)+'\n',encoding='utf-8')
        sources.append('src/reconstruction_blockers.c')
    statement='add_executable(recovered' if target=='executable' else 'add_library(recovered '+('SHARED' if target=='shared' else 'STATIC')
    cmake=['cmake_minimum_required(VERSION 3.20)','project(recovered LANGUAGES C)','set(CMAKE_C_STANDARD 17)',
        statement+' '+' '.join(sources)+')','include(CTest)']
    if fmt=='elf':cmake+=['if(WIN32)','message(FATAL_ERROR "An ELF rebuild requires an ELF toolchain and target environment")','endif()']
    if target=='shared':cmake+=['if(MSVC)','target_sources(recovered PRIVATE exports.def)','endif()']
    if rc_rows and target!='library':cmake+=['if(WIN32)','enable_language(RC)','target_sources(recovered PRIVATE resources/recovered.rc)','target_include_directories(recovered PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")','endif()']
    if imports:cmake+=['if(NOT WIN32)','message(FATAL_ERROR "Windows import bindings require a Windows target")','endif()']
    (root/'CMakeLists.txt').write_text('\n'.join(cmake)+'\n',encoding='utf-8')
    guid=str(uuid.uuid4()).upper()
    configs=''.join('<ProjectConfiguration Include="%s|%s"><Configuration>%s</Configuration><Platform>%s</Platform></ProjectConfiguration>' % (c,p,c,p)
                  for c in ('Debug','Release') for p in ('Win32','x64','ARM64'))
    xml=('<Project DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003"><ItemGroup Label="ProjectConfigurations">'+configs+
        '</ItemGroup><PropertyGroup Label="Globals"><ProjectGuid>{'+guid+'}</ProjectGuid></PropertyGroup><Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />'+
        '<PropertyGroup Label="Configuration"><ConfigurationType>'+{'shared':'DynamicLibrary','executable':'Application','library':'StaticLibrary'}[target]+
        '</ConfigurationType><PlatformToolset>v143</PlatformToolset></PropertyGroup><Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />'+
        '<PropertyGroup><OutDir>build\\$(Platform)\\$(Configuration)\\</OutDir><IntDir>build\\obj\\$(Platform)\\$(Configuration)\\</IntDir><TargetName>recovered</TargetName></PropertyGroup>'+
        '<ItemDefinitionGroup><ClCompile><LanguageStandard_C>stdc17</LanguageStandard_C></ClCompile><Link>'+
        ('<ModuleDefinitionFile>exports.def</ModuleDefinitionFile>' if target=='shared' else '')+
        '</Link><ResourceCompile><AdditionalIncludeDirectories>$(ProjectDir);%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories></ResourceCompile></ItemDefinitionGroup><ItemGroup>'+ ''.join('<ClCompile Include="'+p.replace('/','\\')+'" />' for p in sources)+
        ('<ResourceCompile Include="resources\\recovered.rc" />' if rc_rows and target!='library' else '')+
        '</ItemGroup><Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" /></Project>')
    selected_entry=entry['name'] if isinstance(entry,dict) else ''
    entry='recovered.vcxproj';(root/entry).write_text(xml,encoding='utf-8');workspace._solution(root,'recovered',entry,True,guid)
    reconstruction={'family':'native','target':target,'entryFunction':selected_entry,
        'imports':imports,'resources':rc_rows,'blockers':blockers,'unknowns':notes,'sourceSha256':project.meta()['sha256']}
    write_json(root/'cydec.native.json',reconstruction)
    return {'kind':'native' if fmt=='pe' else 'cmake','entry':entry if fmt=='pe' else 'CMakeLists.txt','note':'Recovered native image project. Review its startup, exports, types and initialization.',
        'reconstruction':reconstruction}
