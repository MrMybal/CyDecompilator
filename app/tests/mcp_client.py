"""Real stdio MCP transport with isolated projects and job storage."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
DONE = {'Completed', 'Failed', 'Cancelled'}


async def payload(session, name, parameters):
    result = await session.call_tool(name, {'parameters': parameters} if name.startswith('op_') else parameters)
    if result.isError:
        raise RuntimeError(f'{name}: {result.content}')
    return json.loads(result.content[0].text)


async def terminal(session, job, timeout=240):
    deadline = time.monotonic() + timeout
    while job['state'] not in DONE:
        if time.monotonic() > deadline:
            await payload(session, 'cy_cancel_job', {'jobId': job['jobId']})
            raise TimeoutError(job['operationId'])
        await asyncio.sleep(.1)
        job = await payload(session, 'cy_get_job', {'jobId': job['jobId']})
    return job


async def run(session, operation, **parameters):
    job = await terminal(session, await payload(session, 'op_' + operation, parameters))
    assert job['state'] == 'Completed', job.get('error', job)
    return job['outputs']


@asynccontextmanager
async def client(directory, model_decisions=None):
    directory.mkdir(parents=True, exist_ok=True)
    # Only replace storage locations. The production manifest, handlers, engines,
    # scheduler, authentication and stdio transport all run unchanged.
    bootstrap = directory / 'server.py'
    model_setup = ''
    if model_decisions is not None:
        model_setup = ('import json\nfrom types import SimpleNamespace\nfrom cydec.ai import assistant\n'
                       f'decisions = iter({model_decisions!r})\n'
                       'assistant.call_model = lambda *a, **k: (json.dumps(next(decisions)), "", "controlled", SimpleNamespace(id="controlled"))\n')
    bootstrap.write_text(
        'import sys\nfrom pathlib import Path\n'
        f'sys.path.insert(0, {str(APP)!r})\n'
        'import tool\nfrom cydec.project import ProjectStore\n'
        f'tool.service.store = ProjectStore(Path({str(directory / "projects")!r}))\n'
        + model_setup +
        f'raise SystemExit(tool.run_cli(tool.create_runtime, ["--data-dir", {str(directory / "jobs")!r}, "mcp"]))\n',
        encoding='utf-8')
    env = dict(os.environ)
    env.pop('CYTOOLS_TOKEN', None)
    server = StdioServerParameters(command=sys.executable, args=[str(bootstrap)], cwd=str(ROOT), env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                yield session
            finally:
                await payload(session, 'cy_finish_task', {'cancelRunning': True})
