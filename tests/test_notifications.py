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


def test_standard_user_task_notifications():
    run_migrations()
    db = SessionLocal()

    try:
        from app.notifications import refresh_standard_user_tasks_notifications, get_user_notifications_query
        from app.models import User, Notification, Listing, ListingStatus

        # 1. Create standard user and admin user
        std_user = db.query(User).filter(User.username == "std_test_user").first()
        if not std_user:
            std_user = User(username="std_test_user", password_hash=b"hash", salt=b"salt", role="user")
            db.add(std_user)

        admin_user = db.query(User).filter(User.username == "admin_test_user").first()
        if not admin_user:
            admin_user = User(username="admin_test_user", password_hash=b"hash", salt=b"salt", role="admin")
            db.add(admin_user)

        db.commit()

        # 2. Add an un-qualified listing
        l = Listing(
            title="Appartement à qualifier",
            url="https://test-qualify.com/1",
            city="VilleInconnueTest",
            status=ListingStatus.ACTIVE
        )
        db.add(l)
        db.commit()

        # 3. Refresh task notifications
        refresh_standard_user_tasks_notifications(db)

        # 4. Standard user query should retrieve the "Zones à qualifier" notification
        std_notifs = get_user_notifications_query(db, std_user).all()
        zones_notif = next((n for n in std_notifs if n.link_url == "/zones"), None)
        assert zones_notif is not None
        assert "zone" in zones_notif.message.lower()
        assert zones_notif.target_role == "user"

        # 5. Non-standard user query (e.g. role admin) with target_role="user" should be excluded when filtering by role
        admin_notifs = get_user_notifications_query(db, admin_user).all()
        admin_zones_notif = next((n for n in admin_notifs if n.link_url == "/zones" and n.target_role == "user"), None)
        assert admin_zones_notif is None

    finally:
        db.close()
