import pytest
import os
import json
from unittest.mock import patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, Listing, ListingStatus, Source
from app.services import (
    is_error_or_generic_title,
    has_valid_local_photos,
    repair_listing_photos,
    create_listing_from_details
)
from app.db_maintenance import identify_problems, MISSING_PHOTOS, repair_listings_batch_task


@pytest.fixture
def db_session(tmp_path):
    db_file = tmp_path / "test_photos_title.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_is_error_or_generic_title():
    # Valid titles
    assert is_error_or_generic_title("Maison 5 pièces 120m²") is False
    assert is_error_or_generic_title("Superbe appartement T3 avec balcon") is False
    assert is_error_or_generic_title("Villa contemporaine vue mer") is False

    # Error / Generic titles
    assert is_error_or_generic_title("") is True
    assert is_error_or_generic_title(None) is True
    assert is_error_or_generic_title("Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403") is True
    assert is_error_or_generic_title("Annonce (https://www.leboncoin.fr/ad/123456789)") is True
    assert is_error_or_generic_title("Annonce (http://test.com/ad)") is True
    assert is_error_or_generic_title("Annonce Le Figaro") is True
    assert is_error_or_generic_title("leboncoin.fr") is True
    assert is_error_or_generic_title("Erreur 500") is True
    assert is_error_or_generic_title("Page Error 404") is True


def test_create_listing_preserves_good_title_and_data_on_scrape_error(db_session):
    import asyncio
    # Initial good listing
    listing = Listing(
        external_id="lbc_12345",
        url="https://www.leboncoin.fr/ad/ventes_immobilieres/12345",
        original_url="https://www.leboncoin.fr/ad/ventes_immobilieres/12345",
        title="Maison de village 120m² 4 chambres",
        description_text="Belle maison rénovée...",
        price=245000.0,
        status=ListingStatus.ACTIVE
    )
    db_session.add(listing)
    db_session.commit()

    # Incoming scrape with 403 error fallback
    bad_details = {
        "external_id": "lbc_12345",
        "title": "Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403",
        "description_text": "",
        "price": 0.0
    }

    updated, is_new = asyncio.run(create_listing_from_details(
        db=db_session,
        details=bad_details,
        source=Source.LEBONCOIN,
        original_url=listing.url,
        download_photos=False
    ))

    assert is_new is False
    assert updated.id == listing.id
    # Title, description, and price must NOT have been overwritten
    assert updated.title == "Maison de village 120m² 4 chambres"
    assert updated.description_text == "Belle maison rénovée..."
    assert updated.price == 245000.0


def test_has_valid_local_photos(tmp_path):
    dummy_photo = tmp_path / "photo_0.webp"
    dummy_photo.write_bytes(b"dummy image data")

    l_empty = Listing(photos_local=None)
    assert has_valid_local_photos(l_empty) is False

    l_empty_json = Listing(photos_local="[]")
    assert has_valid_local_photos(l_empty_json) is False

    l_nonexistent = Listing(photos_local=json.dumps(["/non/existent/path.webp"]))
    assert has_valid_local_photos(l_nonexistent) is False

    l_valid = Listing(photos_local=json.dumps([str(dummy_photo)]))
    assert has_valid_local_photos(l_valid) is True


def test_identify_problems_missing_photos(db_session, tmp_path):
    valid_photo = tmp_path / "valid.jpg"
    valid_photo.write_bytes(b"valid content")

    l_good = Listing(
        external_id="ext_good",
        url="https://example.com/1",
        title="Good listing",
        status=ListingStatus.ACTIVE,
        photos_local=json.dumps([str(valid_photo)])
    )
    l_missing = Listing(
        external_id="ext_missing",
        url="https://example.com/2",
        title="Missing photo listing",
        status=ListingStatus.ACTIVE,
        photos_local=None
    )
    db_session.add_all([l_good, l_missing])
    db_session.commit()

    problems = identify_problems(db_session)
    assert MISSING_PHOTOS in problems
    assert problems[MISSING_PHOTOS]["count"] == 1
    assert l_missing.id in problems[MISSING_PHOTOS]["ids"]
    assert l_good.id not in problems[MISSING_PHOTOS]["ids"]


def test_repair_listing_photos_from_original_urls(db_session, tmp_path):
    import asyncio
    local_photo = tmp_path / "photo_0.webp"
    local_photo.write_bytes(b"downloaded bytes")

    listing = Listing(
        external_id="ext_repair",
        url="https://example.com/repair",
        title="Repair Listing",
        status=ListingStatus.ACTIVE,
        original_photo_urls=json.dumps(["https://img.leboncoin.fr/ad-image/123.jpg"]),
        photos_local=None
    )
    db_session.add(listing)
    db_session.commit()

    with patch("app.services.download_listing_photos", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = [str(local_photo)]
        success = asyncio.run(repair_listing_photos(listing, db_session))
        assert success is True
        mock_dl.assert_called_once_with(listing.id, ["https://img.leboncoin.fr/ad-image/123.jpg"])
        assert json.loads(listing.photos_local) == [str(local_photo)]
