"""Shared model and gesture contract; usable without imgui_bundle."""
from dataclasses import dataclass, field
from math import isfinite, floor, ceil
from copy import deepcopy


@dataclass
class Edit:
    phase: str = 'none'
    value: object = None

    @property
    def committed(self):
        return self.phase == 'commit'


@dataclass
class Range:
    minimum: float = 0.0
    maximum: float = 1.0

    @property
    def span(self):
        return self.maximum - self.minimum

    @property
    def valid(self):
        return isfinite(self.minimum) and isfinite(self.maximum) and self.span > 0

    def contains(self, value):
        return self.minimum <= value <= self.maximum


def snap(value, step):
    if step <= 0 or not isfinite(step):
        return value
    value /= step
    return (floor(value + .5) if value >= 0 else ceil(value - .5)) * step


def zoom_range(view, anchor, factor):
    if not view.valid or not isfinite(anchor) or not isfinite(factor) or factor <= 0:
        return deepcopy(view)
    # The smallest span stays well above the spacing of doubles at this magnitude, so a deep
    # zoom on large values (times in ns) never collapses to minimum == maximum.
    magnitude = max(abs(view.minimum), abs(view.maximum), abs(anchor))
    floor = max(1e-9, magnitude * 1e-12)
    span = max(min(1e15, view.span * factor), min(view.span, floor))
    part = (anchor - view.minimum) / view.span
    result = Range(anchor - part * span, anchor + (1 - part) * span)
    return result if result.valid else deepcopy(view)


def select(selection, identifier, extend=False):
    if not extend:
        selection[:] = [identifier]
    elif identifier in selection:
        selection.remove(identifier)
    else:
        selection.append(identifier)


def ui():
    from imgui_bundle import imgui
    import cyui
    return imgui, cyui


_wheel = None


def wheel_taken():
    i, _ = ui()
    return _wheel == (i.get_current_context(), i.get_frame_count(), i.get_time())


def take_wheel():
    global _wheel
    i, _ = ui()
    _wheel = (i.get_current_context(), i.get_frame_count(), i.get_time())
    if hasattr(i, 'set_item_key_owner'):
        i.set_item_key_owner(i.Key.mouse_wheel_y)


def item_id(identifier):
    """Stable string for 64-bit IDs; never derive focus from a Python object address."""
    return f'##cyui-{identifier}'
