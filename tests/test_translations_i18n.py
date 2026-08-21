import sys
import os
import pytest
from starlette.requests import Request

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.translations import get_text, detect_client_language, get_available_languages, load_translations

def make_request(headers=None, session=None):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "session": session or {}
    }
    return Request(scope)

def test_available_languages_discovery():
    load_translations()
    langs = get_available_languages()
    codes = [l["code"] for l in langs]
    assert "en" in codes
    assert "fr" in codes

def test_language_detection_default_en():
    req = make_request()
    assert detect_client_language(req) == "en"

def test_language_detection_accept_language_fr():
    req = make_request(headers={"accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"})
    assert detect_client_language(req) == "fr"

def test_language_detection_session_override():
    req = make_request(headers={"accept-language": "fr-FR,fr;q=0.9"}, session={"lang": "en"})
    assert detect_client_language(req) == "en"

def test_translation_get_text_en():
    req = make_request(session={"lang": "en"})
    txt = get_text(req, "nav.dashboard")
    assert txt == "Dashboard"

def test_translation_get_text_fr():
    req = make_request(session={"lang": "fr"})
    txt = get_text(req, "nav.dashboard")
    assert txt in ["Tableau de bord", "Dashboard"]

