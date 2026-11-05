"""Actual Xbox input workers and Runtime boundaries; no commercial game launch."""
from pathlib import Path
import hashlib
import json
import os
import struct
import sys
import zipfile

import pytest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from cytools_core import CyToolError
from cydec import xbox
from cydec.engines.base import EngineContext
from cydec.paths import write_json
from cydec.project import ProjectStore


def xex():
    data=bytearray(0x500);data[:4]=b'XEX2'
    struct.pack_into('>5I',data,4,1,0x400,0,0x80,4)
    for i,pair in enumerate(((0x10100,0x82001000),(0x10201,0x82000000),(0x3FF,0x280),(0x40006,0x290))):
        struct.pack_into('>II',data,24+8*i,*pair)
    struct.pack_into('>II',data,0x80,0x184,0x2000)
    struct.pack_into('>I',data,0x190,0x82000000)
    struct.pack_into('>IHH',data,0x280,8,0,0)
    struct.pack_into('>I',data,0x29C,0x12345678)
    return bytes(data)


def iso():
    data=bytearray(40*2048);magic=b'MICROSOFT*XBOX*MEDIA';o=32*2048
    data[o:o+20]=magic;data[o+2048-20:o+2048]=magic
    struct.pack_into('<II',data,o+20,33,2048)
    struct.pack_into('<HHIIBB',data,33*2048,0,0,34,len(xex()),0,11)
    data[33*2048+14:33*2048+25]=b'default.xex'
    data[34*2048:34*2048+len(xex())]=xex()
    return bytes(data)


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(xbox,'TOOLS_FILE',tmp_path/'settings.json')
    store=ProjectStore(tmp_path/'projects')
    work=tmp_path/'job';work.mkdir()
    context=EngineContext(workdir=work)
    source=tmp_path/'game';source.mkdir()
    (source/'default.xex').write_bytes(xex())
    (source/'textures').mkdir();(source/'textures/a.bin').write_bytes(b'asset')
    return store,context,source


def test_real_folder_preparation_survives_job_cleanup_and_keeps_source(setup):
    store,ctx,source=setup
    result=xbox.open_input(store,source,ctx)
    assert result['console']=='xbox360' and result['assetsComplete']
    assert len(result['files'])==2
    assert (Path(result['directory'])/'textures/a.bin').read_bytes()==b'asset'
    assert (source/'default.xex').read_bytes()==xex()
    import shutil
    shutil.rmtree(ctx.workdir)
    assert xbox.input_info(store.get(result['projectId']))['sha256']==hashlib.sha256(xex()).hexdigest()
    assert (Path(result['directory'])/'default.xex').is_file()


@pytest.mark.parametrize('archive',[False,True])
def test_actual_disc_and_zip_worker(setup,tmp_path,archive):
    store,ctx,_=setup
    source=tmp_path/('disc.zip' if archive else 'disc.iso')
    if archive:
        with zipfile.ZipFile(source,'w') as out:out.writestr('my disc.iso',iso())
    else:source.write_bytes(iso())
    result=xbox.open_input(store,source,ctx)
    assert result['entry']=='default.xex' and result['assetsComplete']
    assert Path(result['directory'],'default.xex').read_bytes()==xex()


def test_single_executable_does_not_import_its_parent_folder(setup):
    store,ctx,source=setup
    result=xbox.open_input(store,source/'default.xex',ctx)
    assert result['assetsComplete'] is False and len(result['files'])==1
    assert not Path(result['directory'],'textures').exists()


def test_bounds_ambiguous_entries_and_path_escape(setup,tmp_path):
    store,ctx,source=setup
    with pytest.raises(CyToolError,match='exceeds'):xbox.open_input(store,source,ctx,limit=1024)
    (source/'other.xex').write_bytes(xex())
    with pytest.raises(CyToolError):xbox.open_input(store,source,ctx,entry='../other.xex')
    assert not store.list()


def attached_fixture(setup,tmp_path):
    store,ctx,source=setup
    native=tmp_path/'native';native.mkdir()
    sdk=tmp_path/'sdk';(sdk/'bin').mkdir(parents=True);(sdk/'bin/rexglue.exe').write_bytes(b'sdk')
    manifest=native/'fixture_manifest.toml'
    manifest.write_text('[project]\nname="fixture"\n[entrypoint]\nfile_path='+json.dumps((source/'default.xex').as_posix())+'\n')
    guest_hash=hashlib.sha256(xex()).hexdigest()
    write_json(native/'native-project.json',dict(executable_sha256=guest_hash,game=str(source),sdk=str(sdk)))
    (native/'build').mkdir();exe=native/'build/fixture.exe';exe.write_bytes(b'controlled executable')
    write_json(native/'native-build.json',dict(executable=str(exe),sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),guest_sha256=guest_hash))
    result=xbox.attach(store,native,ctx)
    return store.get(result['projectId']),ctx,result


def test_attach_checks_original_build_and_does_not_execute(setup,tmp_path,monkeypatch):
    monkeypatch.setattr(xbox.process,'run',lambda *a,**k:pytest.fail('Attach must not execute anything'))
    project,ctx,result=attached_fixture(setup,tmp_path)
    assert result['status']=='built' and result['attached'] and result['nativeGameReady'] is False
    assert xbox.input_info(project)['build']['buildId']==result['buildId']
    executable=Path(result['executable']);executable.write_bytes(b'tampered')
    with pytest.raises(CyToolError,match='receipt'):xbox.run(project,ctx)


def test_changed_guest_or_manifest_prevents_build(setup,tmp_path):
    project,ctx,result=attached_fixture(setup,tmp_path)
    guest=Path(result['gameDirectory'])/'default.xex';guest.write_bytes(xex()+b'changed')
    with pytest.raises(CyToolError,match='executable changed'):xbox.build(project,ctx)
    guest.write_bytes(xex())
    manifest=next(Path(result['directory']).glob('*_manifest.toml'));manifest.write_text(manifest.read_text()+'\n# change')
    with pytest.raises(CyToolError,match='manifest changed'):xbox.build(project,ctx)


def test_legacy_rexglue_project_without_initialization_receipt(setup,tmp_path):
    project,ctx,result=attached_fixture(setup,tmp_path)
    directory=Path(result['directory'])
    (directory/'native-project.json').unlink()
    source=Path(result['gameDirectory'])
    manifest=next(directory.glob('*_manifest.toml'))
    manifest.write_text('[project]\nname="fixture"\ngame_root='+json.dumps(source.as_posix())+'\n[entrypoint]\nfile_path='+json.dumps((source/'default.xex').as_posix())+'\n')
    out=xbox.attach(setup[0],directory,ctx)
    assert out['status']=='built' and out['guestSha256']==result['guestSha256']


@pytest.mark.skipif(os.name!='nt',reason='Windows native launch contract')
def test_native_launch_is_job_owned_and_never_claims_gameplay(setup,tmp_path,monkeypatch):
    project,ctx,result=attached_fixture(setup,tmp_path)
    monkeypatch.setattr(xbox,'HALO_SHA',result['guestSha256'])
    observed={}
    def run(command,**kw):
        observed.update(command=command,**kw)
        return 0,'fixture output',''
    monkeypatch.setattr(xbox.process,'run',run)
    launched=xbox.run(project,ctx,timeout=2)
    assert launched['status']=='executed-unverified' and launched['nativeGameReady'] is False
    assert observed['own_children'] and observed['context'] is ctx and observed['timeout']==2
    assert '--game_data_root='+result['gameDirectory'] in observed['command']
    assert '--readback_resolve=full' in observed['command']
    assert '--gamma_render_target_as_unorm16=false' in observed['command']
    assert all('XboxGame' not in str(c) for c in observed['command'])


def test_gpu_settings_validate_paths(setup,tmp_path):
    sdk=tmp_path/'sdk';(sdk/'bin').mkdir(parents=True);(sdk/'bin/rexglue.exe').write_bytes(b'sdk')
    value=xbox.tools({'sdkRoot':str(sdk)})
    assert value['available']['sdkRoot']
    with pytest.raises(CyToolError):xbox.tools({'sdkRoot':str(tmp_path)})
    with pytest.raises(CyToolError):xbox.tools({'unknown':'x'})


def test_a_failed_build_cannot_launch_the_previous_executable(setup,tmp_path):
    project,ctx,result=attached_fixture(setup,tmp_path)
    result['status']='build-failed';xbox._save_build(project,result)
    with pytest.raises(CyToolError,match='Build the native'):xbox.run(project,ctx)


def test_coop_checkbox_overrides_legacy_saved_profile_without_losing_peer(tmp_path):
    path=tmp_path/'campaign-coop.toml'
    path.write_text('local_players = 2\nkeyboard_player_one = false\npeer = "192.0.2.10"\n')
    xbox._halo_player_settings(tmp_path,False)
    import tomllib
    saved=tomllib.loads(path.read_text())
    assert saved['local_players']==1 and saved['peer']=='192.0.2.10'
    xbox._halo_player_settings(tmp_path,True)
    saved=tomllib.loads(path.read_text())
    assert saved['local_players']==2 and saved['keyboard_player_one'] is True


def test_cancelled_backend_stops_its_actual_child_tree(setup,tmp_path):
    import psutil
    _,ctx,_=setup
    pid_file=tmp_path/'child.pid'
    script=tmp_path/'owned_worker.py'
    script.write_text('import subprocess,sys,time\nfrom pathlib import Path\n'
        'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"])\n'
        'Path(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(60)\n')
    class Cancellation:
        def check(self):
            if pid_file.exists():raise CyToolError('Cancelled','owned test cancellation')
    ctx.cancellation=Cancellation()
    with pytest.raises(CyToolError,match='cancellation'):
        xbox._worker(ctx,script,[pid_file],timeout=5)
    assert pid_file.exists()
    assert not psutil.pid_exists(int(pid_file.read_text()))


def test_packaged_profile_overlay_needs_no_original_module_or_sdk_checkout(tmp_path):
    import importlib.util
    path=APP/'xbox_support/scripts/rex_multiplayer_patch.py'
    spec=importlib.util.spec_from_file_location('overlay_test',path);overlay=importlib.util.module_from_spec(spec);spec.loader.exec_module(overlay)
    project=tmp_path/'project';(project/'generated').mkdir(parents=True)
    (project/'fixture_manifest.toml').write_text('[project]\nname="fixture"\n[entrypoint]\nout_directory_path="generated"\n')
    (project/'CMakeLists.txt').write_text('add_executable(fixture main.cpp)\n')
    generated=project/'generated/function.cpp';generated.write_text('__imp__XamUserGetXUID(ctx, base);\n__imp__NetDll_sendto(ctx,base);')
    report=overlay.prepare(project)
    assert '__imp__XboxNative_XamUserGetXUID' in generated.read_text()
    assert '__imp__XboxNative_NetDll_sendto' in generated.read_text()
    assert (project/'native-overlay/multiplayer/rex_native_profile.cpp').is_file()
    assert 'runtime/engines/rexglue/source' not in str(overlay.SDK_SOURCE)
    assert 'XamUserGetXUID' in report['imports']


def test_manifest_handlers_and_input_staging_are_registered(tmp_path,monkeypatch):
    from tool import create_runtime,declared_permissions
    from operations import OPERATIONS
    from cydec import service
    monkeypatch.setattr(service,'store',ProjectStore(tmp_path/'projects'))
    ids={op['id'] for op in OPERATIONS}
    assert {'xbox_open','xbox_attach','xbox_create','xbox_build','xbox_run','xbox_guide'}<=ids
    with create_runtime(tmp_path/'jobs') as runtime:
        actor=runtime.authenticate(runtime.create_client('test',declared_permissions(runtime))['token'])
        session=runtime.create_session(actor,temporary=False)['sessionId']
        source=tmp_path/'fixture.xex';source.write_bytes(xex())
        job=runtime.submit(actor,session,'xbox_open',{'file':str(source)})
        completed=runtime.wait(actor,job['jobId'],timeout=30)
        assert completed['state']=='Completed',completed.get('error')
        output=completed['outputs']
        assert output['source']==str(source) and output['assetsComplete'] is False
        job=runtime.submit(actor,session,'xbox_guide',{})
        result=runtime.wait(actor,job['jobId'],timeout=30)
        assert result['state']=='Completed' and result['outputs']['scope']['directIp']
