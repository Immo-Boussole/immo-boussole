#!/usr/bin/env python3
"""
Unit test for external listing API endpoint (/api/v1/actions/submit-external-listing).
"""
import sys
import os
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.database import SessionLocal, run_migrations
from app.models import User, Listing, Source

client = TestClient(app)

def test_submit_external_listing():
    run_migrations()
    db = SessionLocal()
    
    # Ensure test user with API key exists
    import hashlib
    raw_key = "test_browser_extension_api_key"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    
    user = db.query(User).filter(User.username == "test_ext_user").first()
    if not user:
        user = User(
            username="test_ext_user",
            password_hash=b"fakehashedpassword",
            salt=b"fakesalt",
            role="admin",
            api_key_hash=key_hash,
            can_create_api_key=True
        )
        db.add(user)
        db.commit()
    else:
        user.api_key_hash = key_hash
        db.commit()
    db.close()

    headers = {
        "Authorization": f"Bearer {raw_key}"
    }

    payload = {
        "url": "https://www.leboncoin.fr/ad/ventes_immobilieres/999999999",
        "title": "Bel appartement 3 pièces Lyon 6",
        "price": 350000.0,
        "area": 75.0,
        "rooms": 3,
        "bedrooms": 2,
        "city": "Lyon",
        "postal_code": "69006",
        "location": "Lyon 6ème",
        "description": "Superbe appartement rénové au cœur du 6ème arrondissement.",
        "photos": ["https://img.leboncoin.fr/1.jpg", "https://img.leboncoin.fr/2.jpg"],
        "source": "leboncoin"
    }

    res = client.post("/api/v1/actions/submit-external-listing", json=payload, headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "success"
    assert "data" in data
    assert "listing_id" in data["data"]

    # Verify DB insertion
    db2 = SessionLocal()
    listing = db2.query(Listing).filter(Listing.url == payload["url"]).first()
    assert listing is not None
    assert listing.title == "Bel appartement 3 pièces Lyon 6"
    assert listing.price == 350000.0
    assert listing.price_per_sqm == 4666.67
    assert listing.source == Source.LEBONCOIN.value
    from app.models import ListingStatus
    assert listing.status == ListingStatus.NEW

    # Test re-submitting the same listing (already exists)
    res2 = client.post("/api/v1/actions/submit-external-listing", json=payload, headers=headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "success"
    assert data2["data"]["already_exists"] is True
    assert data2["data"]["listing_id"] == listing.id

    # Test unauthenticated access to /listings/{id} redirects with ?next=
    res_unauth = client.get(f"/listings/{listing.id}", follow_redirects=False)
    assert res_unauth.status_code == 307
    assert "next=" in res_unauth.headers.get("location", "")

    # Test SeLoger canonical matching (short vs long URL with params and hash)
    seloger_short = "https://www.seloger.com/annonce/achat/auvergne-rhone-alpes/isere-38/saint-clair-du-rhone-38370/269W7APVLTZA"
    seloger_long = "https://www.seloger.com/annonce/achat/auvergne-rhone-alpes/isere-38/saint-clair-du-rhone-38370/269W7APVLTZA?serp_view=list&search=classifiedBusiness%3DProfessional%26distributionTypes%3DBuy#ln=classified_search_results"
    
    # 1. Insert short URL
    res_sl1 = client.post("/api/v1/actions/submit-external-listing", json={
        "url": seloger_short,
        "title": "Maison 5 pièces 140 m² Saint-Clair-du-Rhône",
        "price": 320000.0,
        "area": 140.0,
        "rooms": 5,
        "city": "Saint-Clair-du-Rhône",
        "source": "seloger"
    }, headers=headers)
    assert res_sl1.status_code == 200
    sl_id = res_sl1.json()["data"]["listing_id"]

    # 2. Check existence using the long URL with query params & hash
    res_check = client.get(f"/api/v1/actions/check-listing?url={seloger_long}", headers=headers)
    assert res_check.status_code == 200
    check_data = res_check.json()
    assert check_data["exists"] is True
    assert check_data["listing_id"] == sl_id

    # 3. Submit long URL directly -> should detect already_exists
    res_sl2 = client.post("/api/v1/actions/submit-external-listing", json={
        "url": seloger_long,
        "title": "Maison 5 pièces 140 m² Saint-Clair-du-Rhône",
        "price": 320000.0,
        "area": 140.0
    }, headers=headers)
    assert res_sl2.status_code == 200
    assert res_sl2.json()["data"]["already_exists"] is True
    assert res_sl2.json()["data"]["listing_id"] == sl_id

    db2.close()
