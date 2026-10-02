"""Every path the Tool uses, resolved from the root it was installed in.

Projects, settings and credentials live in data/. Engines, their runtimes (JDK, .NET) and
downloads live in runtime/. Writes go through `write_json`, which replaces the file
atomically so an interrupted save never leaves a half-written project behind.
"""
import json
import os
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
DATA = ROOT / 'data'
RUNTIME = ROOT / 'runtime'

PROJECTS = DATA / 'projects'
SETTINGS = DATA / 'settings'
INPUTS = DATA / 'inputs'
JOBS = DATA / 'jobs'
REPORTS = DATA / 'reports'
EXPORTS = DATA / 'exports'
ENGINES = RUNTIME / 'engines'
DOWNLOADS = RUNTIME / 'downloads'

TOOL_ID = 'cy.tool.decompilator'


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {} if default is None else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temp, path)
    return path


def ensure_tree():
    for directory in (PROJECTS, SETTINGS, INPUTS, JOBS, REPORTS, EXPORTS, ENGINES, DOWNLOADS):
        directory.mkdir(parents=True, exist_ok=True)
