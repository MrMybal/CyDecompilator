"""Opt-in filters for host-owned panels, menus and lists; no ImGui patch needed."""
from dataclasses import dataclass, field
from .locale import tr, tr_label
from .common import ui, item_id

_groups = {
    'a': 'ÀÁÂÃÄÅàáâãäåĀāĂăĄą', 'c': 'ÇçĆćĈĉĊċČč',
    'd': 'ĎďĐđ', 'e': 'ÈÉÊËèéêëĒēĔĕĖėĘęĚě',
    'g': 'ĜĝĞğĠġĢģ', 'h': 'ĤĥĦħ', 'i': 'ÌÍÎÏìíîïĨĩĪīĬĭĮįİı',
    'j': 'Ĵĵ', 'k': 'Ķķĸ', 'l': 'ĹĺĻļĽľĿŀŁł', 'n': 'ÑñŃńŅņŇňŉŊŋ',
    'o': 'ÒÓÔÕÖòóôõöØøŌōŎŏŐő', 'r': 'ŔŕŖŗŘř', 's': 'ŚśŜŝŞşŠšſ',
    't': 'ŢţŤťŦŧ', 'u': 'ÙÚÛÜùúûüŨũŪūŬŭŮůŰűŲų',
    'w': 'Ŵŵ', 'y': 'ÝýÿŶŷŸ', 'z': 'ŹźŻżŽž',
    'ae': 'Ææ', 'oe': 'Œœ', 'ss': 'ßẞ', 'ij': 'Ĳĳ',
}
_fold = {ord(letter): folded for folded, letters in _groups.items() for letter in letters}
_fold.update({ord(chr(code)): chr(code+32) for code in range(65, 91)})
_fold.update({code: '' for code in range(0x300, 0x370)})
_fold.update({code: ' ' for code in (0xa0, *range(0x2000, 0x200b))})


def fold_filter_text(text):
    """ASCII/Latin case, accents and ligatures; preserve other Unicode text."""
    return text.translate(_fold)


@dataclass
class TextFilter:
    query: str = ''
    _compiled: str = field(default='', init=False, repr=False)
    _words: tuple = field(default=(), init=False, repr=False)
    _focus: bool = field(default=False, init=False, repr=False)

    def _compile(self):
        if self.query != self._compiled:
            self._compiled = self.query
            self._words = tuple(fold_filter_text(self.query).split())

    def active(self):
        self._compile()
        return bool(self._words)

    def matches(self, label, keywords=''):
        self._compile()
        visible = label.split('##', 1)[0]
        text = fold_filter_text(visible+' '+tr(visible)+' '+keywords)
        return all(word in text for word in self._words)

    def clear(self):
        self.query = self._compiled = ''
        self._words = ()

    def focus(self):
        self._focus = True


def filter_box(identifier, state, hint='Filter (Ctrl/Cmd+F)...', width=0., shortcut=True,
               focus_on_appearing=False, reset_on_appearing=False):
    """Returns query_changed; keep one TextFilter per panel/menu/list."""
    i, c = ui()
    i.push_id(identifier)
    before = state.query
    appearing, io = i.is_window_appearing(), i.get_io()
    if appearing and reset_on_appearing:
        state.clear()
    # Modern Dear ImGui normalizes macOS Command to Ctrl in its input queue.
    modifier = io.key_ctrl
    focus = shortcut and modifier and not io.key_shift and not io.key_alt and not io.want_text_input and i.is_window_focused(i.FocusedFlags_.child_windows) and i.is_key_pressed(i.Key.f, False)
    if state._focus or focus or (appearing and focus_on_appearing):
        i.set_keyboard_focus_here()
    state._focus = False
    height = i.get_frame_height()
    extent = width if width > 0 else i.get_content_region_avail().x+width
    clear = height+i.get_style().item_spacing.x
    i.set_next_item_width(max(c.dp(32), extent-clear))
    _, state.query = i.input_text_with_hint('##query', tr(hint), state.query, i.InputTextFlags_.escape_clears_all)
    i.same_line()
    with c.scoped_disabled(not state.query):
        if c.ghost_button('x##clear', (height, height)):
            state.clear(); state.focus()
    c.tooltip('Clear filter (Escape)')
    i.pop_id()
    return before != state.query


def begin_filtered_section(label, state, has_matching_children, default_open=True):
    i, c = ui()
    title = tr_label(label)
    if not state.active():
        return c.begin_section(title, default_open)
    if not has_matching_children and not state.matches(label):
        return False
    storage, key = i.get_state_storage(), i.get_id(title)
    previous = storage.get_int(key, int(default_open))
    i.set_next_item_open(True, i.Cond_.always)
    shown = c.begin_section(title, default_open)
    storage.set_int(key, previous)
    return shown


@dataclass
class FilterMenuItem:
    id: int = 0
    label: str = ''
    shortcut: str = ''
    keywords: str = ''
    enabled: bool = True
    checked: bool = False
    children: list = field(default_factory=list)


@dataclass
class FilterMenuMatch:
    id: int
    label: str
    shortcut: str
    breadcrumb: str
    enabled: bool
    checked: bool


def filter_menu_matches(entries, state):
    result = []
    def visit(items, aliases='', path='', enabled=True):
        for entry in items:
            visible = entry.label.split('##', 1)[0]
            label, keywords = tr(visible), aliases+' '+entry.keywords
            if entry.children:
                visit(entry.children, keywords+' '+visible+' '+label,
                      path+' / '+label if path else label, enabled and entry.enabled)
            elif entry.id and state.matches(entry.label, keywords):
                result.append(FilterMenuMatch(entry.id, label, entry.shortcut, path, enabled and entry.enabled, entry.checked))
    visit(entries)
    return result


def filter_menu(identifier, state, entries, width=260., reset_on_open=True, focus_on_open=True):
    """Draw inside an open menu, popup or panel; return a host action ID or 0."""
    i, c = ui()
    i.push_id(identifier)
    filter_box('##filter', state, 'Filter menu...', c.dp(width), focus_on_appearing=focus_on_open, reset_on_appearing=reset_on_open)
    i.separator()
    request = 0
    if state.active():
        matches = filter_menu_matches(entries, state)
        if not matches:
            c.text_dim(tr('No matching items'))
        path = ''
        for match in matches:
            if path != match.breadcrumb:
                path = match.breadcrumb
                if path: c.section_title(path)
            i.push_id(item_id(match.id))
            clicked, _ = i.menu_item(match.label+'###action', match.shortcut, match.checked, match.enabled)
            if clicked: request = match.id
            i.pop_id()
    else:
        def draw(items):
            chosen = 0
            for n, entry in enumerate(items):
                i.push_id(n)
                if entry.children:
                    if i.begin_menu(tr_label(entry.label), entry.enabled):
                        chosen = draw(entry.children) or chosen
                        i.end_menu()
                elif entry.id:
                    clicked, _ = i.menu_item(tr_label(entry.label), entry.shortcut, entry.checked, entry.enabled)
                    if clicked: chosen = entry.id
                elif not entry.label:
                    i.separator()
                i.pop_id()
            return chosen
        request = draw(entries)
    i.pop_id()
    return request
