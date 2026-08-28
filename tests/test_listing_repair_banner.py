import sys
import os
import json
import uuid
import hashlib
import secrets
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, run_migrations
from app.models import Listing, Source, ListingStatus, User
from app.db_maintenance import get_listing_repair_issues


def test_get_listing_repair_issues_helper():
    # Listing without issues
    l1 = Listing(
        title="Maison Parfaite",
        city="Grenoble (38000)",
        location="Grenoble (38000)",
        price=300000,
        area=100,
        repair_tags=None
    )
    issues1 = get_listing_repair_issues(l1)
    assert len(issues1) == 0

    # Listing with missing location
    l2 = Listing(
        title="Annonce Sans Ville",
        city="inconnu",
        location="inconnu",
        price=150000,
        repair_tags=json.dumps(["missing_location", "incorrect_price_per_sqm"])
    )
    issues2 = get_listing_repair_issues(l2)
    assert len(issues2) == 2
    keys2 = [i["key"] for i in issues2]
    assert "missing_location" in keys2
    assert "incorrect_price_per_sqm" in keys2


def test_listing_repair_banner_html_rendering():
    run_migrations()
    db = SessionLocal()
    client = TestClient(app)

    u = str(uuid.uuid4())[:8]
    test_user = db.query(User).filter(User.username == f"test_banner_{u}").first()
    salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
    if not test_user:
        test_user = User(username=f"test_banner_{u}", password_hash=pwd_hash, salt=salt, role="admin")
        db.add(test_user)
        db.commit()

    res_login_page = client.get("/login")
    csrf_token = res_login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    res_post_login = client.post("/login", data={"username": f"test_banner_{u}", "password": "password123", "csrf_token": csrf_token}, follow_redirects=True)
    assert res_post_login.status_code == 200

    listing_repair = Listing(
        title=f"Maison Test Banner {u}",
        url=f"https://test.fr/listing-banner-{u}",
        source=Source.LEBONCOIN,
        status=ListingStatus.ACTIVE,
        price=200000,
        city="inconnu",
        location="inconnu",
        repair_tags=json.dumps(["missing_location", "incorrect_price_per_sqm"])
    )
    db.add(listing_repair)
    db.commit()
    db.refresh(listing_repair)

    res = client.get(f"/listings/{listing_repair.id}")
    assert res.status_code == 200
    html = res.text

    assert "zone-repair-banner" in html
    assert "Localisation manquante" in html
    assert "Prix/m" in html
    assert "Corriger l'annonce" in html
    assert "openEditModal()" in html

    db.close()
