#!/usr/bin/env python3
"""
Unit test for dynamic Google Sync settings (google_pilot_email).
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import GlobalSettings
from app import google_service

def test_dynamic_google_settings():
    run_migrations()
    db = SessionLocal()

    try:
        # 1. Test fallback email
        email = google_service.get_pilot_email(db)
        print(f"Fallback email (should be default): {email}")
        assert email == "GOOGLE_ACCOUNT_EMAIL@gmail.com"

        # 2. Modify email in database
        settings = db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings()
            db.add(settings)
        
        settings.google_pilot_email = "test-custom-email@domain.com"
        db.commit()

        # 3. Test dynamic retrieval
        updated_email = google_service.get_pilot_email(db)
        print(f"Updated email (should be custom): {updated_email}")
        assert updated_email == "test-custom-email@domain.com"

        # 4. Cleanup
        settings.google_pilot_email = "GOOGLE_ACCOUNT_EMAIL@gmail.com"
        db.commit()
        print("ALL GOOGLE SETTINGS TESTS PASSED!")

    finally:
        db.close()

if __name__ == "__main__":
    test_dynamic_google_settings()
