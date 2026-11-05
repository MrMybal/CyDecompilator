"""Keep known invalid Halo branch destinations fatal instead of silently returning.

ReXGlue 0.10.0 emits a return for two bdz targets at 0x8317EE64. In this exact
image that address contains the illegal instruction word 0, just beyond the
owning .pdata extent. We preserve the conditional branch and fail if reached.
This does not invent valid code for that address or change the original XEX.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tomllib

HALO_SHA = '1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19'
OLD = 'if (ctx.ctr.u32 == 0) { /* branch to 0x8317EE64 outside function */ return; }'
NEW = 'if (ctx.ctr.u32 == 0) { __builtin_trap(); /* illegal guest instruction at 0x8317EE64 */ }'


def guard(project):
    manifests = list(project.glob('*_manifest.toml'))
    if len(manifests) != 1:
        raise ValueError('Expected one project manifest')
    manifest = tomllib.loads(manifests[0].read_text(encoding='utf-8'))
    xex = (project / manifest['entrypoint']['file_path']).resolve(strict=True)
    with xex.open('rb') as stream:
        identity = hashlib.file_digest(stream, 'sha256').hexdigest()
    if identity != HALO_SHA:
        raise ValueError('These branch guards require the exact verified Halo executable')
    generated = (project / manifest['entrypoint']['out_directory_path']).resolve(strict=True)
    if project not in generated.parents:
        raise ValueError('Generated sources must be inside the project')
    found = []
    for path in generated.glob('*.cpp'):
        contents = path.read_text(encoding='utf-8')
        count = contents.count(OLD) + contents.count(NEW)
        if count:
            found.append((path, contents, count))
    if sum(count for _, _, count in found) != 2:
        raise ValueError('Expected exactly two reviewed bdz guards; inspect changed codegen')
    for path in generated.glob('*.cpp'):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if 'outside function' in line and OLD not in line:
                raise ValueError(f'Unreviewed external branch in {path.name}:{number}: {line.strip()}')
    files = []
    for path, contents, count in found:
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        if OLD in contents:
            path.write_text(contents.replace(OLD, NEW), encoding='utf-8')
        files.append(dict(file=path.name, sites=count, before_sha256=before,
                          after_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    receipt = dict(schema_version=1, executable_sha256=identity, guarded_sites=2,
                   target_pc='0x8317EE64', original_word='0x00000000', files=files)
    (project / 'branch-guards.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    from rex_halo_test_patches import apply
    apply(project, identity)
    from rex_halo_menu_patch import apply as apply_menu
    apply_menu(project)
    from rex_halo_animation_patch import apply as apply_animation
    apply_animation(project)
    from rex_halo_physics_patch import apply as apply_physics
    apply_physics(project)
    from rex_multiplayer_patch import prepare
    prepare(project)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(guard(args.project.resolve()), indent=2))
