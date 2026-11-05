"""Compile the pinned MIT SMAA reference for the native three-pass pipeline."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

MODULE = Path(__file__).resolve().parents[1]


def build(work):
    source = MODULE / 'third_party/smaa'
    receipt = json.loads((source / 'source.json').read_text())
    for name, digest in receipt['files'].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Pinned SMAA input changed: ' + name)
    directory = work / 'smaa'; directory.mkdir(exist_ok=True)
    # Compute has no implicit derivatives or pixel discard. Keep zero edge
    # masks through the remaining math instead of discarding the pixel. The
    # result matches a cleared render target without leaving unwritten texels.
    shader = (source / 'SMAA.hlsl').read_text()
    shader = shader.replace('discard;', '; // compute: retain zero edge mask')
    shader = shader.replace('float4 delta;', 'float4 delta = 0;')
    shader = shader.replace('tex.Sample(LinearSampler, coord)', 'tex.SampleLevel(LinearSampler, coord, 0)')
    shader = shader.replace('tex.Sample(PointSampler, coord)', 'tex.SampleLevel(PointSampler, coord, 0)')
    shader = shader.replace('tex.Sample(LinearSampler, coord, offset)', 'tex.SampleLevel(LinearSampler, coord, 0, offset)')
    (directory / 'SMAA.compute.hlsl').write_text(shader)
    kits = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Windows Kits/10/bin'
    compilers = sorted(kits.glob('*/x64/fxc.exe'))
    if not compilers: raise RuntimeError('Windows SDK fxc.exe required to build native SMAA')
    for entry in ('edges', 'weights', 'blend'):
        subprocess.run([str(compilers[-1]), '/nologo', '/T', 'cs_5_1', '/E', entry,
                        '/O3', '/I', str(directory), '/Vn', 'native_smaa_' + entry,
                        '/Fh', str(directory / ('smaa_' + entry + '.h')),
                        str(MODULE / 'native/smaa_compute.hlsl')], check=True)
