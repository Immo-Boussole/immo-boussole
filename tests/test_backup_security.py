import io
import zipfile
import pytest
import hashlib
import secrets
from fastapi.testclient import TestClient
from app.main import app
from app.models import User
from app.database import SessionLocal, run_migrations

def test_zip_slip_prevention():
    """Verify that uploading a zip containing relative path traversal filenames is rejected."""
    run_migrations()
    db = SessionLocal()
    client = TestClient(app)

    # Ensure admin user exists
    test_user = db.query(User).filter(User.username == "test_backup_admin").first()
    salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
    if not test_user:
        test_user = User(username="test_backup_admin", password_hash=pwd_hash, salt=salt, role="admin")
        db.add(test_user)
        db.commit()
    else:
        test_user.password_hash = pwd_hash
        test_user.salt = salt
        test_user.role = "admin"
        db.commit()

    # Login to get session
    res_login_page = client.get("/login")
    match = res_login_page.text.split('name="csrf_token" value="')
    csrf_token = match[1].split('"')[0] if len(match) > 1 else ""

    client.post("/login", data={"username": "test_backup_admin", "password": "password123", "csrf_token": csrf_token}, follow_redirects=True)

    # Create a malicious zip payload in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add a malicious path attempting path traversal
        zipf.writestr("../../malicious.txt", "evil content")
    zip_buffer.seek(0)

    # Post to restore endpoint
    response = client.post(
        "/api/admin/restore",
        files={"file": ("backup.zip", zip_buffer, "application/zip")},
        data={
            "restore_env": "false",
            "restore_media": "false",
            "restore_users": "false",
            "restore_listings": "false",
            "restore_settings": "false"
        }
    )

    assert response.status_code in [400, 500]
    assert "path traversal" in response.text.lower() or "zip file contains unsafe file path" in response.text.lower() or "restore failed" in response.text.lower()
