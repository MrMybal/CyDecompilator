"""Source documents, revision-checked semantic overlays and themed editing/reading."""
from dataclasses import dataclass, field
import re
from .common import ui, item_id

KEYWORDS = set('async await break case catch class const constexpr continue def default delete do else enum export extern false finally fn for from function if impl import in interface let match namespace new None null nullptr override pass private protected pub public raise return self sizeof static struct super switch template this throw trait true try type typedef using var virtual void while with yield'.split())
TYPES = set('auto bool byte char double float float2 float3 float4 float4x4 half int int32_t int64_t long short signed size_t std string String uint uint32_t uint64_t unsigned Vec2 Vec3 vec2 vec3 vec4'.split())
TOKEN = re.compile(r'(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|(?P<number>\b\d[\w.]*)|(?P<word>[^\W\d]\w*)|(?P<text>.)', re.UNICODE)


def expand_tabs(text, tab_size=4):
    return text.expandtabs(max(1, tab_size))


def display_offset(raw, byte_offset, tab_size=4):
    prefix = raw.encode('utf8')[:byte_offset].decode('utf8')
    return len(prefix.expandtabs(tab_size).encode('utf8'))


@dataclass
class CodeLine:
    text: str
    spans: list = field(default_factory=list)
    overlays: list = field(default_factory=list)


@dataclass
class SourceSpan:
    line: int
    start_byte: int
    end_byte: int
    role: str


class CodeDocument:
    def __init__(self, text='', language='plain', revision=0):
        self.text, self.language, self.revision, self.lines, self.columns = None, language, 0, [], 0
        self.set_text(text, language, revision)

    def set_text(self, text, language='plain', revision=0):
        if len(text.encode('utf8')) > 32*1024*1024:
            raise ValueError('CodeDocument exceeds 32 MiB; supply a paged document')
        if text == self.text and language == self.language:
            if revision and revision != self.revision:
                self.revision = revision
                for line in self.lines:
                    line.overlays.clear()
            return False
        self.text, self.language, self.revision = text, language, revision or self.revision+1
        self.raw_lines = [line.removesuffix('\r') for line in text.split('\n')]
        self.lines, block_comment, quote = [], False, ''
        # As in C++: '#' comments in Python/INI, '--' in SQL/Lua, '//' in the C family only,
        # and '/* */' everywhere except Python/INI.
        hash_comments, dash_comments = language in ('python', 'ini'), language in ('sql', 'lua')
        for raw in self.raw_lines:
            text = expand_tabs(raw)
            line, at = CodeLine(text), 0
            while at < len(text):
                start = at
                if language == 'plain':
                    line.spans.append((0, len(text), 'text'))
                    break
                if block_comment or quote:
                    end_marker = '*/' if block_comment else quote
                    end = text.find(end_marker, at)
                    at = len(text) if end < 0 else end+len(end_marker)
                    line.spans.append((start, at-start, 'comment' if block_comment else 'string'))
                    if end >= 0:
                        block_comment, quote = False, ''
                    continue
                if not hash_comments and text.startswith('/*', at):
                    end = text.find('*/', at+2)
                    block_comment = end < 0
                    at = len(text) if end < 0 else end+2
                    line.spans.append((start, at-start, 'comment'))
                    continue
                if language == 'python' and (text.startswith('"""', at) or text.startswith("'''", at)):
                    quote = text[at:at+3]
                    end = text.find(quote, at+3)
                    at = len(text) if end < 0 else end+3
                    if end >= 0:
                        quote = ''
                    line.spans.append((start, at-start, 'string'))
                    continue
                if (hash_comments and text[at] == '#') or (dash_comments and text.startswith('--', at)) or (language == 'ini' and text[at] == ';') or (not hash_comments and not dash_comments and text.startswith('//', at)):
                    line.spans.append((at, len(text)-at, 'comment'))
                    break
                if text[at] == '#' and not hash_comments:
                    line.spans.append((at, len(text)-at, 'preprocessor'))
                    break
                token = TOKEN.match(text, at)
                at = token.end()
                role = token.lastgroup
                if role == 'word':
                    word = token.group()
                    role = 'keyword' if word in KEYWORDS else 'type' if word in TYPES else 'function' if text[at:].lstrip().startswith('(') else 'text'
                line.spans.append((start, at-start, role))
            self.lines.append(line)
        # The widest line in characters; the viewer sizes its scroll width from it, like C++.
        self.columns = max((len(line.text) for line in self.lines), default=0)
        return True

    def set_overlays(self, spans, revision):
        if revision != self.revision:
            return False
        for line in self.lines:
            line.overlays.clear()
        for span in spans:
            if not 0 <= span.line < len(self.lines) or not 0 <= span.start_byte <= span.end_byte <= len(self.raw_lines[span.line].encode('utf8')):
                continue
            raw = self.raw_lines[span.line].encode('utf8')
            try:
                start = len(expand_tabs(raw[:span.start_byte].decode('utf8')))
                end = len(expand_tabs(raw[:span.end_byte].decode('utf8')))
            except UnicodeDecodeError:
                continue
            self.lines[span.line].overlays.append((start, end-start, span.role))
        return True


def token_color(role, background=None):
    _, c = ui()
    p = c.palette()
    color = {'keyword': p.accent, 'type': p.info, 'number': p.warning, 'string': p.success, 'comment': p.textFaint, 'preprocessor': c.mix(p.info, p.accent, .5), 'function': c.mix(p.text, p.warning, .4)}.get(role, p.text)
    def luminance(color):
        values = [(color >> shift & 255)/255 for shift in (0, 8, 16)]
        values = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(a*b for a, b in zip(values, (.2126, .7152, .0722)))
    ground = luminance(p.bg0 if background is None else background)
    for step in range(11):
        candidate = c.mix(color, p.text, step/10)
        value = luminance(candidate)
        if (max(ground, value)+.05)/(min(ground, value)+.05) >= 4.5:
            return candidate
    return p.text


def paint_line(draw, position, line, background=None):
    i, _ = ui()
    cuts = sorted({0, len(line.text)} | {max(0, min(len(line.text), at)) for a, length, _ in line.spans+line.overlays for at in (a, a+length)})
    x, y = position
    for a, b in zip(cuts, cuts[1:]):
        role = 'text'
        for start, length, kind in line.spans+line.overlays:
            if start <= a < start+length:
                role = kind
        text = line.text[a:b]
        draw.add_text((x, y), token_color(role, background), text)
        x += i.calc_text_size(text).x


@dataclass
class CodeViewState:
    query: str = ''
    selected_line: int = -1
    focus_line: int = -1


def code_viewer(identifier, state, document, size=(0, 300), annotations=()):
    i, c = ui()
    i.push_id(identifier)
    i.set_next_item_width(-c.dp(100))
    _, state.query = i.input_text('##find', state.query)
    i.same_line()
    if i.button(c.tr_label('Next')) and state.query:
        for offset in range(1, len(document.lines)+1):
            index = (state.selected_line+offset) % len(document.lines)
            if state.query in document.lines[index].text:
                state.focus_line = state.selected_line = index
                break
    size = size[0], max(c.dp(1), size[1]-i.get_frame_height_with_spacing()) if size[1] > 0 else size[1]
    i.begin_child('##source', size, i.ChildFlags_.borders, i.WindowFlags_.horizontal_scrollbar)
    if hasattr(c, 'mono_font'):
        i.push_font(c.mono_font(), 0.)
    height, gutter = i.get_text_line_height_with_spacing(), c.dp(56)
    width = max(i.get_content_region_avail().x, gutter+document.columns*i.calc_text_size('M').x)
    if state.focus_line >= 0:
        i.set_scroll_y(max(0, state.focus_line*height-i.get_window_height()*.25))
        state.focus_line = -1
    request = None
    # Each row is exactly height tall (it already holds the spacing), so the clipper, the
    # scroll extent and focus_line agree down to the last line.
    i.push_style_var(i.StyleVar_.item_spacing, (i.get_style().item_spacing.x, 0))
    clip = i.ListClipper()
    clip.begin(len(document.lines), height)
    while clip.step():
        for index in range(clip.display_start, clip.display_end):
            position = tuple(i.get_cursor_screen_pos())
            i.invisible_button(item_id(index), (width, height))
            draw, p = i.get_window_draw_list(), c.palette()
            if state.selected_line == index:
                draw.add_rect_filled(position, (position[0]+width, position[1]+height), p.selection)
            draw.add_text((position[0]+c.dp(4), position[1]), p.textFaint, str(index+1))
            paint_line(draw, (position[0]+gutter, position[1]), document.lines[index])
            if state.query and state.query in document.lines[index].text:
                draw.add_rect((position[0]+gutter, position[1]), (position[0]+width, position[1]+height), p.warning, 0, 0, c.dp(1))
            if i.is_item_clicked():
                request = state.selected_line = index
            for line, message in annotations:
                if line == index and i.is_item_hovered():
                    i.set_tooltip(message)
    i.pop_style_var()
    if hasattr(c, 'mono_font'):
        i.pop_font()
    i.end_child()
    i.pop_id()
    return request


class CodeEditor:
    """Themed text editing with native ImGui undo and an optional live syntax preview.

    The richer C++ CodeEditor is separate. No Python binding palette or backend ABI
    is patched, and plain import does not load editor/parser dependencies.
    """
    def __init__(self, text='', language='plain'):
        self.text, self.language = text, language
        self.read_only, self.preview = False, True
        self.document, self.view = CodeDocument(text, language), CodeViewState()

    def set_text(self, text):
        self.text = text

    def draw(self, identifier, size=(0, 360)):
        i, c = ui()
        flags = i.InputTextFlags_.allow_tab_input | (i.InputTextFlags_.read_only if self.read_only else 0)
        crlf = '\r\n' in self.text
        changed, value = i.input_text_multiline(identifier, self.text, (size[0], size[1]*.5 if self.preview else size[1]), flags)
        if changed:
            self.text = value.replace('\r\n', '\n').replace('\n', '\r\n') if crlf else value
        if self.preview:
            self.document.set_text(self.text, self.language)
            code_viewer(identifier+'##preview', self.view, self.document, (size[0], size[1]*.5))
        return changed
