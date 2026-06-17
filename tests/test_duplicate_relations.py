#!/usr/bin/env python3
"""
Test suite to verify the duplicate relationships and UI banner display.
"""
import sys
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, get_db
from app.models import Listing, ListingStatus, User
from app.main import app, templates

# Use file-based SQLite database for testing to avoid multi-thread isolation of :memory:
SQLALCHEMY_DATABASE_URL = "sqlite:///test_duplicate_relations.db"
if os.path.exists("test_duplicate_relations.db"):
    try:
        os.remove("test_duplicate_relations.db")
    except Exception:
        pass

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables in the test database
Base.metadata.create_all(bind=engine)

# Override get_db dependency
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def setup_test_data():
    db = TestingSessionLocal()
    # Clean database
    db.query(Listing).delete()
    db.query(User).delete()
    
    # 1. Create a test admin user and login session
    import hashlib
    salt = os.urandom(32)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', b"test_password", salt, 100000)
    admin = User(
        username="Jean-Marc",
        password_hash=pwd_hash,
        salt=salt,
        role="admin"
    )
    db.add(admin)
    db.commit()

    # 2. Add test listings:
    # Listing 2: The Parent/Original listing
    l2 = Listing(
        id=2,
        title="Appartement Original #2",
        url="https://www.example.com/annonce-2",
        original_url="https://www.example.com/annonce-2",
        is_duplicate=False,
        duplicate_of_id=None,
        status=ListingStatus.ACTIVE,
        photos_local="[]"
    )
    # Listing 144: Duplicate child of #2 (first sibling)
    l144 = Listing(
        id=144,
        title="Doublon #144",
        url="https://www.example.com/annonce-144",
        original_url="https://www.example.com/annonce-144",
        is_duplicate=True,
        duplicate_of_id=2,
        status=ListingStatus.ACTIVE,
        photos_local="[]"
    )
    # Listing 145: Sibling duplicate child of #2 (second sibling)
    l145 = Listing(
        id=145,
        title="Doublon #145",
        url="https://www.example.com/annonce-145",
        original_url="https://www.example.com/annonce-145",
        is_duplicate=True,
        duplicate_of_id=2,
        status=ListingStatus.ACTIVE,
        photos_local="[]"
    )
    # Listing 142: Normal listing (not a duplicate)
    l142 = Listing(
        id=142,
        title="Maison Normale #142",
        url="https://www.example.com/annonce-142",
        original_url="https://www.example.com/annonce-142",
        is_duplicate=False,
        duplicate_of_id=None,
        status=ListingStatus.ACTIVE,
        photos_local="[]"
    )
    
    db.add(l2)
    db.add(l144)
    db.add(l145)
    db.add(l142)
    db.commit()
    db.close()

def test_duplicate_queries():
    print("Testing backend duplicate query logic...")
    db = TestingSessionLocal()
    
    # Verify Listing 2 (Parent) query behavior
    l2 = db.query(Listing).filter(Listing.id == 2).first()
    # Check what duplicate_children should look like for parent
    dup_children_l2 = db.query(Listing).filter(Listing.duplicate_of_id == l2.id).all()
    assert len(dup_children_l2) == 2, "Parent #2 should have exactly 2 duplicate children"
    assert {c.id for c in dup_children_l2} == {144, 145}, "Children of #2 should be 144 and 145"
    
    # Verify Listing 144 (Sibling) query behavior
    l144 = db.query(Listing).filter(Listing.id == 144).first()
    # If listing.duplicate_of_id exists (child duplicate), duplicate_original should point to parent
    dup_original_l144 = db.query(Listing).filter(Listing.id == l144.duplicate_of_id).first()
    assert dup_original_l144.id == 2, "Duplicate original for #144 should be #2"
    # Sibling query: Sibling duplicates should be other children of the same parent
    dup_siblings_l144 = db.query(Listing).filter(
        Listing.duplicate_of_id == l144.duplicate_of_id,
        Listing.id != l144.id
    ).all()
    assert len(dup_siblings_l144) == 1, "Sibling duplicate list for #144 should contain exactly 1 element"
    assert dup_siblings_l144[0].id == 145, "Sibling for #144 should be #145"

    # Verify Listing 142 (Not a duplicate) query behavior
    l142 = db.query(Listing).filter(Listing.id == 142).first()
    assert not l142.is_duplicate, "#142 is not marked as duplicate"
    assert l142.duplicate_of_id is None, "#142 has no parent duplicate ID"
    dup_children_l142 = db.query(Listing).filter(Listing.duplicate_of_id == l142.id).all()
    assert len(dup_children_l142) == 0, "#142 should have 0 children"
    
    db.close()
    print("Backend query logic test: PASSED")

def test_ui_rendering():
    print("Testing template duplicate UI rendering...")
    
    # First GET the login page to retrieve the CSRF token
    login_page = client.get("/login")
    import re
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text)
    csrf_token = match.group(1) if match else ""
    
    # Force login by posting to /login endpoint with the CSRF token
    response = client.post("/login", data={"username": "Jean-Marc", "password": "test_password", "csrf_token": csrf_token})
    assert response.status_code in [200, 303], "Login should succeed"
        
    # 1. Render Listing 142 (Not a duplicate)
    response = client.get("/listings/142")
    assert response.status_code == 200, "Should load listing detail page for #142"
    html_142 = response.text
    # Listing 142 is NOT a duplicate and has no children, so the banner should NOT render.
    assert "CETTE ANNONCE EST DÉCLARÉE COMME DUPLICAT" not in html_142, "Warning banner should not be present on non-duplicate #142"
    print("Listing #142 (Not a duplicate) correctly conceals banner: PASSED")
    
    # 2. Render Listing 144 (Sibling / Child duplicate)
    response = client.get("/listings/144")
    assert response.status_code == 200, "Should load listing detail page for #144"
    html_144 = response.text
    assert "CETTE ANNONCE EST DÉCLARÉE COMME DUPLICAT" in html_144, "Warning banner should be present on duplicate #144"
    assert "Annonce originale" in html_144, "'Annonce originale' label should show on duplicate #144"
    assert "/listings/2" in html_144, "Should have a link pointing to original parent listing #2"
    assert "/listings/145" in html_144, "Should have a link pointing to duplicate sibling #145"
    assert "Annonces liées" in html_144, "'Annonces liées' label should show on duplicate #144"
    print("Listing #144 (Sibling duplicate) correctly renders parent and sibling links: PASSED")

    # 3. Render Listing 2 (Parent / Original duplicate)
    response = client.get("/listings/2")
    assert response.status_code == 200, "Should load listing detail page for #2"
    html_2 = response.text
    assert "CETTE ANNONCE EST DÉCLARÉE COMME DUPLICAT" in html_2, "Warning banner should be present on parent duplicate #2 because it has duplicate children"
    assert "Annonce originale" not in html_2, "Parent duplicate #2 should not have an 'Annonce originale' section since it is the root"
    assert "/listings/144" in html_2, "Should link to child duplicate #144 under Annonces liées"
    assert "/listings/145" in html_2, "Should link to child duplicate #145 under Annonces liées"
    print("Listing #2 (Parent duplicate) correctly renders children links under Annonces liées: PASSED")

if __name__ == "__main__":
    try:
        setup_test_data()
        test_duplicate_queries()
        test_ui_rendering()
        print("All tests passed successfully!")
    finally:
        # Clean up database file
        if os.path.exists("test_duplicate_relations.db"):
            try:
                os.remove("test_duplicate_relations.db")
            except Exception:
                pass
