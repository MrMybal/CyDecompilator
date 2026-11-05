"""Stage the locally built GPU plugin in the playable project, with a rollback copy."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

MODULE = Path(__file__).resolve().parents[1]
PREVIOUS_SMAA = '4af88f3ceec6ec8329d560726f509558092d145d644acc33ba51338427416b70'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(project):
    receipt = json.loads((MODULE / 'work/gpu-occlusion/plugin.json').read_text())
    source = Path(receipt['plugin']).resolve(strict=True)
    owned_root = (MODULE / 'work/gpu-occlusion/build').resolve()
    if source.parent != owned_root or sha(source) != receipt['sha256']:
        raise ValueError('Local plugin does not match its build receipt')
    build = project.resolve(strict=True) / 'build'
    target = build / 'rexgpu-xenos-occlusion.dll'
    install_receipt = build / 'native-gpu-install.json'
    previous = json.loads(install_receipt.read_text()) if install_receipt.exists() else {}
    if target.exists() and sha(target) not in (PREVIOUS_SMAA, receipt['sha256'], previous.get('sha256')):
        raise ValueError('Playable GPU plugin has external changes; leaving it untouched')
    backup = build / 'rexgpu-xenos-occlusion.dll.pre-native-rt.bak'
    if target.exists() and sha(target) != receipt['sha256'] and not backup.exists():
        shutil.copy2(target, backup)
    if not target.exists() or sha(target) != receipt['sha256']:
        shutil.copy2(source, target)
    record = dict(source=str(source), installed=str(target), sha256=sha(target),
                  rollback=str(backup), native_raytracing=receipt.get('native_raytracing'))
    install_receipt.write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=MODULE / 'work/halo-rex/project')
    print(json.dumps(install(parser.parse_args().project), indent=2))
