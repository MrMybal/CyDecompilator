from dataclasses import dataclass, replace
from .common import ui, item_id


@dataclass
class Command:
    id: int
    label: str
    shortcut: str = ''
    category: str = ''
    enabled: bool = True


@dataclass
class CommandState:
    query: str = ''
    selected: int = 0
    was_open: bool = False


def rank_commands(commands, query):
    words, ranked = query.casefold().split(), []
    for index, command in enumerate(commands):
        label, text = command.label.casefold(), (command.label+' '+command.category+' '+command.shortcut).casefold()
        positions = [text.find(word) for word in words]
        if all(p >= 0 for p in positions):
            ranked.append((sum(min(position, 10000) for position in positions), index))
    return [index for _, index in sorted(ranked)]


def command_palette(identifier, opened, state, commands, size=(560, 400)):
    """Returns (open, requested_id). The host executes the requested command."""
    i, c = ui()
    identifier = c.tr_label(identifier)
    commands = [replace(command, label=c.tr(command.label), category=c.tr(command.category)) for command in commands]
    request = 0
    if opened and not state.was_open:
        i.open_popup(identifier)
        state.query, state.selected = '', 0
    state.was_open = opened
    if not opened:
        if i.is_popup_open(identifier):
            shown, _ = i.begin_popup_modal(identifier)
            if shown:
                i.close_current_popup()
                i.end_popup()
        return False, request
    i.set_next_window_size((c.dp(size[0]), c.dp(size[1])), i.Cond_.appearing)
    shown, opened = i.begin_popup_modal(identifier, opened)
    if shown:
        if i.is_window_appearing():
            i.set_keyboard_focus_here()
        i.set_next_item_width(-1)
        # CallbackHistory makes the field own Up/Down, so keyboard navigation does not move
        # the focus out of it; the list selection below reads them instead.
        changed, state.query = i.input_text('##query', state.query, i.InputTextFlags_.callback_history, lambda data: 0)
        if changed:
            state.selected = 0
        ranked = rank_commands(commands, state.query)
        if ranked:
            state.selected = max(0, min(len(ranked)-1, state.selected + int(i.is_key_pressed(i.Key.down_arrow)) - int(i.is_key_pressed(i.Key.up_arrow))))
        i.begin_child('##results')
        for n, index in enumerate(ranked):
            command = commands[index]
            i.push_id(item_id(command.id))
            i.begin_disabled(not command.enabled)
            pos = tuple(i.get_cursor_screen_pos())
            clicked, _ = i.selectable('##command', n == state.selected, 0, (0, i.get_frame_height()))
            c.clipped_text(i.get_window_draw_list(), pos, max(0, i.get_content_region_avail().x-c.dp(100)), c.palette().text, command.label)
            if command.shortcut:
                i.same_line(max(0, i.get_window_width()-c.dp(120)))
                c.text_faint(command.shortcut)
            if n == state.selected and (i.is_key_pressed(i.Key.down_arrow) or i.is_key_pressed(i.Key.up_arrow)):
                i.set_scroll_here_y(.5)
            if command.enabled and (clicked or (n == state.selected and i.is_key_pressed(i.Key.enter))):
                request, opened = command.id, False
                i.close_current_popup()
            i.end_disabled()
            i.pop_id()
        i.end_child()
        if i.is_key_pressed(i.Key.escape):
            opened = False
            i.close_current_popup()
        i.end_popup()
    state.was_open = opened
    return opened, request
