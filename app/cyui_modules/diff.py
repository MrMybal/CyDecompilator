"""Backend-free unified/split diff presentation. Never performs a Git operation."""
from dataclasses import dataclass
from bisect import bisect_left
from collections import defaultdict
from array import array
import re
from .common import ui, item_id
from .code import CodeDocument, paint_line


@dataclass
class DiffRow:
    kind: str
    old_line: int
    new_line: int
    code: object


class DiffDocument:
    def __init__(self):
        self.rows, self.pairs, self.hunks = [], [], []
        self.revision, self.approximate = 0, False

    def _prepare(self, raw, language):
        old = '\n'.join(text for kind, a, b, text in raw if a)
        new = '\n'.join(text for kind, a, b, text in raw if b)
        old_doc, new_doc = CodeDocument(old, language), CodeDocument(new, language)
        ai = bi = 0
        self.rows, self.pairs, self.hunks = [], [], []
        changing = False
        for kind, a, b, text in raw:
            if kind == 'hunk' or (kind in ('added', 'removed') and not changing):
                self.hunks.append(len(self.rows))
            changing = kind in ('added', 'removed', 'hunk')
            line = new_doc.lines[bi] if b else old_doc.lines[ai] if a else CodeDocument(text).lines[0]
            ai += bool(a)
            bi += bool(b)
            self.rows.append(DiffRow(kind, a, b, line))
        at = 0
        while at < len(self.rows):
            if self.rows[at].kind in ('removed', 'added'):
                left, right = [], []
                while at < len(self.rows) and self.rows[at].kind in ('removed', 'added'):
                    (left if self.rows[at].kind == 'removed' else right).append(at)
                    at += 1
                self.pairs.extend((left[n] if n < len(left) else -1, right[n] if n < len(right) else -1) for n in range(max(len(left), len(right))))
            else:
                self.pairs.append((at, at))
                at += 1
        self.columns = max([len(row.code.text) for row in self.rows] or [0])
        self.revision += 1

    def set_texts(self, before, after, language='plain', work_budget=4000000):
        if max(len(before.encode('utf8')), len(after.encode('utf8'))) > 32*1024*1024:
            raise ValueError('DiffDocument exceeds 32 MiB per input')
        def lines(text):
            # A CR before each LF is a line ending, not content: CRLF against LF compares equal.
            rows = text.split('\n')[:-1] if text.endswith('\n') else text.split('\n') if text else []
            # Each line records whether it lost a CR, for the line-ending notice below.
            return [row.removesuffix('\r') for row in rows], [row.endswith('\r') for row in rows]
        (a, a_cr), (b, b_cr) = lines(before), lines(after)
        left, right = defaultdict(list), defaultdict(list)
        for n, text in enumerate(a):
            left[text].append(n)
        for n, text in enumerate(b):
            right[text].append(n)
        candidates = [(n, right[text][0]) for n, text in enumerate(a) if len(left[text]) == 1 and len(right[text]) == 1]
        tails, tail_values, previous = [], [], [-1]*len(candidates)
        for n, (_, value) in enumerate(candidates):
            slot = bisect_left(tail_values, value)
            if slot:
                previous[n] = tails[slot-1]
            if slot == len(tails):
                tails.append(n); tail_values.append(value)
            else:
                tails[slot], tail_values[slot] = n, value
        anchors = []
        n = tails[-1] if tails else -1
        while n >= 0:
            anchors.append(candidates[n]); n = previous[n]
        anchors.reverse(); anchors.append((len(a), len(b)))
        raw, ai, bi, self.approximate = [], 0, 0, False
        def emit(kind, x, y):
            raw.append((kind, 0 if kind == 'added' else x+1, 0 if kind == 'removed' else y+1, b[y] if kind == 'added' else a[x]))
        for anchor_a, anchor_b in anchors:
            end_a, end_b = anchor_a, anchor_b
            while ai < end_a and bi < end_b and a[ai] == b[bi]:
                emit('context', ai, bi); ai += 1; bi += 1
            suffix = 0
            while end_a > ai and end_b > bi and a[end_a-1] == b[end_b-1]:
                end_a -= 1; end_b -= 1; suffix += 1
            n, m = end_a-ai, end_b-bi
            if n and m and (n+1)*(m+1) <= work_budget:
                work_budget -= (n+1)*(m+1)
                dp = array('I', [0])*((n+1)*(m+1))
                for x in range(n-1, -1, -1):
                    for y in range(m-1, -1, -1):
                        dp[x*(m+1)+y] = 1+dp[(x+1)*(m+1)+y+1] if a[ai+x] == b[bi+y] else max(dp[(x+1)*(m+1)+y], dp[x*(m+1)+y+1])
                x = y = 0
                while x < n or y < m:
                    if x < n and y < m and a[ai+x] == b[bi+y]:
                        emit('context', ai+x, bi+y); x += 1; y += 1
                    elif y < m and (x == n or dp[x*(m+1)+y+1] > dp[(x+1)*(m+1)+y]):
                        emit('added', ai+x, bi+y); y += 1
                    else:
                        emit('removed', ai+x, bi+y); x += 1
            else:
                self.approximate |= bool(n and m)
                for x in range(ai, end_a):
                    emit('removed', x, bi)
                for y in range(bi, end_b):
                    emit('added', end_a, y)
            ai, bi = end_a, end_b
            for _ in range(suffix):
                emit('context', ai, bi); ai += 1; bi += 1
            if anchor_a < len(a):
                emit('context', ai, bi); ai += 1; bi += 1
        if a == b and raw and before.endswith('\n') != after.endswith('\n'):
            # Only the final newline differs: show the last line as changed.
            _, old, new, text = raw.pop()
            raw.extend((('removed', old, 0, text), ('added', 0, new, text)))
        # One notice when a line shown as unchanged differs only by its CR.
        if any(kind == 'context' and a_cr[old-1] != b_cr[new-1] for kind, old, new, _ in raw):
            raw.append(('notice', 0, 0, '\\ Line endings differ (CRLF / LF)'))
        if before and not before.endswith('\n'):
            raw.append(('notice', 0, 0, '\\ No newline at end of old document'))
        if after and not after.endswith('\n'):
            raw.append(('notice', 0, 0, '\\ No newline at end of new document'))
        self._prepare(raw, language)

    def set_unified(self, text, language='plain'):
        if len(text.encode('utf8')) > 32*1024*1024:
            raise ValueError('Unified diff exceeds 32 MiB')
        raw, a, b, in_hunk = [], 0, 0, False
        self.approximate = False
        # Only LF (and CRLF) end a line: splitlines() would also split on form feeds,
        # U+2028 and other characters that belong to the content.
        lines = text.split('\n')
        if lines and lines[-1] == '':
            lines.pop()
        for line in lines:
            line = line.removesuffix('\r')
            match = re.match(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                a, b = map(int, match.groups())
                raw.append(('hunk', 0, 0, line))
                in_hunk = True
            elif in_hunk and line.startswith('-'):
                raw.append(('removed', a, 0, line[1:])); a += 1
            elif in_hunk and line.startswith('+'):
                raw.append(('added', 0, b, line[1:])); b += 1
            elif in_hunk and line.startswith(' '):
                raw.append(('context', a, b, line[1:])); a += 1; b += 1
            else:
                if line.startswith(('diff ', '--- ')):
                    in_hunk = False
                raw.append(('notice', 0, 0, line))
        self._prepare(raw, language)


@dataclass
class DiffState:
    split: bool = True
    scroll: float = 0
    selected: int = -1
    focus: int = -1
    hunk: int = -1
    query: str = ''


def diff_viewer(identifier, state, document, size=(0, 320)):
    i, c = ui()
    i.push_id(identifier)
    _, state.split = i.checkbox(c.tr_label('Side by side'), state.split)
    i.same_line()
    if c.ghost_button(c.tr_label('Next change')) and document.hunks:
        state.hunk = (state.hunk+1) % len(document.hunks)
        state.focus = document.hunks[state.hunk]
    i.same_line()
    i.set_next_item_width(c.dp(180))
    _, state.query = i.input_text('##find', state.query)
    i.same_line()
    if c.ghost_button(c.tr_label('Find next')) and state.query and document.rows:
        count = len(document.rows)
        for n in range(1, count+1):
            index = (max(-1, state.selected)+n) % count
            if state.query in document.rows[index].code.text:
                state.focus = state.selected = index
                break
    height = max(c.dp(1), size[1]-i.get_frame_height_with_spacing()) if size[1] else 0
    width = size[0] or i.get_content_region_avail().x
    request = None
    def pane(name, side, pane_width):
        nonlocal request
        count = len(document.rows) if side < 0 else len(document.pairs)
        row_width = max(pane_width, max(c.dp(500), document.columns*i.calc_text_size('M').x+c.dp(90)))
        i.begin_child(name, (pane_width, height), i.ChildFlags_.borders, i.WindowFlags_.horizontal_scrollbar)
        row_height = i.get_text_line_height_with_spacing()
        if side >= 0:
            if i.is_window_hovered():
                state.scroll = i.get_scroll_y()
            else:
                i.set_scroll_y(state.scroll)
        if state.focus >= 0:
            row = state.focus if side < 0 else next((n for n, pair in enumerate(document.pairs) if state.focus in pair), 0)
            state.scroll = max(0, row*row_height-i.get_window_height()*.25)
            i.set_scroll_y(state.scroll)
        # Rows are exactly row_height tall, so the clipper and the scroll extent agree.
        i.push_style_var(i.StyleVar_.item_spacing, (i.get_style().item_spacing.x, 0))
        clip = i.ListClipper(); clip.begin(count, row_height)
        while clip.step():
            for n in range(clip.display_start, clip.display_end):
                index = n if side < 0 else document.pairs[n][side]
                pos = tuple(i.get_cursor_screen_pos())
                i.invisible_button(item_id(n), (row_width, row_height))
                if index < 0:
                    continue
                row, p, draw = document.rows[index], c.palette(), i.get_window_draw_list()
                tint = p.success if row.kind == 'added' else p.error if row.kind == 'removed' else p.info if row.kind == 'hunk' else p.bg0
                background = c.mix(p.bg0, tint, .14)
                draw.add_rect_filled(pos, (pos[0]+row_width, pos[1]+row_height), p.selection if state.selected == index else background)
                draw.add_text(pos, p.textFaint, f'{row.old_line:5} {row.new_line:5}' if side < 0 else str(row.old_line if side == 0 else row.new_line))
                if row.kind == 'notice':
                    draw.add_text((pos[0]+c.dp(88), pos[1]), p.textDim, c.tr(row.code.text))
                else:
                    paint_line(draw, (pos[0]+c.dp(88), pos[1]), row.code, background)
                if state.query and state.query in row.code.text:
                    draw.add_rect(pos, (pos[0]+row_width, pos[1]+row_height), p.warning, 0, 0, c.dp(1))
                if i.is_item_clicked():
                    state.selected, request = index, row
        i.pop_style_var()
        i.end_child()
    if state.split:
        pane('##before', 0, (width-i.get_style().item_spacing.x)/2)
        i.same_line()
        pane('##after', 1, (width-i.get_style().item_spacing.x)/2)
    else:
        pane('##unified', -1, width)
    state.focus = -1
    i.pop_id()
    return request
