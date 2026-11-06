"""Validated file:// help routes. No engine, HTTP server or Node runtime at read time."""
import json
from pathlib import Path
from urllib.parse import quote, urlencode, unquote
import webbrowser


class Documentation:
    """Resolve only pages, sections and media included in the installed export."""

    def __init__(self, root=None, opener=None):
        self.root = Path(root or Path(__file__).with_name('Documentation')).resolve()
        self.routes = json.loads((self.root / 'DocData/routes.json').read_text(encoding='utf-8'))
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

        ## Signature {#signature}

        ```text
        Documentation.url(topic='start', language='en', anchor='', media='', **state) -> str
        ```

        ## Parameters {#parameters}

        `topic` is a stable chapter ID or supported legacy alias. `language` selects
        English or French. `anchor` names an explicit section. `media` names a
        distributed image; optional `note`, `zoom`, `x` and `y` select its annotation
        and view. A zoom must be finite and between 0.25 and 12.

        ## Returns and errors {#returns}

        Returns an encoded absolute `file://` URL to `Documentation/Documentation.html`.
        This method does not open a browser. Unknown destinations or invalid view
        values raise `ValueError`; a missing reader raises `FileNotFoundError`.

        See [the user guide](doc:start) and [the integration API](doc:help-api).
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

        ## Signature {#signature}

        ```text
        Documentation.url(topic='start', language='en', anchor='', media='', **state) -> str
        ```

        ## Paramètres {#parameters}

        `topic` est l’identifiant stable du chapitre ou un ancien alias accepté.
        `language` choisit l’anglais ou le français. `anchor` désigne une section
        explicite. `media` désigne une image fournie ; `note`, `zoom`, `x` et `y`
        sélectionnent son annotation et sa vue. Le zoom doit être fini et compris
        entre 0,25 et 12.

        ## Retours et erreurs {#returns}

        Retourne une URL absolue `file://` encodée vers `Documentation/Documentation.html`,
        sans ouvrir le navigateur. Une destination ou une vue invalide provoque
        `ValueError` ; un lecteur absent provoque `FileNotFoundError`.

        Voir [le guide](doc:start) et [l’API d’intégration](doc:help-api).
        """
        locale = self.language(language)
        topic = str(topic).removeprefix('doc:')
        if '#' in topic:
            topic, old_anchor = topic.split('#', 1)
            anchor = anchor or old_anchor
        legacy_topic = False
        seen = set()
        while topic in self.routes['aliases']:
            if topic in seen:
                raise ValueError('Cyclic documentation alias')
            seen.add(topic)
            legacy_topic = True
            topic, _, default_anchor = self.routes['aliases'][topic].partition('#')
            anchor = anchor or default_anchor
        page = self.routes['pages'].get(topic)
        if page is None:
            raise ValueError('Unknown documentation page: ' + topic)
        if locale not in page['locales']:
            locale = self.routes['defaultLocale']
        anchor = unquote(str(anchor).removeprefix('#'))
        legacy = self.routes['legacyAnchors'].get(topic, {})
        anchor = legacy.get(locale, {}).get(anchor, legacy.get('fr', {}).get(anchor, anchor))
        if legacy_topic and anchor and anchor not in page['anchors'][locale]:
            anchor = ''  # Removed appendices retain a link to their current task guide.
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
        entry = self.root / 'Documentation.html'
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
        ## Signature {#signature}

        ```text
        Documentation.open(topic='start', language='en', anchor='', media='', **state) -> str
        ```

        ## Parameters {#parameters}

        The same chapter, language, section and image-view parameters as
        [Documentation.url](doc:help-route-api#parameters). Import the class with
        `from documentation import Documentation` in an installed application.

        ## Returns and errors {#returns}

        Returns the opened local URL. Validation errors are the same as `url`.
        An unavailable system browser raises `OSError`. No application code or
        analysis engine runs when this method opens the manual.

        See [the guide](doc:start) and [the integration API](doc:help-api).
        """
        """
        @doc open-help-api
        @locale fr
        @title Ouvrir l’aide locale
        @section API
        @symbol Documentation.open
        Valide la destination puis ouvre le lecteur CyDoc installé avec le navigateur
        configuré sur le système. Aucun serveur ni moteur d’analyse n’est lancé.
        Les entrées d’aide de l’application appellent cette méthode lors d’une action utilisateur.
        Les erreurs de destination sont affichées dans le panneau Documentation.
        ## Signature {#signature}

        ```text
        Documentation.open(topic='start', language='en', anchor='', media='', **state) -> str
        ```

        ## Paramètres {#parameters}

        Les paramètres de chapitre, langue, section et vue d’image sont identiques à
        ceux de [Documentation.url](doc:help-route-api#parameters). Importer la classe
        avec `from documentation import Documentation` dans une application installée.

        ## Retours et erreurs {#returns}

        Retourne l’URL locale ouverte. Les erreurs de validation sont celles de `url`.
        Un navigateur système indisponible provoque `OSError`. Ouvrir le manuel
        n’exécute aucun code de l’application analysée ni moteur d’analyse.

        Voir [le guide](doc:start) et [l’API d’intégration](doc:help-api).
        """
        url = self.url(topic, language, anchor, media, **state)
        if not self.opener(url, new=0):
            raise OSError('The system browser could not open the local documentation')
        return url
