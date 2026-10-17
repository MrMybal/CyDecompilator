"""Real managed method edits, metadata remapping and unchanged-method verification."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from cytools_core import CyToolError
from cydec import managed_patching, process, service, workspace
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore


@pytest.fixture
def sample(tmp_path, monkeypatch):
    ctx = EngineContext(workdir=tmp_path / 'work', options={'symbols': False})
    sdk = workspace.dotnet_sdk(ctx)
    source = tmp_path / 'source'
    source.mkdir()
    _, out, _ = process.run([sdk, '--version'], context=ctx)
    version = int(out.strip().split('.')[0])
    (source / 'Sample.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            '<TargetFramework>net%d.0</TargetFramework><AssemblyName>Sample</AssemblyName></PropertyGroup></Project>' % version,
            encoding='utf-8')
    code = ('using System; class Program { private static int offset=3; '
            'static int Helper(int v) => v+2; static int Value(int v) => v+1; '
            'static void Main() { Console.WriteLine("original:"+Value(3)); } }')
    (source / 'Program.cs').write_text(code, encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(source), '-o', str(tmp_path / 'original')], context=ctx, timeout=120)
    assert rc == 0, out + err
    store = ProjectStore(tmp_path / 'projects')
    monkeypatch.setattr(service, 'store', store)
    project, _ = store.open(tmp_path / 'original/Sample.dll')
    service.workspace_open(project.id, str(source))
    return project, source, ctx, sdk


def value_method(project, ctx):
    listing = service.managed_methods(project.id, ctx, 'Program')
    return next(m for m in listing['methods'] if m['name'] == 'Value')


def edit(source, value, extra=''):
    (source / 'Program.cs').write_text(
        'using System; class Program { private static int offset=100; static int Helper(int v) => 999; '
        + value + ' static void Main() { Console.WriteLine("DONOR:"+Value(3)); } ' + extra + ' }', encoding='utf-8')


def test_patch_larger_method_fields_calls_locals_exceptions_and_original_main(sample):
    project, source, ctx, sdk = sample
    original_hash = hashlib.sha256(project.binary.read_bytes()).hexdigest()
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v) { try { int total=offset; for(int i=0;i<v;i++) total+=Helper(i); '
                 'return total; } catch(Exception) { return -1; } }')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    assert plan['size'] > plan['capacity'] and plan['unchangedMethods'] >= 3
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, result['path']], context=ctx)
    assert rc == 0 and 'original:12' in out, out + err
    assert hashlib.sha256(project.binary.read_bytes()).hexdigest() == original_hash
    assert result['originalPreserved'] and len(result['companions']) == 2
    with pytest.raises(CyToolError, match='already exists'):
        service.patch_apply(project.id, plan['planId'], context=ctx)


def test_signature_and_new_helper_refused(sample):
    project, source, ctx, _ = sample
    method = value_method(project, ctx)
    edit(source, 'static long Value(int v) => 42;')
    with pytest.raises(CyToolError, match='signature'):
        service.managed_patch_prepare(project.id, method['id'], ctx)
    edit(source, 'static int Value(int v) => Added(v);', 'static int Added(int v) => v+40;')
    with pytest.raises(CyToolError, match='introduces|missing member'):
        service.managed_patch_prepare(project.id, method['id'], ctx)


def test_new_strings_and_internal_branches(sample):
    project, source, ctx, sdk = sample
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v) { string s="new text"; Console.WriteLine(s); '
                 'switch(v) { case 3: return s.Length+40; case 4: return 9; default: return 0; } }')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, result['path']], context=ctx)
    assert rc == 0 and 'new text' in out and 'original:48' in out, out + err


def test_stale_sources_and_tampered_candidate_refused(sample):
    project, source, ctx, _ = sample
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v) => 42;')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    with pytest.raises(CyToolError, match='original'):
        service.patch_apply(project.id, plan['planId'], str(project.binary), ctx)
    candidate = project.dir / 'patches/managed' / plan['planId'] / 'candidate.dll'
    candidate.write_bytes(candidate.read_bytes() + b'tampered')
    with pytest.raises(CyToolError, match='changed'):
        service.patch_apply(project.id, plan['planId'], context=ctx)
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    (source / 'Program.cs').write_text('// edit\n' + (source / 'Program.cs').read_text(), encoding='utf-8')
    with pytest.raises(CyToolError, match='source project changed'):
        service.patch_apply(project.id, plan['planId'], context=ctx)


def test_generated_lambda_helper_is_isolated(sample):
    project, source, ctx, sdk = sample
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v) { Func<int,int> f=x=>x+42; return f(v); }')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    assert plan['generatedTypes'] and plan['generatedMethods']
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, result['path']], context=ctx)
    assert rc == 0 and 'original:45' in out, out + err


@pytest.mark.parametrize(('body', 'expected'), [
    ('Func<int> f=()=>v+offset+Helper(v); return f();', 11),
    ('int Local(int x)=>x+v+offset; return Local(2);', 8),
    ('Func<int,Func<int>> outer=x=>()=>v+x+offset; return outer(4)();', 10),
    ('Func<System.Threading.Tasks.Task<int>> f=async()=>{ await System.Threading.Tasks.Task.Delay(1); return v+offset; }; '
     'return f().GetAwaiter().GetResult();', 6),
])
def test_captured_nested_and_local_function_dependencies(sample, body, expected):
    project, source, ctx, sdk = sample
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v) { ' + body + ' }')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    assert plan['generatedMethods'] and all('__cydec_' in name for name in plan['generatedMethods'])
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, result['path']], context=ctx)
    assert rc == 0 and 'original:' + str(expected) in out, out + err


def compiled_project(sample, tmp_path, original):
    _, source, ctx, sdk = sample
    (source / 'Program.cs').write_text(original, encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(source), '-o', str(tmp_path / 'generated-original')], context=ctx)
    assert rc == 0, out + err
    project, _ = service.store.open(tmp_path / 'generated-original/Sample.dll')
    service.workspace_open(project.id, str(source))
    method = next(m for m in service.managed_methods(project.id, ctx)['methods'] if m['name'] == 'Value')
    return project, method


def test_shared_singleton_cache_does_not_change_other_lambdas(sample, tmp_path):
    _, source, ctx, sdk = sample
    original = ('using System; class Program { static int Value(int v) { Func<int,int> f=x=>x+1; return f(v); } '
                'static int Other(int v) { Func<int,int> f=x=>x+10; return f(v); } '
                'static void Main(){Console.WriteLine("original:"+Value(3)+":"+Other(3));} }')
    project, method = compiled_project(sample, tmp_path, original)
    # Reorder and alter the unrelated method so compiler helper names/cache fields shift.
    donor = ('using System; class Program { static int Other(int v) { Func<int,int> f=x=>999; return f(v); } '
             'static int Value(int v) { Func<int,int> f=x=>x+40; return f(v); } '
             'static void Main(){Console.WriteLine("DONOR:"+Value(3)+":"+Other(3));} }')
    (source / 'Program.cs').write_text(donor, encoding='utf-8')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    assert len(plan['generatedMethods']) == 3  # singleton ctor/cctor and selected lambda only
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, result['path']], context=ctx)
    assert rc == 0 and 'original:43:13' in out, out + err


@pytest.mark.parametrize('body', [
    'Func<T> f=()=>v; Console.WriteLine(typeof(T).Name); return f();',
    'await Task.Delay(1); Func<T> f=()=>v; Console.WriteLine(typeof(T).Name); return f();',
])
def test_generated_generic_closure_and_async_state_machine(sample, tmp_path, body):
    _, source, ctx, sdk = sample
    asynchronous = 'await ' in body
    signature = 'async Task<T>' if asynchronous else 'T'
    original_body = 'await Task.Delay(1); return v;' if asynchronous else 'return v;'
    call = 'Value<int>(3).GetAwaiter().GetResult()' if asynchronous else 'Value<int>(3)'
    original = ('using System; using System.Threading.Tasks; class Program { static ' + signature +
                ' Value<T>(T v) where T:struct {' + original_body + '} '
                'static void Main(){Console.WriteLine("original:"+' + call + ');} }')
    project, method = compiled_project(sample, tmp_path, original)
    (source / 'Program.cs').write_text(original.replace(original_body, body), encoding='utf-8')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    output = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, output['path']], context=ctx)
    assert rc == 0 and 'Int32' in out and 'original:3' in out, out + err


def test_generated_new_user_dependency_still_refused(sample):
    project, source, ctx, _ = sample
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v) { Func<int> f=()=>Added(v); return f(); }',
         'static int Added(int v)=>v+100;')
    with pytest.raises(CyToolError, match='introduces|missing member'):
        service.managed_patch_prepare(project.id, method['id'], ctx)


def test_import_new_user_members_types_fields_and_portable_symbols(sample):
    project, source, ctx, sdk = sample
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v) { AddedCounter++; return Added(v)+new HelperBox(v).Result+AddedCounter; }',
         'static int AddedCounter; static int Added(int v)=>v+20; '
         'class HelperBox { int value; public HelperBox(int v){value=v;} public int Result=>value*2; }')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, allow_new_members=True, symbols=True)
    assert plan['addedTypes'] and plan['addedMethods'] and plan['addedFields'] and plan['symbols']
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    assert result['symbols'] and Path(result['path']).with_suffix('.pdb').read_bytes()[:4] == b'BSJB'
    rc, out, err = process.run([sdk, result['path']], context=ctx)
    assert rc == 0 and 'original:30' in out, out + err


def test_portable_symbols_conflicts_and_tampering_protect_copy(sample, tmp_path):
    project, source, ctx, _ = sample
    method = value_method(project, ctx)
    edit(source, 'static int Value(int v)=>v+40;')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, symbols=True)
    output = tmp_path / 'output'
    output.mkdir()
    pdb = output / 'Sample.pdb'
    pdb.write_bytes(b'existing-symbols')
    with pytest.raises(CyToolError, match='symbols'):
        service.patch_apply(project.id, plan['planId'], str(output/'Sample.dll'), ctx)
    assert not (output/'Sample.dll').exists() and pdb.read_bytes()==b'existing-symbols'
    receipt = service.patch_apply(project.id, plan['planId'], context=ctx)
    pdb = Path(receipt['path']).with_suffix('.pdb')
    pdb.write_bytes(pdb.read_bytes()+b'tamper')
    with pytest.raises(CyToolError, match='dependency changed'):
        service.patch_run(project.id, receipt['receiptId'], ctx)


@pytest.mark.parametrize('declaration', ['int Added=10;', 'static int Added=10;'])
def test_new_fields_cannot_silently_change_original_initializers(sample, declaration):
    project, source, ctx, _ = sample
    method = value_method(project, ctx)
    body = 'return Added+v;' if declaration.startswith('static') else 'return new Program().Added+v;'
    edit(source, 'static int Value(int v) {' + body + '}', declaration)
    with pytest.raises(CyToolError, match='initializer|instance/layout'):
        service.managed_patch_prepare(project.id, method['id'], ctx, allow_new_members=True)


@pytest.mark.parametrize(('original_body', 'donor_body', 'using', 'signature', 'main', 'expected'), [
    ('await Task.Delay(1); return v+1;', 'await Task.Delay(1); return v+40;', 'using System.Threading.Tasks;',
     'async Task<int>', 'Console.WriteLine("original:"+Value(3).GetAwaiter().GetResult());', 'original:43'),
    ('yield return v; yield return 1;', 'yield return v; yield return 40;', 'using System.Collections.Generic;',
     'IEnumerable<int>', 'int sum=0; foreach(int x in Value(3))sum+=x; Console.WriteLine("original:"+sum);', 'original:43'),
    ('await Task.Delay(1); yield return v;', 'await Task.Delay(1); yield return v+40;',
     'using System.Threading.Tasks; using System.Collections.Generic;', 'async IAsyncEnumerable<int>',
     'int sum=0; await foreach(int x in Value(3))sum+=x; Console.WriteLine("original:"+sum);', 'original:43'),
])
@pytest.mark.parametrize('configuration', ['Debug', 'Release'])
def test_async_iterator_and_async_iterator_replace_isolated_state_machine(sample, tmp_path,
        original_body, donor_body, using, signature, main, expected, configuration):
    _, source, ctx, sdk = sample
    main_signature = 'async System.Threading.Tasks.Task' if 'await foreach' in main else 'void'
    original = ('using System; ' + using + ' class Program { static ' + signature + ' Value(int v) {' + original_body + '} '
                'static ' + main_signature + ' Main() {' + main + '} }')
    project, method = compiled_project(sample, tmp_path, original)
    assert method['editable']
    donor = original.replace(original_body, donor_body).replace('original:', 'DONOR:')
    (source / 'Program.cs').write_text(donor, encoding='utf-8')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, configuration=configuration)
    assert plan['generatedTypes'] and plan['generatedMethods']
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, result['path']], context=ctx, timeout=30)
    assert rc == 0 and expected in out, out + err
    assert result['generatedTypes'] == plan['generatedTypes']


def test_instance_async_generic_owner_uses_original_fields_and_methods(sample, tmp_path):
    _, source, ctx, sdk = sample
    original = ('using System; using System.Threading.Tasks; class Box<T> { int Offset=3; int Helper()=>2; '
                'public async Task<int> Value(T v) { await Task.Yield(); return 1; } } '
                'class Program {static void Main(){Console.WriteLine("original:"+new Box<int>().Value(3).GetAwaiter().GetResult());}}')
    project, method = compiled_project(sample, tmp_path, original)
    donor = original.replace('Offset=3', 'Offset=999').replace('Helper()=>2', 'Helper()=>999').replace(
        'await Task.Yield(); return 1;', 'await Task.Delay(1); Func<int> f=()=>Offset+Helper()+v.ToString().Length; return f();')
    (source / 'Program.cs').write_text(donor, encoding='utf-8')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, configuration='Release')
    output = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, output['path']], context=ctx)
    assert rc == 0 and 'original:6' in out, out + err


def test_second_patch_keeps_first_generated_dependencies_and_old_tokens(sample, tmp_path):
    _, source, ctx, sdk = sample
    original = ('using System; class Program { static int Value(int v)=>v+1; '
                'static void Main(){Console.WriteLine("original:"+Value(3));} }')
    project, method = compiled_project(sample, tmp_path, original)
    for extra in (40, 80):
        donor = original.replace('Value(int v)=>v+1;', 'Value(int v) { Func<int> f=()=>v+' + str(extra) + '; return f(); }')
        (source / 'Program.cs').write_text(donor, encoding='utf-8')
        original_listing = service.managed_methods(project.id, ctx)['methods']
        plan = service.managed_patch_prepare(project.id, method['id'], ctx)
        output = service.patch_apply(project.id, plan['planId'], context=ctx)
        rc, out, err = process.run([sdk, output['path']], context=ctx)
        assert rc == 0 and 'original:' + str(extra+3) in out, out + err
        project, _ = service.store.open(output['path'])
        service.workspace_open(project.id, str(source))
        patched_listing = service.managed_methods(project.id, ctx)['methods']
        assert {(m['id'], m['signature']) for m in original_listing} <= {(m['id'], m['signature']) for m in patched_listing}
        assert all(not m['editable'] for m in patched_listing if m['generatedKind'] == 'helper')


def test_generic_method_and_async_editability(sample, tmp_path):
    project, source, ctx, sdk = sample
    original = ('using System; using System.Threading.Tasks; class Program { '
                'static T Value<T>(T v) => v; static async Task<int> AsyncValue(int v) { await Task.Delay(1); return v; } '
                'static void Main() { Console.WriteLine("original:"+Value<int>(3)); } }')
    (source / 'Program.cs').write_text(original, encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(source), '-o', str(tmp_path / 'generic-original')], context=ctx)
    assert rc == 0, out + err
    project, _ = service.store.open(tmp_path / 'generic-original/Sample.dll')
    service.workspace_open(project.id, str(source))
    listing = service.managed_methods(project.id, ctx, 'Program')
    asynchronous = next(m for m in listing['methods'] if m['name'] == 'AsyncValue')
    assert asynchronous['editable'] and asynchronous['generatedKind'] == 'state-machine'
    (source / 'Program.cs').write_text(original.replace('static T Value<T>(T v) => v;',
        'static T Value<T>(T v) { Console.WriteLine(typeof(T).Name); return v; }'), encoding='utf-8')
    method = next(m for m in listing['methods'] if m['name'] == 'Value')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    output = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, output['path']], context=ctx)
    assert rc == 0 and 'Int32' in out and 'original:3' in out, out + err


def test_members_on_own_generic_type(sample, tmp_path):
    _, source, ctx, sdk = sample
    code = ('using System; class Box<T> { static int Offset=3; static int Helper(T v)=>3; '
            'public static int Value(T v)=>1; } '
            'class Program { static void Main() { Console.WriteLine("original:"+Box<int>.Value(3)); } }')
    (source / 'Program.cs').write_text(code, encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(source), '-o', str(tmp_path / 'generic-type')], context=ctx)
    assert rc == 0, out + err
    project, _ = service.store.open(tmp_path / 'generic-type/Sample.dll')
    service.workspace_open(project.id, str(source))
    listing = service.managed_methods(project.id, ctx)
    method = next(m for m in listing['methods'] if m['name'] == 'Value')
    edited = code.replace('Offset=3', 'Offset=100').replace('Helper(T v)=>3', 'Helper(T v)=>999').replace(
        'Value(T v)=>1;', 'Value(T v) { return Offset+v.ToString().Length+Helper(v); }')
    (source / 'Program.cs').write_text(edited, encoding='utf-8')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx)
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    rc, out, err = process.run([sdk, result['path']], context=ctx)
    assert rc == 0 and 'original:7' in out, out + err


@pytest.mark.skipif(sys.platform != 'win32', reason='Test key generation uses Windows CSP')
def test_strong_name_requires_explicit_removal(sample, tmp_path):
    _, source, ctx, sdk = sample
    script = tmp_path / 'test-key.ps1'
    script.write_text('param([string]$Output)\n'
        '$key = [System.Security.Cryptography.RSACryptoServiceProvider]::new(1024)\n'
        'try { [IO.File]::WriteAllBytes($Output, $key.ExportCspBlob($true)) } finally { $key.Dispose() }', encoding='utf-8')
    rc, out, err = process.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                              '-Output', str(source / 'test.snk')], context=ctx)
    assert rc == 0, out + err
    csproj = source / 'Sample.csproj'
    csproj.write_text(csproj.read_text().replace('</PropertyGroup>',
        '<SignAssembly>true</SignAssembly><AssemblyOriginatorKeyFile>test.snk</AssemblyOriginatorKeyFile></PropertyGroup>'), encoding='utf-8')
    rc, out, err = process.run([sdk, 'build', str(source), '-o', str(tmp_path / 'signed')], context=ctx)
    assert rc == 0, out + err
    project, _ = service.store.open(tmp_path / 'signed/Sample.dll')
    service.workspace_open(project.id, str(source))
    listing = service.managed_methods(project.id, ctx, 'Program')
    assert listing['signed']
    method = next(m for m in listing['methods'] if m['name'] == 'Value')
    edit(source, 'static int Value(int v) => 42;')
    with pytest.raises(CyToolError, match='strong-name'):
        service.managed_patch_prepare(project.id, method['id'], ctx)
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, remove_strong_name=True)
    result = service.patch_apply(project.id, plan['planId'], context=ctx)
    assert result['strongNameRemoved']
    modified, _ = service.store.open(result['path'])
    assert not service.managed_methods(modified.id, ctx)['signed']
    rc, out, err = process.run([sdk, result['path']], context=ctx)
    assert rc == 0 and 'original:42' in out, out + err
