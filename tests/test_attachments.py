import sys
import os
import uuid
import hashlib
import secrets
import io
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app, failed_logins
from app.database import SessionLocal, run_migrations
from app.models import Listing, ListingAttachment, Source, ListingStatus, User
from app.media import get_listing_attachments_dir, delete_attachment_file, sanitize_filename
from app.translations import load_translations


def setup_test_user(db, username="test_att_user", role="admin"):
    failed_logins.clear()
    test_user = db.query(User).filter(User.username == username).first()
    salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
    if not test_user:
        test_user = User(username=username, password_hash=pwd_hash, salt=salt, role=role)
        db.add(test_user)
        db.commit()
    else:
        test_user.password_hash = pwd_hash
        test_user.salt = salt
        test_user.role = role
        db.commit()
    return test_user


def test_sanitize_filename():
    assert sanitize_filename("DPE & Rapport Énergétique 2026.pdf") == "DPE_Rapport_Energetique_2026.pdf"
    assert sanitize_filename("plan-de-masse_v1.2.png") == "plan-de-masse_v1.2.png"


def test_attachment_model_and_media_helpers():
    run_migrations()
    db = SessionLocal()
    u = str(uuid.uuid4())[:8]

    # Create listing
    listing = Listing(
        title=f"Maison Test Attachments {u}",
        url=f"https://test.immo/listing-att-{u}",
        source=Source.MANUAL,
        status=ListingStatus.ACTIVE,
        price=320000,
        city="Grenoble"
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    # Test directory creation
    att_dir = get_listing_attachments_dir(listing.id)
    assert att_dir.exists()
    assert att_dir.is_dir()

    # Create attachment directly via ORM
    sample_file_path = f"static/media/{listing.id}/attachments/test_doc_{u}.pdf"
    full_sample_path = att_dir / f"test_doc_{u}.pdf"
    full_sample_path.write_bytes(b"%PDF-1.4 test content")

    att = ListingAttachment(
        listing_id=listing.id,
        filename=f"test_doc_{u}.pdf",
        original_filename="Diagnostic_DPE_2026.pdf",
        file_path=sample_file_path,
        file_type="diagnostic",
        title="DPE Complet 2026",
        description="Diagnostic réalisé en Mars 2026",
        file_size=len(b"%PDF-1.4 test content"),
        mime_type="application/pdf",
        created_by="test_user"
    )
    db.add(att)
    db.commit()
    db.refresh(att)

    assert att.id is not None
    assert len(listing.attachments) == 1
    assert listing.attachments[0].title == "DPE Complet 2026"

    # Test safe deletion helper
    assert full_sample_path.exists()
    deleted = delete_attachment_file(sample_file_path)
    assert deleted is True
    assert not full_sample_path.exists()

    db.delete(listing)
    db.commit()
    db.close()


def test_attachments_api_crud_flow():
    run_migrations()
    load_translations()
    db = SessionLocal()
    client = TestClient(app)

    # Setup user & login
    setup_test_user(db, username="test_att_admin", role="admin")

    res_login_page = client.get("/login")
    csrf_token = res_login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    res_post_login = client.post(
        "/login",
        data={"username": "test_att_admin", "password": "password123", "csrf_token": csrf_token},
        follow_redirects=True
    )
    assert res_post_login.status_code == 200

    u = str(uuid.uuid4())[:8]

    # Create test listing
    listing = Listing(
        title=f"Appartement T3 Centre {u}",
        url=f"https://test.immo/listing-crud-{u}",
        source=Source.MANUAL,
        status=ListingStatus.ACTIVE,
        price=210000,
        city="Lyon"
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    listing_id = listing.id

    try:
        # 1. Upload a single PDF file with metadata
        pdf_content = b"%PDF-1.5 fake pdf content for diagnostics"
        files = [
            ("files", ("dpe_diag_2026.pdf", io.BytesIO(pdf_content), "application/pdf"))
        ]
        data = {
            "title": "DPE et Audit Énergétique",
            "file_type": "diagnostic",
            "description": "DPE classé C, GES classé B"
        }

        res_upload = client.post(f"/api/listings/{listing_id}/attachments", data=data, files=files)
        assert res_upload.status_code == 200
        uploaded_data = res_upload.json()
        assert len(uploaded_data) == 1
        att1 = uploaded_data[0]
        att1_id = att1["id"]
        assert att1["listing_id"] == listing_id
        assert att1["title"] == "DPE et Audit Énergétique"
        assert att1["file_type"] == "diagnostic"
        assert att1["description"] == "DPE classé C, GES classé B"
        assert att1["original_filename"] == "dpe_diag_2026.pdf"
        assert att1["file_size"] == len(pdf_content)

        # 2. Upload multiple files (e.g. Plans and Quote)
        img_content = b"fake-png-image-binary-data"
        doc_content = b"fake-docx-binary-data"
        files_multi = [
            ("files", ("plan_rdc.png", io.BytesIO(img_content), "image/png")),
            ("files", ("devis_toiture.docx", io.BytesIO(doc_content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        ]
        res_upload_multi = client.post(
            f"/api/listings/{listing_id}/attachments",
            data={"file_type": "plan"},
            files=files_multi
        )
        assert res_upload_multi.status_code == 200
        multi_data = res_upload_multi.json()
        assert len(multi_data) == 2

        # 3. GET /api/listings/{listing_id}/attachments
        res_list = client.get(f"/api/listings/{listing_id}/attachments")
        assert res_list.status_code == 200
        all_att = res_list.json()
        assert len(all_att) == 3

        # 4. GET /api/v1/listings/{listing_id}/attachments
        res_v1_list = client.get(f"/api/v1/listings/{listing_id}/attachments")
        assert res_v1_list.status_code == 200
        assert len(res_v1_list.json()) == 3

        # 5. PUT /api/listings/{listing_id}/attachments/{attachment_id} (Update metadata)
        res_update = client.put(
            f"/api/listings/{listing_id}/attachments/{att1_id}",
            json={
                "title": "DPE et Audit Énergétique Modifié",
                "file_type": "copropriete",
                "description": "Nouvelle note de synthèse"
            }
        )
        assert res_update.status_code == 200
        updated_att = res_update.json()
        assert updated_att["title"] == "DPE et Audit Énergétique Modifié"
        assert updated_att["file_type"] == "copropriete"
        assert updated_att["description"] == "Nouvelle note de synthèse"

        # 6. GET /api/listings/{listing_id}/attachments/{attachment_id}/download
        res_download = client.get(f"/api/listings/{listing_id}/attachments/{att1_id}/download")
        assert res_download.status_code == 200
        assert res_download.content == pdf_content
        assert "dpe_diag_2026.pdf" in res_download.headers.get("content-disposition", "")

        # 7. Check listing detail HTML page rendering (French & English)
        client.get("/lang/fr")
        res_page_fr = client.get(f"/listings/{listing_id}")
        assert res_page_fr.status_code == 200
        assert "Pièces jointes" in res_page_fr.text
        assert "attachments-section" in res_page_fr.text
        assert "DPE et Audit" in res_page_fr.text
        assert "plan_rdc.png" in res_page_fr.text
        assert "btn-delete-selected-attachments" in res_page_fr.text
        assert "Supprimer un/des document(s)" in res_page_fr.text
        assert "attachment-item-checkbox" in res_page_fr.text

        client.get("/lang/en")
        res_page_en = client.get(f"/listings/{listing_id}")
        assert res_page_en.status_code == 200
        assert "Attachments" in res_page_en.text
        assert "attachments-section" in res_page_en.text
        assert "btn-delete-selected-attachments" in res_page_en.text
        assert "Delete document(s)" in res_page_en.text

        # 8. Single DELETE attachment
        res_del = client.delete(f"/api/listings/{listing_id}/attachments/{att1_id}")
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "deleted"

        res_list_after_del = client.get(f"/api/listings/{listing_id}/attachments")
        assert len(res_list_after_del.json()) == 2

        # 9. Bulk DELETE attachments
        remaining_ids = [a["id"] for a in res_list_after_del.json()]
        res_bulk_del = client.post(
            f"/api/listings/{listing_id}/attachments/bulk-delete",
            json={"attachment_ids": remaining_ids}
        )
        assert res_bulk_del.status_code == 200
        assert res_bulk_del.json()["status"] == "deleted"
        assert res_bulk_del.json()["count"] == 2

        res_list_empty = client.get(f"/api/listings/{listing_id}/attachments")
        assert len(res_list_empty.json()) == 0

    finally:
        # Clean up: Delete listing (tests cascade cleanup)
        res_del_listing = client.delete(f"/api/listings/{listing_id}")
        assert res_del_listing.status_code == 200
        db.close()
