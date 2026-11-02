"""Small, predictable Markdown subset and cached message transcripts."""
from dataclasses import dataclass, field
import re
from .common import ui, item_id
from .code import CodeDocument, CodeViewState, code_viewer


@dataclass
class Block:
    kind: str
    text: str = ''
    level: int = 0
    language: str = ''
    code: object = None
    rows: list = field(default_factory=list)


class Document:
    def __init__(self, text=''):
        self.text, self.blocks = None, []
        self.set_markdown(text)

    def set_markdown(self, text):
        if text == self.text:
            return False
        if len(text.encode('utf8')) > 32*1024*1024:
            raise ValueError('Document exceeds 32 MiB')
        self.text, self.blocks = text, []
        lines, at = text.splitlines(), 0
        while at < len(lines):
            line = lines[at]; at += 1
            if line.startswith(('```', '~~~')):
                fence, language, content = line[:3], line[3:].strip(), []
                while at < len(lines) and not lines[at].startswith(fence):
                    content.append(lines[at]); at += 1
                at += at < len(lines)
                value = '\n'.join(content)+ ('\n' if content else '')
                self.blocks.append(Block('code', value, language=language, code=CodeDocument(value, language or 'plain')))
            elif not line.strip():
                continue
            elif at < len(lines) and '|' in line and re.fullmatch(r'[\s|:\-]+', lines[at]) and '-' in lines[at]:
                rows = [[v.strip() for v in line.strip('|').split('|')]]
                at += 1
                while at < len(lines) and '|' in lines[at] and lines[at].strip():
                    rows.append([v.strip() for v in lines[at].strip('|').split('|')]); at += 1
                self.blocks.append(Block('table', rows=rows))
            elif line in ('---', '***', '___'):
                self.blocks.append(Block('rule'))
            elif match := re.match(r'^(#{1,6})\s+(.*)$', line):
                self.blocks.append(Block('heading', match[2], len(match[1])))
            elif line.startswith('> '):
                self.blocks.append(Block('quote', line[2:]))
            elif match := re.match(r'^\s*(?:[-*+] |\d+[.)] )(.*)$', line):
                self.blocks.append(Block('list', match[1]))
            else:
                self.blocks.append(Block('paragraph', line))
        return True


@dataclass
class DocumentState:
    code_views: dict = field(default_factory=dict)


# Explicit tokens plus words allow wrapping at each word, including links. The group that
# matched says what a token is: an unmatched '*', '**' or '`' is part of a plain word and is
# drawn as written (*args, **kwargs, a lone backtick).
_INLINE = re.compile(r'(?P<link>\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\))|(?P<mono>`[^`]+`)'
                     r'|(?P<strong>\*\*[^*\s](?:[^*]*[^*\s])?\*\*)|(?P<emphasis>\*[^*\s](?:[^*]*[^*\s])?\*)|(?P<word>\S+\s*)')


def _inline(text):
    i, c = ui()
    link, first = '', True
    tokens = _INLINE.finditer(text)
    right = i.get_cursor_screen_pos().x+i.get_content_region_avail().x
    previous_end = 0
    for token_match in tokens:
        gap = i.calc_text_size(" ").x if token_match.start() > previous_end else 0
        previous_end = token_match.end()
        token, kind = token_match.group(), token_match.lastgroup
        i.push_id(token_match.start())
        match = token_match if kind == 'link' else None
        mono, strong, emphasis = kind == 'mono', kind == 'strong', kind == 'emphasis'
        label = match['label'] if match else token[1:-1] if mono or emphasis else token[2:-2] if strong else token
        font = c.mono_font() if mono else c.bold_font() if strong else None
        if font:
            i.push_font(font, 0.)
        width = i.calc_text_size(label).x
        if not first:
            if i.get_item_rect_max().x+width+gap < right:
                i.same_line(0, gap)
        if match:
            if c.link_text(label):
                link = match['url']
        elif mono:
            c.text_coloured(c.palette().accent, label)
        elif emphasis:
            c.text_coloured(c.palette().textDim, label)
        else:
            i.text_unformatted(label)
        if font:
            i.pop_font()
        first = False
        i.pop_id()
    return link


def _content(state, document):
    i, c = ui()
    result = {'link': '', 'copied_block': -1}
    for n, block in enumerate(document.blocks):
        i.push_id(n)
        if block.kind == 'heading':
            c.heading(block.text, min(3, block.level))
        elif block.kind == 'rule':
            c.divider()
        elif block.kind == 'quote':
            c.callout('info', block.text)
        elif block.kind == 'code':
            c.text_faint(block.language)
            i.same_line()
            if c.ghost_button(c.tr_label('Copy')):
                i.set_clipboard_text(block.text)
                result['copied_block'] = n
            code_viewer('##code', state.code_views.setdefault(n, CodeViewState()), block.code, (0, c.dp(max(90, min(320, len(block.code.lines)*20+48)))))
        elif block.kind == 'table':
            columns = min(32, max(map(len, block.rows)))
            if i.begin_table('##table', columns, i.TableFlags_.borders | i.TableFlags_.row_bg | i.TableFlags_.sizing_stretch_same):
                for row, cells in enumerate(block.rows):
                    i.table_next_row(i.TableRowFlags_.headers if row == 0 else 0)
                    for col, cell in enumerate(cells[:columns]):
                        i.push_id(f"{row}-{col}")
                        i.table_next_column()
                        link = _inline(cell)
                        result['link'] = link or result['link']
                        i.pop_id()
                i.end_table()
        else:
            if block.kind == 'list':
                i.bullet(); i.same_line()
            result['link'] = _inline(block.text) or result['link']
        c.space(3)
        i.pop_id()
    return result


def document_view(identifier, state, document, size=(0, 320)):
    i, _ = ui()
    i.push_id(identifier)
    i.begin_child('##document', size)
    result = _content(state, document)
    i.end_child()
    i.pop_id()
    return result


@dataclass
class TranscriptMessage:
    id: int
    role: str
    content: str
    time: str = ''


@dataclass
class TranscriptState:
    documents: dict = field(default_factory=dict)
    views: dict = field(default_factory=dict)
    follow: bool = True
    count: int = 0


def transcript(identifier, state, messages, size=(0, 320)):
    i, c = ui()
    result, changed = {'copy': 0, 'link': ''}, False
    i.push_id(identifier)
    i.begin_child('##transcript', size)
    bottom = i.get_scroll_y() >= i.get_scroll_max_y()-c.dp(3)
    present = {m.id for m in messages}
    for message in messages:
        doc = state.documents.setdefault(message.id, Document())
        changed |= doc.set_markdown(message.content)
        view = state.views.setdefault(message.id, DocumentState())
        i.push_id(item_id(message.id))
        c.heading(message.role, 3); i.same_line(); c.text_faint(message.time)
        if c.ghost_button(c.tr_label('Copy message')):
            i.set_clipboard_text(message.content)
            result['copy'] = message.id
        result['link'] = _content(view, doc)['link'] or result['link']
        c.divider()
        i.pop_id()
    if state.follow and bottom and (changed or state.count != len(messages)):
        i.set_scroll_here_y(1.)
    state.count = len(messages)
    for key in set(state.documents)-present:
        del state.documents[key]
        state.views.pop(key, None)
    i.end_child()
    i.pop_id()
    return result
