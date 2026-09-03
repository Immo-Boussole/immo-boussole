import sys
import os
import unittest
import secrets
import hashlib
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app, login_required, user_required, admin_required
from app.api.deps import get_current_user_api
from app.database import SessionLocal, run_migrations
from app.models import User, Listing, ListingStatus, Source


class TestSourcePreviewProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        cls.db = SessionLocal()
        cls.client = TestClient(app)

        # Setup test admin user
        cls.admin_user = cls.db.query(User).filter(User.username == "test_proxy_admin").first()
        salt = secrets.token_bytes(16)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
        if not cls.admin_user:
            cls.admin_user = User(
                username="test_proxy_admin",
                password_hash=pwd_hash,
                salt=salt,
                role="admin"
            )
            cls.db.add(cls.admin_user)
            cls.db.commit()
        else:
            cls.admin_user.password_hash = pwd_hash
            cls.admin_user.salt = salt
            cls.admin_user.role = "admin"
            cls.db.commit()

        app.dependency_overrides[login_required] = lambda: {"username": "test_proxy_admin", "role": "admin"}
        app.dependency_overrides[user_required] = lambda: {"username": "test_proxy_admin", "role": "admin"}
        app.dependency_overrides[admin_required] = lambda: {"username": "test_proxy_admin", "role": "admin"}
        app.dependency_overrides[get_current_user_api] = lambda: cls.admin_user

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()

    def test_01_preview_not_found(self):
        res = self.client.get("/api/listings/999999/source-preview-html")
        self.assertEqual(res.status_code, 404)

    def test_02_preview_fallback_when_invalid_url(self):
        token = secrets.token_hex(6)
        listing = Listing(
            title="Appartement apercu test",
            description_text="Superbe appartement 3 pièces lumineux au calme.",
            url=f"not_a_valid_url_{token}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            price=245000,
            area=68,
            rooms=3,
            photos_local=json.dumps(["/static/media/test_photo.jpg"])
        )
        self.db.add(listing)
        self.db.commit()
        self.db.refresh(listing)

        res = self.client.get(f"/api/listings/{listing.id}/source-preview-html")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("x-frame-options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("content-security-policy"), "frame-ancestors 'self'")
        self.assertIn("Appartement apercu test", res.text)
        self.assertIn("Superbe appartement 3 pièces lumineux", res.text)
        self.assertIn("245 000 €", res.text)

    def test_03_preview_with_simulated_html(self):
        token = secrets.token_hex(6)
        listing = Listing(
            title="Maison de village test",
            description_text="Maison ancienne rénovée.",
            url=f"https://example.com/test-ad-{token}",
            source=Source.LEBONCOIN,
            status=ListingStatus.ACTIVE,
            price=310000,
            area=110
        )
        self.db.add(listing)
        self.db.commit()
        self.db.refresh(listing)

        res = self.client.get(f"/api/listings/{listing.id}/source-preview-html")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("x-frame-options"), "SAMEORIGIN")
        # Should contain either base href or fallback
        self.assertTrue("<base href=" in res.text or "Maison de village test" in res.text)


if __name__ == "__main__":
    unittest.main()
