"""Application data adapters for the selected upstream CyUI Python views.

No service, process, repository or document write is performed by these adapters.
"""
import hashlib
import json
from pathlib import PurePosixPath
import re

import cyui
from imgui_bundle import imgui
from cyui_modules import code, diagnostics, diff, documents


def stable_id(*parts):
    data = json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), 'little') or 1


def language_for_path(path):
    return {'.cs': 'csharp', '.cpp': 'cpp', '.cc': 'cpp', '.c': 'c', '.h': 'cpp',
            '.hlsl': 'hlsl', '.glsl': 'glsl', '.py': 'python', '.js': 'javascript',
            '.jsx': 'javascript', '.ts': 'typescript', '.tsx': 'typescript',
            '.json': 'json', '.rs': 'rust', '.md': 'markdown', '.sql': 'sql',
            '.lua': 'lua', '.ini': 'ini'}.get(PurePosixPath(path).suffix.lower(), 'plain')


def _copy(text):
    if cyui.ghost_button(cyui.tr_label('Copy')):
        imgui.set_clipboard_text(text)


def _remaining(size):
    width, height = tuple(size)
    if width <= 0:
        width = max(cyui.dp(1), imgui.get_content_region_avail().x + width)
    if height > 0:
        height = max(cyui.dp(1), height - imgui.get_frame_height_with_spacing())
    return width, height


def _link(result):
    if result.get('link'):
        imgui.set_clipboard_text(result['link'])
        cyui.notify(cyui.tr('Link copied'), 'info')


class SourceView:
    def __init__(self, language='plain'):
        self.document = code.CodeDocument(language=language or 'plain')
        self.state = code.CodeViewState()
        self.raw = False

    def set_text(self, text):
        if self.document.set_text(text, self.document.language):
            self.state.selected_line = self.state.focus_line = -1

    def get_text(self):
        return self.document.text

    def set_language(self, language):
        self.document.set_text(self.document.text, language or 'plain')

    def focus_line(self, line):
        self.state.selected_line = self.state.focus_line = max(0, min(line, len(self.document.lines)-1))

    def render(self, identifier, size=(0, 0)):
        imgui.push_id(identifier)
        _copy(self.get_text())
        imgui.same_line()
        _, self.raw = imgui.checkbox(cyui.tr_label('Raw text'), self.raw)
        if self.raw:
            imgui.input_text_multiline('##raw', self.get_text(), _remaining(size), imgui.InputTextFlags_.read_only)
        else:
            code.code_viewer('##code', self.state, self.document, _remaining(size))
        imgui.pop_id()


class DocumentView:
    def __init__(self):
        self.document = documents.Document()
        self.state = documents.DocumentState()
        self.raw = False

    def set_text(self, text):
        self.document.set_markdown(text)

    def get_text(self):
        return self.document.text

    def render(self, identifier, size=(0, 0)):
        imgui.push_id(identifier)
        _copy(self.get_text())
        imgui.same_line()
        _, self.raw = imgui.checkbox(cyui.tr_label('Raw text'), self.raw)
        if self.raw:
            imgui.input_text_multiline('##raw', self.get_text(), _remaining(size), imgui.InputTextFlags_.read_only)
        else:
            _link(documents.document_view('##markdown', self.state, self.document, _remaining(size)))
        imgui.pop_id()


class ConversationView:
    def __init__(self):
        self.messages = []
        self.state = documents.TranscriptState()
        self.raw = False

    def append(self, role, text):
        identifier = stable_id('message', len(self.messages)+1)
        self.messages.append(documents.TranscriptMessage(identifier, role, text))

    def clear(self):
        self.messages.clear()
        self.state = documents.TranscriptState()

    def render(self, identifier, streamed='', size=(0, 0)):
        rows = list(self.messages)
        if streamed:
            rows.append(documents.TranscriptMessage(stable_id('message', len(rows)+1), 'Assistant', streamed))
        rows = [documents.TranscriptMessage(m.id, cyui.tr(m.role), m.content, m.time) for m in rows]
        imgui.push_id(identifier)
        text = '\n\n'.join('### '+m.role+'\n'+m.content for m in rows)
        _copy(text)
        imgui.same_line()
        _, self.raw = imgui.checkbox(cyui.tr_label('Raw text'), self.raw)
        if self.raw:
            imgui.input_text_multiline('##raw', text, _remaining(size), imgui.InputTextFlags_.read_only)
        else:
            _link(documents.transcript('##messages', self.state, rows, _remaining(size)))
        imgui.pop_id()


class LogView:
    def __init__(self):
        self.text = ''
        self.buffer = diagnostics.LogBuffer()
        self.state = diagnostics.LogState()
        self.raw = False

    def set_text(self, text):
        if self.text == text:
            return
        self.text = text
        self.buffer.clear()
        for line in text.splitlines():
            level = 'error' if re.search(r'\b(error|fatal|failed)\b', line, re.I) else (
                'warning' if re.search(r'\bwarn(?:ing)?\b', line, re.I) else
                'debug' if re.search(r'\bdebug\b', line, re.I) else 'info')
            self.buffer.append(level, line)

    def get_text(self):
        return self.text

    def render(self, identifier, size=(0, 0)):
        imgui.push_id(identifier)
        _, self.raw = imgui.checkbox(cyui.tr_label('Raw text'), self.raw)
        if self.raw:
            imgui.input_text_multiline('##raw', self.text, _remaining(size), imgui.InputTextFlags_.read_only)
        else:
            diagnostics.log_view('##log', self.state, self.buffer, _remaining(size))
        imgui.pop_id()


class DiffView:
    def __init__(self):
        self.document = diff.DiffDocument()
        self.state = diff.DiffState()
        self.signature = None
        self.raw_text = ''
        self.raw = False

    def set_unified(self, text, language='plain'):
        signature = ('unified', text, language)
        if signature != self.signature:
            self.document.set_unified(text, language)
            self.signature, self.raw_text = signature, text
            self.state = diff.DiffState(split=self.state.split)

    def set_texts(self, before, after, language='plain'):
        signature = ('texts', before, after, language)
        if signature != self.signature:
            self.document.set_texts(before, after, language)
            self.signature, self.raw_text = signature, after
            self.state = diff.DiffState(split=self.state.split)

    def render(self, identifier, size=(0, 0)):
        imgui.push_id(identifier)
        _copy(self.raw_text)
        imgui.same_line()
        _, self.raw = imgui.checkbox(cyui.tr_label('Raw text'), self.raw)
        if self.document.approximate:
            cyui.callout('warning', cyui.tr('Diff work limit reached; unmatched regions are shown as replacements.'))
        if self.raw:
            imgui.input_text_multiline('##raw', self.raw_text, _remaining(size), imgui.InputTextFlags_.read_only)
            result = None
        else:
            result = diff.diff_viewer('##diff', self.state, self.document, _remaining(size))
        imgui.pop_id()
        return result


def diagnostic_rows(rows, namespace):
    result = []
    for index, row in enumerate(rows):
        location = row.get('location') or {}
        point = location.get('point') or {}
        path = row.get('file') or location.get('path', '')
        line, column = row.get('line', point.get('line', 0)), row.get('column', point.get('column', 0))
        message = (str(row['code']) + ': ' if row.get('code') else '') + row.get('message', '')
        result.append(diagnostics.Diagnostic(stable_id(namespace, path, line, column, row.get('code'), index),
            message, path, line, column,
            {'warn': 'warning', 'information': 'info', 'hidden': 'debug'}.get(
                str(row.get('severity', row.get('level', 'error'))).lower(),
                str(row.get('severity', row.get('level', 'error'))).lower())))
    return result
