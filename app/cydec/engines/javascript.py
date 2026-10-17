import shutil
from .base import Engine
from .. import javascript, investigation


class JavaScriptEngine(Engine):
    id = 'javascript'
    name = 'JavaScript / Electron / Web'
    license = 'Apache-2.0'
    url = 'https://github.com/microsoft/TypeScript'
    description = 'Inert AST analysis of JavaScript, TypeScript, Electron IPC, preload and local web artifacts.'
    formats = ('javascript-app',)
    components = ('typescript',)
    language = 'javascript'
    def availability(self):
        state = super().availability()
        if not shutil.which('node'):
            state.update(available=False, detail='Install Node.js on PATH.')
        return state
    def analyze(self, project, context):
        return javascript.analyze(project, context)
    def decompile(self, project, analysis, function, context):
        return {'code': investigation.source(project, function['id'])['text'],
                'language': 'javascript' if function['id'].split('.')[-1] not in ('html', 'htm') else 'html'}
