"""Boundaries that matter for shipping full, relocatable Windows packages."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from cydec import updates


def builder():
    spec=importlib.util.spec_from_file_location('build_windows',APP/'scripts/build_windows.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_updater_selects_application_zip_with_full_packages_first():
    assets=[{'name':'CyDecompilator-1.5.2-windows-x64-portable.zip'},
            {'name':'CyDecompilator-1.5.2-windows-x64-setup.exe'},
            {'name':'CyDecompilator-1.5.2.zip'}]
    assert updates.update_asset(assets) is assets[2]
    with pytest.raises(Exception,match='application-update ZIP'):
        updates.update_asset(assets[:2])


@pytest.mark.parametrize('name',['python/../../escape.txt','/absolute.txt','python/C:/escape.txt'])
def test_runtime_archive_cannot_escape_its_destination(tmp_path,name):
    source=tmp_path/'hostile.tar.gz'
    with tarfile.open(source,'w:gz') as archive:
        entry=tarfile.TarInfo(name);entry.size=1;archive.addfile(entry,io.BytesIO(b'x'))
    with pytest.raises(ValueError):builder().extract_python(source,tmp_path/'runtime')
    assert not (tmp_path/'escape.txt').exists()


def test_runtime_archive_rejects_links(tmp_path):
    source=tmp_path/'link.tar.gz'
    with tarfile.open(source,'w:gz') as archive:
        entry=tarfile.TarInfo('python/link');entry.type=tarfile.SYMTYPE;entry.linkname='../../outside';archive.addfile(entry)
    with pytest.raises(ValueError):builder().extract_python(source,tmp_path/'runtime')


def test_packaging_cleanup_preserves_an_external_directory(tmp_path):
    inside=tmp_path/'work';inside.mkdir();outside=tmp_path/'personal';outside.mkdir();(outside/'keep').write_text('keep')
    with pytest.raises(ValueError):builder().reset_owned(outside,inside)
    assert (outside/'keep').read_text()=='keep'


def test_bundled_sdk_and_build_inputs_are_hash_locked():
    build=builder(); config=json.loads(build.CONFIG.read_text('utf-8'))
    sdk=APP/'packaging/vendor'/config['sdk']['wheel']
    assert build.digest(sdk)==config['sdk']['sha256']
    assert all('--hash=sha256:' in line for line in build.LOCK.read_text().splitlines() if line and not line.startswith('#'))
