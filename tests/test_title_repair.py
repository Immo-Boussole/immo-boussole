import pytest
import os
import json
from unittest.mock import patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.models import Base, Listing, ListingStatus, Source, User
from app.services import (
    is_error_or_generic_title,
    clean_extracted_title,
    extract_title_from_url_slug,
    extract_title_from_description,
    generate_synthetic_title_from_listing,
    repair_listing_title,
)
from app.db_maintenance import identify_problems, GENERIC_TITLE_FIGARO
from app.main import app
from app.database import get_db


@pytest.fixture
def db_session(tmp_path):
    db_file = tmp_path / "test_title_repair.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_is_error_or_generic_title_comprehensive():
    # True for error and generic titles
    assert is_error_or_generic_title("Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403") is True
    assert is_error_or_generic_title("Annonce (https://www.leboncoin.fr/ad/123456789)") is True
    assert is_error_or_generic_title("Annonce (http://test.com/ad) - Erreur 500") is True
    assert is_error_or_generic_title("Annonce Le Figaro") is True
    assert is_error_or_generic_title("leboncoin.fr") is True
    assert is_error_or_generic_title("Erreur 403") is True
    assert is_error_or_generic_title("Error 404") is True
    assert is_error_or_generic_title("Sans titre") is True
    assert is_error_or_generic_title("Bien immobilier") is True
    assert is_error_or_generic_title("") is True
    assert is_error_or_generic_title(None) is True

    # False for valid titles
    assert is_error_or_generic_title("Maison 5 pièces 120m²") is False
    assert is_error_or_generic_title("Superbe appartement T3 avec balcon - Lyon") is False
    assert is_error_or_generic_title("Villa contemporaine avec piscine") is False


def test_clean_extracted_title():
    assert clean_extracted_title("  Maison 4 pièces - Leboncoin  ") == "Maison 4 pièces"
    assert clean_extracted_title("Appartement T2 lumineux | SeLoger") == "Appartement T2 lumineux"
    assert clean_extracted_title("Belle demeure en pierre - Le Figaro Immobilier") == "Belle demeure en pierre"
    assert clean_extracted_title('&quot;Maison de ville&quot;') == "Maison de ville"


def test_extract_title_from_url_slug():
    url_lbc = "https://www.leboncoin.fr/ad/ventes_immobilieres/maison-5-pieces-saint-etienne-2881234567"
    assert extract_title_from_url_slug(url_lbc) == "Maison 5 pieces saint etienne"

    url_seloger = "https://www.seloger.com/annonces/achat/appartement/paris-15eme-75/214309485.htm"
    assert extract_title_from_url_slug(url_seloger) == "Paris 15eme 75"

    url_numeric = "https://www.leboncoin.fr/ad/ventes_immobilieres/2881234567"
    assert extract_title_from_url_slug(url_numeric) is None


def test_extract_title_from_description():
    desc = """
    À VENDRE : Superbe maison contemporaine de 140m² avec jardin clos.
    Cette maison comprend une grande pièce de vie lumineuse...
    """
    assert extract_title_from_description(desc) == "Superbe maison contemporaine de 140m² avec jardin clos."

    desc_emoji = "🏡 Magnifique appartement 3 pièces au calme à Saint-Chamond"
    assert extract_title_from_description(desc_emoji) == "Magnifique appartement 3 pièces au calme à Saint-Chamond"


def test_generate_synthetic_title_from_listing():
    l1 = Listing(
        property_type="Maison",
        rooms=5,
        area=125.0,
        city="Saint-Étienne"
    )
    assert generate_synthetic_title_from_listing(l1) == "Maison 5 pièces 125 m² - Saint-Étienne"

    l2 = Listing(
        property_type="Appartement",
        rooms=2,
        area=45.5,
        city="Lyon (69007)"
    )
    assert generate_synthetic_title_from_listing(l2) == "Appartement 2 pièces 45.5 m² - Lyon"

    l3 = Listing(
        description_text="Vente d'une maison de plain-pied...",
        city="Grenoble"
    )
    assert generate_synthetic_title_from_listing(l3) == "Maison - Grenoble"


@pytest.mark.anyio
async def test_repair_listing_title_via_slug_when_403(db_session):
    listing = Listing(
        external_id="lbc_2881234567",
        url="https://www.leboncoin.fr/ad/ventes_immobilieres/maison-5-pieces-saint-etienne-2881234567",
        original_url="https://www.leboncoin.fr/ad/ventes_immobilieres/maison-5-pieces-saint-etienne-2881234567",
        title="Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403",
        status=ListingStatus.ACTIVE
    )
    db_session.add(listing)
    db_session.commit()

    with patch("app.services.fetch_basic_metadata", new_callable=AsyncMock) as mock_meta, \
         patch("app.main._resolve_scraper", return_value=(Source.LEBONCOIN, None)):
        mock_meta.return_value = {"title": "Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403"}
        
        repaired, new_title = await repair_listing_title(listing, db_session)
        assert repaired is True
        assert new_title == "Maison 5 pieces saint etienne"
        assert listing.title == "Maison 5 pieces saint etienne"


@pytest.mark.anyio
async def test_repair_listing_title_via_attributes_when_403_and_no_slug(db_session):
    listing = Listing(
        external_id="lbc_99999",
        url="https://www.leboncoin.fr/ad/ventes_immobilieres/99999",
        original_url="https://www.leboncoin.fr/ad/ventes_immobilieres/99999",
        title="Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403",
        property_type="Appartement",
        rooms=3,
        area=68.0,
        city="Saint-Chamond",
        status=ListingStatus.ACTIVE
    )
    db_session.add(listing)
    db_session.commit()

    with patch("app.services.fetch_basic_metadata", new_callable=AsyncMock) as mock_meta, \
         patch("app.main._resolve_scraper", return_value=(Source.LEBONCOIN, None)):
        mock_meta.return_value = {"title": "Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403"}

        repaired, new_title = await repair_listing_title(listing, db_session)
        assert repaired is True
        assert new_title == "Appartement 3 pièces 68 m² - Saint-Chamond"
        assert listing.title == "Appartement 3 pièces 68 m² - Saint-Chamond"


@pytest.mark.anyio
async def test_repair_listing_title_via_fresh_scrape(db_session):
    listing = Listing(
        external_id="lbc_11111",
        url="https://www.leboncoin.fr/ad/ventes_immobilieres/11111",
        original_url="https://www.leboncoin.fr/ad/ventes_immobilieres/11111",
        title="Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403",
        status=ListingStatus.ACTIVE
    )
    db_session.add(listing)
    db_session.commit()

    with patch("app.services.fetch_basic_metadata", new_callable=AsyncMock) as mock_meta, \
         patch("app.main._resolve_scraper", return_value=(Source.LEBONCOIN, None)):
        mock_meta.return_value = {
            "title": "Maison contemporaine 6 pièces avec piscine",
            "description_text": "Superbe villa...",
            "price": 380000.0,
            "city": "Saint-Galmier"
        }

        repaired, new_title = await repair_listing_title(listing, db_session)
        assert repaired is True
        assert new_title == "Maison contemporaine 6 pièces avec piscine"
        assert listing.title == "Maison contemporaine 6 pièces avec piscine"
        assert listing.price == 380000.0
        assert listing.city == "Saint-Galmier"


def test_identify_problems_includes_error_403_titles(db_session):
    l_error = Listing(
        external_id="lbc_403",
        url="https://example.com/403",
        title="Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403",
        status=ListingStatus.ACTIVE
    )
    l_ok = Listing(
        external_id="lbc_ok",
        url="https://example.com/ok",
        title="Superbe Maison 120m²",
        status=ListingStatus.ACTIVE
    )
    db_session.add_all([l_error, l_ok])
    db_session.commit()

    problems = identify_problems(db_session)
    assert GENERIC_TITLE_FIGARO in problems
    assert l_error.id in problems[GENERIC_TITLE_FIGARO]["ids"]
    assert l_ok.id not in problems[GENERIC_TITLE_FIGARO]["ids"]


def test_rescrape_endpoint_repairs_title(db_session):
    from app.main import user_required

    listing = Listing(
        external_id="lbc_endpoint_test",
        url="https://www.leboncoin.fr/ad/ventes_immobilieres/superbe-appartement-t4-terrasse-12345",
        original_url="https://www.leboncoin.fr/ad/ventes_immobilieres/superbe-appartement-t4-terrasse-12345",
        title="Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403",
        city="Lyon",
        status=ListingStatus.ACTIVE
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[user_required] = lambda: {"user_id": 1, "username": "admin", "role": "admin"}
    try:
        client = TestClient(app)
        with patch("app.main._resolve_scraper", return_value=(Source.LEBONCOIN, None)), \
             patch("app.services.fetch_basic_metadata", new_callable=AsyncMock) as mock_meta:
            mock_meta.return_value = {"title": "Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403"}

            resp = client.post(f"/api/listings/{listing.id}/rescrape")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "updated"
            assert data["scraping_success"] is True
            assert data["title"] == "Superbe appartement t4 terrasse"
            
            db_session.refresh(listing)
            assert listing.title == "Superbe appartement t4 terrasse"
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(user_required, None)
