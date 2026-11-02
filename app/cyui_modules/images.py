from dataclasses import dataclass, field
from copy import deepcopy
from math import hypot, cos, sin
from .common import Edit, ui
from .canvas import Canvas, CanvasState


@dataclass
class ImageData:
    texture: object = 0
    width: int = 0
    height: int = 0
    uv_min: tuple = (0, 0)
    uv_max: tuple = (1, 1)


@dataclass
class ImageState:
    canvas: CanvasState = field(default_factory=CanvasState)
    fit_pending: bool = True
    crop: object = None
    before: object = None
    start: object = None


def image_viewport(identifier, state, image, size=(0, 280), tool='inspect'):
    i, c = ui()
    result = {'pixel': None, 'clicked': False, 'crop': Edit()}
    with Canvas(identifier, state.canvas, size, False) as f:
        if image.width <= 0 or image.height <= 0:
            return result
        if state.fit_pending or (f.hovered and i.is_mouse_double_clicked(0)):
            state.canvas.view.fit((0, 0), (image.width, image.height), f.size, c.dp(12))
            state.fit_pending = False
        view, draw, p = state.canvas.view, f.draw, c.palette()
        a, b = view.screen((0, 0), f.top), view.screen((image.width, image.height), f.top)
        tile = c.dp(16)
        low, high = tuple(max(a[n], f.top[n]) for n in (0, 1)), tuple(min(b[n], f.bottom[n]) for n in (0, 1))
        y = low[1]
        while y < high[1]:
            x = low[0]
            while x < high[0]:
                draw.add_rect_filled((x, y), (min(x+tile, high[0]), min(y+tile, high[1])), p.bg2 if (int((x-low[0])/tile)+int((y-low[1])/tile)) % 2 else p.bg3)
                x += tile
            y += tile
        if image.texture:
            texture = image.texture if isinstance(image.texture, i.ImTextureRef) else i.ImTextureRef(image.texture)
            draw.add_image(texture, a, b, image.uv_min, image.uv_max)
        mouse = view.world(tuple(i.get_io().mouse_pos), f.top)
        if f.hovered and 0 <= mouse[0] < image.width and 0 <= mouse[1] < image.height:
            result['pixel'], result['clicked'] = (int(mouse[0]), int(mouse[1])), i.is_mouse_clicked(0)
        if tool == 'crop' and not state.canvas.panning:
            if result['clicked']:
                state.start, state.before = mouse, state.crop
                result['crop'] = Edit('begin', state.crop)
            if state.start:
                state.crop = tuple(tuple(max(0, min((image.width, image.height)[n], op(state.start[n], mouse[n]))) for n in (0, 1)) for op in (min, max))
                if i.is_key_pressed(i.Key.escape):
                    state.crop, state.start = state.before, None
                    result['crop'] = Edit('cancel')
                elif not i.is_mouse_down(0):
                    state.start, result['crop'] = None, Edit('commit', state.crop)
                elif i.get_io().mouse_delta.x or i.get_io().mouse_delta.y:
                    result['crop'] = Edit('update', state.crop)
        if state.crop:
            a, b = (view.screen(point, f.top) for point in state.crop)
            draw.add_rect_filled(a, b, p.selection)
            draw.add_rect(a, b, p.accent, 0., 0, c.dp(2))
    return result


@dataclass
class GradientStop:
    id: int
    position: float
    color: tuple


def sample_gradient(stops, position, linear_light=False):
    if not stops:
        return 0., 0., 0., 0.
    ordered = sorted(stops, key=lambda x: x.position)
    left = ordered[0]
    for right in ordered[1:]:
        if position <= right.position and position >= left.position:
            k = (position-left.position)/(right.position-left.position) if right.position > left.position else 1.
            def blend(a, b):
                if not linear_light:
                    return a+(b-a)*k
                def decode(x):
                    return x/12.92 if x <= .04045 else ((x+.055)/1.055)**2.4
                value = decode(a)+(decode(b)-decode(a))*k
                return value*12.92 if value <= .0031308 else 1.055*value**(1/2.4)-.055
            return tuple(blend(left.color[n], right.color[n]) for n in range(3))+(left.color[3]+(right.color[3]-left.color[3])*k,)
        if position < left.position:
            return left.color
        left = right
    return left.color


@dataclass
class GradientState:
    selected: int = 0
    dragging: int = 0
    before: list = field(default_factory=list)
    preview: list = field(default_factory=list)
    revision: int = 0


def gradient_editor(identifier, state, stops, size=(0, 48), linear_light=False, revision=0):
    i, c = ui()
    edit = Edit()
    with Canvas(identifier, CanvasState(), size, False, False) as f:
        io, p, d = i.get_io(), c.palette(), f.draw
        if state.dragging and (state.revision != revision or i.is_key_pressed(i.Key.escape)):
            state.dragging, edit = 0, Edit('cancel')
        shown = state.preview if state.dragging else stops
        bottom, count = f.bottom[1]-c.dp(14), max(1, min(4096, int(f.size[0]/c.dp(2))))
        for n in range(count):
            color = i.color_convert_float4_to_u32(sample_gradient(shown, (n+.5)/count, linear_light))
            d.add_rect_filled((f.top[0]+f.size[0]*n/count, f.top[1]), (f.top[0]+f.size[0]*(n+1)/count, bottom), color)
        hit = 0
        for stop in shown:
            x = f.top[0]+f.size[0]*stop.position
            a, b, e = (x, bottom), (x-c.dp(6), bottom+c.dp(10)), (x+c.dp(6), bottom+c.dp(10))
            d.add_triangle_filled(a, b, e, i.color_convert_float4_to_u32(stop.color))
            d.add_triangle(a, b, e, p.accent if state.selected == stop.id else p.text, c.dp(1.5))
            if abs(io.mouse_pos.x-x) < c.dp(8):
                hit = stop.id
        mouse = max(0., min(1., (io.mouse_pos.x-f.top[0])/f.size[0]))
        if f.hovered and i.is_mouse_double_clicked(0) and not hit:
            new_id = max([s.id for s in stops]+[0])+1
            edit = Edit('commit', deepcopy(stops)+[GradientStop(new_id, mouse, sample_gradient(stops, mouse, linear_light))])
            state.selected = new_id
        elif f.hovered and i.is_mouse_clicked(0) and hit:
            state.selected, state.dragging, state.revision = hit, hit, revision
            state.before, state.preview = deepcopy(stops), deepcopy(stops)
            edit = Edit('begin', deepcopy(state.preview))
        if state.dragging:
            if i.is_mouse_down(0):
                for stop in state.preview:
                    if stop.id == state.dragging:
                        stop.position = mouse
                if edit.phase != 'begin' and io.mouse_delta.x:
                    edit = Edit('update', deepcopy(state.preview))
            else:
                state.dragging, edit = 0, Edit('commit', deepcopy(state.preview))
        if f.hovered and hit and i.is_mouse_clicked(1) and len(stops) > 2:
            edit = Edit('commit', [deepcopy(s) for s in stops if s.id != hit])
    return edit
