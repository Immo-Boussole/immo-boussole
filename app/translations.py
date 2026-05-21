import json
import os
from fastapi import Request

LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locales")

translations: dict = {}
_translations_mtime: dict = {}


def _get_locale_mtime(lang: str) -> float:
    """Return the file modification time for a locale file, or 0 if missing."""
    path = os.path.join(LOCALES_DIR, f"{lang}.json")
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def load_translations():
    """Load (or reload) all locale JSON files into the in-memory cache."""
    global translations, _translations_mtime
    if not os.path.exists(LOCALES_DIR):
        print(f"[i18n] Warning: {LOCALES_DIR} not found.")
        return

    for lang in ["fr", "en"]:
        path = os.path.join(LOCALES_DIR, f"{lang}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                translations[lang] = json.load(f)
            _translations_mtime[lang] = os.path.getmtime(path)
        else:
            translations[lang] = {}
            _translations_mtime[lang] = 0.0


def _reload_if_changed():
    """Reload any locale file whose mtime has changed since last load."""
    for lang in ["fr", "en"]:
        current_mtime = _get_locale_mtime(lang)
        if current_mtime != _translations_mtime.get(lang, 0.0):
            path = os.path.join(LOCALES_DIR, f"{lang}.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    translations[lang] = json.load(f)
                _translations_mtime[lang] = current_mtime
                print(f"[i18n] Reloaded translations for '{lang}'")


# Load them once at startup
load_translations()

def get_text(request: Request, key: str, default: str = None, **kwargs) -> str:
    """
    Get a translated string based on the current session language.
    `key` can be nested like 'nav.dashboard'.
    Automatically reloads locale JSON files if they have been modified on disk.
    """
    # Reload translations if locale files have changed (hot-reload support)
    _reload_if_changed()

    # default to fr
    lang = "fr"

    # Extract lang from session safely
    if hasattr(request, "session"):
        lang = request.session.get("lang", "fr")
    
    dict_lang = translations.get(lang, translations.get("fr", {}))

    keys = key.split(".")
    val = dict_lang
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, key)
        else:
            val = key
            break

    # fallback to FR if missing in EN
    if val == key and lang != "fr":
        val = translations.get("fr", {})
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, key)
            else:
                val = key
                break

    if isinstance(val, str) and val != key:
        if kwargs:
            try:
                return val.format(**kwargs)
            except KeyError:
                return val
        return val

    # If not found (val == key), return default if provided
    if default is not None:
        return default

    return str(key)

# Trigger reload for locales change
