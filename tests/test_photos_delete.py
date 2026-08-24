import sys
import os
import uuid
import hashlib
import secrets
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app, failed_logins, photos_to_json, json_to_photos
from app.database import SessionLocal, run_migrations
from app.models import Listing, Source, ListingStatus, User


def setup_test_user(db, username="test_photo_user", role="admin"):
    failed_logins.clear()
    test_user = db.query(User).filter(User.username == username).first()
    salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
    if not test_user:
        test_user = User(username=username, password_hash=pwd_hash, salt=salt, role=role)
        db.add(test_user)
        db.commit()
    else:
        test_user.password_hash = pwd_hash
        test_user.salt = salt
        test_user.role = role
        db.commit()
    return test_user


def test_bulk_delete_photos():
    run_migrations()
    db = SessionLocal()
    u = str(uuid.uuid4())[:8]

    # Create dummy photo paths
    photos_list = [
        f"static/media/test_p1_{u}.jpg",
        f"static/media/test_p2_{u}.jpg",
        f"static/media/test_p3_{u}.jpg",
        f"static/media/test_p4_{u}.jpg"
    ]

    listing = Listing(
        title=f"Maison Test Photo Delete {u}",
        url=f"https://test.immo/listing-photo-{u}",
        source=Source.MANUAL,
        status=ListingStatus.ACTIVE,
        price=250000,
        city="Annecy",
        photos_local=photos_to_json(photos_list)
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    setup_test_user(db, username=f"photo_admin_{u}", role="admin")

    client = TestClient(app)
    # Login via /login with CSRF
    res_login_page = client.get("/login")
    csrf_token = res_login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    res_post_login = client.post(
        "/login",
        data={"username": f"photo_admin_{u}", "password": "password123", "csrf_token": csrf_token},
        follow_redirects=True
    )
    assert res_post_login.status_code == 200

    # Delete photos at index 1 and 3 (p2 and p4)
    del_resp = client.request("DELETE", f"/api/listings/{listing.id}/photos", json={"indices": [1, 3]})
    assert del_resp.status_code == 200
    data = del_resp.json()
    assert data["status"] == "deleted"
    assert data["deleted_count"] == 2
    assert data["remaining_count"] == 2

    # Check database
    db.refresh(listing)
    remaining_photos = json_to_photos(listing.photos_local)
    assert len(remaining_photos) == 2
    assert remaining_photos[0] == f"static/media/test_p1_{u}.jpg"
    assert remaining_photos[1] == f"static/media/test_p3_{u}.jpg"

    # Also test POST /bulk-delete
    del_resp2 = client.post(f"/api/listings/{listing.id}/photos/bulk-delete", json={"indices": [0]})
    assert del_resp2.status_code == 200
    db.refresh(listing)
    remaining_photos2 = json_to_photos(listing.photos_local)
    assert len(remaining_photos2) == 1
    assert remaining_photos2[0] == f"static/media/test_p3_{u}.jpg"
