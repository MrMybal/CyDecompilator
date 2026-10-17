"""Install the bundled AI skill without editing MCP/client configuration."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'app/skills/cydecompilator'


def files(root):
    return {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def install(destination):
    target = Path(destination).expanduser().resolve() / SOURCE.name
    if not (SOURCE / 'SKILL.md').is_file():
        raise ValueError('The bundled app/skills/cydecompilator folder is missing.')
    if target == SOURCE.resolve():
        return target
    if target.exists():
        if target.is_dir() and files(target) == files(SOURCE):
            return target
        raise ValueError('Destination already contains a different skill. Choose another --destination or preserve it before replacing it.')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE, target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path,
        default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills',
        help='Parent skills folder (default: CODEX_HOME/skills).')
    arguments = parser.parse_args()
    try:
        target = install(arguments.destination)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')
    print('Installed: ' + str(target))
    print('Reload skill discovery in your client. Configure the CyDecompilator MCP server separately; see app/Docs/AIIntegration.md.')


if __name__ == '__main__':
    main()
