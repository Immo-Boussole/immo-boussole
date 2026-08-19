#!/usr/bin/env python3
import sys
import os
import datetime
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import Listing, Source, ListingStatus, Visit, User
from app.geo import search_ban_addresses, resolve_address_details
from app.services import update_listing_address, create_listing_from_details
from app.main import app, login_required, user_required


def test_ban_search_and_resolve():
    mock_ban_response = {
        "features": [
            {
                "properties": {
                    "label": "10 Rue de la Paix 75002 Paris",
                    "name": "10 Rue de la Paix",
                    "postcode": "75002",
                    "city": "Paris",
                    "context": "75, Paris, Île-de-France",
                    "type": "housenumber",
                    "score": 0.95
                },
                "geometry": {
                    "coordinates": [2.3312, 48.8698]
                }
            },
            {
                "properties": {
                    "label": "Rue de la Paix 75002 Paris",
                    "name": "Rue de la Paix",
                    "postcode": "75002",
                    "city": "Paris",
                    "context": "75, Paris, Île-de-France",
                    "type": "street",
                    "score": 0.85
                },
                "geometry": {
                    "coordinates": [2.3315, 48.8700]
                }
            }
        ]
    }

    with patch("app.geo.httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ban_response
        mock_get.return_value = mock_response

        results = search_ban_addresses("10 rue de la paix", limit=5)
        assert len(results) == 2
        assert results[0]["label"] == "10 Rue de la Paix 75002 Paris"
        assert results[0]["precision"] == "exact"
        assert results[0]["lat"] == 48.8698
        assert results[0]["lon"] == 2.3312
        assert results[1]["precision"] == "street"

        resolved = resolve_address_details("10 Rue de la Paix 75002 Paris")
        assert resolved is not None
        assert resolved["precision"] == "exact"
        assert resolved["city"] == "Paris"
        assert resolved["postcode"] == "75002"


def test_update_listing_address_and_override_protection():
    run_migrations()
    db = SessionLocal()
    try:
        ts = datetime.datetime.now().timestamp()
        listing = Listing(
            url=f"https://example.com/ad/test-address-{ts}",
            source=Source.LEBONCOIN,
            title="Maison sympa",
            location="FausseVille (75000)",
            city="FausseVille",
            price=250000.0,
            status=ListingStatus.ACTIVE,
            manual_address_override=False
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        # Update address precisely
        with patch("app.geo.find_nearby_stations") as mock_stations, \
             patch("app.geo.calculate_station_times") as mock_times:
            mock_stations.return_value = [{"name": "Gare Centrale", "lat": 48.86, "lon": 2.33}]
            mock_times.return_value = {"walk": 10, "bike": 4, "car": 2}
            
            updated = update_listing_address(
                db=db,
                listing=listing,
                address="12 Rue des Fleurs",
                city="VraieVille",
                postal_code="75001",
                precision="exact",
                lat=48.86,
                lon=2.33
            )
            assert updated.address == "12 Rue des Fleurs"
            assert "vraieville" in updated.city.lower()
            assert updated.postal_code == "75001"
            assert "12 Rue des Fleurs" in updated.location
            assert updated.address_precision == "exact"
            assert updated.manual_address_override is True
            assert updated.nearest_sncf_station == "Gare Centrale"
            assert updated.walk_time_sncf == 10
            assert mock_stations.called

        # Simulate scraper running on same listing
        scraped_data = {
            "title": "Maison sympa MAJ",
            "price": 240000.0,
            "location": "ScraperVille",
            "city": "ScraperVille",
            "latitude": 49.0,
            "longitude": 3.0
        }
        with patch("app.services.update_listing_georisques", new_callable=AsyncMock), \
             patch("app.services.ensure_city_map_pin"), \
             patch("app.services.fetch_sncf_times_for_city"):
            res_listing, is_new = asyncio.run(create_listing_from_details(
                db, scraped_data, Source.LEBONCOIN, f"https://example.com/ad/test-address-{ts}", download_photos=False
            ))
        
        # Address & city & coordinates must remain the manually overridden values
        assert res_listing.address == "12 Rue des Fleurs"
        assert "vraieville" in res_listing.city.lower()
        assert "12 Rue des Fleurs" in res_listing.location
        assert res_listing.latitude == 48.86
        assert res_listing.longitude == 2.33
        assert res_listing.price == 240000.0  # Other fields like price are updated
    finally:
        db.close()


def test_api_address_autocomplete_endpoint():
    app.dependency_overrides[login_required] = lambda: None
    app.dependency_overrides[user_required] = lambda: None
    client = TestClient(app)

    mock_ban_response = {
        "features": [
            {
                "properties": {
                    "label": "5 Avenue des Champs-Élysées 75008 Paris",
                    "name": "5 Avenue des Champs-Élysées",
                    "postcode": "75008",
                    "city": "Paris",
                    "context": "75, Paris, Île-de-France",
                    "type": "housenumber",
                    "score": 0.98
                },
                "geometry": {
                    "coordinates": [2.312, 48.868]
                }
            }
        ]
    }

    with patch("app.geo.httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ban_response
        mock_get.return_value = mock_response

        resp = client.get("/api/geo/address-autocomplete?q=champs")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["label"] == "5 Avenue des Champs-Élysées 75008 Paris"
        assert data["results"][0]["precision"] == "exact"


def test_visit_creation_with_listing_address_propagation():
    run_migrations()
    db = SessionLocal()
    app.dependency_overrides[login_required] = lambda: None
    app.dependency_overrides[user_required] = lambda: None
    client = TestClient(app)

    try:
        ts = datetime.datetime.now().timestamp()
        listing = Listing(
            url=f"https://example.com/ad/test-visit-{ts}",
            source=Source.LEBONCOIN,
            title="Appartement cosy",
            location="Quartier inconnu",
            city="Inconnu",
            price=300000.0,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        # Post a visit with address
        with patch("app.geo.find_nearby_stations"), \
             patch("app.geo.calculate_station_times"):
            resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "step_family": "visite",
                "step": "rdv_planifie",
                "status": "programme",
                "scheduled_at": "2026-08-25T14:00:00",
                "listing_address": "8 Rue de Rivoli",
                "listing_city": "Paris",
                "listing_postal_code": "75004",
                "listing_address_precision": "exact"
            })
            assert resp.status_code == 200
            
            db.refresh(listing)
            assert listing.address == "8 Rue de Rivoli"
            assert "paris" in listing.city.lower()
            assert listing.postal_code == "75004"
            assert listing.address_precision == "exact"
            assert listing.manual_address_override is True
    finally:
        db.close()
