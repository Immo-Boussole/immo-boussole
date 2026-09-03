import sys
import os
import unittest
import datetime
import secrets
import hashlib
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, run_migrations
from app.models import Listing, Visit, Source, ListingStatus, User, UserListingView

class TestVisitStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        cls.db = SessionLocal()
        cls.client = TestClient(app)

        # Setup test admin user
        test_user = cls.db.query(User).filter(User.username == "test_visit_admin").first()
        salt = secrets.token_bytes(16)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
        if not test_user:
            test_user = User(username="test_visit_admin", password_hash=pwd_hash, salt=salt, role="admin")
            cls.db.add(test_user)
            cls.db.commit()
        else:
            test_user.password_hash = pwd_hash
            test_user.salt = salt
            test_user.role = "admin"
            cls.db.commit()

        # Login via client
        res_login_page = cls.client.get("/login")
        csrf_token = res_login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
        res_post_login = cls.client.post("/login", data={"username": "test_visit_admin", "password": "password123", "csrf_token": csrf_token}, follow_redirects=True)
        assert res_post_login.status_code == 200

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        # Create test listing
        self.listing = Listing(
            title="Appartement Test Status Badge",
            url=f"http://example.com/test-badge-{uuid.uuid4().hex[:8]}",
            price=300000.0,
            city="Grenoble",
            area=70.0,
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            to_visit=False,
            last_visit_status=None
        )
        self.db.add(self.listing)
        self.db.commit()
        self.db.refresh(self.listing)

    def tearDown(self):
        # Safe cleanup
        self.db.query(Visit).filter(Visit.listing_id == self.listing.id).delete()
        self.db.query(UserListingView).filter(UserListingView.listing_id == self.listing.id).delete()
        self.db.delete(self.listing)
        self.db.commit()

    def test_patch_visit_status_success(self):
        # 1. Update to valid status
        res = self.client.patch(f"/api/listings/{self.listing.id}/visit-status", json={"last_visit_status": "visite_programmee"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["last_visit_status"], "visite_programmee")
        
        self.db.refresh(self.listing)
        self.assertEqual(self.listing.last_visit_status, "visite_programmee")

    def test_patch_visit_status_clear(self):
        # 2. Clear status
        self.listing.last_visit_status = "retour_agence"
        self.db.commit()

        res = self.client.patch(f"/api/listings/{self.listing.id}/visit-status", json={"last_visit_status": None})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNone(data["last_visit_status"])

        self.db.refresh(self.listing)
        self.assertIsNone(self.listing.last_visit_status)

    def test_patch_visit_status_invalid(self):
        # 3. Invalid status should return 400
        res = self.client.patch(f"/api/listings/{self.listing.id}/visit-status", json={"last_visit_status": "invalid_status_xyz"})
        self.assertEqual(res.status_code, 400)

    def test_visit_creation_syncs_last_visit_status(self):
        # 4. Creating a visit should sync listing.last_visit_status
        res = self.client.post("/api/visites", json={
            "listing_id": self.listing.id,
            "visit_type": "visite",
            "step_family": "visite",
            "step": "1ere_visite",
            "status": "effectuee",
            "scheduled_at": datetime.datetime.now().isoformat(),
            "notes": "Bien apprécié, en cours de réflexion"
        })
        self.assertEqual(res.status_code, 200)

        self.db.refresh(self.listing)
        self.assertEqual(self.listing.last_visit_status, "deja_visitee")

    def test_reflexion_step_syncs_deja_visitee(self):
        # 5. Creating a reflexion step activity should set last_visit_status to deja_visitee and to_visit to True
        res = self.client.post("/api/visites", json={
            "listing_id": self.listing.id,
            "step_family": "reflexion",
            "step": "en_reflexion_sans_offre",
            "status": "effectuee",
            "scheduled_at": datetime.datetime.now().isoformat(),
            "notes": "Phase de réflexion après visite"
        })
        self.assertEqual(res.status_code, 200)

        self.db.refresh(self.listing)
        self.assertEqual(self.listing.last_visit_status, "deja_visitee")
        self.assertTrue(self.listing.to_visit)

    def test_rdv_planifie_syncs_visite_programmee(self):
        # 6. Creating a scheduled visit (rdv_planifie) should sync listing.last_visit_status to visite_programmee
        res = self.client.post("/api/visites", json={
            "listing_id": self.listing.id,
            "visit_type": "visite",
            "step_family": "visite",
            "step": "rdv_planifie",
            "status": "programme",
            "scheduled_at": datetime.datetime.now().isoformat(),
            "notes": "Créé automatiquement suite au passage à l'état 'Visite programmée'"
        })
        self.assertEqual(res.status_code, 200)

        self.db.refresh(self.listing)
        self.assertEqual(self.listing.last_visit_status, "visite_programmee")
        self.assertTrue(self.listing.to_visit)

    def test_patch_visit_status_contre_visite(self):
        # 7. Updating to contre_visite should mark to_visit = True
        res = self.client.patch(f"/api/listings/{self.listing.id}/visit-status", json={"last_visit_status": "contre_visite"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["last_visit_status"], "contre_visite")
        self.assertTrue(data["to_visit"])

        self.db.refresh(self.listing)
        self.assertEqual(self.listing.last_visit_status, "contre_visite")
        self.assertTrue(self.listing.to_visit)

if __name__ == "__main__":
    unittest.main()


