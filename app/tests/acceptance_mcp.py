"""A real MCP session over stdio, as an AI client would drive CyDecompilator.

Starts `app/tool.py mcp`, lists the tools, opens a file, lists its units, decompiles one,
renames a symbol and reads the code back with the rename applied. With --ai it also asks
the configured AI provider to explain the unit (this sends the code to that provider).

    runtime/python/Scripts/python.exe app/tests/acceptance_mcp.py [--file PATH] [--ai]

Writes data/reports/mcp-acceptance.json.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

DONE = ('Completed', 'Failed', 'Cancelled')


async def payload(session, name, arguments):
    wrapped = arguments if name.startswith('cy_') else {'parameters': arguments}
    result = await session.call_tool(name, wrapped)
    if result.isError:
        raise RuntimeError('%s: %s' % (name, result.content[0].text))
    return json.loads(result.content[0].text)


async def run(session, operation, parameters, timeout=900):
    job = await payload(session, 'op_' + operation, parameters)
    if 'jobId' not in job:
        return job
    deadline = time.monotonic() + timeout
    while job['state'] not in DONE:
        if time.monotonic() > deadline:
            raise TimeoutError(operation + ' timed out')
        await asyncio.sleep(0.2)
        job = await payload(session, 'cy_get_job', {'jobId': job['jobId']})
    if job['state'] != 'Completed':
        raise RuntimeError('%s: %s' % (operation, json.dumps(job.get('error'))))
    return job['outputs']


async def main(arguments):
    server = StdioServerParameters(command=str(ROOT / 'runtime/python/Scripts/python.exe'),
                                   args=[str(APP / 'tool.py'), 'mcp'], cwd=str(ROOT))
    report = {'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'file': arguments.file}
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(tool.name for tool in (await session.list_tools()).tools)
            report['toolCount'] = len(tools)
            operations = json.loads((APP / 'CyTool.json').read_text(encoding='utf-8'))['operations']
            declared = {'op_' + operation['id'] for operation in operations}
            assert declared.issubset(tools), sorted(declared - set(tools))
            assert {'cy_get_job', 'cy_cancel_job', 'cy_finish_task', 'cy_describe_operation'}.issubset(tools)
            report['declaredOperationCount'] = len(declared)
            report['allDeclaredOperationsExposed'] = True
            described = await payload(session, 'cy_describe_operation', {'operationId': 'decompile'})
            report['decompileInputs'] = sorted(described.get('inputSchema', described.get('operation', {}).get('inputSchema', {})).get('properties', {}))
            opened = await run(session, 'open_file', {'path': arguments.file})
            project = opened['projectId']
            report['project'] = {'id': project, 'format': opened['format']['format'], 'engine': opened['engine']}
            units = await run(session, 'list_functions', {'projectId': project, 'limit': 50})
            unit = units['functions'][0]['id']
            report['units'] = units['total']
            code = await run(session, 'decompile', {'projectId': project, 'function': unit})
            report['language'] = code['language']
            report['codeChars'] = len(code['code'])
            await run(session, 'rename', {'projectId': project, 'old': 'main', 'new': 'shader_main'})
            renamed = await run(session, 'decompile', {'projectId': project, 'function': 'shader_main'})
            report['renameApplied'] = 'shader_main' in renamed['code']
            if arguments.ai:
                explained = await run(session, 'ai_explain', {'projectId': project, 'function': 'shader_main',
                                                              'language': 'en'}, timeout=900)
                report['ai'] = {'provider': explained['provider'], 'chars': len(explained['text'])}
            await run(session, 'rename', {'projectId': project, 'old': 'shader_main', 'new': 'main'})
            finished = await payload(session, 'cy_finish_task', {})
            report['finishTask'] = bool(finished)
    report['passed'] = report['renameApplied'] and report['codeChars'] > 0
    out = ROOT / 'data/reports/mcp-acceptance.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default=str(APP / 'tests/fixtures/shaders/lit_frag.spv'))
    parser.add_argument('--ai', action='store_true')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
