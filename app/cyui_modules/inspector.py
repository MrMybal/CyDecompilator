"""Typed property editing. Hosts validate and apply committed proposals."""
from dataclasses import dataclass, field
from copy import deepcopy
from .common import Edit, ui, item_id
from .locale import tr


@dataclass
class Property:
    id: int
    label: str
    value: object
    help: str = ''
    read_only: bool = False
    password: bool = False
    multiline: bool = False
    minimum: object = None
    maximum: object = None
    choices: tuple = ()


@dataclass
class InspectorState:
    drafts: dict = field(default_factory=dict)
    active: set = field(default_factory=set)
    before: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    revision: int = 0


def property_matches(filter_state, prop, context=''):
    return filter_state.matches(prop.label, context+' '+tr(context)+' '+prop.help+' '+tr(prop.help))


def inspector(identifier, state, properties, revision=0, validate=None, filter_state=None, filter_context=''):
    i, c = ui()
    events = []
    if state.revision != revision:
        events.extend((key, Edit('cancel')) for key in state.active)
        state.active.clear()
        state.drafts.clear()
        state.errors.clear()
        state.revision = revision
    present = {p.id for p in properties}
    for key in set(state.drafts)-present:
        state.drafts.pop(key, None)
        state.before.pop(key, None)
        state.errors.pop(key, None)
        state.active.discard(key)
    i.push_id(identifier)
    visible = 0
    for prop in properties:
        key = prop.id
        if filter_state is not None and not property_matches(filter_state, prop, filter_context):
            if key in state.active:
                i.push_id(item_id(key))
                if i.internal.get_active_id() == i.get_id('##value'):
                    i.internal.clear_active_id()
                i.pop_id()
                state.drafts[key] = deepcopy(state.before[key])
                state.active.discard(key)
                state.errors.pop(key, None)
                events.append((key, Edit('cancel', deepcopy(state.before[key]))))
            continue
        visible += 1
        if key not in state.active:
            state.drafts[key] = deepcopy(prop.value)
        value = state.drafts[key]
        i.push_id(item_id(key))
        i.text_unformatted(c.tr(prop.label))
        if prop.help and i.is_item_hovered():
            i.set_tooltip(c.tr(prop.help))
        i.set_next_item_width(-1)
        i.begin_disabled(prop.read_only)
        immediate = False
        if isinstance(value, bool):
            changed, value = i.checkbox('##value', value)
            immediate = True
        elif isinstance(value, int):
            # Decimal text preserves all int64 bits on every Python binding.
            changed, text = i.input_text('##value', str(value), i.InputTextFlags_.chars_decimal)
            try:
                value = int(text)
            except ValueError:
                changed = False
        elif isinstance(value, float):
            changed, value = i.input_double('##value', value, 0., 0., '%.9g')
        elif prop.choices:
            index = prop.choices.index(value) if value in prop.choices else -1
            changed, index = i.combo('##value', index, [c.tr(choice) for choice in prop.choices])
            if changed:
                value = prop.choices[index]
            immediate = True
        elif isinstance(value, str):
            flags = i.InputTextFlags_.password if prop.password else 0
            if prop.multiline:
                changed, value = i.input_text_multiline('##value', value, (0, c.dp(80)), flags)
            else:
                changed, value = i.input_text('##value', value, flags)
        else:
            i.text_unformatted(str(value))
            changed = False
        activated, active = i.is_item_activated(), i.is_item_active()
        deactivated, edited = i.is_item_deactivated(), i.is_item_deactivated_after_edit()
        escape = i.is_key_pressed(i.Key.escape, False)
        i.end_disabled()
        if prop.read_only:
            changed = False
        if not prop.read_only and (activated or (changed and key not in state.active)):
            state.active.add(key)
            state.before[key] = deepcopy(prop.value)
            events.append((key, Edit('begin', deepcopy(prop.value))))
        if changed:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if prop.minimum is not None:
                    value = max(prop.minimum, value)
                if prop.maximum is not None:
                    value = min(prop.maximum, value)
            state.drafts[key] = value
            state.errors[key] = validate(key, value) if validate else ''
            events.append((key, Edit('update', deepcopy(value))))
        # As in C++: Escape cancels only the field being edited. A text field takes Escape
        # itself and deactivates on that frame, so a field that has just let go counts too.
        if key in state.active and escape and (active or deactivated):
            if active and hasattr(i, 'internal'):
                i.internal.clear_active_id()
            state.drafts[key] = deepcopy(state.before[key])
            state.active.discard(key)
            state.errors.pop(key, None)
            events.append((key, Edit('cancel')))
        elif key in state.active and ((immediate and changed) or edited) and not state.errors.get(key):
            # Switches and choices commit at once; text and numbers when they let go.
            state.active.discard(key)
            events.append((key, Edit('commit', deepcopy(state.drafts[key]))))
        elif key in state.active and deactivated and not edited and not (immediate and changed):
            # Activated and left without an edit: let prop.value refresh the field again.
            state.drafts[key] = deepcopy(state.before[key])
            state.active.discard(key)
            state.errors.pop(key, None)
            events.append((key, Edit('cancel')))
        if state.errors.get(key):
            c.text_coloured(c.palette().error, state.errors[key])
        i.pop_id()
    i.pop_id()
    if not visible and filter_state is not None and filter_state.active():
        c.text_dim(c.tr('No matching properties'))
    return events
