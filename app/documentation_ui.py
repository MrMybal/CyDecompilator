"""Native help entry panel; the offline reader is the packaged CyDoc export."""
import cyui
import ui_common
from ui_common import imgui, label, tr
from documentation import Documentation


class DocumentationUI:
    def __init__(self, documentation=None):
        self.error = ''
        self.documentation = documentation
        try:
            self.documentation = documentation or Documentation()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = str(exc)
        self.topic = 'start'
        self.last_url = ''

    def language(self):
        choice = ui_common.preferences.values.get('manual_language', 'auto')
        if choice not in ('en', 'fr'):
            choice = ui_common.preferences.values.get('language', 'en')
        return Documentation.language(choice)

    def open(self, topic=None, anchor='', media='', context=None):
        if self.documentation is None:
            return False
        self.topic = topic or (self.documentation.topic_for_context(context) if context else self.topic)
        try:
            self.last_url = self.documentation.open(self.topic, self.language(), anchor, media)
            self.error = ''
            return True
        except (OSError, ValueError, KeyError) as exc:
            self.error = str(exc)
            return False

    def draw(self, app):
        cyui.heading(tr('Documentation'), 2)
        imgui.same_line()
        cyui.kbd('F1')
        imgui.text_wrapped(tr('Read the bundled CyDoc documentation in your browser. No internet or server is required.'))
        codes = ('auto', 'en', 'fr')
        choice = ui_common.preferences.values.get('manual_language', 'auto')
        changed, index = imgui.combo(label('Documentation language'), codes.index(choice) if choice in codes else 0,
                                     [tr('Follow interface language'), 'English', 'Français'])
        if changed:
            ui_common.preferences.values['manual_language'] = codes[index]
            ui_common.preferences.save()
        if self.documentation is not None:
            chapters = self.documentation.routes['chapters']
            if self.topic not in {chapter['id'] for chapter in chapters}:
                current = self.documentation.routes['pages'].get(self.topic)
                if current:
                    chapters = [{'id':self.topic, 'title':current['title']}] + chapters
            ids = [chapter['id'] for chapter in chapters]
            selected = ids.index(self.topic) if self.topic in ids else 0
            changed, selected = imgui.combo(label('Chapters'), selected,
                                             [chapter['title'][self.language()] for chapter in chapters])
            if changed:
                self.topic = ids[selected]
            if cyui.button(label('Open documentation')):
                self.open()
            imgui.same_line()
            if cyui.ghost_button(label('Copy local documentation link')):
                try:
                    self.last_url = self.documentation.url(self.topic, self.language())
                    imgui.set_clipboard_text(self.last_url)
                except (OSError, ValueError) as exc:
                    self.error = str(exc)
            if self.last_url:
                imgui.text_wrapped(self.last_url)
        if self.error:
            cyui.callout('error', tr('Documentation unavailable: %s') % self.error)
