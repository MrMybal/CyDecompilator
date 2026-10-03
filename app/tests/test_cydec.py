"""CyDecompilator tests: format detection, the shader engine against reference compilers,
projects and annotations, the service layer, archive safety, the AI reply parsers and the
Runtime contract (operations, client isolation, cancellation).

    runtime/python/Scripts/python.exe -m pytest app/tests -q

Tests that need an engine component (Ghidra, ILSpy, Java) or the Windows shader compiler
skip themselves when it is not installed; they never download anything.
"""
import json
import os
import py_compile
import re
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
FIXTURES = APP / 'tests' / 'fixtures'
SHADERS = FIXTURES / 'shaders'
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from cytools_core import CyToolError  # noqa: E402

from cydec import components, detect, service  # noqa: E402
from cydec.engines.base import EngineContext  # noqa: E402
from cydec.project import ProjectStore  # noqa: E402
from cydec.shader import dxbc, dxil, glsl, hlsl, spirv  # noqa: E402


def context(tmp_path, cancellation=None):
    return EngineContext(cancellation=cancellation, progress=lambda p, s: None, log=lambda m, l='Info': None,
                         workdir=tmp_path / 'work')


@pytest.fixture()
def store(tmp_path, monkeypatch):
    value = ProjectStore(tmp_path / 'projects')
    monkeypatch.setattr(service, 'store', value)
    return value


# ---------------------------------------------------------------------- detection

@pytest.mark.parametrize('name,expected', [('lit_ps.cso', 'dxbc'), ('lit_vs.cso', 'dxbc'), ('lit_cs.cso', 'dxbc'),
                                           ('lit_ps60.dxil.cso', 'dxil'), ('lit_frag.spv', 'spirv'),
                                           ('blur_comp.spv', 'spirv')])
def test_detect_shaders(name, expected):
    record = detect.detect(SHADERS / name)
    assert record['format'] == expected
    assert record['engines'] == ['shader']


def test_detect_pyc_and_archives(tmp_path):
    source = tmp_path / 'sample.py'
    source.write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
    pyc = tmp_path / 'sample.pyc'
    py_compile.compile(str(source), cfile=str(pyc))
    record = detect.detect(pyc)
    assert record['format'] == 'pyc'
    assert record['details']['pythonVersion'] == '%d.%d' % sys.version_info[:2]
    jar = tmp_path / 'lib.jar'
    with zipfile.ZipFile(jar, 'w') as archive:
        archive.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\n')
        archive.writestr('a/B.class', b'\xca\xfe\xba\xbe\x00\x00\x00\x34')
    assert detect.detect(jar)['format'] == 'jar'
    plain = tmp_path / 'plain.zip'
    with zipfile.ZipFile(plain, 'w') as archive:
        archive.writestr('readme.txt', 'x')
    assert detect.detect(plain)['format'] == 'zip'
    assert detect.detect(plain)['engines'] == []


def test_detect_pe_and_elf(tmp_path):
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    pe = windows / 'System32' / 'cmd.exe'
    if pe.is_file():
        record = detect.detect(pe)
        assert record['format'] == 'pe' and record['arch'] == 'x86_64'
    elf = tmp_path / 'tiny.elf'
    header = bytearray(64)
    header[:4] = b'\x7fELF'
    header[4], header[5] = 2, 1
    header[16:18] = (3).to_bytes(2, 'little')
    header[18:20] = (183).to_bytes(2, 'little')
    elf.write_bytes(bytes(header))
    record = detect.detect(elf)
    assert record['format'] == 'elf' and record['arch'] == 'arm64' and record['bits'] == 64


# ---------------------------------------------------------------------- DXBC

def fxc_instructions(listing):
    """Instruction lines of an fxc /Fc listing (after the profile line, without comments)."""
    lines = listing.splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r'^(ps|vs|cs|gs|hs|ds)_\d_\d$', line.strip()))
    return [re.sub(r'\s+', ' ', line.strip()) for line in lines[start:] if line.strip() and not line.startswith('//')]


@pytest.mark.parametrize('name', ['lit_ps', 'lit_vs', 'lit_cs'])
def test_dxbc_disassembly_matches_fxc(name):
    shader = dxbc.parse((SHADERS / (name + '.cso')).read_bytes())
    ours = fxc_instructions(dxbc.disassemble(shader))
    reference = fxc_instructions((SHADERS / (name + '.fxc.txt')).read_text(encoding='utf-8', errors='replace'))
    assert ours == reference


def test_dxbc_reflection_names():
    shader = dxbc.parse((SHADERS / 'lit_ps.cso').read_bytes())
    assert [b['name'] for b in shader.bindings] == ['LinearSampler', 'Albedo', 'NormalMap', 'PerFrame']
    assert [v['name'] for v in shader.cbuffers[0]['variables']] == ['WorldViewProj', 'LightDir', 'Time', 'Tint']
    text = hlsl.decompile(shader)
    assert 'Albedo.Sample(LinearSampler, input.TEXCOORD0.xy)' in text
    assert '-LightDir.xyz' in text and 'Tint.xyz' in text
    assert 'float3(0.5, 0.6, 0.7)' in text  # vector immediates keep every component


@pytest.mark.skipif(os.name != 'nt', reason='D3DCompile is Windows only')
@pytest.mark.parametrize('name', ['lit_ps', 'lit_vs', 'lit_cs', 'lit_ps40'])
def test_decompiled_hlsl_recompiles(name):
    """The reconstructed HLSL must be accepted by Microsoft's compiler."""
    import ctypes
    shader = dxbc.parse((SHADERS / (name + '.cso')).read_bytes())
    code = hlsl.decompile(shader)
    profile = '%s_5_0' % shader.program
    compiler = ctypes.WinDLL('d3dcompiler_47.dll')
    blob, errors = ctypes.c_void_p(), ctypes.c_void_p()
    source = code.encode('utf-8')
    result = compiler.D3DCompile(source, len(source), b'decompiled.hlsl', None, None, b'main', profile.encode(),
                                 0, 0, ctypes.byref(blob), ctypes.byref(errors))
    assert result >= 0, code


# ---------------------------------------------------------------------- SPIR-V / DXIL

def test_spirv_glsl_structure():
    module = spirv.parse((SHADERS / 'lit_frag.spv').read_bytes())
    assert module.entry_points[0]['model'] == 'Fragment'
    text = glsl.decompile(module)
    for fragment in ('layout(set = 0, binding = 1) uniform sampler2D albedo;', 'texture(albedo, inUV)',
                     'else if (pc.mode == 2)', 'while (i < 3)', 'discard;', 'vec3 tonemap(inout vec3 c)',
                     'return c / (c + vec3(1.0));', 'dot(color, vec3(0.299, 0.587, 0.114))'):
        assert fragment in text, fragment
    listing = spirv.disassemble(module)
    assert 'OpEntryPoint Fragment' in listing and 'OpImageSampleImplicitLod' in listing


def test_spirv_compute():
    text = glsl.decompile(spirv.parse((SHADERS / 'blur_comp.spv').read_bytes()))
    for fragment in ('layout(local_size_x = 64, local_size_y = 1, local_size_z = 1) in;', 'shared float tile[66];',
                     'barrier();', 'gl_GlobalInvocationID.x', 'dst.data[i] = sum / 3.0;', 'readonly buffer In'):
        assert fragment in text, fragment


def find_dxc():
    import glob
    kits = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Windows Kits' / '10' / 'bin'
    found = sorted(str(p) for p in kits.glob('*/x64/dxc.exe'))
    return found[-1] if found else None


DXIL_FIXTURES = [('sm6_ps', 'ps_6_0'), ('sm6_vs', 'vs_6_0'), ('sm6_cs', 'cs_6_0'), ('sm66_ps', 'ps_6_6'),
                 ('lit_ps60', 'ps_6_0'), ('stress_ps60', 'ps_6_0'), ('stress_ps62', 'ps_6_2')]


@pytest.mark.parametrize('name,profile', DXIL_FIXTURES)
def test_dxil_decompiles_with_names(name, profile):
    from cydec.shader import dxil_hlsl
    text = dxil_hlsl.decompile((SHADERS / (name + '.dxil.cso')).read_bytes())
    assert 'main(' in text and 'dx.op' not in text and '_regs[' not in text
    if name == 'sm6_ps':
        for fragment in ('int            LightCount;', 'StructuredBuffer<Light> Lights', 'Lights[', '.intensity',
                         'while (true)', 'switch (Mode)', 'discard;', 'Albedo.Sample(Linear,'):
            assert fragment in text, fragment
    if name == 'sm6_cs':
        for fragment in ('[numthreads(64, 1, 1)]', 'groupshared float Shared[64];', 'GroupMemoryBarrierWithGroupSync();',
                         'InterlockedAdd(Counters[0], 1', 'uint3 DTid : SV_DispatchThreadID'):
            assert fragment in text, fragment
    if name == 'sm6_vs':
        assert 'ViewProj._m00' in text and 'ViewProj._m30' in text
    if name == 'stress_ps60':
        for fragment in ('Weights[', 'WaveActiveSum(', 'Layers.SampleLevel(S,', 'Shadow.SampleCmpLevelZero(Cmp,',
                         'OutRaw.Store(', 'static const float Kernel[5]', 'Bones._m23'):
            assert fragment in text, fragment


@pytest.mark.parametrize('name,profile', DXIL_FIXTURES)
def test_dxil_output_recompiles_with_dxc(name, profile, tmp_path):
    import subprocess
    from cydec.shader import dxil_hlsl
    dxc = find_dxc()
    if dxc is None:
        pytest.skip('dxc.exe not installed (Windows SDK)')
    source = tmp_path / (name + '.hlsl')
    source.write_text(dxil_hlsl.decompile((SHADERS / (name + '.dxil.cso')).read_bytes()), encoding='utf-8')
    flags = ['-enable-16bit-types'] if profile >= 'ps_6_2' and name.startswith('stress') else []
    result = subprocess.run([dxc, '-nologo', '-T', profile, *flags, '-E', 'main', str(source), '-Fo', str(tmp_path / 'out.cso')],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-3000:]


@pytest.mark.skipif(os.name != 'nt', reason='D3DCompile is Windows only')
@pytest.mark.parametrize('name', ['lit_vs', 'lit_ps'])
def test_dxbc_roundtrip_reads_same_constants(name):
    """Recompiling the decompiled HLSL must read the same cbuffer registers and components."""
    import ctypes
    original = dxbc.parse((SHADERS / (name + '.cso')).read_bytes())
    code = hlsl.decompile(original).encode('utf-8')
    compiler = ctypes.WinDLL('d3dcompiler_47.dll')
    blob, errors = ctypes.c_void_p(), ctypes.c_void_p()
    assert compiler.D3DCompile(code, len(code), b'x.hlsl', None, None, b'main', ('%s_5_0' % original.program).encode(),
                               0, 0, ctypes.byref(blob), ctypes.byref(errors)) >= 0
    vtable = ctypes.cast(ctypes.cast(blob, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    pointer = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(vtable[3])(blob)
    size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(vtable[4])(blob)
    recompiled = dxbc.parse(ctypes.string_at(pointer, size))

    def reads(shader):
        found = set()
        for instruction in shader.instructions:
            for operand in instruction.operands[1:]:
                if operand.type == 8 and len(operand.indices) > 1 and operand.indices[1][1] is None:
                    found.update((operand.indices[1][0], c) for c in operand.components())
        return found
    assert reads(recompiled) <= reads(original) | {(r, c) for r, c in reads(original)}
    assert {r for r, _ in reads(recompiled)} == {r for r, _ in reads(original)}


def test_dxil_container():
    info = dxil.parse((SHADERS / 'lit_ps60.dxil.cso').read_bytes())
    assert info['kind'] == 'Pixel' and info['model'] == '6.0'
    assert {r['type'] for r in info['resources']} >= {'CBV', 'Sampler', 'SRVTyped'}
    assert any(e['name'] == 'TEXCOORD' for e in info['inputs'])


# ---------------------------------------------------------------------- projects / service

def test_project_dedup_and_annotations(store, tmp_path):
    ctx = context(tmp_path)
    first = service.open_file(SHADERS / 'lit_cs.cso', ctx)
    copy = tmp_path / 'renamed_copy.cso'
    copy.write_bytes((SHADERS / 'lit_cs.cso').read_bytes())
    second = service.open_file(copy, ctx)
    assert first['projectId'] == second['projectId'] and second['created'] is False
    service.analyze(first['projectId'], '', ctx)
    code = service.decompile(first['projectId'], 'main', context=ctx)
    assert code['language'] == 'hlsl' and 'numthreads(8, 8, 1)' in code['code']
    service.rename(first['projectId'], 'r0', 'value', function='main')
    service.rename(first['projectId'], 'Output', 'Result')
    service.set_comment(first['projectId'], 'main', 'Doubles bright texels')
    renamed = service.decompile(first['projectId'], 'main', context=ctx)['code']
    assert 'value.xyzw' in renamed and 'Result[vThreadID.xy]' in renamed
    assert renamed.startswith('// Doubles bright texels')
    raw = service.decompile(first['projectId'], 'main', context=ctx, annotate=False)['code']
    assert 'value.xyzw' not in raw
    with pytest.raises(CyToolError):
        service.rename(first['projectId'], 'r1', 'not valid!')


def test_export_and_search(store, tmp_path):
    ctx = context(tmp_path)
    project = service.open_file(SHADERS / 'lit_frag.spv', ctx)
    service.analyze(project['projectId'], '', ctx)
    hits = service.search(project['projectId'], 'tonemap', in_code=False)
    assert hits['hits'] == []
    service.decompile(project['projectId'], 'main', context=ctx)
    hits = service.search(project['projectId'], 'tonemap')
    assert any(h['type'] == 'code' for h in hits['hits'])
    result = service.export_sources(project['projectId'], tmp_path / 'export', context=ctx)
    assert result['written'] == 1
    assert (tmp_path / 'export' / 'main.glsl').read_text(encoding='utf-8').startswith('#version 450')


def test_native_engine_on_windows_binary(store, tmp_path):
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    binary = windows / 'SysWOW64' / 'find.exe'
    if not binary.is_file():
        pytest.skip('No 32-bit Windows binary available')
    ctx = context(tmp_path)
    ctx.options['symbols'] = False
    project = service.open_file(binary, ctx)
    summary = service.analyze(project['projectId'], 'native', ctx)
    assert summary['engine'] == 'native'
    listing = service.list_functions(project['projectId'], 'native', limit=1000)
    assert listing['total'] > 5
    entry = service.program_info(project['projectId'], 'native')['entryPoint']
    code = service.decompile(project['projectId'], entry, 'native', ctx)
    assert code['view'] == 'disassembly' and 'entry:' in code['code']
    assert any('KERNEL32' in i['library'].upper() for i in service.program_info(project['projectId'], 'native')['imports'])


NATIVE = FIXTURES / 'native'


@pytest.mark.parametrize('variant', ['x64_od', 'x64_o2', 'x86_od', 'x86_o2'])
def test_cdec_engine_on_fixtures(store, tmp_path, variant):
    """The built-in C decompiler: selected for x86/x64, every export decompiles, module C is whole."""
    ctx = context(tmp_path)
    ctx.options['symbols'] = False
    project = service.open_file(NATIVE / ('funcs_%s.dll' % variant), ctx)
    assert 'cdec' in project['format']['engines']
    assert project['format']['engines'].index('ghidra') < project['format']['engines'].index('cdec')
    service.analyze(project['projectId'], 'cdec', ctx)
    exports = [f for f in service.store.get(project['projectId']).functions('cdec') if f.get('exported')]
    assert len(exports) == 30
    for function in exports:
        result = service.decompile(project['projectId'], function['id'], 'cdec', ctx)
        assert result['language'] == 'c' and result['view'] == 'decompiled'
        assert function['name'] + '(' in result['code'] and 'unsupported' not in result['code']
    module = service.c_module(project['projectId'], [], str(tmp_path / 'module.c'), True, ctx)
    text = (tmp_path / 'module.c').read_text(encoding='utf-8')
    assert len(module['functions']) == 30 and text == module['code']
    assert text.count('{') == text.count('}') and 'typedef' in text


def test_cdec_switch_and_loops_are_structured(store, tmp_path):
    from cydec.cdec.decompiler import decompile
    from cydec.engines.native import load_pe
    image = load_pe(NATIVE / 'funcs_x64_od.dll')
    names = dict(image.exports)
    by_name = {v: k for k, v in names.items()}
    classify = decompile(image, by_name['classify'], 'classify', names, set(names), 'pe')
    assert 'switch (' in classify and 'case 7:' in classify
    gcd = decompile(image, by_name['gcd'], 'gcd', names, set(names), 'pe')
    assert 'while' in gcd and 'goto' not in gcd


def test_cdec_never_crashes_on_system_binaries(store, tmp_path):
    """Robustness: real compiler output from Windows (both bitnesses) decompiles without exceptions."""
    from cydec.cdec.decompiler import decompile
    from cydec.engines import get as get_engine
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    binaries = [b for b in (windows / 'System32' / 'find.exe', windows / 'SysWOW64' / 'find.exe') if b.is_file()]
    if not binaries:
        pytest.skip('No Windows binaries available')
    ctx = context(tmp_path)
    ctx.options['symbols'] = False
    for binary in binaries:
        project = service.open_file(binary, ctx)
        service.analyze(project['projectId'], 'cdec', ctx)
        functions = service.store.get(project['projectId']).functions('cdec')
        assert functions
        for function in functions[:60]:
            code = service.decompile(project['projectId'], function['id'], 'cdec', ctx)['code']
            assert code.count('{') >= 1


def test_cdec_equivalence_with_msvc(tmp_path):
    """Decompile, recompile with MSVC and run original vs decompiled on random inputs."""
    from cydec.ai.verify import msvc_vcvars
    vcvars = msvc_vcvars()
    if not vcvars:
        pytest.skip('Visual Studio C++ tools not installed')
    sys.path.insert(0, str(APP / 'tests'))
    import native_equivalence
    for variant in ('x64_o2', 'x86_od'):
        report, _ = native_equivalence.run_variant(variant, vcvars, iterations=400, keep=str(tmp_path / variant))
        assert report.get('compiled'), report.get('compileErrors')
        assert not report.get('different'), report['different']
        assert len(report['equivalent']) == 30


@pytest.mark.parametrize('variant', ['O0.dll', 'O2.dll', 'O0.so', 'O2.so'])
def test_cdec_arm64_fixtures(store, tmp_path, variant):
    """ARM64 (PE and ELF): the engine is offered, every export decompiles with every instruction
    modelled, and the module is one balanced C file."""
    ctx = context(tmp_path)
    ctx.options['symbols'] = False
    project = service.open_file(NATIVE / ('funcs_arm64_' + variant), ctx)
    assert project['format']['arch'] == 'arm64' and 'cdec' in project['format']['engines']
    service.analyze(project['projectId'], 'cdec', ctx)
    exports = [f for f in service.store.get(project['projectId']).functions('cdec') if f.get('exported')]
    assert len(exports) == 30
    for function in exports:
        code = service.decompile(project['projectId'], function['id'], 'cdec', ctx)['code']
        assert function['name'] + '(' in code and 'unsupported' not in code and '__condition' not in code
    module = service.c_module(project['projectId'], [], '', True, ctx)
    assert len(module['functions']) == 30 and module['code'].count('{') == module['code'].count('}')


def test_cdec_arm64_equivalence_emulated(tmp_path):
    """Original ARM64 code in the Unicorn emulator vs the decompiled C recompiled for x64."""
    pytest.importorskip('unicorn')
    from cydec.ai.verify import msvc_vcvars
    vcvars = msvc_vcvars()
    if not vcvars:
        pytest.skip('Visual Studio C++ tools not installed')
    sys.path.insert(0, str(APP / 'tests'))
    import arm64_equivalence
    for variant in ('O2.so', 'O0.dll'):
        report = arm64_equivalence.run_variant(variant, vcvars, iterations=60, keep=str(tmp_path / variant))
        assert report.get('compiled'), report.get('compileErrors')
        assert not report.get('different'), {n: report['functions'][n] for n in report['different']}
        assert len(report['equivalent']) == 30


def test_updates_repository_token_and_staged_tree(tmp_path, monkeypatch):
    """Application updates: official repository by default, token sent only as a header,
    a release tree (app/ + release.json) passes verification."""
    import shutil
    import urllib.request
    from cydec import paths, updates
    from cydec.ai import credentials
    monkeypatch.setattr(paths, 'SETTINGS', tmp_path / 'settings')
    monkeypatch.setattr(credentials, 'STORE', tmp_path / 'settings' / 'credentials.json')
    assert updates.settings()['applicationRepository'] == 'MrMybal/CyDecompilator'
    monkeypatch.setenv('GITHUB_TOKEN', 'test-token-value')
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args):
            return b'{"tag_name": "v99.0.0", "assets": [{"name": "CyDecompilator-99.0.0.zip", "size": 10}]}'

    def fake_urlopen(request, timeout=0):
        seen['url'] = request.full_url
        seen['auth'] = request.get_header('Authorization')
        return Response()
    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    row = updates.check()
    assert seen['url'].endswith('/repos/MrMybal/CyDecompilator/releases/latest')
    assert seen['auth'] == 'Bearer test-token-value'
    assert row['updateAvailable'] and row['available'] == 'v99.0.0'
    assert 'test-token-value' not in json.dumps(updates.state())
    staged = tmp_path / 'stage' / 'CyDecompilator' / 'app'
    shutil.copytree(APP, staged, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'fixtures', 'tests'))
    (staged / 'release.json').write_text(json.dumps({'runtimeAbi': updates.RUNTIME_ABI}), encoding='utf-8')
    report = updates.verify_application_tree(tmp_path / 'stage')
    assert report['version'] == updates.current_version() and report['toolId'] == 'cy.tool.decompilator'


def test_interface_translations_complete_and_safe():
    """Every interface language translates every English string, keeps format placeholders,
    surrounding spaces and ImGui identifiers, and tr() switches language without restart."""
    import ui_common
    catalog = json.loads((APP / 'locales' / 'ui.json').read_text(encoding='utf-8-sig'))
    english = {entry['en'] for entry in catalog.values() if 'en' in entry}
    placeholder = re.compile(r'%[-+ #0]*\d*(?:\.\d+)?[sdfxXrc%]|\{[^{}]*\}')
    for code, _ in ui_common.LANGUAGES[2:]:
        path = APP / 'locales' / ('ui.%s.json' % code)
        assert path.is_file(), code
        table = json.loads(path.read_text(encoding='utf-8'))
        assert set(table) == english, (code, len(english - set(table)), len(set(table) - english))
        for source, text in table.items():
            assert isinstance(text, str) and (text or not source), (code, source)
            assert sorted(placeholder.findall(source)) == sorted(placeholder.findall(text)), (code, source, text)
            assert source[:len(source) - len(source.lstrip())] == text[:len(text) - len(text.lstrip())], (code, source)
            assert source[len(source.rstrip()):] == text[len(text.rstrip()):], (code, source)
            if '###' in source:
                assert source.split('###', 1)[1] == text.split('###', 1)[1], (code, source)
    saved = ui_common.preferences.values['language']
    try:
        for code, _ in ui_common.LANGUAGES:
            ui_common.preferences.values['language'] = code
            text = ui_common.tr('Open file...')
            assert text and (code == 'en' or text != 'Open file...'), code
    finally:
        ui_common.preferences.values['language'] = saved


def test_pe_details_and_symbols(store, tmp_path, monkeypatch):
    from cydec import pdb, pe_info
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    binary = windows / 'SysWOW64' / 'find.exe'
    if not binary.is_file():
        pytest.skip('No 32-bit Windows binary available')
    info = pe_info.analyse(binary)
    assert info['kind'] == 'EXE' and info['bits'] == 32 and 'DYNAMIC_BASE (ASLR)' in info['protections']
    assert info['pdb'] and info['pdb']['file'] == 'find.pdb'
    assert info['version'].get('OriginalFilename', '').lower().startswith('find')
    kernel = pe_info.analyse(windows / 'System32' / 'kernel32.dll')
    assert kernel['kind'] == 'DLL' and any(e['forwarder'] for e in kernel['exports'])
    assert not any(p['id'] == 'nsis' for p in kernel['packers'])
    monkeypatch.setattr(pdb, 'SYMBOLS', tmp_path / 'symbols')
    try:
        path = pdb.fetch(info['pdb'])
    except CyToolError as exc:
        pytest.skip('Symbol server unreachable: %s' % exc)
    import pefile
    pe = pefile.PE(str(binary), fast_load=True)
    names = {s['display'] for s in pdb.read_symbols(path, [s.VirtualAddress for s in pe.sections])}
    assert 'FIND::SearchStream' in names and 'FIND::~FIND' in names


def test_demangler():
    from cydec.pdb import demangle
    assert demangle('??_GFIND@@UAEPAXI@Z') == 'FIND::{scalar deleting dtor}'
    assert demangle('??1FIND@@UAE@XZ') == 'FIND::~FIND'
    assert demangle('?Initialize@FIND@@QAEXHPAPA_W@Z') == 'FIND::Initialize'
    assert demangle('_GetFoo@8') == 'GetFoo'
    assert demangle('??_7FIND@@6B@') == "FIND::`vftable'"


def build_pyinstaller_archive(tmp_path):
    """A minimal CArchive (PyInstaller 6 layout) with one entry script and a PYZ of one module."""
    import marshal
    import struct
    import zlib
    from cydec.pe_info import PYINSTALLER_MAGIC
    script = marshal.dumps(compile('print("hi")', 'main.py', 'exec'))
    module = marshal.dumps(compile('VALUE = 42', 'pkg/mod.py', 'exec'))
    import importlib.util
    magic = importlib.util.MAGIC_NUMBER
    module_blob = zlib.compress(module)
    pyz_body = b'PYZ\0' + magic + b'\0\0\0\0'
    module_offset = len(pyz_body)
    pyz_body += module_blob
    toc_offset = len(pyz_body)
    pyz_body += marshal.dumps([('pkg.mod', (0, module_offset, len(module_blob)))])
    pyz = pyz_body[:8] + struct.pack('!I', toc_offset) + pyz_body[12:]
    entries = [('main', zlib.compress(script), len(script), 1, b's'), ('PYZ-00.pyz', pyz, len(pyz), 0, b'z')]
    package = b''
    toc = b''
    for name, blob, size, compressed, kind in entries:
        encoded = name.encode() + b'\0'
        entry_size = 18 + len(encoded)
        entry_size += (16 - entry_size % 16) % 16
        toc += struct.pack('!IIIIBc', entry_size, len(package), len(blob), size, compressed, kind) + \
            encoded.ljust(entry_size - 18, b'\0')
        package += blob
    toc_offset = len(package)
    package += toc
    version = sys.version_info[0] * 100 + sys.version_info[1]
    cookie = PYINSTALLER_MAGIC + struct.pack('!IIII', len(package) + 88, toc_offset, len(toc), version) + \
        b'python%d%d.dll' % sys.version_info[:2] + b'\0' * (64 - len(b'python%d%d.dll' % sys.version_info[:2]))
    stub = (Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'SysWOW64' / 'find.exe')
    data = (stub.read_bytes() if stub.is_file() else b'MZ' + b'\0' * 1022) + package + cookie
    target = tmp_path / 'bundle.exe'
    target.write_bytes(data)
    return target


def test_pyinstaller_extraction(tmp_path):
    from cydec import unpack
    bundle = build_pyinstaller_archive(tmp_path)
    result = unpack.pyinstaller(bundle.read_bytes(), tmp_path / 'out')
    names = {f['name'] for f in result['files']}
    assert 'main.pyc' in names and 'pkg/mod.pyc' in names
    assert result['pythonVersion'] == '%d.%d' % sys.version_info[:2]
    import importlib.util
    main = (tmp_path / 'out' / 'main.pyc').read_bytes()
    assert main[:4] == importlib.util.MAGIC_NUMBER
    assert detect.detect(tmp_path / 'out' / 'PYZ-00.pyz_extracted' / 'pkg' / 'mod.pyc')['format'] == 'pyc'


def test_python_engine_builtin(store, tmp_path):
    source = tmp_path / 'mod.py'
    source.write_text('class A:\n    def m(self, x):\n        return x * 2\n\ndef f():\n    return A().m(21)\n', encoding='utf-8')
    pyc = tmp_path / 'mod.pyc'
    py_compile.compile(str(source), cfile=str(pyc))
    ctx = context(tmp_path)
    project = service.open_file(pyc, ctx)
    service.analyze(project['projectId'], 'python', ctx)
    names = [f['id'] for f in service.list_functions(project['projectId'])['functions']]
    assert '<module>' in names and 'A.m' in names and 'f' in names
    code = service.decompile(project['projectId'], 'A.m', context=ctx, view='disassembly')['code']
    assert 'BINARY_OP' in code or 'BINARY_MULTIPLY' in code


@pytest.mark.skipif(components.locate('ilspycmd') is None or components.locate('dotnet') is None,
                    reason='ILSpy component not installed')
def test_ilspy_engine(store, tmp_path):
    dotnet = Path(components.locate('dotnet')['path'])
    assembly = next(dotnet.glob('shared/Microsoft.NETCore.App/*/System.Text.Json.dll'), None)
    if assembly is None:
        pytest.skip('No managed assembly to test with')
    ctx = context(tmp_path)
    project = service.open_file(assembly, ctx)
    assert project['format']['format'] == 'pe-dotnet'
    service.analyze(project['projectId'], 'ilspy', ctx)
    code = service.decompile(project['projectId'], 'System.Text.Json.JsonException', 'ilspy', ctx)
    assert 'class JsonException : Exception' in code['code']


# ---------------------------------------------------------------------- safety and parsing

def test_extract_refuses_traversal(tmp_path):
    archive = tmp_path / 'evil.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('ok/file.txt', 'fine')
        bundle.writestr('../escape.txt', 'bad')
    with pytest.raises(CyToolError) as error:
        components.extract(archive, tmp_path / 'out')
    assert error.value.code == 'IntegrityFailure'
    assert not (tmp_path / 'escape.txt').exists()


def test_process_cancellation_stops_child(tmp_path):
    from cydec import process

    class Token:
        cancelled = False

        def check(self):
            if self.cancelled:
                raise CyToolError('Cancelled', 'Cancelled')

    token = Token()
    ctx = context(tmp_path, token)
    threading.Timer(0.5, lambda: setattr(token, 'cancelled', True)).start()
    started = time.monotonic()
    with pytest.raises(CyToolError):
        process.run([sys.executable, '-c', 'import time; time.sleep(60)'], context=ctx)
    assert time.monotonic() - started < 15


def test_ai_reply_parsers():
    from cydec.ai import assistant
    reply = 'Sure.\n```json\n{"tool": "decompile", "arguments": {"function": "main"}}\n```'
    assert assistant.extract_json(reply) == {'tool': 'decompile', 'arguments': {'function': 'main'}}
    assert assistant.extract_json('{"answer": "a {brace} inside"} trailing') == {'answer': 'a {brace} inside'}
    assert assistant.extract_json('no json here') is None
    code = assistant.extract_code('Here:\n```c\nint main(void) { return 0; }\n```\nNotes.')
    assert code == 'int main(void) { return 0; }\n'


def test_compile_checks():
    from cydec.ai import verify
    assert verify.check('python', 'def f(:\n')['status'] == 'failed'
    assert verify.check('python', 'def f():\n    return 1\n')['status'] == 'passed'
    assert verify.check('cobol', 'x')['status'] == 'unavailable'


# ---------------------------------------------------------------------- runtime contract

@pytest.fixture()
def runtime(tmp_path, monkeypatch, store):
    monkeypatch.setenv('CYTOOLS_TOKEN', 'preset-token-for-tests')
    from tool import create_runtime, declared_permissions
    value = create_runtime(tmp_path / 'jobs')
    value.start()
    yield value, declared_permissions(value)
    value.close(10)


def test_manifest_matches_handlers(runtime):
    value, permissions = runtime
    manifest = json.loads((APP / 'CyTool.json').read_text(encoding='utf-8'))
    import operations
    assert [o['id'] for o in manifest['operations']] == [o['id'] for o in operations.OPERATIONS]
    assert set(permissions) <= {'network', 'processSpawn', 'filesystemExternal'}


def test_runtime_job_and_client_isolation(runtime):
    value, permissions = runtime
    alice = value.authenticate(value.create_client('alice', permissions)['token'])
    bob = value.authenticate(value.create_client('bob', permissions)['token'])
    session = value.create_session(alice)['sessionId']
    job = value.submit(alice, session, 'open_file', {'path': str(SHADERS / 'lit_vs.cso')})
    done = value.wait(alice, job['jobId'], timeout=60)
    assert done['state'] == 'Completed', done.get('error')
    assert done['outputs']['engine'] == 'shader'
    with pytest.raises(CyToolError):
        value.get_job(bob, job['jobId'])
    with pytest.raises(CyToolError):
        value.cancel(bob, job['jobId'])
    restricted = value.authenticate(value.create_client('restricted', [])['token'])
    other = value.create_session(restricted)['sessionId']
    with pytest.raises(CyToolError) as error:
        value.submit(restricted, other, 'install_component', {'component': 'vineflower'})
    assert error.value.code == 'AccessDenied'


def test_invalid_parameters_are_refused(runtime):
    value, permissions = runtime
    actor = value.authenticate(value.create_client('c', permissions)['token'])
    session = value.create_session(actor)['sessionId']
    with pytest.raises(CyToolError):
        value.submit(actor, session, 'decompile', {'projectId': 'x'})
    job = value.submit(actor, session, 'decompile', {'projectId': 'missing-project', 'function': 'main'})
    result = value.wait(actor, job['jobId'], timeout=30)
    assert result['state'] == 'Failed'
