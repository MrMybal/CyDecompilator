"""Refresh the selected, unmodified Python CyUI sources from a pinned checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


REVISION = 'ff023e646c6a3038b3dfbfd53f6d2b4a2f5955e3'
MODULES = ('__init__', 'common', 'locale', '_locale_catalog', 'filters', 'code',
           'diff', 'commands', 'diagnostics', 'documents', 'inspector', 'canvas', 'images')
APP = Path(__file__).resolve().parents[1]


def vendor(checkout):
    checkout = Path(checkout).resolve()
    git = ['git', '-c', 'safe.directory=' + checkout.as_posix(), '-C', str(checkout)]
    files = {'python/cyui.py': 'vendor/cyui.py', 'LICENSE': 'vendor/CYUI_LICENSE.txt'}
    files.update({'python/cyui_modules/' + name + '.py': 'cyui_modules/' + name + '.py'
                  for name in MODULES})
    hashes = {}
    for source, destination in files.items():
        data = subprocess.check_output(git + ['show', REVISION + ':' + source])
        target = APP / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[destination] = hashlib.sha256(data).hexdigest()
    metadata = {'library': 'CyUI', 'version': '1.2.0',
                'repository': 'https://github.com/MrMybal/CyUI', 'revision': REVISION,
                'source': 'python/cyui.py', 'sha256': hashes['vendor/cyui.py'],
                'license': 'MIT', 'licenseUrl': 'https://github.com/MrMybal/CyUI/blob/' + REVISION + '/LICENSE',
                'files': hashes,
                'modules': ['Core', 'Code', 'CodeEditor', 'Diff', 'Commands', 'Diagnostics',
                            'DocumentViews', 'Inspector', 'Images'],
                'dependencies': ['Canvas'], 'nativeEditorAdapter': 'imgui_bundle.imgui_color_text_edit'}
    (APP / 'vendor/cyui-source.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    print(json.dumps(vendor(parser.parse_args().checkout), indent=2))
