"""Compile the native geometry-capture and DXR shaders with the Windows SDK."""
from pathlib import Path
import os
import subprocess

MODULE = Path(__file__).resolve().parents[1]


def build(work):
    kits = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Windows Kits/10/bin'
    versions = sorted((p for p in kits.iterdir() if p.name[0].isdigit()),
                      key=lambda p: tuple(int(n) for n in p.name.split('.')))
    tools = versions[-1] / 'x64'
    output = work / 'rt'; output.mkdir(exist_ok=True)
    includes = []
    for count in range(17):
        subprocess.run([str(tools / 'fxc.exe'), '/nologo', '/T', 'gs_5_1', '/E', 'main', '/O3',
                        '/D', f'NATIVE_RT_INTERPOLATORS={count}', '/Vn', f'native_rt_capture_{count}',
                        '/Fh', str(output / f'rt_capture_{count}.h'), str(MODULE / 'native/rt_capture.hlsl')], check=True,
                       stdout=subprocess.DEVNULL)
        includes.append(f'#include "rt_capture_{count}.h"')
        subprocess.run([str(tools / 'fxc.exe'), '/nologo', '/T', 'gs_5_1', '/E', 'main', '/O3',
                        '/D', f'NATIVE_RT_INTERPOLATORS={count}', '/D', 'NATIVE_RT_SURFACE=1',
                        '/Vn', f'native_rt_surface_{count}', '/Fh', str(output / f'rt_surface_{count}.h'),
                        str(MODULE / 'native/rt_capture.hlsl')], check=True, stdout=subprocess.DEVNULL)
        includes.append(f'#include "rt_surface_{count}.h"')
    table = ['struct NativeCaptureBytecode { const void *data; size_t size; };',
             'static const NativeCaptureBytecode native_capture_variants[] = {']
    table.extend(f'{{native_rt_capture_{n}, sizeof(native_rt_capture_{n})}},' for n in range(17))
    table += ['};','static const NativeCaptureBytecode native_surface_variants[] = {']
    table.extend(f'{{native_rt_surface_{n}, sizeof(native_rt_surface_{n})}},' for n in range(17))
    (output / 'rt_capture_variants.h').write_text('\n'.join(includes+table+['};'])+'\n')
    for name, compiler, profile in [('capture', 'fxc.exe', 'gs_5_1'), ('ambient', 'dxc.exe', 'cs_6_5'), ('denoise', 'dxc.exe', 'cs_6_5')]:
        source = MODULE / f'native/rt_{name}.hlsl'
        prefix = '/' if compiler == 'fxc.exe' else '-'
        command = [str(tools / compiler), prefix+'nologo', prefix+'T', profile,
                   prefix+'E', 'main', prefix+'O3', prefix+'Vn', f'native_rt_{name}',
                   prefix+'Fh', str(output / f'rt_{name}.h'), str(source)]
        if compiler == 'dxc.exe': command.remove('-nologo')
        subprocess.run(command, check=True)
