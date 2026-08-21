import hashlib
import secrets
import sys
import os
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.database import SessionLocal, run_migrations
from app.models import User

client = TestClient(app)

def test_login_api_success_and_invalid():
    run_migrations()
    db = SessionLocal()

    # Create a test user
    username = "test_auth_user"
    password = "SuperSecretPassword123!"
    salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 600000)

    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            password_hash=pwd_hash,
            salt=salt,
            role="user",
            can_create_api_key=False
        )
        db.add(user)
        db.commit()
    else:
        user.password_hash = pwd_hash
        user.salt = salt
        db.commit()
    db.close()

    # 1. Invalid credentials
    res_bad = client.post("/api/v1/auth/login", json={"username": username, "password": "WrongPassword"})
    assert res_bad.status_code == 401

    # 2. Valid credentials
    res_good = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res_good.status_code == 200
    data = res_good.json()
    assert "api_key" in data
    assert len(data["api_key"]) > 20
    assert data["username"] == username
    assert data["token_type"] == "bearer"

    # 3. Test API key works to query listings
    headers = {"Authorization": f"Bearer {data['api_key']}"}
    res_listings = client.get("/api/v1/listings/?limit=1", headers=headers)
    assert res_listings.status_code == 200
