import json
import os
from fastapi import Request

LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locales")

translations = {}

def load_translations():
    global translations
    if not os.path.exists(LOCALES_DIR):
        print(f"[i18n] Warnings: {LOCALES_DIR} not found.")
        return

    for lang in ["fr", "en"]:
        path = os.path.join(LOCALES_DIR, f"{lang}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                translations[lang] = json.load(f)
        else:
            translations[lang] = {}

# Load them once at startup
load_translations()

def get_text(request: Request, key: str, **kwargs) -> str:
    """
    Get a translated string based on the current session language.
    `key` can be nested like 'nav.dashboard'.
    """
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

    if isinstance(val, str):
        if kwargs:
            try:
                return val.format(**kwargs)
            except KeyError:
                return val
        return val

    return str(key)
