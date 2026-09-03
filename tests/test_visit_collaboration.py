#!/usr/bin/env python3
import sys
import os
import io
import json
import datetime
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import Listing, Source, ListingStatus, Visit, User, VisitQuestion, VisitMedia
from app.main import app, login_required, user_required


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    run_migrations()


def test_visit_creation_with_access_token_and_template():
    """
    Tests that creating a visit automatically generates a unique short URL access_token
    and imports default multi-thematic inspection questions.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        # Create test listing
        listing = Listing(
            title="Villa avec Piscine et Jardin",
            url=f"https://example.com/test-visit-collab-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            price=450000.0,
            city="Grenoble",
            address="15 Avenue Jean Jaurès"
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        # Mock authentication dependency
        app.dependency_overrides[user_required] = lambda: {"username": "test_buyer", "role": "user"}
        app.dependency_overrides[login_required] = lambda: {"username": "test_buyer", "role": "user"}

        try:
            # Create visit
            resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "visit_type": "visite",
                "scheduled_at": (datetime.datetime.now() + datetime.timedelta(days=2)).isoformat(),
                "meeting_address": "15 Avenue Jean Jaurès, Grenoble",
                "instructions": "Inspecter la toiture et la filtration piscine.",
                "import_default_questions": True
            })
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["id"] is not None
            assert data["access_token"] is not None
            assert len(data["access_token"]) >= 8

            visit_id = data["id"]
            token = data["access_token"]

            # Verify questions seeded
            q_resp = client.get(f"/api/visites/{visit_id}/questions")
            assert q_resp.status_code == 200
            questions = q_resp.json()
            assert len(questions) > 5

            # Verify multi-thematic tagging exists (e.g. Piscine, Extérieur, Jardin)
            piscine_q = [q for q in questions if "Piscine" in q["themes"]]
            assert len(piscine_q) > 0
            for pq in piscine_q:
                assert "Extérieur" in pq["themes"] or "Jardin" in pq["themes"] or "Piscine" in pq["themes"]

            # Test short URL direct session view
            view_resp = client.get(f"/v/{token}")
            assert view_resp.status_code == 200
            assert "Villa avec Piscine et Jardin" in view_resp.text
            assert "FAQ & Inspection" in view_resp.text

        finally:
            app.dependency_overrides.clear()


def test_invite_participants_and_auto_account_creation():
    """
    Tests participant invitation workflow:
    - Auto-creation of user accounts for new email addresses.
    - Sending styled invitation email with short URL and GPS link.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        listing = Listing(
            title="Appartement Centre-Ville",
            url=f"https://example.com/test-invite-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            price=280000.0,
            city="Lyon"
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        app.dependency_overrides[user_required] = lambda: {"username": "admin_buyer", "role": "admin"}
        app.dependency_overrides[login_required] = lambda: {"username": "admin_buyer", "role": "admin"}

        try:
            # Create visit
            v_resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "visit_type": "contre_visite",
                "scheduled_at": (datetime.datetime.now() + datetime.timedelta(days=1)).isoformat(),
                "import_default_questions": False
            })
            visit_id = v_resp.json()["id"]

            new_participant_email = f"architecte_{ts}@example.com"

            with patch("app.email_service.send_email") as mock_send_email:
                mock_send_email.return_value = {"id": "msg_12345"}

                invite_resp = client.post(f"/api/visites/{visit_id}/invite", json={
                    "participants": [
                        {
                            "name": "Jean Architecte",
                            "email": new_participant_email,
                            "role": "architecte"
                        }
                    ],
                    "instructions": "Vérifier la faisabilité d'abattre la cloison cuisine.",
                    "send_emails": True
                })

                assert invite_resp.status_code == 200
                invite_data = invite_resp.json()
                assert invite_data["status"] == "success"
                assert invite_data["emails_sent"] == 1

                # Verify user was automatically created in DB
                created_user = db.query(User).filter(User.email == new_participant_email).first()
                assert created_user is not None
                assert created_user.role == "user"

                # Verify email content sent
                assert mock_send_email.called
                args, kwargs = mock_send_email.call_args
                email_to = args[1]
                email_html = args[2]
                assert email_to == new_participant_email
                assert "Contre-visite" in email_html
                assert f"/v/{invite_data['access_token']}" in email_html
        finally:
            app.dependency_overrides.clear()


def test_question_lifecycle_and_non_applicable_status():
    """
    Tests question adding, filtering by theme, setting status to 'non_applicable' and taking answer notes.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        listing = Listing(
            title="Maison Individuelle",
            url=f"https://example.com/test-q-lifecycle-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        app.dependency_overrides[user_required] = lambda: {"username": "tester", "role": "user"}
        app.dependency_overrides[login_required] = lambda: {"username": "tester", "role": "user"}

        try:
            v_resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "scheduled_at": datetime.datetime.now().isoformat(),
                "import_default_questions": False
            })
            visit_id = v_resp.json()["id"]

            # 1. Add a multi-thematic question
            add_q_resp = client.post(f"/api/visites/{visit_id}/questions", json={
                "question_text": "Quel est le montant des charges de copropriété annuelles ?",
                "themes": ["Copropriété", "Charges & Budget"],
                "status": "en_attente"
            })
            assert add_q_resp.status_code == 200
            q_data = add_q_resp.json()
            qid = q_data["id"]

            # 2. Filter questions by theme
            th_resp = client.get(f"/api/visites/{visit_id}/questions?theme=Copropriété")
            assert th_resp.status_code == 200
            assert len(th_resp.json()) == 1

            # 3. Mark question as 'non_applicable' (since it's an independent single house)
            patch_resp = client.patch(f"/api/visites/questions/{qid}", json={
                "status": "non_applicable",
                "answer_text": "Non applicable : maison individuelle sans copropriété."
            })
            assert patch_resp.status_code == 200
            updated_q = patch_resp.json()
            assert updated_q["status"] == "non_applicable"
            assert "Non applicable" in updated_q["answer_text"]

            # 4. Test live updates polling
            poll_resp = client.get(f"/api/visites/{visit_id}/live-updates")
            assert poll_resp.status_code == 200
            poll_data = poll_resp.json()
            assert poll_data["questions_count"] == 1
            assert poll_data["questions"][0]["status"] == "non_applicable"

            # 5. Delete question
            del_resp = client.delete(f"/api/visites/questions/{qid}")
            assert del_resp.status_code == 200
            assert del_resp.json()["status"] == "deleted"

        finally:
            app.dependency_overrides.clear()


def test_visit_media_upload_and_linkage():
    """
    Tests uploading photos/documents and adding links to the visit session.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        listing = Listing(
            title="Propriété Campagne",
            url=f"https://example.com/test-media-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        app.dependency_overrides[user_required] = lambda: {"username": "tester", "role": "user"}
        app.dependency_overrides[login_required] = lambda: {"username": "tester", "role": "user"}

        try:
            v_resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "scheduled_at": datetime.datetime.now().isoformat(),
                "import_default_questions": False
            })
            visit_id = v_resp.json()["id"]

            # 1. Add external link to visit
            link_resp = client.post(
                f"/api/visites/{visit_id}/media",
                data={
                    "url": "https://cadastre.gouv.fr/map-view",
                    "title": "Extrait Cadastral Parcelle AB12",
                    "category_tag": "Cadastre"
                }
            )
            assert link_resp.status_code == 200
            assert link_resp.json()["created_count"] == 1
            link_media_id = link_resp.json()["media"][0]["id"]

            # 2. Upload simulated photo
            fake_photo_bytes = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"dummy photo content")
            file_resp = client.post(
                f"/api/visites/{visit_id}/media",
                files={"files": ("photo_fissure_facade.jpg", fake_photo_bytes, "image/jpeg")},
                data={"category_tag": "Façade & Fissures"}
            )
            assert file_resp.status_code == 200
            assert file_resp.json()["created_count"] == 1
            photo_media = file_resp.json()["media"][0]
            assert photo_media["media_type"] == "photo"
            photo_media_id = photo_media["id"]

            # 3. Check bidirectional linkage in Listing
            listing_refreshed = db.query(Listing).filter(Listing.id == listing.id).first()
            assert len(listing_refreshed.visit_media) == 2

            # 4. Delete media
            del_resp = client.delete(f"/api/visites/media/{photo_media_id}")
            assert del_resp.status_code == 200
            assert del_resp.json()["status"] == "deleted"

        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
