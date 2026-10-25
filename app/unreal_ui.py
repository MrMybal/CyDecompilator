"""Unreal reconstruction rules displayed through the shared Runtime."""
import cyui
import ui_common
from ui_common import imgui, label, tr


class UnrealUI:
    def __init__(self, app):
        self.app = app
        self.profile = 'halo-cea-x360'
        self.category = ''
        self.report = {}
        self.error = ''
        self.loaded = None
        self.generation = 0

    def refresh(self):
        language = 'fr' if ui_common.preferences.values.get('language') == 'fr' else 'en'
        key = (self.profile, self.category, language)
        self.loaded = key
        self.generation += 1
        generation = self.generation
        self.report = {}
        self.error = ''
        def done(out):
            if generation == self.generation:
                self.report = out
        def failed(text):
            if generation == self.generation:
                self.error = text
        self.app.jobs.submit('unreal_rules', dict(zip(('profile', 'category', 'language'), key)),
                             tag='unreal-rules', done=done, failed=failed)

    def draw(self):
        language = 'fr' if ui_common.preferences.values.get('language') == 'fr' else 'en'
        if self.loaded != (self.profile, self.category, language):
            self.refresh()
        cyui.panel_header(tr('Unreal reconstruction'), tr('Reconstruction rules from the Unreal prototype.'))
        cyui.callout('info', tr('Rules and profiles are integrated. Game conversion remains a separate prototype.'))
        profiles = ['generic', 'halo-cea-x360']
        changed, index = imgui.combo(label('Reconstruction profile'), profiles.index(self.profile),
                                     [tr('General reconstruction'), 'Halo CEA Xbox 360 / UE 5.8'])
        if changed:
            self.profile = profiles[index]
            self.category = ''
            self.refresh()
        sections = self.report.get('categories', [])
        keys = [''] + [row['id'] for row in sections]
        changed, index = imgui.combo(label('Rule category'), keys.index(self.category) if self.category in keys else 0,
                                     [tr('All categories')] + [row['name'] for row in sections])
        if changed:
            self.category = keys[index]
            self.refresh()
        if cyui.button(label('Reload reconstruction rules')):
            self.refresh()
        if self.error:
            cyui.callout('error', self.error)
        report = self.report
        if not report:
            return
        imgui.text_wrapped(report['profile']['description'])
        if cyui.button(label('Copy reconstruction guide')):
            self.app.jobs.submit('unreal_guide', {'profile': self.profile, 'category': self.category,
                                               'language': language}, tag='unreal-guide',
                                 done=lambda out: imgui.set_clipboard_text(out['documentation']),
                                 failed=lambda text: setattr(self, 'error', text))
        if cyui.begin_section(label('Reconstruction limits'), True):
            for text in report['limits']:
                imgui.text_wrapped('• ' + text)
            imgui.text_wrapped(report['evidencePolicy'])
            cyui.end_section()
        if cyui.begin_section(label('Campaign profiles'), False):
            for mission in report['profile'].get('missions', []):
                imgui.text_unformatted(mission['map'].upper() + ' — ' + mission['title'])
            cyui.end_section()
        for rule in report['rules']:
            if cyui.begin_section(rule['title'] + '###unreal-rule-' + rule['id'], True):
                imgui.text_wrapped(rule['requirement'])
                cyui.text_dim(tr('Validation'))
                imgui.text_wrapped(rule['validation'])
                for ref in rule['evidence']:
                    imgui.text_wrapped(ref['path'])
                cyui.end_section()
