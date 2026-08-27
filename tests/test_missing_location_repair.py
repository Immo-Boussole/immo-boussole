import sys
import os
import unittest
import secrets
import hashlib
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, run_migrations
from app.models import User, Listing, ListingStatus, Source, ZoneRule
from app.db_maintenance import identify_problems, get_missing_location_summary, is_missing_location, MISSING_LOCATION


class TestMissingLocationRepair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        cls.db = SessionLocal()
        cls.client = TestClient(app)

        # Setup test admin user
        cls.admin_user = cls.db.query(User).filter(User.username == "test_miss_loc_admin").first()
        salt = secrets.token_bytes(16)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
        if not cls.admin_user:
            cls.admin_user = User(
                username="test_miss_loc_admin",
                password_hash=pwd_hash,
                salt=salt,
                role="admin",
                last_seen_missing_loc_count=0
            )
            cls.db.add(cls.admin_user)
            cls.db.commit()
        else:
            cls.admin_user.password_hash = pwd_hash
            cls.admin_user.salt = salt
            cls.admin_user.role = "admin"
            cls.admin_user.missing_loc_snooze_until = None
            cls.admin_user.last_seen_missing_loc_count = 0
            cls.db.commit()

        # Login admin user
        res_login_page = cls.client.get("/login")
        csrf_token = res_login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
        cls.client.post("/login", data={"username": "test_miss_loc_admin", "password": "password123", "csrf_token": csrf_token}, follow_redirects=True)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_01_missing_location_identification(self):
        # Create a listing with missing location
        listing = Listing(
            title="Maison sans ville test",
            url=f"https://test.immo/{secrets.token_hex(6)}",
            source=Source.LEBONCOIN,
            status=ListingStatus.ACTIVE,
            city=None,
            location="",
            price=250000,
            area=90
        )
        self.db.add(listing)
        self.db.commit()
        self.db.refresh(listing)

        self.assertTrue(is_missing_location(listing))

        problems = identify_problems(self.db)
        self.assertIn(MISSING_LOCATION, problems)
        self.assertGreaterEqual(problems[MISSING_LOCATION]["count"], 1)
        self.assertIn(listing.id, problems[MISSING_LOCATION]["ids"])

        # Check summary
        summary = get_missing_location_summary(self.db, current_user=self.admin_user)
        self.assertGreaterEqual(summary["count"], 1)
        self.assertIn("github_issue_url", summary)
        self.assertTrue(summary["github_issue_url"].startswith("https://github.com/Immo-Boussole/immo-boussole/issues/new"))

    def test_02_set_location_api_valid(self):
        listing = Listing(
            title="Appartement centre test",
            url=f"https://test.immo/{secrets.token_hex(6)}",
            source=Source.LEFIGARO,
            status=ListingStatus.ACTIVE,
            city="",
            location=None,
            price=180000,
            area=60
        )
        self.db.add(listing)
        self.db.commit()
        self.db.refresh(listing)

        res = self.client.post(
            f"/api/listings/{listing.id}/set-location",
            json={"location": "Grenoble (38000)"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["listing"]["city"], "Grenoble (38000)")
        self.assertEqual(data["listing"]["postal_code"], "38000")
        self.assertFalse(data["listing"]["is_rejected"])

        # Check DB
        self.db.refresh(listing)
        self.assertEqual(listing.city, "Grenoble (38000)")
        self.assertFalse(is_missing_location(listing))

    def test_03_set_location_api_auto_rejects_forbidden_zone(self):
        # Create forbidden zone rule
        rule_name = f"ZoneTestBan_{secrets.token_hex(4)}"
        rule = ZoneRule(
            zone_type="city",
            name=rule_name,
            rule="forbidden",
            created_by="test_admin"
        )
        self.db.add(rule)
        self.db.commit()

        listing = Listing(
            title="Maison en zone interdite test",
            url=f"https://test.immo/{secrets.token_hex(6)}",
            source=Source.LEBONCOIN,
            status=ListingStatus.ACTIVE,
            city=None,
            location=None,
            price=300000,
            area=120
        )
        self.db.add(listing)
        self.db.commit()
        self.db.refresh(listing)

        res = self.client.post(
            f"/api/listings/{listing.id}/set-location",
            json={"location": f"{rule_name} (38000)"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["listing"]["is_rejected"])

        self.db.refresh(listing)
        self.assertEqual(listing.status, ListingStatus.REJECTED)

    def test_04_notification_and_snooze_endpoints(self):
        res = self.client.get("/api/maintenance/missing-location-notification")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("count", data)
        self.assertIn("delta", data)
        self.assertIn("sources", data)
        self.assertIn("is_snoozed", data)
        self.assertIn("github_issue_url", data)

        # Test Snooze
        res_snooze = self.client.post(
            "/api/maintenance/snooze-missing-location",
            json={"duration": "1h"}
        )
        self.assertEqual(res_snooze.status_code, 200)
        snooze_data = res_snooze.json()
        self.assertTrue(snooze_data["success"])
        self.assertIn("snooze_until", snooze_data)

        # Re-check notification
        res_after = self.client.get("/api/maintenance/missing-location-notification")
        self.assertEqual(res_after.status_code, 200)
        data_after = res_after.json()
        self.assertTrue(data_after["is_snoozed"])


if __name__ == "__main__":
    unittest.main()
