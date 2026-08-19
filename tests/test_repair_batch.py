import sys
import os
import unittest
import secrets
import hashlib

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, run_migrations
from app.models import User

class TestRepairBatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        cls.db = SessionLocal()
        cls.client = TestClient(app)

        # Setup test admin user
        cls.admin_user = cls.db.query(User).filter(User.username == "test_batch_admin").first()
        salt = secrets.token_bytes(16)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
        if not cls.admin_user:
            cls.admin_user = User(username="test_batch_admin", password_hash=pwd_hash, salt=salt, role="admin")
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
        cls.client.post("/login", data={"username": "test_batch_admin", "password": "password123", "csrf_token": csrf_token}, follow_redirects=True)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_repair_batch_endpoint_success(self):
        res = self.client.post(
            "/api/db/repair-batch",
            json={"problem_types": ["empty_description", "generic_title_figaro"]}
        )
        self.assertIn(res.status_code, [200, 400]) # 200 started or 400 if already running
        if res.status_code == 200:
            data = res.json()
            self.assertEqual(data["status"], "started")
            self.assertIn("empty_description", data["problem_types"])

    def test_repair_batch_invalid_type(self):
        res = self.client.post(
            "/api/db/repair-batch",
            json={"problem_types": ["invalid_type_xyz"]}
        )
        self.assertIn(res.status_code, [400, 403])
