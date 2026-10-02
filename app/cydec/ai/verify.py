"""Compile checks for AI-converted code, using whatever toolchain this machine has.

A check never runs the code: it only parses or compiles it into a temporary folder. When
no compiler for the language is installed the result says so ("unavailable"), which is
different from passing. Errors are returned verbatim so the AI can repair its output.
"""
import ast
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def _run(command, cwd, timeout=120):
    try:
        command = command if isinstance(command, str) else [str(c) for c in command]
        result = subprocess.run(command, cwd=str(cwd), capture_output=True,
                                timeout=timeout, creationflags=CREATE_NO_WINDOW)
        raw = result.stdout + result.stderr
        try:
            output = raw.decode('utf-8')
        except UnicodeDecodeError:
            # Windows console tools (cl, cmd) write in the OEM code page.
            output = raw.decode('oem' if os.name == 'nt' else 'latin-1', 'replace')
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return -1, 'Compiler timed out.'
    except OSError as exc:
        return -1, str(exc)


def _python(code, folder):
    try:
        ast.parse(code)
        compile(code, '<converted>', 'exec')
        return {'status': 'passed', 'tool': 'CPython %d.%d compile()' % __import__('sys').version_info[:2], 'output': ''}
    except SyntaxError as exc:
        return {'status': 'failed', 'tool': 'CPython compile()', 'output': 'line %s: %s' % (exc.lineno, exc.msg)}


def _c_family(code, folder, cpp):
    source = folder / ('converted.cpp' if cpp else 'converted.c')
    source.write_text(code, encoding='utf-8')
    for compiler in (('clang++', 'g++') if cpp else ('clang', 'gcc')):
        path = shutil.which(compiler)
        if path:
            code_, output = _run([path, '-fsyntax-only', '-w', str(source)], folder)
            return {'status': 'passed' if code_ == 0 else 'failed', 'tool': compiler, 'output': output[-4000:]}
    cl = shutil.which('cl')
    if cl:
        code_, output = _run([cl, '/nologo', '/Zs', str(source)], folder)
        return {'status': 'passed' if code_ == 0 else 'failed', 'tool': 'cl', 'output': output[-4000:]}
    vcvars = msvc_vcvars()
    if vcvars:
        flag = '/TP' if cpp else '/TC'
        line = 'call "%s" >nul && cl /nologo /Zs /std:%s %s "%s"' % (vcvars, 'c++17' if cpp else 'c17', flag, source)
        # One string, so cmd.exe receives the quotes untouched (/s strips only the outer pair).
        code_, output = _run('cmd.exe /s /c "%s"' % line, folder, 180)
        return {'status': 'passed' if code_ == 0 else 'failed', 'tool': 'MSVC cl', 'output': output[-4000:]}
    return {'status': 'unavailable', 'tool': '', 'output': 'No C/C++ compiler (clang, gcc, cl or Visual Studio C++ tools).'}


_vcvars = []


def msvc_vcvars():
    """vcvars64.bat of the newest Visual Studio with the C++ tools, located with vswhere."""
    if _vcvars:
        return _vcvars[0]
    result = None
    if os.name == 'nt':
        vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        if vswhere.is_file():
            code_, output = _run([vswhere, '-latest', '-products', '*', '-requires',
                                  'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'],
                                 Path.cwd(), 30)
            install = output.strip().splitlines()[0] if code_ == 0 and output.strip() else ''
            candidate = Path(install) / 'VC/Auxiliary/Build/vcvars64.bat' if install else None
            if candidate is not None and candidate.is_file():
                result = str(candidate)
    _vcvars.append(result)
    return result


def _java(code, folder):
    import re
    from .. import components
    jdk = components.locate('jdk')
    javac = Path(jdk['java']).with_name('javac' + ('.exe' if os.name == 'nt' else '')) if jdk else None
    if javac is None or not javac.is_file():
        return {'status': 'unavailable', 'tool': '', 'output': 'No javac (install the jdk component).'}
    match = re.search(r'public\s+(?:final\s+|abstract\s+)*(?:class|interface|enum|record)\s+(\w+)', code)
    source = folder / ((match.group(1) if match else 'Converted') + '.java')
    source.write_text(code, encoding='utf-8')
    code_, output = _run([javac, '-proc:none', '-d', str(folder / 'out'), str(source)], folder)
    return {'status': 'passed' if code_ == 0 else 'failed', 'tool': 'javac', 'output': output[-4000:]}


def _hlsl(code, folder):
    if os.name != 'nt':
        return {'status': 'unavailable', 'tool': '', 'output': 'HLSL check uses d3dcompiler_47 (Windows).'}
    import ctypes
    try:
        compiler = ctypes.WinDLL('d3dcompiler_47.dll')
    except OSError:
        return {'status': 'unavailable', 'tool': '', 'output': 'd3dcompiler_47.dll not found.'}
    source = code.encode('utf-8')
    blob = ctypes.c_void_p()
    errors = ctypes.c_void_p()
    import re
    profile = 'ps_5_0'
    if re.search(r'\[numthreads', code):
        profile = 'cs_5_0'
    elif re.search(r'SV_Position\s*;', code) and 'VSOutput' in code:
        profile = 'vs_5_0'
    entry = 'main'
    function = compiler.D3DCompile
    function.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint,
                         ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    function.restype = ctypes.c_long
    result = function(source, len(source), b'converted.hlsl', None, None, entry.encode(), profile.encode(),
                      0, 0, ctypes.byref(blob), ctypes.byref(errors))
    message = ''
    if errors.value:
        # ID3DBlob vtable: QueryInterface, AddRef, Release, GetBufferPointer, GetBufferSize
        vtable = ctypes.cast(ctypes.cast(errors, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        get_pointer = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(vtable[3])
        get_size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(vtable[4])
        message = ctypes.string_at(get_pointer(errors), get_size(errors)).decode('utf-8', 'replace')
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        release(errors)
    if blob.value:
        vtable = ctypes.cast(ctypes.cast(blob, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(blob)
    return {'status': 'passed' if result >= 0 else 'failed', 'tool': 'D3DCompile %s' % profile,
            'output': message[-4000:]}


def _csharp(code, folder):
    dotnet = shutil.which('dotnet')
    if not dotnet:
        return {'status': 'unavailable', 'tool': '', 'output': 'No .NET SDK on PATH.'}
    code_, output = _run([dotnet, '--list-sdks'], folder, 30)
    if code_ != 0 or not output.strip():
        return {'status': 'unavailable', 'tool': '', 'output': 'A .NET runtime is installed but no SDK.'}
    (folder / 'Converted.csproj').write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Library</OutputType>'
        '<TargetFramework>net%s.0</TargetFramework><Nullable>enable</Nullable>'
        '<AllowUnsafeBlocks>true</AllowUnsafeBlocks><ImplicitUsings>enable</ImplicitUsings>'
        '</PropertyGroup></Project>' % output.split('.')[0].strip(), encoding='utf-8')
    (folder / 'Converted.cs').write_text(code, encoding='utf-8')
    code_, output = _run([dotnet, 'build', '-nologo', '-v', 'q', '-clp:ErrorsOnly'], folder, 300)
    return {'status': 'passed' if code_ == 0 else 'failed', 'tool': 'dotnet build', 'output': output[-4000:]}


def _rust(code, folder):
    rustc = shutil.which('rustc')
    if not rustc:
        return {'status': 'unavailable', 'tool': '', 'output': 'No rustc on PATH.'}
    source = folder / 'converted.rs'
    source.write_text(code, encoding='utf-8')
    code_, output = _run([rustc, '--crate-type', 'lib', '--emit', 'metadata', '-o', str(folder / 'out.rmeta'), str(source)], folder)
    return {'status': 'passed' if code_ == 0 else 'failed', 'tool': 'rustc', 'output': output[-4000:]}


def _go(code, folder):
    go = shutil.which('go')
    if not go:
        return {'status': 'unavailable', 'tool': '', 'output': 'No go toolchain on PATH.'}
    (folder / 'converted.go').write_text(code, encoding='utf-8')
    code_, output = _run([go, 'vet', 'converted.go'], folder)
    return {'status': 'passed' if code_ == 0 else 'failed', 'tool': 'go vet', 'output': output[-4000:]}


CHECKERS = {'python': _python, 'c': lambda c, f: _c_family(c, f, False), 'cpp': lambda c, f: _c_family(c, f, True),
            'java': _java, 'hlsl': _hlsl, 'csharp': _csharp, 'rust': _rust, 'go': _go}


def check(language, code):
    checker = CHECKERS.get(language)
    if checker is None:
        return {'status': 'unavailable', 'tool': '', 'output': 'No compile check for %s.' % language}
    folder = Path(tempfile.mkdtemp(prefix='cydec-verify-'))
    try:
        return checker(code, folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def available():
    """Languages that can be checked on this machine right now."""
    result = {}
    for language in CHECKERS:
        if language == 'python':
            result[language] = True
        elif language in ('c', 'cpp'):
            result[language] = any(shutil.which(c) for c in ('clang', 'gcc', 'cl', 'clang++', 'g++')) or bool(msvc_vcvars())
        elif language == 'java':
            from .. import components
            jdk = components.locate('jdk')
            result[language] = bool(jdk and jdk.get('javac'))
        elif language == 'hlsl':
            result[language] = os.name == 'nt'
        elif language == 'csharp':
            dotnet = shutil.which('dotnet')
            result[language] = bool(dotnet) and bool(_run([dotnet, '--list-sdks'], Path.cwd(), 30)[1].strip())
        else:
            result[language] = bool(shutil.which({'rust': 'rustc', 'go': 'go'}[language]))
    return result
