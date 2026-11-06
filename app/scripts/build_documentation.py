"""Compatibility entry point for the private CyDoc documentation build."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / '.CyDocBuild/build.py'
_spec = importlib.util.spec_from_file_location('cydec_documentation_build', _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
for _name in ('build', 'check_current', 'input_hashes', 'reset_child', 'digest', 'source_digest', 'DOCS', 'DESTINATION', 'setup_tools', 'generate_api'):
    globals()[_name] = getattr(_module, _name)

if __name__ == '__main__':
    _module.main()
