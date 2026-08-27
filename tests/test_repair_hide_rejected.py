import sys
import os
import unittest
import secrets
import hashlib

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, run_migrations
from app.models import User, Listing, ListingStatus, Source, Visit
from app.db_maintenance import (
    identify_problems,
    identify_problems_with_details,
    EMPTY_DESCRIPTION,
    GENERIC_TITLE_FIGARO,
    ANOMALOUS_PRICE,
    MISSING_PHOTOS
)


class TestRepairHideRejected(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        cls.db = SessionLocal()
        cls.client = TestClient(app)

        # Setup test admin user
        cls.admin_user = cls.db.query(User).filter(User.username == "test_repair_hide_admin").first()
        salt = secrets.token_bytes(16)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
        if not cls.admin_user:
            cls.admin_user = User(
                username="test_repair_hide_admin",
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

        # Login admin user
        res_login_page = cls.client.get("/login")
        csrf_token = res_login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
        cls.client.post("/login", data={"username": "test_repair_hide_admin", "password": "password123", "csrf_token": csrf_token}, follow_redirects=True)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_01_identify_problems_hide_rejected(self):
        # 1. Create an active listing with empty description
        active_listing = Listing(
            title="Active listing without desc",
            url=f"https://test.immo/{secrets.token_hex(6)}",
            source=Source.LEBONCOIN,
            status=ListingStatus.ACTIVE,
            city="Lyon (69001)",
            location="Lyon (69001)",
            description_text="",
            price=200000,
            area=50
        )
        # 2. Create a rejected listing with empty description
        rejected_listing = Listing(
            title="Rejected listing without desc",
            url=f"https://test.immo/{secrets.token_hex(6)}",
            source=Source.LEBONCOIN,
            status=ListingStatus.REJECTED,
            city="Lyon (69001)",
            location="Lyon (69001)",
            description_text="",
            price=200000,
            area=50
        )
        self.db.add(active_listing)
        self.db.add(rejected_listing)
        self.db.commit()
        self.db.refresh(active_listing)
        self.db.refresh(rejected_listing)

        # Check with hide_rejected=True (default)
        problems_hidden = identify_problems(self.db, hide_rejected=True)
        self.assertIn(active_listing.id, problems_hidden[EMPTY_DESCRIPTION]["ids"])
        self.assertNotIn(rejected_listing.id, problems_hidden[EMPTY_DESCRIPTION]["ids"])

        # Check with hide_rejected=False
        problems_all = identify_problems(self.db, hide_rejected=False)
        self.assertIn(active_listing.id, problems_all[EMPTY_DESCRIPTION]["ids"])
        self.assertIn(rejected_listing.id, problems_all[EMPTY_DESCRIPTION]["ids"])
        self.assertGreater(problems_all[EMPTY_DESCRIPTION]["count"], problems_hidden[EMPTY_DESCRIPTION]["count"])

    def test_02_identify_problems_with_details_status(self):
        # Create a rejected listing with generic title
        rejected_figaro = Listing(
            title="Annonce Le Figaro",
            url=f"https://test.immo/{secrets.token_hex(6)}",
            source=Source.LEFIGARO,
            status=ListingStatus.REJECTED,
            city="Paris (75001)",
            location="Paris (75001)",
            description_text="Une description normale",
            price=300000,
            area=40
        )
        self.db.add(rejected_figaro)
        self.db.commit()
        self.db.refresh(rejected_figaro)

        # When hide_rejected=True, not present
        details_hidden = identify_problems_with_details(self.db, hide_rejected=True)
        hidden_ids = [l["id"] for l in details_hidden[GENERIC_TITLE_FIGARO]["listings"]]
        self.assertNotIn(rejected_figaro.id, hidden_ids)

        # When hide_rejected=False, present with status
        details_all = identify_problems_with_details(self.db, hide_rejected=False)
        figaro_item = next((l for l in details_all[GENERIC_TITLE_FIGARO]["listings"] if l["id"] == rejected_figaro.id), None)
        self.assertIsNotNone(figaro_item)
        self.assertIn(figaro_item["status"], ["rejetee", "rejected", ListingStatus.REJECTED.value])

    def test_03_api_problems_hide_rejected_query(self):
        res_hidden = self.client.get("/api/db/problems?hide_rejected=true")
        self.assertEqual(res_hidden.status_code, 200)
        data_hidden = res_hidden.json()
        self.assertIn("problems", data_hidden)

        res_all = self.client.get("/api/db/problems?hide_rejected=false")
        self.assertEqual(res_all.status_code, 200)
        data_all = res_all.json()
        self.assertIn("problems", data_all)

        # Count of problems when showing all should be >= count when hiding rejected
        count_hidden = data_hidden["problems"][EMPTY_DESCRIPTION]["count"]
        count_all = data_all["problems"][EMPTY_DESCRIPTION]["count"]
        self.assertGreaterEqual(count_all, count_hidden)

    def test_04_api_check_hide_rejected_query(self):
        res_check = self.client.post("/api/db/check?hide_rejected=true")
        self.assertEqual(res_check.status_code, 200)
        data_check = res_check.json()
        self.assertIn("problems", data_check)

        res_check_all = self.client.post("/api/db/check?hide_rejected=false")
        self.assertEqual(res_check_all.status_code, 200)
        data_check_all = res_check_all.json()
        self.assertIn("problems", data_check_all)


if __name__ == "__main__":
    unittest.main()
