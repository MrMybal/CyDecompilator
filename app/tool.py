"""CyDecompilator runtime: every operation of CyTool.json bound to its handler.

The desktop window, the CLI, HTTP and MCP all go through this Runtime, so they share one
scheduler, one set of jobs and exactly the same behaviour. Handlers are thin: the work is
in cydec.service (projects/engines), cydec.components (downloads) and cydec.ai.
"""
import sys
from pathlib import Path

from installation_ui import configure as configure_storage

configure_storage()

from cytools_core import CyToolError, Runtime, load_manifest  # noqa: E402
from cytools_core.transports.cli import run_cli  # noqa: E402

APP = Path(__file__).resolve().parent
ROOT = APP.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from cydec import components, service  # noqa: E402
from cydec.engines.base import EngineContext  # noqa: E402
from cydec.paths import ensure_tree  # noqa: E402


def engine_context(context, options=None):
    workdir = context.path('work/.keep').parent

    def progress(percent, step=''):
        context.progress(round(float(percent), 2), currentStep=str(step)[:200] or 'Working')

    return EngineContext(cancellation=context.cancellation, progress=progress, log=context.log,
                         workdir=workdir, options=options, emit=context.emit)


def ai_options(parameters):
    return {key: parameters[key] for key in ('provider', 'model') if parameters.get(key)}


# Operations declare their real effects (network, spawning engines, writing outside data/).
# The Core gates them on the caller's identity, so the implicit client the CLI and MCP
# transports would create could not call them. When no identity is configured the Tool
# mints a local client holding exactly the permissions its manifest declares and passes
# its token through CYTOOLS_TOKEN, the variable the Core already reads. Set CYTOOLS_TOKEN
# to a client created with `create-client --permission ...` to use a restricted identity.
EVENT_LIMIT = 20000


def declared_permissions(runtime):
    declared = set()
    for operation in runtime.descriptor['operations']:
        declared.update(operation.get('permissions', []))
    return sorted(declared)


def ensure_standalone_identity(runtime):
    import os
    if os.environ.get('CYTOOLS_TOKEN'):
        return ''
    token = runtime.create_client('standalone', declared_permissions(runtime))['token']
    os.environ['CYTOOLS_TOKEN'] = token
    return token


def create_runtime(data_dir, **options):
    ensure_tree()
    options.setdefault('event_limit', EVENT_LIMIT)
    runtime = Runtime(load_manifest(APP / 'CyTool.json'), data_dir, **options)
    runtime.configure_inputs(ROOT / 'data/inputs', fields={'open_file': ['path']})

    def handler(function):
        def run(context, parameters):
            context.cancellation.check()
            result = function(context, parameters)
            if not isinstance(result, dict):
                result = {'result': result}
            return result
        return run

    # ------------------------------------------------------------------ projects

    def open_file(context, p):
        ctx = engine_context(context, p.get('options'))
        ctx.progress(1, 'Hashing and detecting')
        summary = service.open_file(p['path'], ctx)
        if p.get('analyze', True):
            summary = service.analyze(summary['projectId'], p.get('engine', ''), ctx, force=p.get('force', False))
        return summary

    def analyze(context, p):
        return service.analyze(p['projectId'], p.get('engine', ''), engine_context(context, p.get('options')),
                               force=p.get('force', False))

    def export_sources(context, p):
        ctx = engine_context(context)
        destination = p.get('destination') or ''
        if destination:
            target = Path(destination)
            if not target.is_absolute():
                raise CyToolError('InvalidParameters', 'destination must be an absolute folder path.')
        else:
            target = context.path('export/.keep').parent
        result = service.export_sources(p['projectId'], target, p.get('engine', ''), ctx,
                                        p.get('decompileMissing', False), p.get('maxUnits', 0))
        if p.get('csharpProject'):
            project = service.project_for(p['projectId'])
            from cydec.engines import get as get_engine
            get_engine('ilspy').export_project(project, target / 'csharp-project', ctx)
            result['csharpProject'] = str(target / 'csharp-project')
        return result

    def c_module(context, p):
        destination = p.get('destination') or ''
        if destination and not Path(destination).is_absolute():
            raise CyToolError('InvalidParameters', 'destination must be an absolute file path.')
        return service.c_module(p['projectId'], p.get('functions') or [], destination,
                                p.get('includeCallees', True), engine_context(context))

    registrations = {
        'open_file': open_file,
        'analyze': analyze,
        'list_projects': lambda c, p: {'projects': service.store.list()},
        'project_info': lambda c, p: service.program_info(p['projectId'], p.get('engine', '')),
        'delete_project': lambda c, p: service.store.delete(p['projectId']),
        'list_functions': lambda c, p: service.list_functions(p['projectId'], p.get('engine', ''), p.get('query', ''),
                                                              p.get('offset', 0), p.get('limit', 500), p.get('kind', '')),
        'function_info': lambda c, p: service.function_info(p['projectId'], p['function'], p.get('engine', '')),
        'decompile': lambda c, p: service.decompile(p['projectId'], p['function'], p.get('engine', ''),
                                                    engine_context(c), p.get('refresh', False),
                                                    p.get('view', 'decompiled'), p.get('annotate', True)),
        'xrefs': lambda c, p: service.xrefs(p['projectId'], p['function'], p.get('engine', '')),
        'strings': lambda c, p: service.strings(p['projectId'], p.get('engine', ''), p.get('query', ''),
                                                p.get('offset', 0), p.get('limit', 500)),
        'search': lambda c, p: service.search(p['projectId'], p['query'], p.get('engine', ''),
                                              p.get('inCode', True), p.get('limit', 200)),
        'rename': lambda c, p: service.rename(p['projectId'], p['old'], p['new'], p.get('function', ''),
                                              p.get('engine', '')),
        'set_comment': lambda c, p: service.set_comment(p['projectId'], p['function'], p['text'], p.get('engine', '')),
        'set_notes': lambda c, p: service.set_notes(p['projectId'], p['text']),
        'export_sources': export_sources,
        'c_module': c_module,
        'extract_embedded': lambda c, p: service.extract_embedded(p['projectId'], p.get('kind', ''), engine_context(c)),
        'extracted_files': lambda c, p: service.extracted_files(p['projectId'], p['kind']),
        'load_symbols': lambda c, p: service.load_symbols(p['projectId'], engine_context(c), p.get('force', True)),
        'symbols_configure': lambda c, p: __import__('cydec.symbols', fromlist=['configure']).configure(
            p.get('enabled'), p.get('server'), p.get('localFolders')),
        # -------------------------------------------------------------- engines
        'list_engines': lambda c, p: {'engines': service.engines_status()},
        'list_components': lambda c, p: {'components': components.status(refresh=p.get('refresh', False))},
        'install_component': lambda c, p: components.install(p['component'], engine_context(c),
                                                             p.get('includeRequirements', True)),
        'remove_component': lambda c, p: components.remove(p['component'], p.get('version', '')),
        'set_component_path': lambda c, p: {'installed': components.set_override(p['component'], p.get('path', ''))['installed']},
    }

    # ------------------------------------------------------------------ AI (imported lazily)

    def ai(name):
        def run(context, p):
            from cydec.ai import assistant
            ctx = engine_context(context)
            if name == 'ai_status':
                return assistant.providers_status(p.get('refresh', True))
            if name == 'ai_configure':
                return {'settings': assistant.save_settings({k: v for k, v in p.items()})}
            if name == 'ai_explain':
                return assistant.explain(p['projectId'], p['function'], p.get('engine', ''), p.get('language', 'en'),
                                         ctx, ai_options(p))
            if name == 'ai_rename':
                return assistant.rename(p['projectId'], p['function'], p.get('engine', ''), p.get('apply', False),
                                        ctx, ai_options(p))
            if name == 'ai_convert':
                return assistant.convert(p['projectId'], p['function'], p.get('target', 'same'), p.get('engine', ''),
                                         p.get('verify', True), p.get('instructions', ''), p.get('language', 'en'),
                                         ctx, ai_options(p))
            if name == 'ai_ask':
                return assistant.ask(p['projectId'], p['question'], p.get('function', ''), p.get('engine', ''),
                                     p.get('conversationId', ''), p.get('allowEdits'), p.get('language', 'en'),
                                     ctx, ai_options(p))
            if name == 'ai_batch_rename':
                return assistant.batch_rename(p['projectId'], p.get('engine', ''), p.get('limit', 20),
                                              p.get('onlyUnnamed', True), ctx, ai_options(p))
            if name == 'ai_conversations':
                return {'conversations': assistant.conversations(p['projectId'])}
            if name == 'ai_conversation':
                return assistant.conversation(p['projectId'], p['conversationId'])
            raise CyToolError('NotFound', name)
        return run

    for name in ('ai_status', 'ai_configure', 'ai_explain', 'ai_rename', 'ai_convert', 'ai_ask',
                 'ai_batch_rename', 'ai_conversations', 'ai_conversation'):
        registrations[name] = ai(name)

    from cydec import updates
    registrations.update({
        'update_state': lambda c, p: updates.state(),
        'update_configure': lambda c, p: updates.configure(p.get('repository'), p.get('automaticCheck')),
        'update_check': lambda c, p: updates.check(),
        'update_download': lambda c, p: updates.download(engine_context(c), p.get('version', '')),
        'update_apply': lambda c, p: updates.apply(engine_context(c), runtime, c.job_id),
        'update_rollback': lambda c, p: updates.rollback(engine_context(c), runtime, c.job_id),
    })

    declared = {operation['id'] for operation in runtime.descriptor['operations']}
    for operation_id, function in registrations.items():
        if operation_id in declared:
            runtime.register(operation_id, handler(function))
    missing = declared - set(registrations)
    if missing:
        raise RuntimeError('Operations without handler: %s' % ', '.join(sorted(missing)))
    from cytools_core.shared_installation import register_operations
    register_operations(runtime, ROOT)
    ensure_standalone_identity(runtime)
    return runtime


if __name__ == '__main__':
    argv = sys.argv[1:]
    if '--data-dir' not in argv:
        argv = ['--data-dir', str(ROOT / 'data/jobs'), *argv]
    raise SystemExit(run_cli(create_runtime, argv))
