import sys
import os
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.url_cleaner import (
    extract_urls_from_text,
    extract_single_url_from_text,
    clean_url,
    clean_tracking_params,
)
from app.schemas import SubmitUrlRequest, ExternalListingSubmitRequest
from app.main import app


def test_clean_tracking_params():
    url = "https://www.leboncoin.fr/ad/ventes_immobilieres/12345?utm_source=share&utm_medium=android&id=foo&fbclid=abc123XYZ&gclid=test&ref_src=tw"
    cleaned = clean_tracking_params(url)
    assert cleaned == "https://www.leboncoin.fr/ad/ventes_immobilieres/12345?id=foo"


def test_clean_url_punctuation():
    # Surrounding brackets and trailing dot
    assert clean_url("(https://www.leboncoin.fr/ad/ventes_immobilieres/12345).") == "https://www.leboncoin.fr/ad/ventes_immobilieres/12345"
    assert clean_url("[https://www.seloger.com/annonces/123.htm],") == "https://www.seloger.com/annonces/123.htm"
    assert clean_url("<https://www.bienici.com/annonce/456>;") == "https://www.bienici.com/annonce/456"
    assert clean_url('"https://www.lefigaro.fr/annonce-789.html"') == "https://www.lefigaro.fr/annonce-789.html"


def test_extract_single_url_from_freeform_text():
    raw_user_text = """J'ai trouvé une annonce qui devrait vous intéresser sur leboncoin

 https://www.leboncoin.fr/ad/ventes_immobilieres/3180645396?utm_source=app_android
"""
    result = extract_single_url_from_text(raw_user_text)
    assert result == "https://www.leboncoin.fr/ad/ventes_immobilieres/3180645396"


def test_extract_single_url_errors():
    # Empty
    with pytest.raises(ValueError, match="ne peut pas être vide"):
        extract_single_url_from_text("")

    # No URL
    with pytest.raises(ValueError, match="Aucune URL valide"):
        extract_single_url_from_text("Voici juste du texte sans lien.")

    # Multiple URLs
    multi_text = "Regarde https://www.leboncoin.fr/ad/123 et aussi https://www.seloger.com/annonce/456"
    with pytest.raises(ValueError, match="Plusieurs URLs ont été détectées"):
        extract_single_url_from_text(multi_text)


def test_extract_urls_batch_freeform():
    batch_text = """
    Voici les liens sélectionnés :
    1. https://www.leboncoin.fr/ad/123?utm_source=app (maison)
    2. https://www.seloger.com/annonce/456!
    Et encore https://www.leboncoin.fr/ad/123 (doublon)
    3. https://www.bienici.com/annonce/789
    """
    results = extract_urls_from_text(batch_text)
    assert len(results) == 3
    assert results[0] == "https://www.leboncoin.fr/ad/123"
    assert results[1] == "https://www.seloger.com/annonce/456"
    assert results[2] == "https://www.bienici.com/annonce/789"


def test_pydantic_submit_url_request_validation():
    # Freeform text single URL
    raw = "Voici l'annonce https://www.leboncoin.fr/ad/ventes_immobilieres/999?utm_campaign=winter"
    req = SubmitUrlRequest(url=raw)
    assert req.url == "https://www.leboncoin.fr/ad/ventes_immobilieres/999"

    # Multi URLs in single model should fail validation
    with pytest.raises(ValidationError):
        SubmitUrlRequest(url="https://site.com/1 https://site.com/2")


def test_pydantic_external_listing_request_validation():
    raw = "Annonce https://www.leboncoin.fr/ad/ventes_immobilieres/555?fbclid=xyz"
    req = ExternalListingSubmitRequest(url=raw)
    assert req.url == "https://www.leboncoin.fr/ad/ventes_immobilieres/555"


def test_api_submit_url_freeform_text():
    from app.database import run_migrations, SessionLocal, get_db
    from app.api.deps import get_current_user_api
    from app.models import User

    run_migrations()

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    dummy_user = User(id=1, username="test_user", role="admin")
    app.dependency_overrides[get_current_user_api] = lambda: dummy_user
    app.dependency_overrides[get_db] = override_get_db

    client = TestClient(app)
    try:
        raw_input = "Trouvé sur LBC : https://www.leboncoin.fr/ad/ventes_immobilieres/999999999?utm_source=android"
        res = client.post("/api/v1/actions/submit-url", json={"url": raw_input, "skip_scraping": True})
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") in ("created", "already_exists", "success")
    finally:
        app.dependency_overrides.clear()
