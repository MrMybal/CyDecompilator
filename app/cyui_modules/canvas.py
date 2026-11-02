from dataclasses import dataclass, field
from math import exp, isfinite, ceil
from .common import ui, take_wheel, wheel_taken


@dataclass
class CanvasView:
    origin: tuple = (0.0, 0.0)
    zoom: float = 1.0

    def world(self, screen, top=(0, 0)):
        return tuple(self.origin[n] + (screen[n] - top[n]) / self.zoom for n in (0, 1))

    def screen(self, world, top=(0, 0)):
        return tuple(top[n] + (world[n] - self.origin[n]) * self.zoom for n in (0, 1))

    def zoom_at(self, anchor, zoom, top=(0, 0)):
        fixed = self.world(anchor, top)
        if isfinite(zoom) and zoom > 0:
            self.zoom = zoom
            self.origin = tuple(fixed[n] - (anchor[n] - top[n]) / zoom for n in (0, 1))

    def fit(self, low, high, available, padding=24):
        self.zoom = max(.001, min(1000, min(max(1, available[n] - padding * 2) / max(1, high[n] - low[n]) for n in (0, 1))))
        self.origin = tuple((low[n] + high[n]) / 2 - available[n] / (2 * self.zoom) for n in (0, 1))


@dataclass
class CanvasState:
    view: CanvasView = field(default_factory=CanvasView)
    panning: bool = False


class Canvas:
    """Scoped clipping and the same pointer-centered navigation as C++ CanvasScope."""
    def __init__(self, identifier, state, size=(0, 240), grid=True, navigation=True):
        self.i, self.c = ui()
        i, c = self.i, self.c
        available = i.get_content_region_avail()
        self.size = tuple(max(c.dp(1), size[n] if size[n] > 0 else available[n] + size[n]) for n in (0, 1))
        self.top = tuple(i.get_cursor_screen_pos())
        self.bottom = tuple(self.top[n] + self.size[n] for n in (0, 1))
        i.invisible_button(identifier, self.size, i.ButtonFlags_.mouse_button_left | i.ButtonFlags_.mouse_button_middle)
        self.hovered, self.focused = i.is_item_hovered(), i.is_window_focused(i.FocusedFlags_.root_and_child_windows)
        self.draw = i.get_window_draw_list()
        self.state = state
        io = i.get_io()
        mouse = tuple(io.mouse_pos)
        if navigation:
            if self.hovered and (i.is_mouse_clicked(2) or (i.is_key_down(i.Key.space) and i.is_mouse_clicked(0))):
                state.panning = True
            if not i.is_mouse_down(0) and not i.is_mouse_down(2):
                state.panning = False
            if state.panning:
                state.view.origin = tuple(state.view.origin[n] - io.mouse_delta[n] / state.view.zoom for n in (0, 1))
            if self.hovered and io.mouse_wheel and not wheel_taken():
                state.view.zoom_at(mouse, max(.05, min(64, state.view.zoom * exp(io.mouse_wheel * .15))), self.top)
                take_wheel()
        self.mouse = state.view.world(mouse, self.top)
        self.draw.push_clip_rect(self.top, self.bottom, True)
        p = c.palette()
        self.draw.add_rect_filled(self.top, self.bottom, p.bg0)
        if grid:
            step = 32.0
            while step * state.view.zoom < c.dp(12):
                step *= 2
            low, high = state.view.world(self.top, self.top), state.view.world(self.bottom, self.top)
            for axis in (0, 1):
                value = ceil(low[axis] / step) * step
                for _ in range(4096):
                    if value > high[axis]:
                        break
                    point = [0, 0]
                    point[axis] = value
                    at = state.view.screen(point, self.top)[axis]
                    a, b = list(self.top), list(self.bottom)
                    a[axis] = b[axis] = at
                    self.draw.add_line(a, b, p.grid, c.dp(1))
                    value += step

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.draw.pop_clip_rect()
