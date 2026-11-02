"""English-first UI localization, usable without ImGui or a rendering backend.

The active locale is local to the Python execution context (ContextVar), so
independent async tools can choose different languages. Use locale_scope for a
temporary view or set_locale for the application's UI context.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
import re
from ._locale_catalog import FRENCH

_current = ContextVar('cyui_locale', default='en')
_catalogs = {'en': {}, 'fr': dict(FRENCH)}
_names = {'en': 'English', 'fr': 'Français'}
_lock = RLock()


def _normalize(code):
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,35}', code):
        return ''
    return code.replace('_', '-').lower()


def set_locale(code):
    code = _normalize(code)
    with _lock:
        if code not in _catalogs:
            code = code.split('-')[0]
        if code not in _catalogs:
            return False
    _current.set(code)
    return True


def locale():
    return _current.get()


def available_locales():
    with _lock:
        return [(code, _names[code]) for code in ('en', 'fr', *sorted(set(_names)-{'en', 'fr'}))]


def register_translations(code, translations, name=None):
    code = _normalize(code)
    if not code or not all(isinstance(k, str) and isinstance(v, str) for k, v in translations.items()):
        return False
    with _lock:
        _catalogs.setdefault(code, {}).update(translations)
        _names[code] = name if name is not None else _names.get(code, code)
    return True


def tr(key, english_fallback=None):
    with _lock:
        base = _catalogs.get(locale().split('-')[0], {})
        return _catalogs.get(locale(), {}).get(key, base.get(key, _catalogs['en'].get(key, key if english_fallback is None else english_fallback)))


def tr_label(key, english_fallback=None):
    visible = key.split('##', 1)[0]
    identity = key.split('###', 1)[1] if '###' in key else key
    return tr(visible, english_fallback)+'###'+identity


@contextmanager
def locale_scope(code):
    token = _current.set(_current.get())
    if not set_locale(code):
        _current.reset(token)
        raise ValueError('Unknown CyUI locale')
    try:
        yield
    finally:
        _current.reset(token)
