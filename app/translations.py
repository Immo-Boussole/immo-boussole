import json
import os
import glob
from fastapi import Request

LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locales")

translations: dict = {}
_translations_mtime: dict = {}

LANGUAGE_NAMES = {
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "it": "Italiano",
    "pt": "Português",
    "nl": "Nederlands"
}


def _get_locale_mtime(lang: str) -> float:
    """Return the file modification time for a locale file, or 0 if missing."""
    path = os.path.join(LOCALES_DIR, f"{lang}.json")
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def get_available_languages() -> list:
    """Returns a list of available locales detected in the locales directory."""
    langs = []
    if os.path.exists(LOCALES_DIR):
        for filepath in glob.glob(os.path.join(LOCALES_DIR, "*.json")):
            code = os.path.splitext(os.path.basename(filepath))[0]
            langs.append({
                "code": code,
                "name": LANGUAGE_NAMES.get(code, code.upper())
            })
    return langs or [{"code": "en", "name": "English"}, {"code": "fr", "name": "Français"}]


def load_translations():
    """Load (or reload) all locale JSON files found in locales/ into the in-memory cache."""
    global translations, _translations_mtime
    if not os.path.exists(LOCALES_DIR):
        print(f"[i18n] Warning: {LOCALES_DIR} not found.")
        return

    discovered_files = glob.glob(os.path.join(LOCALES_DIR, "*.json"))
    for filepath in discovered_files:
        lang = os.path.splitext(os.path.basename(filepath))[0]
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                translations[lang] = json.load(f)
            _translations_mtime[lang] = os.path.getmtime(filepath)
        except Exception as e:
            print(f"[i18n] Error loading {filepath}: {e}")
            if lang not in translations:
                translations[lang] = {}


def _reload_if_changed():
    """Reload any locale file whose mtime has changed since last load."""
    if not os.path.exists(LOCALES_DIR):
        return

    discovered_files = glob.glob(os.path.join(LOCALES_DIR, "*.json"))
    for filepath in discovered_files:
        lang = os.path.splitext(os.path.basename(filepath))[0]
        current_mtime = _get_locale_mtime(lang)
        if current_mtime != _translations_mtime.get(lang, 0.0):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    translations[lang] = json.load(f)
                _translations_mtime[lang] = current_mtime
                print(f"[i18n] Reloaded translations for '{lang}'")
            except Exception as e:
                print(f"[i18n] Error reloading {filepath}: {e}")


# Load once at startup
load_translations()


def detect_client_language(request: Request) -> str:
    """
    Detects the best matching language for the user:
    1. Session preference if explicitly set.
    2. Accept-Language HTTP header from browser.
    3. Defaults to 'en'.
    """
    if hasattr(request, "session") and request.session.get("lang"):
        return request.session.get("lang")

    accept_header = request.headers.get("accept-language", "").lower()
    if accept_header:
        # Check available languages against Accept-Language
        available_codes = list(translations.keys()) or ["en", "fr"]
        # Extract quality weights or split by comma
        for part in accept_header.split(","):
            raw_lang = part.split(";")[0].strip()
            primary_lang = raw_lang.split("-")[0]
            if primary_lang in available_codes:
                return primary_lang

    return "en"


def get_text(request: Request, key: str, default: str = None, **kwargs) -> str:
    """
    Get a translated string based on the detected user language.
    Defaults to English ('en') with fallback to English ('en') and French ('fr').
    """
    _reload_if_changed()

    lang = detect_client_language(request)
    dict_lang = translations.get(lang, translations.get("en", {}))

    keys = key.split(".")
    val = dict_lang
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, key)
        else:
            val = key
            break

    # Fallback to English if missing in current language
    if (val == key or not isinstance(val, str)) and lang != "en":
        val = translations.get("en", {})
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, key)
            else:
                val = key
                break

    # Fallback to French if still missing
    if (val == key or not isinstance(val, str)) and lang != "fr":
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

    if default is not None:
        return default

    return str(key)
