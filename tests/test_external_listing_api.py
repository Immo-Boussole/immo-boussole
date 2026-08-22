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

    db2.close()
