"""CyUI for Python: the CyUI look (CyDAW 2, Shaderixel, CyEngineHub) for imgui_bundle.

A port of the C++ library in this folder (include/cyui, src/), for the Python Dear ImGui
applications (imgui_bundle 1.92 or newer) such as the CyTools. Same palettes, same five
themes, same two densities, same fonts and icons, same widgets and layout, same rules: read
docs/AI_GUIDE.md. Names follow Python: primary_button for primaryButton, begin_card for
beginCard. Value controls return (changed, value) the way imgui_bundle does.

What is not ported: knob, fader, meter, the typed value entry, the gallery and the theme
editor (audio and editor controls the C++ apps use).

Start-up, once per application:

    import cyui
    runner.callbacks.load_additional_fonts = cyui.load_fonts   # before the atlas is built
    ...
    cyui.apply('mid-grey', 'comfortable', dpi)                  # before the first frame
    ...
    cyui.render_notifications()                                 # at the end of every frame
"""
import contextlib
import math
import os
import time
from types import SimpleNamespace

from imgui_bundle import imgui

ImVec2 = imgui.ImVec2

# ---- Colours --------------------------------------------------------------------------


def rgb(hex_value, a=1.0):
    """A colour from 0xRRGGBB, as written in a design tool, packed the way ImGui wants (ABGR)."""
    return (((int(a * 255.0 + 0.5) & 0xFF) << 24) | ((hex_value & 0xFF) << 16)
            | (hex_value & 0xFF00) | ((hex_value >> 16) & 0xFF))


FIELDS = ('bg0', 'bg1', 'bg2', 'bg3', 'bg4', 'bg5', 'line', 'lineStrong', 'grid', 'gridStrong',
          'text', 'textDim', 'textFaint', 'accent', 'accentHover', 'accentDim', 'accentText',
          'selection', 'success', 'warning', 'error', 'info')


def _palette(*values):
    return dict(zip(FIELDS, values))


_MID_GREY = _palette(
    rgb(0x262626), rgb(0x2e2e2e), rgb(0x373737), rgb(0x414141), rgb(0x4b4b4b), rgb(0x565656),
    rgb(0x1f1f1f), rgb(0x181818), rgb(0x2d2d2d), rgb(0x383838),
    rgb(0xdadada), rgb(0xa6a6a6), rgb(0x707070),
    rgb(0xf28a2e), rgb(0xffa552), rgb(0x7d4a1d), rgb(0x1e1e1e), rgb(0xf28a2e, 0.24),
    rgb(0x5cd26e), rgb(0xf5a623), rgb(0xee5149), rgb(0x5cb4ef))
_LIGHT_GREY = _palette(
    rgb(0xb3b3b3), rgb(0xc2c2c2), rgb(0xcbcbcb), rgb(0xd6d6d6), rgb(0xe0e0e0), rgb(0xebebeb),
    rgb(0x9c9c9c), rgb(0x7f7f7f), rgb(0xa9a9a9), rgb(0x969696),
    rgb(0x161616), rgb(0x3d3d3d), rgb(0x6e6e6e),
    rgb(0xff8a00), rgb(0xffa233), rgb(0xf0c27e), rgb(0x161616), rgb(0x3d8eff, 0.26),
    rgb(0x15a34e), rgb(0xd98200), rgb(0xe0302b), rgb(0x2a86d1))
_AMBER_NIGHT = _palette(
    rgb(0x111317), rgb(0x16181d), rgb(0x1c1f25), rgb(0x24282f), rgb(0x2c313a), rgb(0x363c47),
    rgb(0x262a31), rgb(0x363b45), rgb(0x1f2228), rgb(0x2b2f37),
    rgb(0xdce1e8), rgb(0x9aa3b0), rgb(0x5f6875),
    rgb(0xf0a43a), rgb(0xf8b95c), rgb(0x7a5524), rgb(0x111317), rgb(0xf0a43a, 0.22),
    rgb(0x3dd68c), rgb(0xf5a623), rgb(0xe5484d), rgb(0x5ab0f0))
_VIOLET = _palette(
    rgb(0x16171b), rgb(0x1b1c21), rgb(0x222329), rgb(0x282a32), rgb(0x343640), rgb(0x40424e),
    rgb(0x30323a), rgb(0x3a3c46), rgb(0xffffff, 0.04), rgb(0xffffff, 0.09),
    rgb(0xdee0e8), rgb(0x8c909e), rgb(0x686c7a),
    rgb(0x7c5cff), rgb(0x967cff), rgb(0x4c3fa0), rgb(0xffffff), rgb(0x7c5cff, 0.35),
    rgb(0x4cd4a0), rgb(0xf5a623), rgb(0xf0505a), rgb(0x2ec4d6))
_NAVY = _palette(
    rgb(0x0a0e13), rgb(0x0d1218), rgb(0x111820), rgb(0x18212c), rgb(0x1f2a37), rgb(0x263343),
    rgb(0x1c2632), rgb(0x283748), rgb(0x111820), rgb(0x1c2632),
    rgb(0xd9e2ec), rgb(0xa4b3c2), rgb(0x65788d),
    rgb(0x2d7ff9), rgb(0x4a93ff), rgb(0x1d4e7a), rgb(0xffffff), rgb(0x2d7ff9, 0.25),
    rgb(0x65cca9), rgb(0xf2b84b), rgb(0xe8747c), rgb(0x70a8fa))

# (key, name shown to people, palette, light)
THEMES = (('mid-grey', 'Mid grey (CyDAW)', _MID_GREY, False),
          ('light-grey', 'Light grey (CyDAW)', _LIGHT_GREY, True),
          ('amber-night', 'Amber night (CyDAW)', _AMBER_NIGHT, False),
          ('violet', 'Violet (Shaderixel)', _VIOLET, False),
          ('navy', 'Navy (CyEngineHub)', _NAVY, False))
DEFAULT_THEME = 'mid-grey'
DENSITIES = ('compact', 'comfortable')

_COMPACT = SimpleNamespace(
    font_size=14.0, window_padding=(8.0, 6.0), frame_padding=(6.0, 3.0), item_spacing=(6.0, 4.0),
    item_inner_spacing=(4.0, 4.0), cell_padding=(5.0, 2.0), indent=14.0, scrollbar=10.0,
    grab_min=9.0, rounding=4.0, rounding_large=6.0, rounding_small=3.0, card_padding=10.0,
    toolbar_height=14.0)
_COMFORTABLE = SimpleNamespace(
    font_size=16.0, window_padding=(10.0, 10.0), frame_padding=(8.0, 5.0), item_spacing=(8.0, 6.0),
    item_inner_spacing=(6.0, 4.0), cell_padding=(6.0, 4.0), indent=16.0, scrollbar=11.0,
    grab_min=10.0, rounding=6.0, rounding_large=8.0, rounding_small=4.0, card_padding=14.0,
    toolbar_height=16.0)

_state = SimpleNamespace(palette=SimpleNamespace(**_MID_GREY), theme=DEFAULT_THEME, light=False,
                         density='compact', metrics=_COMPACT, dpi=1.0, square=False,
                         icons=False, fonts=[], toasts=[], toast_ids=0, modal_open=None)


def palette():
    """The semantic palette: pick a colour by role (palette().bg3 is a field's ground)."""
    return _state.palette


def alpha(colour, factor):
    current = ((colour >> 24) & 0xFF) / 255.0
    byte = int(min(1.0, max(0.0, current * factor)) * 255.0 + 0.5)
    return (colour & 0x00FFFFFF) | (byte << 24)


def mix(a, b, t):
    out = 0
    for shift in (0, 8, 16, 24):
        x, y = (a >> shift) & 0xFF, (b >> shift) & 0xFF
        out |= (int(x + (y - x) * t + 0.5) & 0xFF) << shift
    return out


def brighter(colour, amount):
    return mix(colour, (colour & 0xFF000000) | 0x00FFFFFF, amount)


def darker(colour, amount):
    return mix(colour, colour & 0xFF000000, amount)


def vec(colour):
    return imgui.ImVec4((colour & 0xFF) / 255.0, ((colour >> 8) & 0xFF) / 255.0,
                        ((colour >> 16) & 0xFF) / 255.0, ((colour >> 24) & 0xFF) / 255.0)


_CATEGORICAL = (0xf0a43a, 0x5ab0f0, 0x52d1a2, 0xc792ea, 0xe8765a, 0x7fd1e8,
                0xe8c547, 0x9ccc65, 0xf06292, 0x8c9eff, 0x4dd0b5, 0xffb74d)


def categorical(index):
    """The n-th colour of a pleasant set, for series (tracks, layers, tags, characters)."""
    return rgb(_CATEGORICAL[index % len(_CATEGORICAL)])


def contrast_text(ground):
    """Dark or light text, whichever reads on `ground`."""
    r, g, b = (ground & 0xFF) / 255.0, ((ground >> 8) & 0xFF) / 255.0, ((ground >> 16) & 0xFF) / 255.0
    return rgb(0x141414) if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.55 else rgb(0xffffff)


def tone_colour(tone):
    p = palette()
    return {'accent': p.accent, 'success': p.success, 'warning': p.warning, 'error': p.error,
            'info': p.info}.get(tone, p.textDim)


# ---- Metrics and applying ------------------------------------------------------------------

def metrics():
    return _state.metrics


def density():
    return _state.density


def current_theme():
    return _state.theme


def is_light():
    return _state.light


def dpi():
    return _state.dpi


def dp(value):
    """A design size (96-dpi pixels) on this screen: use it for every size in custom drawing."""
    return value * imgui.get_style().font_scale_dpi


def dp2(x, y):
    return ImVec2(dp(x), dp(y))


def _apply_colours(style):
    p = palette()
    c = imgui.Col_
    colours = {
        c.text: p.text, c.text_disabled: p.textFaint, c.window_bg: p.bg1,
        c.child_bg: alpha(p.bg2, 0.0), c.popup_bg: alpha(p.bg2, 0.98), c.border: p.line,
        c.border_shadow: 0, c.frame_bg: p.bg3, c.frame_bg_hovered: p.bg4, c.frame_bg_active: p.bg5,
        c.title_bg: p.bg0, c.title_bg_active: p.bg0, c.title_bg_collapsed: p.bg0,
        c.menu_bar_bg: p.bg0, c.scrollbar_bg: alpha(p.bg0, 0.0), c.scrollbar_grab: p.bg5,
        c.scrollbar_grab_hovered: brighter(p.bg5, 0.12), c.scrollbar_grab_active: p.accentDim,
        c.check_mark: p.accent, c.slider_grab: p.accent, c.slider_grab_active: p.accentHover,
        c.button: p.bg3, c.button_hovered: p.bg4, c.button_active: p.bg5,
        c.header: alpha(p.accent, 0.16), c.header_hovered: p.bg4, c.header_active: alpha(p.accent, 0.26),
        c.separator: p.line, c.separator_hovered: p.accentDim, c.separator_active: p.accent,
        c.resize_grip: alpha(p.bg5, 0.0), c.resize_grip_hovered: p.accentDim,
        c.resize_grip_active: p.accent, c.tab_hovered: p.bg4, c.tab: p.bg0, c.tab_selected: p.bg1,
        c.tab_selected_overline: p.accent, c.tab_dimmed: p.bg0, c.tab_dimmed_selected: p.bg1,
        c.tab_dimmed_selected_overline: alpha(p.accent, 0.35),
        c.plot_lines: p.info, c.plot_lines_hovered: p.accent, c.plot_histogram: p.accent,
        c.plot_histogram_hovered: p.accentHover, c.table_header_bg: p.bg2,
        c.table_border_strong: p.lineStrong, c.table_border_light: p.line, c.table_row_bg: 0,
        c.table_row_bg_alt: alpha(p.text, 0.025), c.text_link: p.info,
        c.text_selected_bg: alpha(p.accent, 0.30), c.drag_drop_target: p.accent,
        c.nav_cursor: p.accent, c.nav_windowing_highlight: alpha(p.accent, 0.7),
        c.nav_windowing_dim_bg: rgb(0x000000, 0.35),
        c.modal_window_dim_bg: rgb(0x000000, 0.25 if _state.light else 0.45),
        c.input_text_cursor: p.accent, c.tree_lines: p.line}
    for name in ('docking_preview', 'docking_empty_bg'):
        if hasattr(c, name):
            colours[getattr(c, name)] = alpha(p.accent, 0.45) if name == 'docking_preview' else p.bg0
    for index, colour in colours.items():
        style.set_color_(index, vec(colour))
    if _state.square:
        window = style.color_(c.window_bg)
        style.set_color_(c.window_bg, imgui.ImVec4(window.x, window.y, window.z, 1.0))


def _apply_style():
    style = imgui.get_style()
    m, s = _state.metrics, _state.dpi
    style.font_size_base = m.font_size
    style.window_padding = ImVec2(m.window_padding[0] * s, m.window_padding[1] * s)
    style.frame_padding = ImVec2(m.frame_padding[0] * s, m.frame_padding[1] * s)
    style.item_spacing = ImVec2(m.item_spacing[0] * s, m.item_spacing[1] * s)
    style.item_inner_spacing = ImVec2(m.item_inner_spacing[0] * s, m.item_inner_spacing[1] * s)
    style.cell_padding = ImVec2(m.cell_padding[0] * s, m.cell_padding[1] * s)
    style.indent_spacing = m.indent * s
    style.scrollbar_size = m.scrollbar * s
    style.grab_min_size = m.grab_min * s
    style.window_border_size = 1.0
    style.child_border_size = 1.0
    style.popup_border_size = 1.0
    style.frame_border_size = 0.0
    style.tab_border_size = 0.0
    style.tab_bar_border_size = 1.0
    style.tab_bar_overline_size = 2.0 * s
    style.window_rounding = 0.0 if _state.square else m.rounding_large * s
    style.child_rounding = (m.rounding_large - 1.0) * s
    style.frame_rounding = m.rounding * s
    style.popup_rounding = m.rounding_large * s
    style.scrollbar_rounding = 8.0 * s
    style.grab_rounding = m.rounding_small * s
    style.tab_rounding = (m.rounding + 1.0) * s
    style.window_title_align = ImVec2(0.0, 0.5)
    style.window_menu_button_position = imgui.Dir.none
    style.separator_text_border_size = 1.0
    style.separator_text_padding = ImVec2(10.0 * s, 2.0 * s)
    style.window_min_size = ImVec2(60.0 * s, 40.0 * s)
    style.hover_delay_short = 0.25
    style.hover_delay_normal = 0.55
    style.anti_aliased_lines = True
    style.anti_aliased_fill = True
    style.font_scale_dpi = s
    _apply_colours(style)


def set_palette(values):
    """The palette drawn with from now on (a dict or a namespace of the FIELDS); ImGui follows."""
    values = values if isinstance(values, dict) else vars(values)
    _state.palette = SimpleNamespace(**{key: values[key] for key in FIELDS})
    _apply_colours(imgui.get_style())


def set_theme(key):
    for theme_key, _, values, light in THEMES:
        if theme_key == key:
            _state.theme, _state.light = theme_key, light
            set_palette(values)
            return True
    return False


def set_density(value):
    _state.density = 'comfortable' if value == 'comfortable' else 'compact'
    _state.metrics = _COMFORTABLE if _state.density == 'comfortable' else _COMPACT
    _apply_style()


def apply(theme='mid-grey', density_name='compact', dpi_scale=1.0, square_windows=False):
    """Sets ImGui's sizes, roundings and colours from a theme and a density, at a DPI scale.

    Call before the first frame, and again whenever one of them changes: every value is set
    from the theme, nothing accumulates.
    """
    _state.dpi = max(0.5, float(dpi_scale or 1.0))
    _state.square = bool(square_windows)
    _state.density = 'comfortable' if density_name == 'comfortable' else 'compact'
    _state.metrics = _COMFORTABLE if _state.density == 'comfortable' else _COMPACT
    if not any(key == theme for key, _, _, _ in THEMES):
        theme = DEFAULT_THEME
    for theme_key, _, values, light in THEMES:
        if theme_key == theme:
            _state.theme, _state.light = theme_key, light
            _state.palette = SimpleNamespace(**values)
    _apply_style()


def apply_dpi(dpi_scale):
    apply(_state.theme, _state.density, dpi_scale, _state.square)


# ---- Fonts -------------------------------------------------------------------------------

def _windows_font(name):
    if os.name != 'nt':
        return ''
    return os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', name)


def _add_font(candidates, size):
    io = imgui.get_io()
    config = imgui.ImFontConfig()
    config.oversample_h = 2
    config.oversample_v = 2
    config.pixel_snap_h = True
    for path in candidates:
        if path and os.path.isfile(path):
            font = io.fonts.add_font_from_file_ttf(path, size, config)
            if font is not None:
                return font
    return io.fonts.add_font_default()


def _merge_icons(size, wanted):
    if not wanted:
        return
    path = _windows_font('segmdl2.ttf')
    if not os.path.isfile(path):
        return
    config = imgui.ImFontConfig()
    config.merge_mode = True
    config.pixel_snap_h = True
    config.glyph_offset = ImVec2(0.0, 2.0)
    config.glyph_min_advance_x = size
    if imgui.get_io().fonts.add_font_from_file_ttf(path, size * 0.95, config) is not None:
        _state.icons = True


def load_fonts(size=0.0, fallback_folder=None, icons=True):
    """Segoe UI, Segoe UI Semibold and Consolas, each with the Segoe MDL2 icons merged.

    Call where the application builds its font atlas (hello_imgui: the
    load_additional_fonts callback). Fallback .ttf files (Inter, Roboto, JetBrains Mono...)
    are looked for in `fallback_folder` when the Windows fonts are missing.
    """
    size = size or _state.metrics.font_size
    folder = fallback_folder or ''

    def inside(name):
        return os.path.join(folder, name) if folder else ''

    _state.icons = False
    _state.fonts = [
        _add_font([_windows_font('segoeui.ttf'), inside('Inter-Regular.ttf'),
                   inside('Roboto-Regular.ttf'), inside('Roboto-Medium.ttf')], size)]
    _merge_icons(size, icons)
    _state.fonts.append(_add_font([_windows_font('seguisb.ttf'), inside('Inter-SemiBold.ttf'),
                                   inside('Roboto-Bold.ttf'), inside('Roboto-Medium.ttf')], size))
    _merge_icons(size, icons)
    _state.fonts.append(_add_font([_windows_font('consola.ttf'), inside('JetBrainsMono-Regular.ttf'),
                                   inside('Cousine-Regular.ttf')], size - 1.0))
    imgui.get_io().font_default = _state.fonts[0]


def ui_font():
    return _state.fonts[0] if _state.fonts else None


def bold_font():
    return _state.fonts[1] if len(_state.fonts) > 1 else ui_font()


def mono_font():
    return _state.fonts[2] if len(_state.fonts) > 2 else ui_font()


def icons_available():
    return _state.icons


# ---- Scoped helpers ------------------------------------------------------------------------

@contextlib.contextmanager
def scoped_color(*pairs):
    """with scoped_color(imgui.Col_.text, palette().textDim, ...): pairs of (index, colour)."""
    count = 0
    for index in range(0, len(pairs), 2):
        colour = pairs[index + 1]
        imgui.push_style_color(pairs[index], colour if isinstance(colour, imgui.ImVec4) else vec(colour))
        count += 1
    try:
        yield
    finally:
        imgui.pop_style_color(count)


@contextlib.contextmanager
def scoped_var(*pairs):
    count = 0
    for index in range(0, len(pairs), 2):
        imgui.push_style_var(pairs[index], pairs[index + 1])
        count += 1
    try:
        yield
    finally:
        imgui.pop_style_var(count)


@contextlib.contextmanager
def scoped_font(font, size_factor=1.0):
    """A font and/or a size factor of the base size (1 normal, 0.85 small); None keeps the font."""
    imgui.push_font(font, imgui.get_style().font_size_base * size_factor)
    try:
        yield
    finally:
        imgui.pop_font()


@contextlib.contextmanager
def scoped_id(value):
    imgui.push_id(value)
    try:
        yield
    finally:
        imgui.pop_id()


@contextlib.contextmanager
def scoped_disabled(disabled=True):
    imgui.begin_disabled(disabled)
    try:
        yield
    finally:
        imgui.end_disabled()


def _visible(label):
    """What a label shows: the part before '##'."""
    return label.split('##', 1)[0]


# ---- Text --------------------------------------------------------------------------------

def heading(text, level=2):
    """A title: 1 a page (1.5x semibold), 2 a panel (1.2x), 3 a group (1.0x)."""
    factor = 1.5 if level <= 1 else 1.2 if level == 2 else 1.0
    with scoped_font(bold_font(), factor), scoped_color(imgui.Col_.text, palette().text):
        imgui.text_unformatted(text)


def section_title(text):
    """A small semibold dimmed title for a group inside a panel."""
    with scoped_font(bold_font(), 0.85), scoped_color(imgui.Col_.text, palette().textDim):
        imgui.text_unformatted(text)


def overline(text, colour=0):
    """CyEngineHub label: SMALL UPPERCASE, bold, accent-tinted. Pass it uppercased."""
    p = palette()
    with scoped_font(bold_font(), 0.78), \
            scoped_color(imgui.Col_.text, colour or mix(p.accent, p.text, 0.35)):
        imgui.text_unformatted(text)


def text_coloured(colour, text):
    imgui.text_colored(vec(colour), text)


def text_dim(text):
    imgui.text_colored(vec(palette().textDim), text)


def text_faint(text):
    imgui.text_colored(vec(palette().textFaint), text)


def text_mono(text):
    with scoped_font(mono_font(), 1.0):
        imgui.text_unformatted(text)


def kbd(keys):
    """A keyboard shortcut drawn as a key cap."""
    p = palette()
    with scoped_font(None, 0.82):
        size = imgui.calc_text_size(keys)
        pad = dp2(5.0, 1.0)
        origin = imgui.get_cursor_screen_pos()
        box = ImVec2(size.x + pad.x * 2.0, size.y + pad.y * 2.0)
        draw = imgui.get_window_draw_list()
        rounding = dp(3.0)
        draw.add_rect_filled(ImVec2(origin.x, origin.y + dp(1.0)),
                             ImVec2(origin.x + box.x, origin.y + box.y + dp(1.0)), p.lineStrong, rounding)
        draw.add_rect_filled(origin, ImVec2(origin.x + box.x, origin.y + box.y), p.bg3, rounding)
        draw.add_rect(origin, ImVec2(origin.x + box.x, origin.y + box.y), p.line, rounding)
        draw.add_text(ImVec2(origin.x + pad.x, origin.y + pad.y), p.textDim, keys)
        imgui.dummy(ImVec2(box.x, box.y + dp(1.0)))


def tooltip(text):
    """A delayed, wrapped tooltip for the last item."""
    if not text:
        return
    if not imgui.is_item_hovered(imgui.HoveredFlags_.delay_short | imgui.HoveredFlags_.no_shared_delay):
        return
    if imgui.begin_tooltip():
        imgui.push_text_wrap_pos(imgui.get_font_size() * 32.0)
        imgui.text_unformatted(text)
        imgui.pop_text_wrap_pos()
        imgui.end_tooltip()


def help_marker(text):
    """A small (i) after the previous item, its explanation on hover."""
    imgui.same_line(0.0, dp(4.0))
    imgui.text_disabled(icon.info if icons_available() else '(?)')
    if imgui.is_item_hovered(imgui.HoveredFlags_.delay_none) and imgui.begin_tooltip():
        imgui.push_text_wrap_pos(imgui.get_font_size() * 32.0)
        imgui.text_unformatted(text)
        imgui.pop_text_wrap_pos()
        imgui.end_tooltip()


def clipped_text(draw, position, max_width, colour, text):
    """Text cut to `max_width` with an ellipsis."""
    if not text or max_width <= 4.0:
        return
    if imgui.calc_text_size(text).x <= max_width:
        draw.add_text(position, colour, text)
        return
    room = max_width - imgui.calc_text_size('...').x
    shown = text
    while shown and imgui.calc_text_size(shown).x > room:
        shown = shown[:-1]
    draw.add_text(position, colour, shown + '...')


def centred_text(draw, minimum, maximum, colour, text):
    size = imgui.calc_text_size(text)
    draw.add_text(ImVec2(minimum.x + (maximum.x - minimum.x - size.x) * 0.5,
                         minimum.y + (maximum.y - minimum.y - size.y) * 0.5), colour, text)


# ---- Buttons -------------------------------------------------------------------------------

VARIANTS = ('secondary', 'primary', 'ghost', 'outline', 'danger', 'success')


def _variant_colours(variant):
    p = palette()
    if variant == 'primary':
        return p.accent, p.accentHover, brighter(p.accent, 0.2), p.accentText, 0
    if variant == 'ghost':
        return alpha(p.bg3, 0.0), p.bg4, p.bg5, p.text, 0
    if variant == 'outline':
        return alpha(p.bg3, 0.0), alpha(p.accent, 0.12), alpha(p.accent, 0.22), p.text, p.lineStrong
    if variant == 'danger':
        ground = mix(p.error, p.bg1, 0.35)
        return ground, p.error, brighter(p.error, 0.15), contrast_text(ground), 0
    if variant == 'success':
        ground = mix(p.success, p.bg1, 0.25)
        return ground, p.success, brighter(p.success, 0.15), contrast_text(ground), 0
    return p.bg3, p.bg4, p.bg5, p.text, 0


def button(label, variant='secondary', size=(0.0, 0.0), small=False):
    """A button in one of the VARIANTS: one 'primary' per view, 'danger' for what destroys."""
    ground, hovered, active, text, border = _variant_colours(variant)
    colours = [imgui.Col_.button, ground, imgui.Col_.button_hovered, hovered,
               imgui.Col_.button_active, active, imgui.Col_.text, text]
    if border:
        colours += [imgui.Col_.border, border]
    with scoped_color(*colours), scoped_var(imgui.StyleVar_.frame_border_size, 1.0 if border else 0.0):
        if small:
            return imgui.small_button(label)
        return imgui.button(label, ImVec2(*size) if isinstance(size, tuple) else size)


def primary_button(label, size=(0.0, 0.0)):
    return button(label, 'primary', size)


def danger_button(label, size=(0.0, 0.0)):
    return button(label, 'danger', size)


def ghost_button(label, size=(0.0, 0.0)):
    return button(label, 'ghost', size)


def icon_text_button(glyph, label, variant='secondary', size=(0.0, 0.0)):
    """An icon glyph then a label: icon_text_button(icon.save, 'Save')."""
    text = ((glyph + '  ') if glyph and icons_available() else '') + label
    return button(text, variant, size)


def icon_button(glyph, tip='', active=False, active_colour=0, size=(0.0, 0.0)):
    """A flat square icon button, tinted when active. Always give it a tooltip."""
    p = palette()
    width = size[0] if size[0] > 0 else imgui.get_frame_height() + dp(2.0)
    height = size[1] if size[1] > 0 else imgui.get_frame_height()
    origin = imgui.get_cursor_screen_pos()
    imgui.push_id(glyph)
    imgui.push_id(tip or '')
    clicked = imgui.invisible_button('##icon', ImVec2(width, height))
    hovered = imgui.is_item_hovered()
    held = imgui.is_item_active()
    imgui.pop_id()
    imgui.pop_id()
    draw = imgui.get_window_draw_list()
    colour = active_colour or p.accent
    rounding = imgui.get_style().frame_rounding
    maximum = ImVec2(origin.x + width, origin.y + height)
    if active:
        draw.add_rect_filled(origin, maximum, alpha(colour, 0.28 if held else 0.18), rounding)
    elif hovered:
        draw.add_rect_filled(origin, maximum, p.bg5 if held else p.bg4, rounding)
    shown = glyph if icons_available() or len(glyph) > 1 else '?'
    centred_text(draw, origin, maximum, colour if active else (p.text if hovered else p.textDim), shown)
    tooltip(tip)
    return clicked


def toggle_switch(label, value):
    """An on/off switch with its label after it. Returns (clicked, value)."""
    p = palette()
    style = imgui.get_style()
    height = imgui.get_frame_height()
    track_height = round(height * 0.72)
    track_width = round(track_height * 1.8)
    text = _visible(label)
    text_size = imgui.calc_text_size(text)
    origin = imgui.get_cursor_screen_pos()
    width = track_width + ((style.item_inner_spacing.x + text_size.x) if text else 0.0)
    clicked = imgui.invisible_button(label, ImVec2(width, height))
    if clicked:
        value = not value
    hovered = imgui.is_item_hovered()
    storage = imgui.get_state_storage()
    key = imgui.get_item_id()
    target = 1.0 if value else 0.0
    t = storage.get_float(key, target)
    step = imgui.get_io().delta_time * 12.0
    t = min(target, t + step) if t < target else max(target, t - step)
    storage.set_float(key, t)
    draw = imgui.get_window_draw_list()
    track_min = ImVec2(origin.x, origin.y + (height - track_height) * 0.5)
    track_max = ImVec2(track_min.x + track_width, track_min.y + track_height)
    off = p.bg5 if hovered else p.bg4
    on = p.accentHover if hovered else p.accent
    draw.add_rect_filled(track_min, track_max, mix(off, on, t), track_height * 0.5)
    radius = track_height * 0.5 - dp(2.5)
    centre = ImVec2(track_min.x + track_height * 0.5 + (track_width - track_height) * t,
                    track_min.y + track_height * 0.5)
    off_knob = p.text if contrast_text(p.bg1) == rgb(0xffffff) else rgb(0xffffff)
    draw.add_circle_filled(ImVec2(centre.x, centre.y + dp(0.5)), radius + dp(0.5), rgb(0x000000, 0.18), 20)
    draw.add_circle_filled(centre, radius, mix(off_knob, contrast_text(p.accent), t), 20)
    if text:
        draw.add_text(ImVec2(track_max.x + style.item_inner_spacing.x,
                             origin.y + (height - text_size.y) * 0.5), p.text, text)
    return clicked, value


def segmented(identifier, labels, current, width=0.0):
    """Joined buttons, one selected (view modes, units). Returns (changed, current)."""
    p = palette()
    style = imgui.get_style()
    imgui.push_id(identifier)
    height = imgui.get_frame_height()
    inset = dp(2.0)
    widths = [imgui.calc_text_size(_visible(label)).x + style.frame_padding.x * 2.6 for label in labels]
    natural = sum(widths)
    total = width if width > 0 else imgui.get_content_region_avail().x if width < 0 else natural + inset * 2.0
    scale = (total - inset * 2.0) / natural if natural > 0 else 1.0
    origin = imgui.get_cursor_screen_pos()
    draw = imgui.get_window_draw_list()
    draw.add_rect_filled(origin, ImVec2(origin.x + total, origin.y + height), p.bg0,
                         style.frame_rounding + inset)
    changed = False
    x = origin.x + inset
    for index, label in enumerate(labels):
        w = widths[index] * scale
        imgui.set_cursor_screen_pos(ImVec2(x, origin.y + inset))
        imgui.push_id(index)
        size = ImVec2(w, height - inset * 2.0)
        if imgui.invisible_button('##segment', size) and current != index:
            current, changed = index, True
        hovered = imgui.is_item_hovered()
        imgui.pop_id()
        selected = current == index
        minimum, maximum = ImVec2(x, origin.y + inset), ImVec2(x + w, origin.y + height - inset)
        if selected:
            draw.add_rect_filled(minimum, maximum, p.accentDim, style.frame_rounding)
        elif hovered:
            draw.add_rect_filled(minimum, maximum, p.bg3, style.frame_rounding)
        text = _visible(label)
        text_size = imgui.calc_text_size(text)
        draw.add_text(ImVec2(minimum.x + (w - text_size.x) * 0.5, minimum.y + (size.y - text_size.y) * 0.5),
                      contrast_text(p.accentDim) if selected else (p.text if hovered else p.textDim), text)
        x += w
    imgui.set_cursor_screen_pos(origin)
    imgui.dummy(ImVec2(total, height))
    imgui.pop_id()
    return changed, current


def link_text(label):
    return imgui.text_link(label)


def slider_bar(identifier, value, minimum, maximum, fmt='%.2f', width=0.0, colour=0):
    """A slider drawn as a filled bar with its value in it. Returns (changed, value).

    Drag or click to set it, the mouse wheel nudges (Ctrl fine, Shift fast).
    """
    p = palette()
    if width == 0.0:
        width = imgui.calc_item_width()
    elif width < 0.0:
        width = max(dp(20.0), imgui.get_content_region_avail().x + width)
    height = imgui.get_frame_height()
    origin = imgui.get_cursor_screen_pos()
    imgui.push_id(identifier)
    imgui.invisible_button('##bar', ImVec2(width, height))
    hovered, active = imgui.is_item_hovered(), imgui.is_item_active()
    changed = False
    io = imgui.get_io()
    span = maximum - minimum
    if active and span > 0:
        t = min(1.0, max(0.0, (io.mouse_pos.x - origin.x) / max(1.0, width)))
        candidate = minimum + span * t
        if candidate != value:
            value, changed = candidate, True
    if hovered and io.mouse_wheel != 0.0 and span > 0:
        speed = 0.15 if io.key_ctrl else 4.0 if io.key_shift else 1.0
        value = min(maximum, max(minimum, value + io.mouse_wheel * span * 0.01 * speed))
        changed = True
    draw = imgui.get_window_draw_list()
    rounding = imgui.get_style().frame_rounding
    maximum_corner = ImVec2(origin.x + width, origin.y + height)
    draw.add_rect_filled(origin, maximum_corner, p.bg5 if active else p.bg4 if hovered else p.bg3, rounding)
    t = min(1.0, max(0.0, (value - minimum) / span)) if span > 0 else 0.0
    if t > 0.0:
        draw.push_clip_rect(origin, ImVec2(origin.x + width * t, maximum_corner.y), True)
        draw.add_rect_filled(origin, maximum_corner, alpha(colour or p.accent, 0.55 if hovered or active else 0.42),
                             rounding)
        draw.pop_clip_rect()
    centred_text(draw, origin, maximum_corner, p.text, fmt % value)
    imgui.pop_id()
    return changed, value


# ---- Fields ----------------------------------------------------------------------------------

def _draw_magnifier(draw, centre, size, colour):
    radius = size * 0.32
    c = ImVec2(centre.x - size * 0.08, centre.y - size * 0.08)
    draw.add_circle(c, radius, colour, 16, max(1.2, size * 0.1))
    draw.add_line(ImVec2(c.x + radius * 0.7, c.y + radius * 0.7),
                  ImVec2(centre.x + size * 0.42, centre.y + size * 0.42), colour, max(1.4, size * 0.12))


def _draw_cross(draw, centre, size, colour):
    h, thickness = size * 0.5, max(1.2, size * 0.12)
    draw.add_line(ImVec2(centre.x - h, centre.y - h), ImVec2(centre.x + h, centre.y + h), colour, thickness)
    draw.add_line(ImVec2(centre.x - h, centre.y + h), ImVec2(centre.x + h, centre.y - h), colour, thickness)


def search_field(identifier, text, hint='Search', width=0.0):
    """A search box: magnifier, hint, a clear button. Returns (changed, text)."""
    p = palette()
    style = imgui.get_style()
    height = imgui.get_frame_height()
    icon_room = height * 0.9
    imgui.push_id(identifier)
    origin = imgui.get_cursor_screen_pos()
    field_width = max(dp(40.0), (width if width > 0 else imgui.get_content_region_avail().x + width)
                      if width != 0.0 else imgui.calc_item_width())
    imgui.set_next_item_width(field_width)
    imgui.set_next_item_allow_overlap()
    with scoped_var(imgui.StyleVar_.frame_padding, ImVec2(style.frame_padding.x + icon_room * 0.75,
                                                          style.frame_padding.y),
                    imgui.StyleVar_.frame_rounding, height * 0.5):
        changed, text = imgui.input_text_with_hint('##search', hint or '', text)
    focused = imgui.is_item_active()
    end = imgui.get_cursor_screen_pos()
    draw = imgui.get_window_draw_list()
    _draw_magnifier(draw, ImVec2(origin.x + style.frame_padding.x + icon_room * 0.3, origin.y + height * 0.5),
                    height * 0.48, p.accent if focused else p.textFaint)
    if text:
        imgui.set_cursor_screen_pos(ImVec2(origin.x + field_width - height, origin.y))
        if imgui.invisible_button('##clear', ImVec2(height, height)):
            text, changed = '', True
        _draw_cross(draw, ImVec2(origin.x + field_width - height * 0.5, origin.y + height * 0.5),
                    height * 0.26, p.text if imgui.is_item_hovered() else p.textFaint)
        imgui.set_cursor_screen_pos(end)
    imgui.pop_id()
    return changed, text


def text_field(identifier, text, hint='', width=0.0):
    if width != 0.0:
        imgui.set_next_item_width(width)
    return imgui.input_text_with_hint(identifier, hint or '', text)


def combo(identifier, current, items, width=0.0):
    if width != 0.0:
        imgui.set_next_item_width(width)
    return imgui.combo(identifier, current, list(items))


# ---- Containers ------------------------------------------------------------------------------

def begin_card(identifier, title='', height=0.0, tone='neutral'):
    """A raised rounded group with an optional title. Always call end_card(), whatever this
    returned. height: 0 fits the content, > 0 fixed (dp), < 0 fills minus that much."""
    p = palette()
    toned = tone != 'neutral'
    ground = mix(p.bg2, tone_colour(tone), 0.08) if toned else p.bg2
    border = mix(p.line, tone_colour(tone), 0.55) if toned else p.line
    flags = imgui.ChildFlags_.borders | imgui.ChildFlags_.always_use_window_padding
    if height == 0.0:
        flags |= imgui.ChildFlags_.auto_resize_y
    with scoped_color(imgui.Col_.child_bg, ground, imgui.Col_.border, border), \
            scoped_var(imgui.StyleVar_.child_rounding, dp(metrics().rounding_large + 2.0),
                       imgui.StyleVar_.window_padding, dp2(metrics().card_padding, metrics().card_padding)):
        shown = imgui.begin_child(identifier, ImVec2(0.0, 0.0 if height == 0.0 else
                                                     (dp(height) if height > 0 else height)), flags)
    if shown and title:
        heading(title, 3)
        imgui.dummy(ImVec2(0.0, dp(2.0)))
    return shown


def end_card():
    imgui.end_child()


def begin_section(label, default_open=True):
    """A collapsible section with a full-width header. end_section() only when it returned True."""
    p = palette()
    with scoped_color(imgui.Col_.header, p.bg2, imgui.Col_.header_hovered, p.bg3,
                      imgui.Col_.header_active, p.bg4), scoped_font(bold_font(), 0.92):
        return imgui.collapsing_header(label, imgui.TreeNodeFlags_.default_open if default_open else 0)


def end_section():
    imgui.dummy(ImVec2(0.0, dp(4.0)))


def begin_properties(identifier, label_width=0.0):
    """Label / value rows in two aligned columns. end_properties() only when it returned True."""
    avail = imgui.get_content_region_avail().x
    width = dp(label_width) if label_width > 0 else max(dp(80.0), avail * 0.38)
    if not imgui.begin_table(identifier, 2, 0):
        return False
    imgui.table_setup_column('##label', imgui.TableColumnFlags_.width_fixed, width)
    imgui.table_setup_column('##value', imgui.TableColumnFlags_.width_stretch)
    return True


def property(label, help_text=''):  # noqa: A001 - the C++ name, kept on purpose
    """The label in the first column; the second readied, full width, for the control."""
    imgui.table_next_row()
    imgui.table_set_column_index(0)
    imgui.align_text_to_frame_padding()
    position = imgui.get_cursor_screen_pos()
    room = imgui.get_content_region_avail().x - (imgui.get_font_size() if help_text else 0.0)
    if imgui.calc_text_size(label).x <= room:
        text_dim(label)
    else:
        clipped_text(imgui.get_window_draw_list(),
                     ImVec2(position.x, position.y + imgui.get_style().frame_padding.y), room,
                     palette().textDim, label)
        imgui.dummy(ImVec2(room, imgui.get_text_line_height()))
        tooltip(label)
    if help_text:
        help_marker(help_text)
    imgui.table_set_column_index(1)
    imgui.set_next_item_width(-1.17549435e-38)


def end_properties():
    imgui.end_table()


def toolbar_separator():
    imgui.same_line(0.0, dp(6.0))
    origin = imgui.get_cursor_screen_pos()
    height = imgui.get_frame_height()
    imgui.get_window_draw_list().add_line(ImVec2(origin.x, origin.y + height * 0.18),
                                          ImVec2(origin.x, origin.y + height * 0.82), palette().lineStrong)
    imgui.dummy(ImVec2(dp(1.0), height))
    imgui.same_line(0.0, dp(6.0))


def divider(spacing=4.0):
    imgui.dummy(ImVec2(0.0, dp(spacing)))
    origin = imgui.get_cursor_screen_pos()
    width = imgui.get_content_region_avail().x
    imgui.get_window_draw_list().add_line(origin, ImVec2(origin.x + width, origin.y), palette().line)
    imgui.dummy(ImVec2(0.0, dp(spacing)))


def space(height=8.0):
    imgui.dummy(ImVec2(0.0, dp(height)))


# ---- Status and feedback ---------------------------------------------------------------------

def badge(text, tone='neutral'):
    """A small rounded pill: badge('BETA', 'warning')."""
    p = palette()
    colour = p.textDim if tone == 'neutral' else tone_colour(tone)
    with scoped_font(bold_font(), 0.74):
        size = imgui.calc_text_size(text)
        pad = dp2(6.0, 2.0)
        box = ImVec2(size.x + pad.x * 2.0, size.y + pad.y * 2.0)
        line = imgui.get_text_line_height() / 0.74
        origin = imgui.get_cursor_screen_pos()
        origin = ImVec2(origin.x, origin.y + max(0.0, (line - box.y) * 0.5))
        draw = imgui.get_window_draw_list()
        rounding = dp(metrics().rounding_small + 1.0)
        draw.add_rect_filled(origin, ImVec2(origin.x + box.x, origin.y + box.y),
                             p.bg4 if tone == 'neutral' else alpha(colour, 0.16), rounding)
        draw.add_rect(origin, ImVec2(origin.x + box.x, origin.y + box.y), alpha(colour, 0.35), rounding)
        draw.add_text(ImVec2(origin.x + pad.x, origin.y + pad.y),
                      p.text if tone == 'neutral' else mix(colour, p.text, 0.3), text)
        imgui.dummy(box)


def status_dot(colour, tip=''):
    line = imgui.get_text_line_height()
    origin = imgui.get_cursor_screen_pos()
    radius = line * 0.24
    imgui.dummy(ImVec2(radius * 2.0 + dp(2.0), line))
    draw = imgui.get_window_draw_list()
    centre = ImVec2(origin.x + radius + dp(1.0), origin.y + line * 0.5)
    draw.add_circle_filled(centre, radius * 1.8, alpha(colour, 0.18), 16)
    draw.add_circle_filled(centre, radius, colour, 16)
    tooltip(tip)


def progress_bar(fraction, size=(-1.0, 0.0), overlay='', tone='accent'):
    """A thin progress bar; a fraction below 0 sweeps (indeterminate)."""
    p = palette()
    width, height = size
    if width <= 0.0:
        width = max(dp(20.0), imgui.get_content_region_avail().x + (width + 1.0 if width < 0.0 else 0.0))
    if height <= 0.0:
        height = imgui.get_frame_height() if overlay else dp(6.0)
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy(ImVec2(width, height))
    draw = imgui.get_window_draw_list()
    rounding = min(height * 0.5, imgui.get_style().frame_rounding + dp(2.0))
    maximum = ImVec2(origin.x + width, origin.y + height)
    colour = p.textDim if tone == 'neutral' else tone_colour(tone)
    draw.add_rect_filled(origin, maximum, p.bg3, rounding)
    if fraction >= 0.0:
        t = min(1.0, max(0.0, fraction))
        if t > 0.0:
            draw.add_rect_filled(origin, ImVec2(origin.x + max(rounding * 2.0, width * t), maximum.y),
                                 colour, rounding)
    else:
        phase = math.fmod(imgui.get_time() * 0.8, 1.0)
        segment = width * 0.3
        x0 = origin.x - segment + (width + segment) * phase
        draw.push_clip_rect(origin, maximum, True)
        draw.add_rect_filled(ImVec2(x0, origin.y), ImVec2(x0 + segment, maximum.y), colour, rounding)
        draw.pop_clip_rect()
    if overlay:
        centred_text(draw, origin, maximum, p.text, overlay)


def spinner(identifier, radius=7.0, colour=0):
    imgui.push_id(identifier)
    r = dp(radius)
    origin = imgui.get_cursor_screen_pos()
    imgui.dummy(ImVec2(r * 2.0 + dp(2.0), r * 2.0 + dp(2.0)))
    draw = imgui.get_window_draw_list()
    centre = ImVec2(origin.x + r + dp(1.0), origin.y + r + dp(1.0))
    start = imgui.get_time() * 6.0
    thickness = max(1.5, r * 0.28)
    draw.path_clear()
    draw.path_arc_to(centre, r - thickness * 0.5, 0.0, math.pi * 2.0, 24)
    draw.path_stroke(alpha(palette().textFaint, 0.35), thickness)
    draw.path_clear()
    draw.path_arc_to(centre, r - thickness * 0.5, start, start + math.pi * 1.3, 32)
    draw.path_stroke(colour or palette().accent, thickness)
    imgui.pop_id()


def empty_state(title, message='', glyph=''):
    """A centred title and message filling the rest of a panel: never leave a panel blank."""
    p = palette()
    area = imgui.get_content_region_avail()
    origin = imgui.get_cursor_screen_pos()
    draw = imgui.get_window_draw_list()
    middle = origin.y + max(dp(60.0), area.y * 0.45)
    if glyph and icons_available():
        with scoped_font(ui_font(), 2.4):
            centred_text(draw, ImVec2(origin.x, middle - dp(70.0)), ImVec2(origin.x + area.x, middle - dp(24.0)),
                         p.textFaint, glyph)
    with scoped_font(bold_font(), 1.1):
        centred_text(draw, ImVec2(origin.x, middle - dp(22.0)), ImVec2(origin.x + area.x, middle), p.textDim, title)
    if message:
        centred_text(draw, ImVec2(origin.x, middle), ImVec2(origin.x + area.x, middle + dp(20.0)),
                     p.textFaint, message)
    imgui.dummy(ImVec2(area.x, max(0.0, middle + dp(24.0) - origin.y)))


def callout(tone, text):
    """A notice block with a coloured bar, for a standing condition (not an event)."""
    p = palette()
    colour = p.textDim if tone == 'neutral' else tone_colour(tone)
    width = imgui.get_content_region_avail().x
    pad = dp2(10.0, 7.0)
    bar = dp(3.0)
    wrap = max(dp(40.0), width - pad.x * 2.0 - bar)
    size = imgui.calc_text_size(text, None, False, wrap)
    origin = imgui.get_cursor_screen_pos()
    maximum = ImVec2(origin.x + width, origin.y + size.y + pad.y * 2.0)
    draw = imgui.get_window_draw_list()
    rounding = imgui.get_style().frame_rounding
    draw.add_rect_filled(origin, maximum, mix(p.bg2, colour, 0.10), rounding)
    draw.add_rect_filled(origin, ImVec2(origin.x + bar, maximum.y), colour, rounding,
                         imgui.ImDrawFlags_.round_corners_left)
    draw.add_text(imgui.get_font(), imgui.get_font_size(), ImVec2(origin.x + bar + pad.x, origin.y + pad.y),
                  p.text, text, None, wrap)
    imgui.dummy(ImVec2(width, maximum.y - origin.y))


def colour_chip(identifier, colour, size):
    origin = imgui.get_cursor_screen_pos()
    clicked = imgui.invisible_button(identifier, ImVec2(*size))
    draw = imgui.get_window_draw_list()
    maximum = ImVec2(origin.x + size[0], origin.y + size[1])
    draw.add_rect_filled(origin, maximum, colour, dp(2.0))
    if imgui.is_item_hovered():
        draw.add_rect(origin, maximum, palette().text, dp(2.0), 0, 1.5)
    return clicked


def notify(text, tone='neutral', seconds=4.0):
    """A toast at the bottom right, for an event. render_notifications() draws them."""
    if not text:
        return
    _state.toast_ids += 1
    _state.toasts.append({'text': text, 'tone': tone, 'until': time.monotonic() + seconds,
                          'id': _state.toast_ids})
    del _state.toasts[:-6]


def render_notifications():
    """Once per frame, after everything else."""
    now = time.monotonic()
    _state.toasts = [toast for toast in _state.toasts if toast['until'] >= now]
    if not _state.toasts:
        return
    p = palette()
    viewport = imgui.get_main_viewport()
    y = viewport.work_pos.y + viewport.work_size.y - dp(16.0)
    x = viewport.work_pos.x + viewport.work_size.x - dp(16.0)
    flags = (imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.always_auto_resize
             | imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_focus_on_appearing
             | imgui.WindowFlags_.no_nav | imgui.WindowFlags_.no_move)
    if hasattr(imgui.WindowFlags_, 'no_docking'):
        flags |= imgui.WindowFlags_.no_docking
    for toast in reversed(_state.toasts):
        fade = min(1.0, max(0.0, (toast['until'] - now) / 0.3))
        imgui.set_next_window_pos(ImVec2(x, y), imgui.Cond_.always, ImVec2(1.0, 1.0))
        imgui.set_next_window_bg_alpha(0.98 * fade)
        height = 0.0
        with scoped_var(imgui.StyleVar_.window_padding, dp2(14.0, 9.0),
                        imgui.StyleVar_.window_rounding, dp(metrics().rounding_large + 2.0),
                        imgui.StyleVar_.alpha, fade), \
                scoped_color(imgui.Col_.window_bg, p.bg2, imgui.Col_.border, p.lineStrong):
            shown = imgui.begin('##cyuiToast%d' % toast['id'], None, flags)
            if (shown[0] if isinstance(shown, tuple) else shown):
                colour = p.accent if toast['tone'] == 'neutral' else tone_colour(toast['tone'])
                position, size = imgui.get_window_pos(), imgui.get_window_size()
                imgui.get_window_draw_list().add_rect_filled(
                    position, ImVec2(position.x + dp(3.0), position.y + size.y), colour,
                    dp(metrics().rounding_large + 2.0), imgui.ImDrawFlags_.round_corners_left)
                imgui.push_text_wrap_pos(imgui.get_font_size() * 26.0)
                imgui.text_unformatted(toast['text'])
                imgui.pop_text_wrap_pos()
                if imgui.is_window_hovered() and imgui.is_mouse_clicked(imgui.MouseButton_.left):
                    toast['until'] = now + 0.3
                height = size.y
            imgui.end()
        y -= height + dp(8.0)


# ---- Layout --------------------------------------------------------------------------------

_BAR_FLAGS = (imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_saved_settings
              | imgui.WindowFlags_.no_scroll_with_mouse)
_bar_pushed = []


def _side_bar(identifier, direction, size, ground, padding):
    imgui.push_style_color(imgui.Col_.window_bg, vec(ground))
    imgui.push_style_var(imgui.StyleVar_.window_padding, padding)
    imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
    _bar_pushed.append((1, 2))
    shown = imgui.internal.begin_viewport_side_bar(identifier, imgui.get_main_viewport(), direction,
                                                   size, _BAR_FLAGS)
    p = palette()
    position, extent = imgui.get_window_pos(), imgui.get_window_size()
    maximum = ImVec2(position.x + extent.x, position.y + extent.y)
    draw = imgui.get_window_draw_list()
    if direction == imgui.Dir.up:
        draw.add_line(ImVec2(position.x, maximum.y - 0.5), ImVec2(maximum.x, maximum.y - 0.5), p.lineStrong)
    elif direction == imgui.Dir.down:
        draw.add_line(ImVec2(position.x, position.y + 0.5), ImVec2(maximum.x, position.y + 0.5), p.lineStrong)
    elif direction == imgui.Dir.left:
        draw.add_line(ImVec2(maximum.x - 0.5, position.y), ImVec2(maximum.x - 0.5, maximum.y), p.lineStrong)
    return shown


def _end_side_bar():
    imgui.end()
    colours, variables = _bar_pushed.pop()
    imgui.pop_style_var(variables)
    imgui.pop_style_color(colours)


def begin_top_bar(identifier, height=0.0):
    """A bar along the top of the main viewport. Always pair with end_top_bar()."""
    if height <= 0.0:
        height = imgui.get_frame_height() + dp(metrics().toolbar_height)
    pad_y = max(0.0, (height - imgui.get_frame_height()) * 0.5)
    return _side_bar(identifier, imgui.Dir.up, height, palette().bg1, ImVec2(dp(8.0), pad_y))


def end_top_bar():
    _end_side_bar()


def begin_status_bar(identifier):
    height = imgui.get_font_size() * 0.86 + dp(10.0)
    return _side_bar(identifier, imgui.Dir.down, height, palette().bg0, dp2(8.0, 4.0))


def end_status_bar():
    _end_side_bar()


def status_text(tone, text):
    p = palette()
    with scoped_font(None, 0.86):
        imgui.text_colored(vec(p.textFaint if tone == 'neutral' else tone_colour(tone)), text)


def begin_bottom_bar(identifier, height=0.0):
    """A bar along the bottom, above the status bar: a player, a transport. Python port only
    (not in the C++ library). Always pair with end_bottom_bar()."""
    if height <= 0.0:
        height = imgui.get_frame_height() + dp(metrics().toolbar_height * 0.6)
    pad_y = max(0.0, (height - imgui.get_frame_height()) * 0.5)
    return _side_bar(identifier, imgui.Dir.down, height, palette().bg2, ImVec2(dp(8.0), pad_y))


def end_bottom_bar():
    _end_side_bar()


def begin_sidebar(identifier, width=190.0):
    """A navigation column on the left. Always pair with end_sidebar()."""
    return _side_bar(identifier, imgui.Dir.left, dp(width), palette().bg0, dp2(10.0, 12.0))


def end_sidebar():
    _end_side_bar()


def sidebar_header(title, badge_text=''):
    with scoped_font(bold_font(), 1.0), scoped_color(imgui.Col_.text, palette().text):
        imgui.text_unformatted(title)
    if badge_text:
        imgui.same_line(0.0, dp(6.0))
        badge(badge_text, 'warning')
    space(10.0)


def sidebar_group(label):
    space(6.0)
    imgui.indent(dp(4.0))
    overline(label, palette().textFaint)
    imgui.unindent(dp(4.0))
    space(2.0)


def sidebar_item(glyph, label, active, badge_text=''):
    p = palette()
    width = imgui.get_content_region_avail().x
    height = imgui.get_frame_height() + dp(8.0)
    origin = imgui.get_cursor_screen_pos()
    imgui.push_id(label)
    clicked = imgui.invisible_button('##item', ImVec2(width, height))
    hovered = imgui.is_item_hovered()
    imgui.pop_id()
    draw = imgui.get_window_draw_list()
    rounding = imgui.get_style().frame_rounding + dp(2.0)
    maximum = ImVec2(origin.x + width, origin.y + height)
    if active:
        draw.add_rect_filled(origin, maximum, alpha(p.accent, 0.16), rounding)
        draw.add_rect(origin, maximum, alpha(p.accent, 0.45), rounding)
    elif hovered:
        draw.add_rect_filled(origin, maximum, p.bg3, rounding)
    colour = p.text if active or hovered else p.textDim
    x = origin.x + dp(10.0)
    y = origin.y + (height - imgui.get_font_size()) * 0.5
    if glyph and icons_available():
        draw.add_text(ImVec2(x, y), p.accent if active else colour, glyph)
        x += imgui.get_font_size() + dp(10.0)
    room = maximum.x - x - dp(8.0)
    if badge_text:
        with scoped_font(bold_font(), 0.74):
            size = imgui.calc_text_size(badge_text)
            b_max = ImVec2(maximum.x - dp(8.0), origin.y + (height + size.y) * 0.5 + dp(2.0))
            b_min = ImVec2(b_max.x - size.x - dp(10.0), b_max.y - size.y - dp(4.0))
            draw.add_rect_filled(b_min, b_max, p.accent if active else p.bg4, height)
            draw.add_text(ImVec2(b_min.x + dp(5.0), b_min.y + dp(2.0)), p.accentText if active else p.textDim,
                          badge_text)
        room = b_min.x - x - dp(6.0)
    if active:
        with scoped_font(bold_font(), 1.0):
            clipped_text(draw, ImVec2(x, y), room, colour, label)
    else:
        clipped_text(draw, ImVec2(x, y), room, colour, label)
    imgui.dummy(ImVec2(0.0, dp(1.0)))
    return clicked


def panel_header(title, subtitle=''):
    heading(title, 2)
    if subtitle:
        with scoped_font(None, 0.88):
            text_faint(subtitle)


def begin_toolbar(identifier):
    """A toolbar row inside a window. Always pair with end_toolbar()."""
    p = palette()
    pad = dp2(6.0, 4.0)
    with scoped_color(imgui.Col_.child_bg, p.bg2), \
            scoped_var(imgui.StyleVar_.window_padding, pad, imgui.StyleVar_.child_rounding, 0.0,
                       imgui.StyleVar_.child_border_size, 0.0):
        shown = imgui.begin_child(identifier, ImVec2(0.0, imgui.get_frame_height() + pad.y * 2.0),
                                  imgui.ChildFlags_.always_use_window_padding,
                                  imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse)
    position, size = imgui.get_window_pos(), imgui.get_window_size()
    imgui.get_window_draw_list().add_line(ImVec2(position.x, position.y + size.y - 0.5),
                                          ImVec2(position.x + size.x, position.y + size.y - 0.5), p.line)
    return shown


def end_toolbar():
    imgui.end_child()


def begin_modal(title, open_flag, width=460.0):
    """A centred modal with a title and a close cross. Returns (shown, open). Call end_modal()
    only when shown; open becomes False when it closes."""
    if open_flag and not imgui.is_popup_open(title):
        imgui.open_popup(title)
    viewport = imgui.get_main_viewport()
    imgui.set_next_window_pos(viewport.get_center(), imgui.Cond_.appearing, ImVec2(0.5, 0.5))
    imgui.set_next_window_size(ImVec2(dp(width), 0.0), imgui.Cond_.always)
    with scoped_var(imgui.StyleVar_.window_padding, dp2(18.0, 16.0),
                    imgui.StyleVar_.window_rounding, dp(metrics().rounding_large + 4.0)), \
            scoped_color(imgui.Col_.popup_bg, palette().bg2, imgui.Col_.border, palette().lineStrong):
        result = imgui.begin_popup_modal(title, None, imgui.WindowFlags_.no_title_bar
                                         | imgui.WindowFlags_.no_saved_settings)
    shown = result[0] if isinstance(result, tuple) else result
    if not shown:
        return False, False
    _state.modal_open = True
    with scoped_font(bold_font(), 1.15):
        imgui.text_unformatted(_visible(title))
    imgui.same_line()
    align_right(imgui.get_frame_height())
    if icon_button(icon.close if icons_available() else 'x', 'Close (Esc)'):
        imgui.close_current_popup()
        _state.modal_open = False
    space(6.0)
    return True, _state.modal_open


def end_modal():
    imgui.end_popup()


def modal_buttons(confirm, cancel='Cancel', danger=False):
    """Buttons at the foot of a modal: 0 nothing, 1 confirm, 2 cancel. Enter / Escape work."""
    space(10.0)
    style = imgui.get_style()
    confirm_width = max(dp(84.0), button_width(confirm))
    cancel_width = max(dp(84.0), button_width(cancel)) if cancel else 0.0
    align_right(confirm_width + ((cancel_width + style.item_spacing.x) if cancel else 0.0))
    result = 0
    if cancel:
        if button(cancel, 'secondary', (cancel_width, 0.0)) or imgui.is_key_pressed(imgui.Key.escape, False):
            result = 2
        imgui.same_line()
    if button(confirm, 'danger' if danger else 'primary', (confirm_width, 0.0)) \
            or (imgui.is_key_pressed(imgui.Key.enter, False) and not imgui.is_any_item_active()):
        result = 1
    if result:
        imgui.close_current_popup()
        _state.modal_open = False
    return result


def align_right(width):
    right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    imgui.set_cursor_pos_x(max(imgui.get_cursor_pos_x(), right - width))


def button_width(label):
    return imgui.calc_text_size(_visible(label)).x + imgui.get_style().frame_padding.x * 2.0


# ---- Icons (Segoe MDL2 Assets, merged by load_fonts) -----------------------------------------

class icon:  # noqa: N801 - read as cyui.icon.save, like the C++ cyui::icon::save
    play, pause, stop, record = chr(0xE768), chr(0xE769), chr(0xE71A), chr(0xE7C8)
    add, remove, trash, settings, search = chr(0xE710), chr(0xE738), chr(0xE74D), chr(0xE713), chr(0xE721)
    folder, open_file, save, undo, redo = chr(0xE8B7), chr(0xE8E5), chr(0xE74E), chr(0xE7A7), chr(0xE7A6)
    volume, mute, edit, close, check = chr(0xE767), chr(0xE74F), chr(0xE70F), chr(0xE711), chr(0xE73E)
    chevron_down, chevron_up = chr(0xE70D), chr(0xE70E)
    chevron_left, chevron_right = chr(0xE76B), chr(0xE76C)
    more, refresh, zoom_in, zoom_out = chr(0xE712), chr(0xE72C), chr(0xE8A3), chr(0xE71F)
    pin, link, lock, filter, loop = chr(0xE718), chr(0xE71B), chr(0xE72E), chr(0xE71C), chr(0xE8EE)
    microphone, headphone, audio, note = chr(0xE720), chr(0xE7F6), chr(0xE8D6), chr(0xEC4F)
    equalizer, library, tag, star, star_fill = chr(0xE9E9), chr(0xE8F1), chr(0xE8EC), chr(0xE734), chr(0xE735)
    view, copy, paste, cut = chr(0xE890), chr(0xE8C8), chr(0xE77F), chr(0xE8C6)
    import_file, export_file, power, info, warning = (chr(0xE8B5), chr(0xEDE1), chr(0xE7E8),
                                                      chr(0xE946), chr(0xE7BA))
    grid, ruler, connect, shuffle = chr(0xF0E2), chr(0xED5E), chr(0xE703), chr(0xE8B1)
    back, forward, previous, next, sync = chr(0xE72B), chr(0xE72A), chr(0xE892), chr(0xE893), chr(0xE895)
    dock_left, new_window, back_to_window = chr(0xE90C), chr(0xE8A7), chr(0xE73F)
    dock_right, dock_bottom, full_screen, menu = chr(0xE90D), chr(0xE90E), chr(0xE740), chr(0xE700)
    touch, crop, trim, download, presets = chr(0xE815), chr(0xE7A8), chr(0xE78A), chr(0xE896), chr(0xE8F1)
    keyboard, lightbulb, home, globe, people = chr(0xE765), chr(0xE82F), chr(0xE80F), chr(0xE774), chr(0xE716)
    contact, mail, calendar, clock, cloud = chr(0xE77B), chr(0xE715), chr(0xE787), chr(0xE823), chr(0xE753)
    upload, sort, view_all, hide, error = chr(0xE898), chr(0xE8CB), chr(0xE8A9), chr(0xED1A), chr(0xE783)
    help, brightness, colour, flag, heart = chr(0xE897), chr(0xE706), chr(0xE790), chr(0xE7C1), chr(0xEB51)
    bug, repair, document, code, photo = chr(0xEBE8), chr(0xE90F), chr(0xE8A5), chr(0xE943), chr(0xEB9F)
    camera, video, send, share, rename = chr(0xE722), chr(0xE714), chr(0xE724), chr(0xE72D), chr(0xE8AC)
    tiles, list, status_circle = chr(0xECA5), chr(0xEA37), chr(0xEA3B)
