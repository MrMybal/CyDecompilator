"""The reverse-engineering assistant: explain, rename, convert to real code, and ask.

Every task builds its context from the project (program facts, the function's code with
the user's annotations, callers, callees, imports and referenced strings) and sends it to
the configured provider. `ask` runs a bounded tool loop: the model answers with one JSON
object per turn, either a tool call over the decompiler (list, decompile, xrefs, strings,
search, rename...) or the final answer. That protocol needs no native tool calling, so it
works the same with Claude Code, Codex, an API key or a local Ollama/LM Studio model.

Nothing here executes model output. Converted code is only compiled for checking.
"""
import json
import re
import threading
import time
import uuid

from cytools_core import CyToolError

from .. import service
from ..paths import DATA, SETTINGS, read_json, write_json
from . import verify
from .providers import SESSION, ChatRequest, Delta, Registry

SETTINGS_FILE = SETTINGS / 'ai.json'
WORKSPACE = DATA / 'ai-workspace'
DEFAULTS = {'provider': 'claude-code', 'model': '', 'transport': '', 'temperature': None,
            'maxTokens': 8192, 'maxToolSteps': 12, 'allowEdits': True, 'verifyRounds': 2,
            'providers': {}}
CODE_LIMIT = 60000
LANGUAGES = {'c': 'C', 'cpp': 'C++', 'csharp': 'C#', 'java': 'Java', 'python': 'Python', 'rust': 'Rust',
             'go': 'Go', 'hlsl': 'HLSL', 'glsl': 'GLSL', 'javascript': 'JavaScript', 'same': 'the same language'}
SOURCE_NAMES = {'c': 'C pseudo-code (Ghidra)', 'asm': 'assembly', 'csharp': 'C#', 'java': 'Java',
                'python': 'Python', 'pybytecode': 'Python bytecode', 'hlsl': 'HLSL', 'glsl': 'GLSL',
                'il': '.NET IL', 'jvm': 'JVM bytecode', 'dxasm': 'DXBC assembly', 'spvasm': 'SPIR-V assembly',
                'xml': 'XML'}

SYSTEM = ('You are the reverse-engineering assistant inside CyDecompilator, a multi-engine decompiler. '
          'You analyse decompiled code, disassembly and shader bytecode. Be precise and concrete. '
          'Base every statement on the code you are shown; when something is inferred rather than '
          'visible, say so. Recognise well-known algorithms, libraries, compiler idioms and constants. '
          'Never claim to have executed anything.')

_registry = None
_registry_lock = threading.Lock()


# ---------------------------------------------------------------------- settings / providers

def settings():
    value = read_json(SETTINGS_FILE, {})
    result = dict(DEFAULTS)
    if isinstance(value, dict):
        result.update({k: v for k, v in value.items() if k in DEFAULTS})
    return result


def save_settings(changes):
    current = settings()
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise CyToolError('InvalidParameters', 'Unknown AI setting: %s' % key)
        if key == 'providers':
            if not isinstance(value, dict):
                raise CyToolError('InvalidParameters', 'providers must be an object')
            for provider_id, options in value.items():
                if not isinstance(options, dict) or any(k not in ('base_url', 'timeout_seconds', 'executable')
                                                        for k in options):
                    raise CyToolError('InvalidParameters', 'Provider options accept base_url, '
                                      'timeout_seconds and executable only (keys go to the credential store).')
        current[key] = value
    write_json(SETTINGS_FILE, current)
    reset_registry()
    return current


def registry():
    global _registry
    with _registry_lock:
        if _registry is None:
            WORKSPACE.mkdir(parents=True, exist_ok=True)
            _registry = Registry(settings=settings().get('providers', {}), workspace=WORKSPACE)
        return _registry


def reset_registry():
    global _registry
    with _registry_lock:
        if _registry is not None:
            _registry.close()
        _registry = None


def providers_status(refresh=True):
    current = settings()
    return {'settings': current, 'providers': registry().detect() if refresh else registry().descriptors(),
            'verifiers': verify.available()}


def store_key(provider_id, key):
    from . import credentials
    registry().get(provider_id)
    return credentials.store(provider_id, key)


def clear_key(provider_id):
    from . import credentials
    return credentials.clear(provider_id)


# ---------------------------------------------------------------------- one model call

class Streamer:
    """Forward text deltas to the job's event stream, batched to keep the event log small."""

    def __init__(self, context):
        self.context = context
        self.buffer = []
        self.last = time.monotonic()
        self.total = 0

    def __call__(self, channel, value):
        if self.context is None:
            return
        if channel == Delta.TEXT:
            self.buffer.append(value)
            self.total += len(value)
            if time.monotonic() - self.last > 0.25:
                self.flush()
        elif channel == Delta.STATUS:
            self.context.log(str(value)[:300])

    def flush(self):
        if self.buffer and self.context is not None and hasattr(self.context, 'emit'):
            try:
                self.context.emit('AiDelta', {'text': ''.join(self.buffer)})
            except Exception:
                pass
        self.buffer = []
        self.last = time.monotonic()


def call_model(prompt, *, context=None, messages=(), native_id='', system=SYSTEM, options=None):
    """Send one turn. Returns (text, native_id, model)."""
    current = settings()
    options = dict(options or {})
    provider_id = options.get('provider') or current['provider']
    provider = registry().get(provider_id)
    request_settings = dict(current.get('providers', {}).get(provider_id, {}))
    request_settings['max_tokens'] = options.get('maxTokens') or current['maxTokens']
    if current.get('temperature') is not None:
        request_settings['temperature'] = current['temperature']
    request = ChatRequest(prompt=prompt, messages=list(messages) if provider.kind != SESSION else [],
                          system_prompt=system, model=options.get('model') or current['model'],
                          transport=options.get('transport') or current['transport'],
                          settings=request_settings, native_id=native_id,
                          cancellation=getattr(context, 'cancellation', None), workspace=str(WORKSPACE))
    streamer = Streamer(context)
    if context is not None:
        context.log('AI request to %s%s' % (provider.name, (' / ' + request.model) if request.model else ''))
    try:
        result = provider.chat(request, streamer)
    finally:
        streamer.flush()
    return result['text'], result.get('nativeId', ''), result.get('model', request.model), provider


# ---------------------------------------------------------------------- context building

def function_context(project_id, function, engine_id='', view='decompiled'):
    info = service.function_info(project_id, function, engine_id)
    record = info['function']
    try:
        code = service.decompile(project_id, record['id'], info['engine'], view=view)
    except CyToolError:
        code = service.decompile(project_id, record['id'], info['engine'], view='disassembly')
    program = service.program_info(project_id, info['engine'])
    text = code['code']
    truncated = len(text) > CODE_LIMIT
    if truncated:
        text = text[:CODE_LIMIT] + '\n/* ... truncated ... */\n'
    facts = ['File: %s (%s%s)' % (program['name'], program['format']['formatName'],
                                  (', ' + str(program.get('arch'))) if program.get('arch') else ''),
             'Engine: %s' % info['engine']] + (['Binary: ' + line for line in program.get('peSummary', [])]) + [
             'Unit: %s%s' % (record['displayName'], (' at ' + record['address']) if record.get('address') else '')]
    if record.get('signature'):
        facts.append('Signature: ' + record['signature'])
    if record.get('callers'):
        facts.append('Called by: ' + ', '.join(c['name'] for c in record['callers'][:15]))
    if record.get('callees'):
        facts.append('Calls: ' + ', '.join(c['name'] for c in record['callees'][:25]))
    if record.get('imports'):
        facts.append('Imported functions used: ' + ', '.join(record['imports'][:25]))
    if record.get('strings'):
        facts.append('Strings referenced: ' + ' | '.join(repr(s) for s in record['strings'][:20]))
    if record.get('comment'):
        facts.append('Analyst note: ' + record['comment'])
    notes = program.get('annotations', {}).get('notes')
    if notes:
        facts.append('Project notes: ' + notes[:2000])
    return {'record': record, 'engine': info['engine'], 'language': code['language'],
            'code': text, 'truncated': truncated, 'facts': '\n'.join(facts), 'program': program}


def fenced(language, code):
    return '```%s\n%s\n```' % (language, code.rstrip())


def answer_language(language):
    return {'fr': 'French', 'en': 'English', 'de': 'German', 'es': 'Spanish', 'it': 'Italian',
            'pt': 'Portuguese', 'ru': 'Russian', 'zh': 'Simplified Chinese', 'ja': 'Japanese',
            'ko': 'Korean'}.get((language or 'en')[:2], 'English')


def extract_code(text):
    blocks = re.findall(r'```[\w+#.-]*[ \t]*\n(.*?)```', text, re.S)
    if blocks:
        return max(blocks, key=len).rstrip() + '\n'
    return text.strip() + '\n'


def extract_json(text):
    """First JSON object in a reply (fenced or bare)."""
    candidates = re.findall(r'```(?:json)?\s*\n(.*?)```', text, re.S) + [text]
    for candidate in candidates:
        start = candidate.find('{')
        while start >= 0:
            depth = 0
            in_string = False
            escape = False
            for index in range(start, len(candidate)):
                char = candidate[index]
                if in_string:
                    if escape:
                        escape = False
                    elif char == '\\':
                        escape = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(candidate[start:index + 1])
                        except ValueError:
                            break
            start = candidate.find('{', start + 1)
    return None


def _record(project_id, kind, payload):
    project = service.project_for(project_id)
    path = project.dir / 'ai' / kind / ('%s-%s.json' % (time.strftime('%Y%m%d-%H%M%S'), uuid.uuid4().hex[:6]))
    write_json(path, payload)
    return str(path)


# ---------------------------------------------------------------------- tasks

def explain(project_id, function, engine_id='', language='en', context=None, options=None):
    ctx = function_context(project_id, function, engine_id)
    prompt = ('Explain the following %s.\n\n%s\n\n%s\n\n'
              'Answer in %s with Markdown sections: **Summary** (one or two sentences), **How it works** '
              '(step by step), **Inputs and outputs**, **Notable details** (algorithms, constants, error paths, '
              'security-relevant behaviour), and **Suggested name** for the function.'
              % (SOURCE_NAMES.get(ctx['language'], ctx['language']), ctx['facts'],
                 fenced(ctx['language'], ctx['code']), answer_language(language)))
    if context is not None:
        context.progress(10, 'Asking the model')
    text, native, model, provider = call_model(prompt, context=context, options=options)
    record = {'task': 'explain', 'function': ctx['record']['id'], 'name': ctx['record']['displayName'],
              'provider': provider.id, 'model': model, 'createdAt': time.time(), 'text': text}
    path = _record(project_id, 'explain', record)
    return {'projectId': project_id, 'function': ctx['record']['id'], 'name': ctx['record']['displayName'],
            'provider': provider.id, 'model': model, 'text': text, 'savedTo': path}


def rename(project_id, function, engine_id='', apply=False, context=None, options=None):
    ctx = function_context(project_id, function, engine_id)
    prompt = ('Propose meaningful names for the identifiers of this %s.\n\n%s\n\n%s\n\n'
              'Rules: rename only identifiers that appear in the code (function, parameters, locals, '
              'globals named by the decompiler such as FUN_*, DAT_*, local_*, param_*, uVar*, iVar*, r0..rN, '
              'sub_*). Never rename imported library functions or language keywords. New names must be valid '
              'identifiers in snake_case for C/C++/Python and camelCase otherwise. '
              'Reply with ONLY this JSON object:\n'
              '{"function": "<new function name or empty>", "variables": [{"old": "...", "new": "...", '
              '"reason": "..."}], "comment": "<one line describing the function>"}'
              % (SOURCE_NAMES.get(ctx['language'], ctx['language']), ctx['facts'],
                 fenced(ctx['language'], ctx['code'])))
    if context is not None:
        context.progress(10, 'Asking the model')
    text, native, model, provider = call_model(prompt, context=context, options=options)
    proposal = extract_json(text)
    if not isinstance(proposal, dict):
        raise CyToolError('ProviderFailed', 'The model did not return the expected JSON. Reply was: ' + text[:500])
    variables = [v for v in proposal.get('variables', []) if isinstance(v, dict)
                 and isinstance(v.get('old'), str) and isinstance(v.get('new'), str)
                 and re.search(r'\b%s\b' % re.escape(v['old']), ctx['code'])]
    function_name = proposal.get('function') if isinstance(proposal.get('function'), str) else ''
    applied = {'applied': [], 'errors': []}
    if apply:
        if function_name and function_name != ctx['record']['displayName']:
            try:
                service.rename(project_id, ctx['record']['name'], function_name)
                applied['applied'].append({'old': ctx['record']['name'], 'new': function_name, 'scope': 'global'})
            except CyToolError as exc:
                applied['errors'].append({'old': ctx['record']['name'], 'new': function_name, 'error': str(exc)})
        result = service.rename_many(project_id, {v['old']: v['new'] for v in variables},
                                     function=ctx['record']['id'], engine_id=ctx['engine'])
        applied['applied'] += result['applied']
        applied['errors'] += result['errors']
        comment = proposal.get('comment')
        if isinstance(comment, str) and comment.strip() and not ctx['record'].get('comment'):
            service.set_comment(project_id, ctx['record']['id'], comment.strip(), ctx['engine'])
    record = {'task': 'rename', 'function': ctx['record']['id'], 'provider': provider.id, 'model': model,
              'createdAt': time.time(), 'proposal': proposal, 'applied': applied}
    _record(project_id, 'rename', record)
    return {'projectId': project_id, 'function': ctx['record']['id'], 'provider': provider.id, 'model': model,
            'functionName': function_name, 'variables': variables,
            'comment': proposal.get('comment', '') if isinstance(proposal.get('comment'), str) else '',
            'applied': applied if apply else None}


def convert(project_id, function, target='c', engine_id='', verify_code=True, instructions='',
            language='en', context=None, options=None):
    ctx = function_context(project_id, function, engine_id)
    source = ctx['language']
    if target == 'same':
        target = {'asm': 'c', 'pybytecode': 'python', 'il': 'csharp', 'jvm': 'java', 'dxasm': 'hlsl',
                  'spvasm': 'glsl'}.get(source, source)
    if target not in LANGUAGES:
        raise CyToolError('InvalidParameters', 'Unsupported target language %s. Use one of: %s'
                          % (target, ', '.join(LANGUAGES)))
    target_name = LANGUAGES[target]
    prompt = ('Rewrite this %s as clean, idiomatic, compilable %s source code.\n\n%s\n\n%s\n\n'
              'Requirements:\n'
              '- Preserve the exact behaviour, including edge cases and error paths.\n'
              '- Recover real types, structures, enums, loops and named constants where the code makes them evident; '
              'remove decompiler artefacts (undefinedN, CONCAT, extraout_, unaff_, redundant casts, gotos).\n'
              '- Use meaningful names.\n'
              '- The code must compile on its own: declare structures, and declare external functions '
              'it calls as prototypes or minimal stubs clearly marked as such.\n'
              '- Put a short comment where a type or intent is an assumption.\n'
              '%s'
              '- Reply with exactly one fenced code block, then at most five short lines of notes in %s.'
              % (SOURCE_NAMES.get(source, source), target_name, ctx['facts'], fenced(source, ctx['code']),
                 ('- Additional instructions: %s\n' % instructions.strip()) if instructions.strip() else '',
                 answer_language(language)))
    if context is not None:
        context.progress(10, 'Converting to ' + target_name)
    current = settings()
    rounds = int(current.get('verifyRounds', 2)) if verify_code else 0
    messages = []
    text, native, model, provider = call_model(prompt, context=context, options=options)
    messages += [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': text}]
    code = extract_code(text)
    checks = []
    if verify_code:
        for attempt in range(rounds + 1):
            if context is not None:
                context.progress(60 + 10 * attempt, 'Compile check')
            result = verify.check(target, code)
            checks.append(result)
            if result['status'] != 'failed' or attempt == rounds:
                break
            repair = ('The %s compile check (%s) failed:\n```\n%s\n```\nFix every error and reply with the full '
                      'corrected code in one fenced block.' % (target_name, result['tool'], result['output'][-3000:]))
            text, native, model, provider = call_model(repair, context=context, messages=messages,
                                                       native_id=native, options=options)
            messages += [{'role': 'user', 'content': repair}, {'role': 'assistant', 'content': text}]
            code = extract_code(text)
    notes = text[text.rfind('```') + 3:].strip() if text.count('```') >= 2 else ''
    project = service.project_for(project_id)
    from ..project import safe_name
    from ..service import EXTENSIONS
    extension = EXTENSIONS.get(target, {'cpp': '.cpp', 'rust': '.rs', 'go': '.go', 'javascript': '.js'}.get(target, '.txt'))
    output = project.dir / 'ai' / 'converted' / (safe_name(ctx['record']['displayName'] or ctx['record']['id'], 80) + extension)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(code, encoding='utf-8')
    final = checks[-1]['status'] if checks else 'skipped'
    _record(project_id, 'convert', {'task': 'convert', 'function': ctx['record']['id'], 'target': target,
                                    'provider': provider.id, 'model': model, 'createdAt': time.time(),
                                    'checks': checks, 'file': str(output)})
    return {'projectId': project_id, 'function': ctx['record']['id'], 'name': ctx['record']['displayName'],
            'target': target, 'code': code, 'notes': notes, 'verification': final, 'checks': checks,
            'file': str(output), 'provider': provider.id, 'model': model}


# ---------------------------------------------------------------------- agentic Q&A

TOOLS = {
    'program_info': ('{}', 'Format, architecture, sections, imports summary, counts.'),
    'list_functions': ('{"query": "", "offset": 0, "limit": 100}', 'Functions/units, filtered by a substring.'),
    'function_info': ('{"function": "name, id or address"}', 'Signature, callers, callees, imports, strings, notes.'),
    'decompile': ('{"function": "..."}', 'Decompiled code of one unit (annotations applied).'),
    'disassemble': ('{"function": "..."}', 'Assembly/bytecode of one unit, when the engine has it.'),
    'xrefs': ('{"function": "..."}', 'Callers and callees.'),
    'strings': ('{"query": "", "limit": 100}', 'Strings found in the binary.'),
    'search': ('{"query": "..."}', 'Search names, decompiled code and strings.'),
    'rename': ('{"old": "...", "new": "...", "function": "optional unit for a local rename"}',
               'Rename a symbol (only when the user asked for changes).'),
    'set_comment': ('{"function": "...", "text": "..."}', 'Attach a note to a unit (only when asked).'),
}
EDIT_TOOLS = {'rename', 'set_comment'}
RESULT_LIMIT = 24000


def _run_tool(project_id, engine_id, name, arguments, allow_edits):
    if name not in TOOLS:
        raise CyToolError('InvalidParameters', 'Unknown tool %s' % name)
    if name in EDIT_TOOLS and not allow_edits:
        raise CyToolError('AccessDenied', 'Editing tools are disabled for this conversation.')
    a = arguments if isinstance(arguments, dict) else {}
    if name == 'program_info':
        info = service.program_info(project_id, engine_id)
        info.pop('annotations', None)
        info['imports'] = info.get('imports', [])[:200]
        if isinstance(info.get('pe'), dict):
            pe = dict(info['pe'])
            pe['exports'] = pe.get('exports', [])[:200]
            pe['manifest'] = (pe.get('manifest') or '')[:1500]
            info['pe'] = pe
        return info
    if name == 'list_functions':
        return service.list_functions(project_id, engine_id, a.get('query', ''), a.get('offset', 0),
                                      min(int(a.get('limit', 100)), 300))
    if name == 'function_info':
        return service.function_info(project_id, a['function'], engine_id)
    if name == 'decompile':
        return service.decompile(project_id, a['function'], engine_id)['code']
    if name == 'disassemble':
        return service.decompile(project_id, a['function'], engine_id, view='disassembly')['code']
    if name == 'xrefs':
        return service.xrefs(project_id, a['function'], engine_id)
    if name == 'strings':
        return service.strings(project_id, engine_id, a.get('query', ''), 0, min(int(a.get('limit', 100)), 500))
    if name == 'search':
        return service.search(project_id, a.get('query', ''), engine_id)
    if name == 'rename':
        return service.rename(project_id, a['old'], a['new'], a.get('function', ''), engine_id)
    if name == 'set_comment':
        return service.set_comment(project_id, a['function'], a.get('text', ''), engine_id)
    raise CyToolError('InvalidParameters', name)


def ask(project_id, question, function='', engine_id='', conversation_id='', allow_edits=None,
        language='en', context=None, options=None):
    project = service.project_for(project_id)
    current = settings()
    allow_edits = current['allowEdits'] if allow_edits is None else bool(allow_edits)
    engine_id = project.resolve_engine(engine_id)
    conversations = project.dir / 'ai' / 'conversations'
    conversation = None
    if conversation_id:
        conversation = read_json(conversations / (re.sub(r'[^A-Za-z0-9_-]', '', conversation_id) + '.json'), None)
    if not isinstance(conversation, dict):
        conversation = {'id': uuid.uuid4().hex[:12], 'createdAt': time.time(), 'provider': '', 'nativeId': '',
                        'messages': [], 'turns': []}
    tool_lines = '\n'.join('- %s %s: %s' % (name, signature, help_)
                           for name, (signature, help_) in TOOLS.items()
                           if allow_edits or name not in EDIT_TOOLS)
    system = (SYSTEM + '\n\nYou are working on the project "%s". You can use these tools:\n%s\n\n'
              'PROTOCOL: reply with exactly ONE JSON object and nothing else. To call a tool: '
              '{"tool": "<name>", "arguments": {...}}. To finish: {"answer": "<your answer in Markdown>"}. '
              'Call tools as needed (at most %d calls), then answer in %s. Quote function names and addresses '
              'so the user can navigate to them.'
              % (project.meta()['name'], tool_lines, current['maxToolSteps'], answer_language(language)))
    opening = question
    if function:
        try:
            ctx = function_context(project_id, function, engine_id)
            opening = '%s\n\nCurrently open unit:\n%s\n%s' % (question, ctx['facts'],
                                                              fenced(ctx['language'], ctx['code'][:20000]))
        except CyToolError:
            pass
    messages = list(conversation['messages'])
    native = conversation.get('nativeId', '') if conversation.get('provider') == (
        (options or {}).get('provider') or current['provider']) else ''
    prompt = opening
    trace = []
    answer = None
    steps = int(current['maxToolSteps'])
    for step in range(steps + 1):
        if context is not None:
            context.progress(min(95, 5 + 90 * step / (steps + 1)), 'Thinking' if step == 0 else 'Tool step %d' % step)
        text, native, model, provider = call_model(prompt, context=context, messages=messages, native_id=native,
                                                   system=system, options=options)
        messages += [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': text}]
        decision = extract_json(text)
        if not isinstance(decision, dict) or ('tool' not in decision and 'answer' not in decision):
            answer = text.strip()
            break
        if 'answer' in decision and 'tool' not in decision:
            answer = str(decision['answer'])
            break
        name = str(decision.get('tool'))
        arguments = decision.get('arguments', {})
        if step == steps:
            prompt = 'Tool budget exhausted. Reply now with {"answer": "..."} based on what you know.'
            continue
        try:
            result = _run_tool(project_id, engine_id, name, arguments, allow_edits)
            payload = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1)
            status = 'ok'
        except (CyToolError, KeyError, ValueError, TypeError) as exc:
            payload = 'ERROR: %s' % exc
            status = 'error'
        if len(payload) > RESULT_LIMIT:
            payload = payload[:RESULT_LIMIT] + '\n... (truncated; narrow the query)'
        trace.append({'tool': name, 'arguments': arguments, 'status': status, 'chars': len(payload)})
        if context is not None:
            context.log('AI tool %s(%s) -> %s' % (name, json.dumps(arguments, ensure_ascii=False)[:120], status))
            try:
                context.emit('AiTool', {'tool': name, 'arguments': arguments, 'status': status})
            except Exception:
                pass
        prompt = 'TOOL RESULT %s:\n%s\n\nContinue with one JSON object.' % (name, payload)
    if answer is None:
        answer = 'No answer was produced within the tool budget.'
    conversation['provider'] = provider.id
    conversation['nativeId'] = native
    # Keep the transcript compact: questions, tool exchanges and answers, capped in size.
    conversation['messages'] = messages[-40:]
    conversation['turns'].append({'question': question, 'answer': answer, 'tools': trace, 'at': time.time(),
                                  'function': function})
    write_json(conversations / (conversation['id'] + '.json'), conversation)
    return {'projectId': project_id, 'conversationId': conversation['id'], 'answer': answer, 'tools': trace,
            'provider': provider.id, 'model': model}


def conversations(project_id):
    project = service.project_for(project_id)
    folder = project.dir / 'ai' / 'conversations'
    result = []
    if folder.is_dir():
        for path in sorted(folder.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            value = read_json(path, {})
            turns = value.get('turns', [])
            result.append({'conversationId': value.get('id', path.stem), 'turns': len(turns),
                           'first': turns[0]['question'][:120] if turns else '', 'provider': value.get('provider', ''),
                           'updatedAt': path.stat().st_mtime})
    return result


def conversation(project_id, conversation_id):
    project = service.project_for(project_id)
    value = read_json(project.dir / 'ai' / 'conversations' / (re.sub(r'[^A-Za-z0-9_-]', '', conversation_id) + '.json'), None)
    if not isinstance(value, dict):
        raise CyToolError('NotFound', 'Conversation not found.')
    return {'conversationId': value['id'], 'provider': value.get('provider', ''), 'turns': value.get('turns', [])}


def batch_rename(project_id, engine_id='', limit=20, only_unnamed=True, context=None, options=None):
    """Name many functions in one job (auto-named ones first: FUN_*, sub_*)."""
    listing = service.list_functions(project_id, engine_id, limit=5000)
    candidates = [f for f in listing['functions']
                  if not f.get('thunk') and (not only_unnamed or re.match(r'(FUN_|sub_|thunk_FUN_|LAB_)', f['displayName']))]
    candidates = candidates[:max(1, int(limit))]
    results = []
    for index, function in enumerate(candidates):
        if context is not None:
            context.progress(100 * index / max(len(candidates), 1),
                             currentStep='Naming %d / %d' % (index + 1, len(candidates)))
        try:
            result = rename(project_id, function['id'], listing['engine'], apply=True, context=context, options=options)
            results.append({'function': function['id'], 'old': function['displayName'],
                            'new': result['functionName'], 'variables': len(result['variables'])})
        except CyToolError as exc:
            results.append({'function': function['id'], 'old': function['displayName'], 'error': str(exc)})
    return {'projectId': project_id, 'processed': len(results), 'results': results}
