import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import hashlib
import os
import secrets
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, run_migrations
from app.models import Listing, Agent, Agency, Source, ListingStatus, User

def test_listing_detail_contact_rendering():
    run_migrations()
    db = SessionLocal()
    client = TestClient(app)

    # Setup admin user
    test_user = db.query(User).filter(User.username == "test_contact_admin").first()
    salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', "password123".encode('utf-8'), salt, 600000)
    if not test_user:
        test_user = User(username="test_contact_admin", password_hash=pwd_hash, salt=salt, role="admin")
        db.add(test_user)
        db.commit()
    else:
        test_user.password_hash = pwd_hash
        test_user.salt = salt
        test_user.role = "admin"
        db.commit()

    # Login via client
    res_login_page = client.get("/login")
    csrf_token = res_login_page.text.split('name="csrf_token" value="')[1].split('"')[0]
    res_post_login = client.post("/login", data={"username": "test_contact_admin", "password": "password123", "csrf_token": csrf_token}, follow_redirects=True)
    assert res_post_login.status_code == 200

    u1 = str(uuid.uuid4())[:8]
    u2 = str(uuid.uuid4())[:8]

    # 1. Create agency, agent and listing
    agency = Agency(legal_name=f"Agence Des Alpes {u1}", commercial_name=f"Alpes Immo {u1}", city="Grenoble", phone="04 76 00 00 00", email=f"contact_{u1}@alpesimmo.fr")
    db.add(agency)
    db.commit()
    db.refresh(agency)

    agent = Agent(first_name="Sophie", last_name="Bernard", phone_mobile="06 11 22 33 44", email=f"sophie_{u1}@alpesimmo.fr", agency_id=agency.id)
    db.add(agent)
    db.commit()
    db.refresh(agent)

    listing_with_contact = Listing(
        title="Appartement T4 Hyper Centre",
        url=f"https://test.fr/listing-contact-{u1}",
        source=Source.LEBONCOIN,
        status=ListingStatus.ACTIVE,
        price=295000,
        main_agent_id=agent.id,
        agency_id=agency.id,
        description_text="Bel appartement rénové. Contact Sophie Bernard au 06 11 22 33 44"
    )
    db.add(listing_with_contact)

    listing_without_contact_with_regex = Listing(
        title="Maison de Ville",
        url=f"https://test.fr/listing-contact-{u2}",
        source=Source.LEBONCOIN,
        status=ListingStatus.ACTIVE,
        price=450000,
        description_text="Contactez Marc Dupont au 06 99 88 77 66 chez iad France pour visiter."
    )
    db.add(listing_without_contact_with_regex)
    db.commit()
    db.refresh(listing_with_contact)
    db.refresh(listing_without_contact_with_regex)

    # 2. Test GET listing detail with assigned contact
    res1 = client.get(f"/listings/{listing_with_contact.id}")
    assert res1.status_code == 200, f"Expected 200, got {res1.status_code}"
    html1 = res1.text
    assert "btn-contact-nav" in html1
    assert "Sophie Bernard" in html1
    assert "06 11 22 33 44" in html1
    assert "Alpes Immo" in html1
    assert "listingContactModal" in html1

    # 3. Test GET listing detail with detected regex contact (unassigned)
    res2 = client.get(f"/listings/{listing_without_contact_with_regex.id}")
    assert res2.status_code == 200, f"Expected 200, got {res2.status_code}"
    html2 = res2.text
    assert "btn-contact-nav" in html2
    assert "Coordonnées détectées" in html2
    assert "listingContactModal" in html2

    # Cleanup
    db.query(Listing).filter(Listing.id.in_([listing_with_contact.id, listing_without_contact_with_regex.id])).delete(synchronize_session=False)
    db.delete(agent)
    db.delete(agency)
    db.commit()
    db.close()
    print("Listing detail contact rendering tests passed successfully!")

if __name__ == "__main__":
    test_listing_detail_contact_rendering()
