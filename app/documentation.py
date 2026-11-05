"""Validated file:// help routes. No engine, HTTP server or Node runtime at read time."""
import json
from pathlib import Path
from urllib.parse import quote, urlencode, unquote
import webbrowser


class Documentation:
    """Resolve only pages, sections and media included in the installed export."""

    def __init__(self, root=None, opener=None):
        self.root = Path(root or Path(__file__).with_name('help')).resolve()
        self.routes = json.loads((self.root / 'routes.json').read_text(encoding='utf-8'))
        if self.routes.get('schemaVersion') != 1:
            raise ValueError('Unsupported documentation route catalogue')
        self.opener = opener or webbrowser.open

    @staticmethod
    def language(value):
        return 'fr' if str(value).lower().split('-')[0].split('_')[0] == 'fr' else 'en'

    def topic_for_context(self, context):
        return self.routes['contexts'].get(context, 'start')

    def url(self, topic='start', language='en', anchor='', media='', **state):
        """
        @doc help-route-api
        @locale en
        @title Local help links
        @section API
        @symbol Documentation.url
        Build a validated file URL for the installed CyDoc export. The default language
        is English; French is retained and other interface languages fall back to English.
        Legacy chapter filenames and translated heading slugs resolve through the packaged
        compatibility map. Unknown pages, anchors, media and media state are rejected.

        ```python
        from documentation import Documentation
        help = Documentation()
        url = help.url('start', 'fr', media='workspace-screenshot', note='function-list')
        ```

        See [the user guide](doc:start) and [the source index](doc:source-policy).
        """
        """
        @doc help-route-api
        @locale fr
        @title Liens locaux de l’aide
        @section API
        @symbol Documentation.url
        Construit une URL file pour le lecteur CyDoc installé. L’anglais est la langue
        par défaut ; le français est conservé et les autres langues utilisent l’anglais.
        Les anciens noms de chapitres et ancres françaises sont résolus par la table
        de compatibilité. Les pages, sections, médias et états inconnus sont refusés.

        ```python
        from documentation import Documentation
        help = Documentation()
        url = help.url('start', 'fr', media='workspace-screenshot', note='function-list')
        ```

        Voir [le guide](doc:start) et [la portée de l’index](doc:source-policy).
        """
        locale = self.language(language)
        topic = str(topic).removeprefix('doc:')
        if '#' in topic:
            topic, old_anchor = topic.split('#', 1)
            anchor = anchor or old_anchor
        topic = self.routes['aliases'].get(topic, topic)
        page = self.routes['pages'].get(topic)
        if page is None:
            raise ValueError('Unknown documentation page: ' + topic)
        if locale not in page['locales']:
            locale = self.routes['defaultLocale']
        anchor = unquote(str(anchor).removeprefix('#'))
        legacy = self.routes['legacyAnchors'].get(topic, {})
        anchor = legacy.get(locale, {}).get(anchor, legacy.get('fr', {}).get(anchor, anchor))
        if anchor and anchor not in page['anchors'][locale]:
            raise ValueError('Unknown documentation section: ' + anchor)
        if media and media not in page['media'][locale]:
            raise ValueError('Unknown documentation media: ' + media)
        allowed = {'note', 'zoom', 'x', 'y'}
        if state.keys() - allowed or (state and not media):
            raise ValueError('Unsupported documentation media state')
        if 'note' in state and state['note'] not in page['media'][locale].get(media, []):
            raise ValueError('Unknown documentation annotation')
        for key in ('zoom', 'x', 'y'):
            if key in state:
                import math
                number = float(state[key])
                if not math.isfinite(number) or (key == 'zoom' and not 0.25 <= number <= 12):
                    raise ValueError('Invalid documentation media position')
        entry = self.root / 'index.html'
        if not entry.is_file():
            raise FileNotFoundError(entry)
        fragment = '#/' + locale + '/' + quote(topic, safe='')
        if anchor:
            fragment += '/' + quote(anchor, safe='')
        query = {key: str(value) for key, value in state.items()}
        if media:
            query['media'] = media
        return entry.as_uri() + fragment + ('?' + urlencode(sorted(query.items())) if query else '')

    def open(self, topic='start', language='en', anchor='', media='', **state):
        """
        @doc open-help-api
        @locale en
        @title Opening local help
        @section API
        @symbol Documentation.open
        Validate the destination and open the installed CyDoc reader in the system browser.
        No server or analysis engine is started. Application help entry points call this
        method on a user action. Destination errors are shown in the Documentation panel.
        See [the guide](doc:start) and [the source index](doc:source-policy).
        """
        """
        @doc open-help-api
        @locale fr
        @title Liens locaux de l’aide
        @section API
        @symbol Documentation.open
        Valide la destination puis ouvre le lecteur CyDoc installé avec le navigateur
        configuré sur le système. Aucun serveur ni moteur d’analyse n’est lancé.
        Les entrées d’aide de l’application appellent cette méthode lors d’une action utilisateur.
        Les erreurs de destination sont affichées dans le panneau Documentation.
        Voir [le guide](doc:start) et [la portée de l’index](doc:source-policy).
        """
        url = self.url(topic, language, anchor, media, **state)
        if not self.opener(url, new=0):
            raise OSError('The system browser could not open the local documentation')
        return url
