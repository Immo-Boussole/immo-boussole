#!/usr/bin/env python3
"""
Unit tests for In-App Notifications system in Immo-Boussole.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, SessionLocal, engine, run_migrations
from app.models import Notification, User
from app.notifications import (
    auto_mark_read_expired_notifications,
    create_in_app_notification,
    get_unread_notifications_count,
    get_user_notifications_query,
)
from app.main import app


def test_notifications_crud_and_auto_read():
    run_migrations()
    db = SessionLocal()

    try:
        # 1. Create test user
        user = db.query(User).filter(User.username == "test_notif_user").first()
        if not user:
            user = User(
                username="test_notif_user",
                password_hash=b"hash",
                salt=b"salt",
                role="user",
                auto_read_after_days=7,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        # 2. Create in-app notifications
        n1 = create_in_app_notification(
            db=db,
            title="Avis de visite",
            message="Visite de bien programmé à 14h00",
            category="visite",
            user_id=user.id,
            link_url="/visites"
        )
        n2 = create_in_app_notification(
            db=db,
            title="Nouvelle annonce",
            message="Appartement 3 pièces 75m²",
            category="annonce",
            user_id=user.id,
            link_url="/listings/table"
        )

        assert n1.id is not None
        assert n2.id is not None
        assert n1.is_read is False

        # 3. Check unread count
        unread_count = get_unread_notifications_count(db, user)
        assert unread_count >= 2

        # 4. Mark n1 as read via API router logic or DB update
        n1.is_read = True
        n1.read_at = datetime.now(timezone.utc)
        db.commit()

        unread_count_after = get_unread_notifications_count(db, user)
        assert unread_count_after == unread_count - 1

        # 5. Create an expired notification (> 7 days old)
        expired_date = datetime.now(timezone.utc) - timedelta(days=10)
        n_expired = Notification(
            user_id=user.id,
            title="Notification ancienne",
            message="Alerte système expirée",
            category="systeme",
            is_read=False,
            created_at=expired_date
        )
        db.add(n_expired)
        db.commit()
        db.refresh(n_expired)

        # Run auto-mark-read job
        updated_cnt = auto_mark_read_expired_notifications(db)
        assert updated_cnt >= 1

        db.refresh(n_expired)
        assert n_expired.is_read is True

    finally:
        db.close()


def test_notifications_endpoints():
    client = TestClient(app)

    # Test GET /notifications page response
    response = client.get("/notifications")
    assert response.status_code == 200
    assert "Notifications" in response.text

    # Test GET /api/v1/notifications/unread-count
    count_res = client.get("/api/v1/notifications/unread-count")
    assert count_res.status_code == 200
    data = count_res.json()
    assert "unread_count" in data
