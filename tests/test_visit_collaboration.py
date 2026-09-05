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
from app.models import Listing, Source, ListingStatus, Visit, User, VisitQuestion, VisitMedia, GlobalSettings
from app.main import app, login_required, user_required
from app import email_service


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

                # Verify external participant is isolated and does NOT pollute the system User table
                created_user = db.query(User).filter(User.email == new_participant_email).first()
                assert created_user is None
                assert invite_data["participants"][0].get("id") is not None

                # Verify email content sent
                assert mock_send_email.called
                args, kwargs = mock_send_email.call_args
                email_to = args[1]
                email_html = args[2]
                assert email_to == new_participant_email
                assert "Contre-visite" in email_html
                assert f"/v/{invite_data['access_token']}" in email_html

                # Verify adding a second participant preserves existing participant
                second_email = f"artisan_{ts}@example.com"
                invite2_resp = client.post(f"/api/visites/{visit_id}/invite", json={
                    "participants": [
                        {
                            "name": "Pierre Artisan",
                            "email": second_email,
                            "role": "artisan"
                        }
                    ],
                    "send_emails": False
                })
                assert invite2_resp.status_code == 200
                invite2_data = invite2_resp.json()
                assert len(invite2_data["participants"]) == 2
                emails_in_list = [p.get("email") for p in invite2_data["participants"]]
                assert new_participant_email in emails_in_list
                assert second_email in emails_in_list

                # Verify adding multiple participants with identical roles (e.g. 2 conseillers) coexists without overwriting
                c1_email = f"conseil1_{ts}@example.com"
                c2_email = f"conseil2_{ts}@example.com"
                invite_c1 = client.post(f"/api/visites/{visit_id}/invite", json={
                    "participants": [{"name": "Conseiller Un", "email": c1_email, "role": "conseiller"}],
                    "send_emails": False
                })
                assert invite_c1.status_code == 200
                invite_c2 = client.post(f"/api/visites/{visit_id}/invite", json={
                    "participants": [{"name": "Conseiller Deux", "email": c2_email, "role": "conseiller"}],
                    "send_emails": False
                })
                assert invite_c2.status_code == 200
                participants_after = invite_c2.json()["participants"]
                conseillers = [p for p in participants_after if p.get("role") == "conseiller"]
                assert len(conseillers) == 2
                assert {p.get("name") for p in conseillers} == {"Conseiller Un", "Conseiller Deux"}
                assert {p.get("email") for p in conseillers} == {c1_email, c2_email}

                # Test inviting an existing user without email, updating their email in DB
                existing_uname = f"user_no_email_{ts}"
                user_obj = User(
                    username=existing_uname,
                    password_hash=b"fakehash",
                    salt=b"fakesalt",
                    role="user",
                    email=None
                )
                db.add(user_obj)
                db.commit()

                completed_email = f"completed_{ts}@example.com"
                invite_existing_resp = client.post(f"/api/visites/{visit_id}/invite", json={
                    "participants": [
                        {
                            "username": existing_uname,
                            "name": "Utilisateur Existant",
                            "email": completed_email,
                            "role": "conseiller"
                        }
                    ],
                    "send_emails": False
                })
                assert invite_existing_resp.status_code == 200

                # Verify user in DB now has the completed email persisted
                db.refresh(user_obj)
                assert user_obj.email == completed_email

                # Test error if email is missing
                bad_invite_resp = client.post(f"/api/visites/{visit_id}/invite", json={
                    "participants": [
                        {
                            "username": existing_uname,
                            "name": "Sans email",
                            "email": "",
                            "role": "visiteur"
                        }
                    ],
                    "send_emails": False
                })
                assert bad_invite_resp.status_code == 400
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


def test_global_question_catalog_and_import():
    """
    Tests platform-wide master question catalog:
    - Pre-seeded questions retrieval and category filtering.
    - Adding custom reusable question.
    - Batch importing selected catalog questions into visit FAQ.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        listing = Listing(
            title="Appartement Haussmannien",
            url=f"https://example.com/test-catalog-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        app.dependency_overrides[user_required] = lambda: {"username": "tester", "role": "user"}
        app.dependency_overrides[login_required] = lambda: {"username": "tester", "role": "user"}

        try:
            # 1. Check global catalog retrieval
            cat_resp = client.get("/api/visites/catalog/questions")
            assert cat_resp.status_code == 200
            catalog = cat_resp.json()
            assert len(catalog) > 10

            # 2. Filter catalog by category
            struct_resp = client.get("/api/visites/catalog/questions?category=Structure%20%26%20Gros%20%C5%93uvre")
            assert struct_resp.status_code == 200
            assert len(struct_resp.json()) > 0

            # 3. Add custom question to master catalog
            new_cat_resp = client.post("/api/visites/catalog/questions", json={
                "question_text": f"Présence d'un adoucisseur d'eau et date du dernier entretien ? {ts}",
                "themes": ["Plomberie & Sanitaires", "Équipements"],
                "category": "Réseaux & Électricité",
                "advice_notes": "Vérifier le niveau de sel et la dureté de l'eau."
            })
            assert new_cat_resp.status_code == 200
            created_cat_q = new_cat_resp.json()
            cat_id = created_cat_q["id"]

            # 4. Create visit and import from catalog
            v_resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "scheduled_at": datetime.datetime.now().isoformat(),
                "import_default_questions": False
            })
            visit_id = v_resp.json()["id"]

            import_resp = client.post(f"/api/visites/{visit_id}/questions/import-from-catalog", json={
                "question_ids": [cat_id, catalog[0]["id"]]
            })
            assert import_resp.status_code == 200
            assert import_resp.json()["imported_count"] == 2

            # Verify questions in visit
            vq_resp = client.get(f"/api/visites/{visit_id}/questions")
            assert vq_resp.status_code == 200
            assert len(vq_resp.json()) == 2

        finally:
            app.dependency_overrides.clear()


def test_cross_visit_continuity_and_search_filters():
    """
    Tests cross-visit continuity:
    - Questions created in Visit 1 are accessible in Visit 2 (Contre-visite).
    - Origin label shows provenance.
    - Multi-criteria full-text keyword search and author filtering.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        listing = Listing(
            title="Maison Contemporaine avec Jardin",
            url=f"https://example.com/test-continuity-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        app.dependency_overrides[user_required] = lambda: {"username": "acheteur_1", "role": "user"}
        app.dependency_overrides[login_required] = lambda: {"username": "acheteur_1", "role": "user"}

        try:
            # 1. Create Visit 1
            v1_resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "visit_type": "visite",
                "scheduled_at": (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(),
                "import_default_questions": False
            })
            v1_id = v1_resp.json()["id"]

            # Add question in Visit 1
            q1_resp = client.post(f"/api/visites/{v1_id}/questions", json={
                "question_text": "Quelle est la marque de la pompe à chaleur et sa consommation ?",
                "themes": ["Chauffage & Énergie", "DPE & Isolation"],
                "status": "satisfaisante"
            })
            assert q1_resp.status_code == 200
            q1_id = q1_resp.json()["id"]

            # Add answer
            client.patch(f"/api/visites/questions/{q1_id}", json={
                "answer_text": "Pompe Daikin installée en 2022, facture annuelle de 850€.",
                "answered_by": "expert_energie"
            })

            # 2. Create Visit 2 (Contre-visite) on the same listing
            v2_resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "visit_type": "contre_visite",
                "scheduled_at": datetime.datetime.now().isoformat(),
                "import_default_questions": False
            })
            v2_id = v2_resp.json()["id"]
            v2_token = v2_resp.json()["access_token"]

            # Query questions from Visit 2 endpoint -> should include Visit 1 questions
            v2_qs_resp = client.get(f"/api/visites/{v2_id}/questions")
            assert v2_qs_resp.status_code == 200
            qs = v2_qs_resp.json()
            assert len(qs) == 1
            assert "Daikin" in qs[0]["answer_text"]
            assert qs[0]["origin_visit_type"] == "visite"

            # 3. Test Full-text Keyword Search query
            search_resp = client.get(f"/api/visites/{v2_id}/questions?q=daikin")
            assert search_resp.status_code == 200
            assert len(search_resp.json()) == 1

            search_none = client.get(f"/api/visites/{v2_id}/questions?q=chaudiere_fioul")
            assert search_none.status_code == 200
            assert len(search_none.json()) == 0

            # 4. Test Author filter
            auth_resp = client.get(f"/api/visites/{v2_id}/questions?author=expert_energie")
            assert auth_resp.status_code == 200
            assert len(auth_resp.json()) == 1

            # 5. Access HTML session for Visit 2
            page_resp = client.get(f"/v/{v2_token}")
            assert page_resp.status_code == 200
            assert "Maison Contemporaine" in page_resp.text
            assert "Pompe à chaleur" in page_resp.text or "pompe à chaleur" in page_resp.text.lower()

        finally:
            app.dependency_overrides.clear()


def test_csv_import_and_export():
    """
    Tests CSV Import & Export functionality:
    - Exporting visit FAQ to standard UTF-8-SIG CSV.
    - Importing CSV with smart update/creation and auto-catalog enrollment.
    - Downloading CSV template.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        listing = Listing(
            title="Chalet Montagne",
            url=f"https://example.com/test-csv-{ts}",
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

            # Add 2 questions
            client.post(f"/api/visites/{visit_id}/questions", json={
                "question_text": "Quel est le type d'isolation sous toiture ?",
                "themes": ["Toiture & Charpente", "DPE & Isolation"],
                "status": "en_attente"
            })
            client.post(f"/api/visites/{visit_id}/questions", json={
                "question_text": "Présence d'un poêle à bois et date du dernier ramonage ?",
                "themes": ["Chauffage & Énergie"],
                "status": "satisfaisante"
            })

            # 1. Export CSV
            exp_resp = client.get(f"/api/visites/{visit_id}/questions/export-csv")
            assert exp_resp.status_code == 200
            assert exp_resp.headers["content-type"].startswith("text/csv")
            csv_content = exp_resp.content.decode("utf-8-sig")
            assert "isolation sous toiture" in csv_content
            assert "poêle à bois" in csv_content
            assert ";" in csv_content

            # 2. Template CSV
            tmpl_resp = client.get("/api/visites/questions/csv-template")
            assert tmpl_resp.status_code == 200
            assert "thematiques;question;statut;reponse" in tmpl_resp.content.decode("utf-8-sig")

            # 3. Import CSV
            new_csv_content = (
                "thematiques;question;statut;reponse\n"
                "Extérieur, Jardin;État de la clôture et mitoyenneté ?;en_attente;\n"
                "Sécurité;Présence d'un détecteur de fumée DAAF en état ?;satisfaisante;2 détecteurs fonctionnels testés sur place\n"
            )
            fake_csv_file = io.BytesIO(new_csv_content.encode("utf-8-sig"))

            imp_resp = client.post(
                f"/api/visites/{visit_id}/questions/import-csv",
                files={"file": ("import_questions.csv", fake_csv_file, "text/csv")}
            )
            assert imp_resp.status_code == 200
            res_json = imp_resp.json()
            assert res_json["status"] == "success"
            assert res_json["created_count"] == 2

            # Verify total questions is now 4
            all_qs = client.get(f"/api/visites/{visit_id}/questions").json()
            assert len(all_qs) == 4

        finally:
            app.dependency_overrides.clear()


def test_inclusions_furniture_services_and_offer_clause():
    """
    Tests Inclusions & Services:
    - Adding physical objects (room, variant, condition, estimated value, negotiation status).
    - Adding service contracts (provider, equipment, dates, initial/monthly/annual fees).
    - Generating the purchase offer annex clause.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        listing = Listing(
            title="Appartement T4 Meublé",
            url=f"https://example.com/test-inclusions-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        app.dependency_overrides[user_required] = lambda: {"username": "acheteur", "role": "user"}
        app.dependency_overrides[login_required] = lambda: {"username": "acheteur", "role": "user"}

        try:
            v_resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "scheduled_at": datetime.datetime.now().isoformat(),
                "import_default_questions": False
            })
            visit_id = v_resp.json()["id"]

            # 1. Add furniture items (including one with condition 'À définir')
            f1_resp = client.post(f"/api/visites/{visit_id}/inclusions", json={
                "item_type": "objet",
                "room": "Chambre 1",
                "title": "Lit double 160x200",
                "variation_notes": "avec sommier et matelas mémoire de forme",
                "condition": "Très bon état",
                "estimated_value": 450.0,
                "negotiation_status": "inclus_prix_negocie"
            })
            assert f1_resp.status_code == 200
            f1_id = f1_resp.json()["id"]

            f2_resp = client.post(f"/api/visites/{visit_id}/inclusions", json={
                "item_type": "objet",
                "room": "Salon",
                "title": "Table à manger en chêne massif + 6 chaises",
                "condition": "Bon état",
                "estimated_value": 600.0,
                "negotiation_status": "inclus_prix_negocie"
            })
            assert f2_resp.status_code == 200

            f3_resp = client.post(f"/api/visites/{visit_id}/inclusions", json={
                "item_type": "objet",
                "room": "Cuisine",
                "title": "Réfrigérateur américain Samsung",
                "condition": "À définir",
                "estimated_value": 300.0,
                "negotiation_status": "en_discussion"
            })
            assert f3_resp.status_code == 200
            f3_id = f3_resp.json()["id"]

            # 2. Add service contract
            s1_resp = client.post(f"/api/visites/{visit_id}/inclusions", json={
                "item_type": "service",
                "title": "Système d'alarme et télésurveillance 24/7",
                "provider_name": "Verisure",
                "equipment_included": "Centrale + 3 détecteurs photos + 1 sirène + 2 badges",
                "contract_start_date": "2024-01-01",
                "contract_end_date": "2027-01-01",
                "initial_cost": 490.0,
                "monthly_cost": 39.90,
                "annual_cost": 478.80,
                "transfer_status": "reprise_contrat",
                "negotiation_status": "inclus_prix_negocie"
            })
            assert s1_resp.status_code == 200
            s1_id = s1_resp.json()["id"]

            # 3. Retrieve inclusions list and check condition filtering
            inc_list_resp = client.get(f"/api/visites/{visit_id}/inclusions")
            assert inc_list_resp.status_code == 200
            items = inc_list_resp.json()
            assert len(items) == 4

            # Filter by condition: to_define
            to_define_resp = client.get(f"/api/visites/{visit_id}/inclusions?condition=to_define")
            assert to_define_resp.status_code == 200
            to_define_items = to_define_resp.json()
            assert len(to_define_items) == 1
            assert to_define_items[0]["id"] == f3_id

            # 4. Check visit session template render (counters & À définir option)
            session_resp = client.get(f"/visites/{visit_id}/session")
            assert session_resp.status_code == 200
            assert "État à définir" in session_resp.text
            assert "summary-to-define-count" in session_resp.text
            assert "Réfrigérateur américain Samsung" in session_resp.text

            # 5. Quick edit condition via PATCH
            patch_resp = client.patch(f"/api/visites/inclusions/{f3_id}", json={"condition": "Très bon état"})
            assert patch_resp.status_code == 200
            assert patch_resp.json()["condition"] == "Très bon état"

            # 6. Generate Offer Annex Clause
            clause_resp = client.get(f"/api/visites/{visit_id}/inclusions/offer-clause")
            assert clause_resp.status_code == 200
            clause_data = clause_resp.json()

            assert clause_data["total_furniture_count"] == 3
            assert clause_data["total_furniture_value"] == 1350.0
            assert clause_data["total_service_count"] == 1

            clause_text = clause_data["clause_text"]
            assert "INVENTAIRE DU MOBILIER ET DES CONTRATS DE SERVICES" in clause_text
            assert "Lit double 160x200" in clause_text
            assert "avec sommier et matelas" in clause_text
            assert "Verisure" in clause_text
            assert "39.90 €/mois" in clause_text or "39,90" in clause_text

            # 7. Delete one item
            del_resp = client.delete(f"/api/visites/inclusions/{f1_id}")
            assert del_resp.status_code == 200
            assert del_resp.json()["status"] == "deleted"

        finally:
            app.dependency_overrides.clear()


def test_language_attribution_and_filtering():
    """
    Tests language attribution, language-based filtering in master catalog and visit questions,
    and bilingual CSV import/export.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        # 1. Test languages catalog endpoint
        lang_resp = client.get("/api/visites/catalog/languages")
        assert lang_resp.status_code == 200
        langs = lang_resp.json()
        assert len(langs) >= 2
        lang_codes = [l["code"] for l in langs]
        assert "fr" in lang_codes
        assert "en" in lang_codes

        # 2. Test catalog language filtering
        fr_resp = client.get("/api/visites/catalog/questions?language=fr")
        assert fr_resp.status_code == 200
        fr_qs = fr_resp.json()
        assert len(fr_qs) > 0
        assert all(q["language"] == "fr" for q in fr_qs)

        en_resp = client.get("/api/visites/catalog/questions?language=en")
        assert en_resp.status_code == 200
        en_qs = en_resp.json()
        assert len(en_qs) > 0
        assert all(q["language"] == "en" for q in en_qs)

        # 3. Create listing and visit to test question creation with explicit language
        listing = Listing(
            title="Bilingual Inspection Property",
            url=f"https://example.com/test-lang-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        app.dependency_overrides[user_required] = lambda: {"username": "tester_i18n", "role": "user"}
        app.dependency_overrides[login_required] = lambda: {"username": "tester_i18n", "role": "user"}

        try:
            v_resp = client.post("/api/visites", json={
                "listing_id": listing.id,
                "scheduled_at": datetime.datetime.now().isoformat(),
                "import_default_questions": False
            })
            visit_id = v_resp.json()["id"]

            # Add English question
            q_en_resp = client.post(f"/api/visites/{visit_id}/questions", json={
                "question_text": "Is there any active damp or saltpetre in the basement?",
                "themes": ["Dampness & Drainage", "Basement & Cellar"],
                "language": "en",
                "status": "en_attente"
            })
            assert q_en_resp.status_code == 200
            assert q_en_resp.json()["language"] == "en"

            # Add French question
            q_fr_resp = client.post(f"/api/visites/{visit_id}/questions", json={
                "question_text": "Quel est le montant de la dernière taxe foncière ?",
                "themes": ["Charges & Budget"],
                "language": "fr",
                "status": "satisfaisante"
            })
            assert q_fr_resp.status_code == 200
            assert q_fr_resp.json()["language"] == "fr"

            # Filter visit questions by language
            filter_en = client.get(f"/api/visites/{visit_id}/questions?language=en")
            assert filter_en.status_code == 200
            assert len(filter_en.json()) == 1
            assert filter_en.json()[0]["language"] == "en"

            # Export visit questions CSV and verify 'langue' column
            csv_exp_resp = client.get(f"/api/visites/{visit_id}/questions/export-csv")
            assert csv_exp_resp.status_code == 200
            csv_content = csv_exp_resp.content.decode("utf-8-sig")
            assert "langue" in csv_content
            assert ";en;" in csv_content
            assert ";fr;" in csv_content

            # Test CSV import with language column
            test_csv_import = (
                "langue;thematiques;question;statut;reponse;auteur_question\n"
                "en;Roof & Framework;What is the age of the roofing?;satisfaisante;Replaced in 2022;Inspector\n"
                "fr;Piscine;La pompe est-elle sous garantie ?;en_attente;;Acheteur\n"
            )
            import_resp = client.post(
                f"/api/visites/{visit_id}/questions/import-csv",
                files={"file": ("test_import.csv", io.BytesIO(test_csv_import.encode("utf-8-sig")), "text/csv")}
            )
            assert import_resp.status_code == 200
            assert import_resp.json()["created_count"] == 2

            # Verify imported questions languages
            all_q_resp = client.get(f"/api/visites/{visit_id}/questions")
            assert all_q_resp.status_code == 200
            all_qs = all_q_resp.json()
            assert len(all_qs) == 4
            roof_q = next((q for q in all_qs if "roofing" in q["question_text"].lower()), None)
            assert roof_q is not None
            assert roof_q["language"] == "en"

            # ── Test /v/{token} rendering connected user badge ──
            # 1. Unauthenticated / anonymous visitor
            token_visit = db.query(Visit).filter(Visit.id == visit_id).first()
            resp_anon = client.get(f"/v/{token_visit.access_token}")
            assert resp_anon.status_code == 200
            anon_html = resp_anon.text
            assert 'vs-user-badge' not in anon_html

            # 2. Authenticated user with active session
            # Mock session cookie / state
            app.dependency_overrides[user_required] = lambda: {"username": "jean_marc", "role": "user"}
            app.dependency_overrides[login_required] = lambda: {"username": "jean_marc", "role": "user"}

            # Set session in client
            with client as sess_client:
                # Use a session cookie simulation
                with patch("fastapi.Request.session", new_callable=lambda: property(lambda self: {"username": "jean_marc", "role": "user"})):
                    resp_auth = sess_client.get(f"/v/{token_visit.access_token}")
                    assert resp_auth.status_code == 200
                    auth_html = resp_auth.text
                    assert 'class="vs-user-badge"' in auth_html
                    assert 'jean_marc' in auth_html
                    assert '<div class="vs-user-avatar">J</div>' in auth_html

        finally:
            app.dependency_overrides.clear()


def test_invite_unmocked_email_service_and_global_settings_safety():
    """
    Regression test: ensures invite endpoint handles real GlobalSettings without
    AttributeError on APP_ENV or NameError on logger, returning 200 even when email sending fails or is skipped.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        # Ensure GlobalSettings exists in DB
        settings = db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(resend_api_key="re_test_dummy_key_123", resend_sender_email="test@example.com")
            db.add(settings)
            db.commit()
            db.refresh(settings)

        listing = Listing(
            title="Appartement Sécurisé",
            url=f"https://example.com/test-safety-{ts}",
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
                "scheduled_at": (datetime.datetime.now() + datetime.timedelta(days=2)).isoformat(),
                "import_default_questions": False
            })
            assert v_resp.status_code == 200
            visit_id = v_resp.json()["id"]

            # Direct call to send_visit_invitation_email without mocks
            visit = db.query(Visit).filter(Visit.id == visit_id).first()
            # This should NEVER raise AttributeError or NameError
            email_res = email_service.send_visit_invitation_email(
                db=db,
                visit=visit,
                participant_email=f"notif_{ts}@example.com",
                participant_name="Notification Test",
                base_url="https://immo.example.com"
            )

            # Route call to /api/visites/{visit_id}/invite with send_emails=True without mocking
            invite_resp = client.post(f"/api/visites/{visit_id}/invite", json={
                "participants": [
                    {
                        "name": "Marie Témoin",
                        "email": f"marie_{ts}@example.com",
                        "role": "conjoint"
                    }
                ],
                "instructions": "Rendez-vous devant l'immeuble.",
                "send_emails": True
            })

            # Must succeed with 200 OK (no 500 error!)
            assert invite_resp.status_code == 200
            data = invite_resp.json()
            assert data["status"] == "success"
            assert data["short_url"].startswith("/v/")
            assert len(data["participants"]) >= 1

        finally:
            app.dependency_overrides.clear()


def test_visit_question_assignees_attribution_and_value_added():
    """
    Tests:
    1. Creating a question with multiple assignees and respondent_type.
    2. Auto-setting answered_by and answered_at upon adding answer_text.
    3. Customizing answered_by and switching respondent_type.
    4. Bulk assigning questions to multiple persons.
    5. CSV export & import round-trip preserving assignees, respondent_type, answered_by, and answered_at.
    6. Rendering value-added statistics in the visit session view.
    """
    client = TestClient(app)
    ts = int(datetime.datetime.now().timestamp() * 1000)

    with SessionLocal() as db:
        listing = Listing(
            title="Maison Lumineuse avec Jardin",
            url=f"https://example.com/test-assignees-{ts}",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        app.dependency_overrides[user_required] = lambda: {"username": "alice", "role": "user"}
        app.dependency_overrides[login_required] = lambda: {"username": "alice", "role": "user"}

        try:
            with patch("fastapi.Request.session", new_callable=lambda: property(lambda self: {"username": "alice", "role": "user", "authenticated": True})):
                # 1. Create visit
                v_resp = client.post("/api/visites", json={
                    "listing_id": listing.id,
                    "scheduled_at": (datetime.datetime.now() + datetime.timedelta(days=1)).isoformat(),
                    "import_default_questions": False
                })
                assert v_resp.status_code == 200
                visit_id = v_resp.json()["id"]
                token = v_resp.json()["access_token"]

                # 2. Create question with assignees and respondent_type
                q1_resp = client.post(f"/api/visites/{visit_id}/questions", json={
                    "question_text": "Quel est l'âge de la chaudière ?",
                    "themes": ["Chauffage & Énergie"],
                    "status": "en_attente",
                    "assigned_to": ["Marie", "Jean"],
                    "respondent_type": "agent"
                })
                assert q1_resp.status_code == 200, q1_resp.text
                q1_data = q1_resp.json()
                assert q1_data["assigned_list"] == ["Marie", "Jean"]
                assert q1_data["respondent_type"] == "agent"
                q1_id = q1_data["id"]

                # Create second question
                q2_resp = client.post(f"/api/visites/{visit_id}/questions", json={
                    "question_text": "Y a-t-il eu des infiltrations en toiture ?",
                    "themes": ["Toiture & Charpente"],
                    "status": "en_attente",
                    "assigned_to": "Bob",
                    "respondent_type": "proprietaire_direct"
                })
                assert q2_resp.status_code == 200
                q2_data = q2_resp.json()
                assert q2_data["assigned_list"] == ["Bob"]
                q2_id = q2_data["id"]

                # 3. Answer q1 -> auto-attribution to alice and timestamp
                ans_resp = client.patch(f"/api/visites/questions/{q1_id}", json={
                    "answer_text": "Chaudière installée en 2021, révisée annuellement."
                })
                assert ans_resp.status_code == 200
                ans_data = ans_resp.json()
                assert ans_data["answered_by"] == "alice"
                assert ans_data["answered_at"] is not None

                # 4. Modify answered_by, respondent_type and assignees
                mod_resp = client.patch(f"/api/visites/questions/{q1_id}", json={
                    "answered_by": "Agent Stéphane",
                    "respondent_type": "proprietaire_via_agent",
                    "assigned_to": ["Marie", "Expert Chauffage"]
                })
                assert mod_resp.status_code == 200
                mod_data = mod_resp.json()
                assert mod_data["answered_by"] == "Agent Stéphane"
                assert mod_data["respondent_type"] == "proprietaire_via_agent"
                assert mod_data["assigned_list"] == ["Marie", "Expert Chauffage"]

                # 5. Bulk Assign
                bulk_resp = client.post(f"/api/visites/{visit_id}/questions/bulk-assign", json={
                    "question_ids": [q1_id, q2_id],
                    "assigned_to": ["Notaire", "Jean"]
                })
                assert bulk_resp.status_code == 200
                assert bulk_resp.json()["updated_count"] == 2

                # Verify both questions have updated assignees
                q_list_resp = client.get(f"/api/visites/{visit_id}/questions")
                assert q_list_resp.status_code == 200
                questions_map = {q["id"]: q for q in q_list_resp.json()}
                assert questions_map[q1_id]["assigned_list"] == ["Notaire", "Jean"]
                assert questions_map[q2_id]["assigned_list"] == ["Notaire", "Jean"]

                # 6. CSV Export verification
                export_resp = client.get(f"/api/visites/{visit_id}/questions/export-csv")
                assert export_resp.status_code == 200
                csv_content = export_resp.content.decode("utf-8-sig")
                assert "personnes_affectees" in csv_content
                assert "source_reponse" in csv_content
                assert "compte_reponse" in csv_content
                assert "date_reponse" in csv_content
                assert "Notaire, Jean" in csv_content
                assert "proprietaire_via_agent" in csv_content

                # 7. CSV Import verification
                csv_to_import = (
                    "question;reponse;statut;thematiques;personnes_affectees;source_reponse;compte_reponse;date_reponse\n"
                    "La toiture est-elle isolée ?;Oui, laine de roche 30cm;satisfaisante;Isolation, Toiture;Artisan Couvreur;agent;alice;2026-09-01 10:00\n"
                )
                import_file = io.BytesIO(csv_to_import.encode("utf-8"))
                import_resp = client.post(
                    f"/api/visites/{visit_id}/questions/import-csv",
                    files={"file": ("test_import.csv", import_file, "text/csv")}
                )
                assert import_resp.status_code == 200
                import_data = import_resp.json()
                assert import_data["created_count"] >= 1

                # Verify the imported question has the right properties
                q_list_resp2 = client.get(f"/api/visites/{visit_id}/questions")
                imported_q = next((q for q in q_list_resp2.json() if "toiture est-elle isolée" in q["question_text"]), None)
                assert imported_q is not None
                assert imported_q["assigned_list"] == ["Artisan Couvreur"]
                assert imported_q["respondent_type"] == "agent"
                assert imported_q["answered_by"] == "alice"

                # 8. HTML Visit Session View Check
                view_resp = client.get(f"/v/{token}")
                assert view_resp.status_code == 200
                assert "vs-value-added-card" in view_resp.text
                assert "Valeur Ajoutée & Contributions" in view_resp.text
                assert "Source de réponse" in view_resp.text

        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))



