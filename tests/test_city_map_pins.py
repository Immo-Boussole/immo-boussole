import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import Listing, MapPin, Source, ListingStatus
from app.geo import get_commune_coordinates
from app.services import ensure_city_map_pin


def test_get_commune_coordinates_with_zip():
    mock_api_response = [
        {
            "nom": "Vienne",
            "code": "38544",
            "codeDepartement": "38",
            "codesPostaux": ["38200"],
            "centre": {
                "type": "Point",
                "coordinates": [4.878, 45.525]
            }
        }
    ]

    with patch("app.geo.httpx.get") as mock_get:
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = mock_api_response
        mock_get.return_value = mock_res

        coords = get_commune_coordinates("Vienne (38200)")
        assert coords is not None
        lat, lon = coords
        assert pytest.approx(lat, 0.001) == 45.525
        assert pytest.approx(lon, 0.001) == 4.878


def test_ensure_city_map_pin_priority_existing_listing():
    import time
    run_migrations()
    db = SessionLocal()
    try:
        # Create an active listing in Vienne with known coords
        listing = Listing(
            url=f"https://example.com/ad/test-vienne-pin-{time.time()}",
            source=Source.LEBONCOIN,
            title="Appartement Vienne",
            city="Vienne (38200)",
            location="Vienne (38200)",
            latitude=45.524,
            longitude=4.875,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()

        # Clean any preexisting pins for Vienne in test DB
        preexisting = db.query(MapPin).filter(MapPin.title.ilike("%vienne%")).all()
        for p in preexisting:
            db.delete(p)
        db.commit()

        # Call ensure_city_map_pin
        with patch("app.services.get_commune_coordinates") as mock_geo_coord:
            ensure_city_map_pin("Vienne", db)
            # Should NOT have called geo.api.gouv.fr because listing coordinates exist (Priority 1)
            assert not mock_geo_coord.called

        pin = db.query(MapPin).filter(MapPin.pin_type == "city", MapPin.title.ilike("%vienne%")).first()
        assert pin is not None
        assert pytest.approx(pin.lat, 0.001) == 45.524
        assert pytest.approx(pin.lon, 0.001) == 4.875

        # Calling again should not duplicate
        ensure_city_map_pin("Vienne (38200)", db)
        count = db.query(MapPin).filter(MapPin.pin_type == "city", MapPin.title.ilike("%vienne%")).count()
        assert count == 1
    finally:
        db.close()


def test_ensure_city_map_pin_fallback_geo_api():
    run_migrations()
    db = SessionLocal()
    try:
        # Clean any pins or listings for TestVille
        for p in db.query(MapPin).filter(MapPin.title.ilike("%testville%")).all():
            db.delete(p)
        for l in db.query(Listing).filter(Listing.city.ilike("%testville%")).all():
            db.delete(l)
        db.commit()

        with patch("app.services.get_commune_coordinates", return_value=(45.339, 5.055)):
            ensure_city_map_pin("TestVille (38270)", db)

        pin = db.query(MapPin).filter(MapPin.pin_type == "city", MapPin.title.ilike("%testville%")).first()
        assert pin is not None
        assert pytest.approx(pin.lat, 0.001) == 45.339
        assert pytest.approx(pin.lon, 0.001) == 5.055
    finally:
        db.close()
