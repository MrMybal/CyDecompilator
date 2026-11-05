"""CyUI application navigation; panels retain their Runtime jobs and widget IDs."""
import cyui
import time
from cyui_modules import commands
from ui_views import stable_id
from ui_common import imgui, tr

PAGES = (
    ('workspace', 'Workspace', 'code', 'Explore'),
    ('project', 'Project IDE', 'document', 'Explore'),
    ('investigation', 'Investigation', 'search', 'Explore'),
    ('porting', 'PS5 porting', 'sync', 'Explore'),
    ('xbox', 'Xbox porting', 'sync', 'Explore'),
    ('unreal', 'Unreal reconstruction', 'library', 'Explore'),
    ('assistant', 'AI', 'people', 'Explore'),
    ('engines', 'Engines', 'library', 'Tools'),
    ('ai', 'AI assistant settings', 'people', 'Tools'),
    ('log', 'Application log', 'list', 'System'),
    ('advanced', 'Advanced operations', 'settings', 'System'),
    ('options', 'Options', 'colour', 'System'),
    ('help', 'Documentation', 'document', 'System'),
)


def command_model(app):
    result = [commands.Command(stable_id('command', 'open'), 'Open file...', 'Ctrl+O')]
    result += [commands.Command(stable_id('page', key), caption, 'F1' if key == 'help' else '', category=section)
               for key, caption, _, section in PAGES]
    pid = (app.project or {}).get('projectId')
    session = app.ide.sessions.get(pid, {})
    available = (bool(session.get('info', {}).get('available'))
                 and not app.jobs.busy('ide-' + str(pid))
                 and not session.get('history_restoring') and not session.get('reconstruction_busy')
                 and not app.ide.debug.active(pid))
    result += [commands.Command(stable_id('command', 'save'), 'Save all', category='Project IDE', enabled=available),
               commands.Command(stable_id('command', 'build'), 'Build', category='Project IDE', enabled=available)]
    return result


def execute_command(app, identifier):
    if identifier == stable_id('command', 'open'):
        app.choose_file()
        return
    for key, _, _, _ in PAGES:
        if identifier == stable_id('page', key):
            if key == 'help':
                app.open_help('start')
            else:
                app.force_tab = key
            return
    allowed = next((c.enabled for c in command_model(app) if c.id == identifier), False)
    if allowed:
        pid = app.project['projectId']
        if identifier == stable_id('command', 'save'):
            app.ide.save_all(pid)
        elif identifier == stable_id('command', 'build'):
            app.ide.execute(pid, 'build')


def draw(app, render):
    import ui_common
    ui_common._shell_navigation = True
    if not hasattr(app, '_commands'):
        app._commands = commands.CommandState()
        app._commands_open = False
        app._navigation_filter = cyui.TextFilter()
    if imgui.is_key_chord_pressed(imgui.Key.mod_ctrl | imgui.Key.mod_shift | imgui.Key.p):
        app._commands_open = not app._commands_open
    page = getattr(app, 'active_page', 'workspace')
    requested, app.force_tab = app.force_tab, ''
    if requested in {p[0] for p in PAGES}:
        page = requested
    if ui_common.journal.test: page = 'log'
    if ui_common._advanced_panel and ui_common._advanced_panel.test: page = 'advanced'
    import sys
    if '--ui-test-options' in sys.argv: page = 'options'

    viewport = imgui.get_main_viewport()
    top = bottom = left = 0.0
    if cyui.begin_top_bar('###cydec-top'):
        app.logo(imgui.get_frame_height())
        imgui.same_line()
        cyui.heading('CyDecompilator', 3)
        if app.project:
            imgui.same_line(0, cyui.dp(24))
            cyui.text_dim(app.project['name'])
        # A quiet global entry point; the primary action belongs to the current panel.
        reserve = 2 * imgui.get_frame_height() + cyui.dp(110)
        if imgui.get_content_region_avail().x > reserve:
            imgui.same_line(max(imgui.get_cursor_pos_x(), imgui.get_window_width() - reserve))
            cyui.kbd('Ctrl+O')
            imgui.same_line()
            if cyui.icon_button(cyui.icon.open_file, tr('Open file...') + ' (Ctrl+O)'):
                app.choose_file()
            imgui.same_line()
            if cyui.icon_button(cyui.icon.search, tr('Command palette') + ' (Ctrl+Shift+P)'):
                app._commands_open = True
        top = imgui.get_window_size().y
    cyui.end_top_bar()

    if cyui.begin_status_bar('###cydec-status'):
        busy = bool(app.jobs.jobs)
        cyui.status_dot(cyui.palette().accent if busy else cyui.palette().success)
        imgui.same_line()
        cyui.status_text('accent' if busy else 'neutral', tr('Working...') if busy else tr('Ready'))
        if busy:
            imgui.same_line()
            cyui.text_dim(' · '.join(dict.fromkeys(tr(r['job']['state']) for r in app.jobs.jobs.values())))
        elif app.project:
            imgui.same_line()
            cyui.text_faint(app.project['format']['formatName'] + ' · ' + app.engine)
        bottom = imgui.get_window_size().y
    cyui.end_status_bar()

    # Keep code space at smaller window sizes; all navigation stays available.
    width = 190 if viewport.size.x > cyui.dp(1200) else 156
    if cyui.begin_sidebar('###cydec-sidebar', width):
        cyui.sidebar_header(tr('Navigation'))
        cyui.filter_box('###navigation-filter', app._navigation_filter, hint='Search', width=-1, shortcut=False)
        imgui.begin_child('###navigation-items', imgui.ImVec2(0, 0))
        group = None
        for key, caption, glyph, section in PAGES:
            if not app._navigation_filter.matches(caption, section):
                continue
            if group != section:
                cyui.sidebar_group(tr(section).upper())
                group = section
            with cyui.scoped_id(key):
                origin = imgui.get_cursor_screen_pos()
                width = imgui.get_content_region_avail().x
                height = imgui.get_frame_height() + cyui.dp(8)
                if cyui.sidebar_item(getattr(cyui.icon, glyph), cyui.tr_label(caption + '###page-' + key), key == page):
                    page = key
                    if key == 'help':
                        app.open_help('start')
                # CyUI ends with a spacer, so its last-item tooltip cannot target the row.
                maximum = imgui.ImVec2(origin.x + width, origin.y + height)
                if imgui.is_window_hovered() and imgui.is_mouse_hovering_rect(origin, maximum):
                    previous, started = getattr(app, '_navigation_hover', ('', 0))
                    if previous != key:
                        app._navigation_hover = (key, time.monotonic())
                    elif time.monotonic() - started > 0.4 and imgui.begin_tooltip():
                        imgui.text_unformatted(tr(caption))
                        imgui.end_tooltip()
                elif getattr(app, '_navigation_hover', ('', 0))[0] == key:
                    app._navigation_hover = ('', 0)
        imgui.end_child()
        left = imgui.get_window_size().x
    cyui.end_sidebar()
    app.active_page = page
    origin = viewport.pos
    imgui.set_next_window_pos(imgui.ImVec2(origin.x + left, origin.y + top))
    imgui.set_next_window_size(imgui.ImVec2(max(cyui.dp(180), viewport.size.x-left),
                                          max(cyui.dp(120), viewport.size.y-top-bottom)))
    flags = (imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_resize | imgui.WindowFlags_.no_move
             | imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_saved_settings)
    shown, _ = imgui.begin('###cydec-content', flags=flags)
    try:
        if shown:
            render(page)
    finally:
        imgui.end()
    app._commands_open, requested = commands.command_palette('Command palette###commands',
        app._commands_open, app._commands, command_model(app))
    if requested:
        execute_command(app, requested)


def utility_page(page):
    """Use the existing scaffold panels without duplicating their functionality."""
    import ui_common
    if page == 'options':
        ui_common.options_panel()
        return
    if imgui.begin_tab_bar('###cydec-utilities'):
        if page == 'log': ui_common.journal.draw_tab()
        elif page == 'advanced' and ui_common._advanced_panel: ui_common._advanced_panel.draw_tab()
        imgui.end_tab_bar()
