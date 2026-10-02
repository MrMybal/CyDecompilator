"""Engine registry. Order matters only for display; selection follows the detected format."""
from .cdec import CDecompilerEngine
from .ghidra import GhidraEngine
from .ilspy import IlspyEngine
from .java import JadxEngine, VineflowerEngine
from .native import NativeEngine
from .python import PythonEngine
from .shader import ShaderEngine

ENGINES = {engine.id: engine for engine in (GhidraEngine(), CDecompilerEngine(), NativeEngine(), IlspyEngine(),
                                           VineflowerEngine(), JadxEngine(), PythonEngine(),
                                           ShaderEngine())}


def get(engine_id):
    from cytools_core import CyToolError
    engine = ENGINES.get(str(engine_id))
    if engine is None:
        raise CyToolError('NotFound', 'Unknown engine %r. Known: %s' % (engine_id, ', '.join(ENGINES)))
    return engine
