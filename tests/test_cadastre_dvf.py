import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import Listing, User, ListingStatus, Source
from app.geo import fetch_cadastral_parcel
from app.main import app, login_required
from app.mcp_server import tool_get_listing_details, tool_search_listings


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    run_migrations()


def test_fetch_cadastral_parcel_with_mock():
    mock_apicarto_response = {
        "features": [
            {
                "properties": {
                    "id": "33063000AB0123",
                    "code_insee": "33063",
                    "prefixe": "000",
                    "section": "AB",
                    "numero": "0123",
                    "contenance": 450
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[ -0.579, 44.837 ], [ -0.578, 44.837 ], [ -0.578, 44.836 ], [ -0.579, 44.836 ], [ -0.579, 44.837 ]]]
                }
            }
        ]
    }

    with patch("app.geo.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_apicarto_response
        mock_get.return_value = mock_resp

        res = fetch_cadastral_parcel(lat=44.837, lon=-0.579, insee_code="33063")
        assert res is not None
        assert res["parcel_id"] == "33063000AB0123"
        assert res["section"] == "AB"
        assert res["numero"] == "0123"
        assert "explore.data.gouv.fr/fr/immobilier" in res["dvf_url"]


def test_cadastre_lookup_api():
    client = TestClient(app)
    app.dependency_overrides[login_required] = lambda: {"username": "testuser", "role": "admin"}

    mock_apicarto_response = {
        "features": [
            {
                "properties": {
                    "id": "75101000AA0042",
                    "code_insee": "75101",
                    "section": "AA",
                    "numero": "0042",
                    "contenance": 200
                }
            }
        ]
    }

    with patch("app.geo.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_apicarto_response
        mock_get.return_value = mock_resp

        response = client.get("/api/geo/cadastre-lookup?lat=48.86&lon=2.33")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["parcel"]["parcel_id"] == "75101000AA0042"

    app.dependency_overrides.clear()


def test_listing_update_cadastral_parcel():
    db = SessionLocal()
    client = TestClient(app)
    app.dependency_overrides[login_required] = lambda: {"username": "testuser", "role": "admin"}

    test_listing = Listing(
        title="Appartement Test Cadastre",
        url="https://example.com/test-cadastre-1",
        price=250000.0,
        city="Lyon",
        latitude=45.75,
        longitude=4.85,
        status=ListingStatus.ACTIVE,
        source=Source.MANUAL,
        cadastral_parcel=None
    )
    db.add(test_listing)
    db.commit()
    db.refresh(test_listing)
    listing_id = test_listing.id
    db.close()

    try:
        # Update with cadastral parcel
        res = client.put(f"/api/listings/{listing_id}", json={
            "cadastral_parcel": "69002000AC0088"
        })
        assert res.status_code == 200

        # Query with fresh session
        db_check = SessionLocal()
        updated_listing = db_check.query(Listing).filter(Listing.id == listing_id).first()
        assert updated_listing is not None
        assert updated_listing.cadastral_parcel == "69002000AC0088"

        # Check MCP tool
        mcp_details = json.loads(tool_get_listing_details(listing_id))
        assert mcp_details["cadastral_parcel"] == "69002000AC0088"
        assert "explore.data.gouv.fr" in mcp_details["dvf_url"]
        db_check.close()
    finally:
        db_clean = SessionLocal()
        to_del = db_clean.query(Listing).filter(Listing.id == listing_id).first()
        if to_del:
            db_clean.delete(to_del)
            db_clean.commit()
        db_clean.close()
        app.dependency_overrides.clear()


def test_admin_settings_public_services_toggles():
    client = TestClient(app)
    from app.main import admin_required
    app.dependency_overrides[admin_required] = lambda: {"username": "admin", "role": "admin"}
    app.dependency_overrides[login_required] = lambda: {"username": "admin", "role": "admin"}

    try:
        toggles = {"dvf": True, "cadastre": True, "georisques": False}
        res = client.post("/api/admin/settings", json={
            "public_services_json": json.dumps(toggles)
        })
        assert res.status_code == 200

        # Query GET /api/admin/settings
        res_get = client.get("/api/admin/settings")
        assert res_get.status_code == 200
        data = res_get.json()
        assert data.get("public_services_json") is not None
        saved_services = json.loads(data["public_services_json"]) if isinstance(data["public_services_json"], str) else data["public_services_json"]
        assert saved_services.get("dvf") is True
        assert saved_services.get("cadastre") is True
        assert saved_services.get("georisques") is False

        # Query directly from DB
        db_check = SessionLocal()
        from app.models import GlobalSettings
        gs = db_check.query(GlobalSettings).first()
        assert gs is not None
        assert gs.public_services_json is not None
        db_services = json.loads(gs.public_services_json)
        assert db_services.get("dvf") is True
        assert db_services.get("cadastre") is True
        assert db_services.get("georisques") is False
        db_check.close()
    finally:
        app.dependency_overrides.clear()
