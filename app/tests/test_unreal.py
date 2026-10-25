"""Portable reconstruction knowledge through production Runtime, agent and MCP."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from cytools_core import CyToolError
from cydec import unreal, service
from cydec.project import ProjectStore


def test_profile_scope_and_edition():
    result = unreal.rules(language='fr')
    assert len(result['rules']) == 26
    assert len(result['categories']) == 11
    assert result['profile']['visualEdition'] == 'anniversary'
    assert result['profile']['gameplayImplementation'] == 'native-unreal-cpp'
    assert result['scope'] == 'rules-only' and result['enforcement'] == 'guidance-only'
    assert not result['automaticConversion'] and not result['fullGameEquivalence']
    assert not result['implementation']['executionIntegrated']
    missions = result['profile']['missions']
    assert {row['map'] for row in missions} == {'a10','a30','a50','b30','b40','c10','c20','c40','d20','d40'}
    assert {row['xexSha256'] for row in missions} == {result['profile']['xexSha256']}
    assert all(row['templates'] for row in missions)


def test_generic_profile_excludes_title_identity_and_vertex_decoder():
    result = unreal.rules(profile='generic')
    assert len(result['rules']) == 24
    assert not result['profile']['missions']
    assert not {'exact-profile', 'vertex-declaration'} & {row['id'] for row in result['rules']}
    assert 'xexSha256' not in result['profile']


def test_categories_partition_the_catalog_and_guide_matches():
    result = unreal.rules()
    all_ids = []
    for category in result['categories']:
        filtered = unreal.guide(category=category['id'])
        assert filtered['rules']
        assert {row['category'] for row in filtered['rules']} == {category['id']}
        assert all(row['id'] in filtered['documentation'] for row in filtered['rules'])
        all_ids.extend(row['id'] for row in filtered['rules'])
    assert len(all_ids) == len(set(all_ids)) == len(result['rules'])
    assert set(all_ids) == {row['id'] for row in result['rules']}


def test_guides_have_real_newlines_and_distinct_french_content():
    en = unreal.guide(category='vehicles')
    fr = unreal.guide(category='vehicles', language='fr')
    assert len(fr['documentation'].splitlines()) > 15
    assert 'Contrôle :' in fr['documentation'] and 'Check:' in en['documentation']
    assert 'véhicules' in fr['documentation']
    assert [r['id'] for r in en['rules']] == [r['id'] for r in fr['rules']]
    assert en['rules'][0]['title'] != fr['rules'][0]['title']
    assert 'vehicles\\warthog\\warthog' in fr['documentation']


@pytest.mark.parametrize('parameters', [dict(profile='unknown'),dict(category='../../secrets'),
    dict(category='weapons'),dict(language='xx')])
def test_unknown_inputs_are_not_used_as_paths(parameters):
    with pytest.raises(CyToolError) as caught:
        unreal.rules(**parameters)
    assert caught.value.code == 'InvalidParameters'


def test_catalog_is_self_contained_without_research_module(tmp_path, monkeypatch):
    catalog = tmp_path/'app/unreal_support/reconstruction-rules.json'
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(unreal.CATALOG.read_bytes())
    monkeypatch.setattr(unreal, 'CATALOG', catalog)
    monkeypatch.setattr(unreal, 'MODULE', tmp_path/'absent-module')
    result = unreal.guide(language='fr')
    assert not result['implementation']['available']
    assert len(result['rules']) == 26 and 'SHA-256' in result['documentation']
    assert list(tmp_path.iterdir()) == [tmp_path/'app']


def test_reference_snapshots_match_existing_module_sources():
    if not unreal.MODULE.is_dir():
        pytest.skip('Optional research module is not shipped with this installation.')
    result = unreal.rules()
    refs = [ref for row in result['rules'] for ref in row['evidence']]
    refs.extend(row['source'] for row in result['profile']['missions'])
    for ref in refs:
        assert ref['path'].startswith('modules/unreal-reconstruction/')
        path = APP.parent/ref['path']
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == ref['sha256'], ref['path']
    assert hashlib.sha256(unreal.CATALOG.read_bytes()).hexdigest() == result['catalogSha256']


def test_runtime_rules_work_without_permissions_or_open_project(tmp_path, monkeypatch):
    from tool import create_runtime
    monkeypatch.setattr(service, 'store', ProjectStore(tmp_path/'projects'))
    with create_runtime(tmp_path/'jobs') as runtime:
        actor = runtime.authenticate(runtime.create_client('knowledge-only', [])['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        for operation in ('unreal_rules','unreal_guide'):
            job = runtime.submit(actor, session, operation, {'category':'effects','language':'fr'})
            row = runtime.wait(actor, job['jobId'], timeout=15)
            assert row['state'] == 'Completed', row.get('error')
            assert {r['category'] for r in row['outputs']['rules']} == {'effects'}
        assert service.store.list() == []
        job = runtime.submit(actor, session, 'unreal_rules', {'category':'../../outside'})
        row = runtime.wait(actor, job['jobId'], timeout=15)
        assert row['state'] == 'Failed' and row['error']['code'] == 'InvalidParameters'


def test_integrated_agent_discovers_and_reads_rules_without_claiming_reconstruction(tmp_path, monkeypatch):
    from tool import create_runtime, declared_permissions
    from cydec.ai import assistant
    store = ProjectStore(tmp_path/'projects')
    monkeypatch.setattr(service, 'store', store)
    source = tmp_path/'input.js'
    source.write_text('console.log(1);', encoding='utf8')
    project, _ = store.open(source)
    calls = []
    def model(prompt, **kwargs):
        payload = json.loads(prompt)
        if not calls:
            assert {'unreal_rules','unreal_guide'} <= set(payload['operations'])
            decision = {'tool':'unreal_rules','arguments':{'category':'ai','language':'fr'}}
        else:
            output = json.loads(payload['result'])['outputs']
            assert output['scope'] == 'rules-only'
            assert {row['category'] for row in output['rules']} == {'ai'}
            decision = {'answer':'Rules read; reconstruction was not performed.','status':'completed'}
        calls.append(decision)
        return json.dumps(decision), '', 'controlled', SimpleNamespace(id='controlled')
    monkeypatch.setattr(assistant, 'call_model', model)
    with create_runtime(tmp_path/'jobs') as runtime:
        actor = runtime.authenticate(runtime.create_client('agent', declared_permissions(runtime))['token'])
        session = runtime.create_session(actor, temporary=False)['sessionId']
        job = runtime.submit(actor, session, 'ai_agent', {'projectId':project.id,
            'objective':'Inspect Unreal reconstruction rules.','workflow':'reconstruct','maxSteps':1})
        result = runtime.wait(actor, job['jobId'], timeout=30)
        assert result['state'] == 'Completed', result.get('error')
        report = result['outputs']
        assert report['status'] == 'budget-exhausted'
        assert not report['verification']['verified']
        assert len(report['childJobs']) == 1
        child = runtime.get_job(actor, report['childJobs'][0]['jobId'])
        assert child['operationId'] == 'unreal_rules' and child['state'] == 'Completed'
    assert source.read_text() == 'console.log(1);'


def test_ui_ignores_stale_job_results_and_switches_language(monkeypatch):
    import ui_common
    from unreal_ui import UnrealUI
    submitted = []
    jobs = SimpleNamespace(submit=lambda op, params, **callbacks: submitted.append((op, params, callbacks)))
    prefs = SimpleNamespace(values={'language':'en'})
    monkeypatch.setattr(ui_common, 'preferences', prefs)
    ui = UnrealUI(SimpleNamespace(jobs=jobs))
    ui.refresh()
    ui.category = 'vehicles'
    prefs.values['language'] = 'fr'
    ui.refresh()
    submitted[0][2]['done']({'old':True})
    assert ui.report == {}
    submitted[1][2]['done']({'current':True})
    assert ui.report == {'current':True}
    assert submitted[1][1] == {'profile':'halo-cea-x360','category':'vehicles','language':'fr'}
    submitted[0][2]['failed']('old failure')
    assert not ui.error


def test_real_mcp_discovery_and_filtered_guide(tmp_path):
    from mcp_client import client, payload, run
    async def scenario():
        async with client(tmp_path/'mcp') as session:
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert {'op_unreal_rules','op_unreal_guide'} <= names
            schema = await payload(session, 'cy_describe_operation', {'operationId':'unreal_rules'})
            assert 'profile' in schema['inputSchema']['properties']
            result = await run(session, 'unreal_guide', category='vehicles', language='fr')
            assert len(result['rules']) == 2
            assert 'Contrôle :' in result['documentation']
            assert result['scope'] == 'rules-only' and not result['automaticConversion']
    asyncio.run(scenario())


@pytest.mark.parametrize('operation', ['unreal_rules', 'unreal_guide'])
@pytest.mark.parametrize('workflow', ['investigate', 'reconstruct', 'patch'])
def test_knowledge_only_calls_do_not_certify_project_work(operation, workflow):
    from cydec.ai import agent
    report = {'workflow':workflow,'steps':[{'tool':operation,'arguments':{},
        'result':{'state':'Completed','outputs':unreal.rules()}}]}
    assert not agent.verified(report)['verified']
    if workflow == 'investigate':
        report['steps'].append({'tool':'project_info','result':{'state':'Completed','outputs':{}}})
        assert agent.verified(report)['verified']
