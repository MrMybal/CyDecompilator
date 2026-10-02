"""Developer helper: install components from a terminal with progress on stderr.

Usage: runtime/python/Scripts/python.exe app/scripts/install_component.py ghidra [jadx ...]
The interface and the install_component operation do the same through the Runtime.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cydec import components  # noqa: E402
from cydec.engines.base import EngineContext  # noqa: E402

last = [-10]


def progress(percent, step):
    if percent - last[0] >= 5 or percent >= 100:
        last[0] = percent
        print('%5.1f%% %s' % (percent, step), file=sys.stderr, flush=True)


def log(message, level):
    print('[%s] %s' % (level, message), file=sys.stderr, flush=True)


for name in sys.argv[1:]:
    context = EngineContext(progress=progress, log=log,
                            workdir=Path(__file__).resolve().parents[2] / 'data' / 'reports' / 'install')
    last[0] = -10
    result = components.install(name, context)
    print(result['installed'], file=sys.stderr)
