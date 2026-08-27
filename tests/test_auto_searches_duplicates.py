import pytest
import os
import sys
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, get_db
from app.models import Listing, ListingStatus, ReadySearch, RejectedDuplicate, User, Source
from app.services import normalize_listing_url, enrich_auto_search_duplicates
from app.main import app


import tempfile

temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
TEST_DB_FILE = os.path.join(temp_dir.name, "test_auto_searches_duplicates.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    try:
        temp_dir.cleanup()
    except Exception:
        pass


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def test_normalize_listing_url():
    # 1. Strip tracking params
    url1 = "https://www.leboncoin.fr/ad/ventes_immobilieres/12345.htm?utm_source=alert&utm_medium=email&fbclid=abc123xyz"
    assert normalize_listing_url(url1) == "https://leboncoin.fr/ad/ventes_immobilieres/12345.htm"

    # 2. Preserve essential query params
    url2 = "https://www.seloger.com/annonces/achat/appartement/paris/12345.htm?id=99&utm_campaign=winter"
    assert normalize_listing_url(url2) == "https://seloger.com/annonces/achat/appartement/paris/12345.htm?id=99"

    # 3. Strip trailing slashes and normalize scheme
    url3 = "http://www.lefigaro.fr/annonces/annonce-67890.html/"
    assert normalize_listing_url(url3) == "https://lefigaro.fr/annonces/annonce-67890.html"

    # 4. Handle empty/invalid gracefully
    assert normalize_listing_url("") == ""
    assert normalize_listing_url(None) == ""


def test_enrich_auto_search_duplicates(db):
    # Create active existing listing in DB
    active_l = Listing(
        id=10,
        title="Superbe T3 Lyon 6ème",
        url="https://leboncoin.fr/ad/ventes_immobilieres/10001.htm",
        original_url="https://leboncoin.fr/ad/ventes_immobilieres/10001.htm",
        price=350000.0,
        area=75.0,
        city="Lyon 6ème",
        location="Lyon 6ème",
        status=ListingStatus.ACTIVE,
        is_duplicate=False,
        source=Source.LEBONCOIN
    )
    db.add(active_l)
    db.commit()

    # Create new auto search listing that is similar (same city, price, area)
    new_similar = Listing(
        id=20,
        title="Appartement T3 Lyon 6ème avec balcon",
        url="https://seloger.com/annonces/achat/20002.htm",
        original_url="https://seloger.com/annonces/achat/20002.htm",
        price=350000.0,
        area=75.0,
        city="Lyon 6ème",
        location="Lyon 6ème",
        status=ListingStatus.NEW,
        is_duplicate=False,
        source=Source.SELOGER
    )

    # Create new auto search listing that is completely different
    new_different = Listing(
        id=30,
        title="Maison de campagne à Marseille",
        url="https://lefigaro.fr/annonces/30003.htm",
        original_url="https://lefigaro.fr/annonces/30003.htm",
        price=850000.0,
        area=220.0,
        city="Marseille",
        location="Marseille",
        status=ListingStatus.NEW,
        is_duplicate=False,
        source=Source.LEFIGARO
    )
    db.add_all([new_similar, new_different])
    db.commit()

    # Run duplicate enrichment
    enriched = enrich_auto_search_duplicates([new_similar, new_different], db)

    # new_similar should have duplicate metadata detected (> 50%)
    assert new_similar._duplicate is not None
    assert new_similar._duplicate["score"] >= 50
    assert new_similar._duplicate["target_id"] == 10
    assert "price" in new_similar._duplicate["common"]
    assert "area" in new_similar._duplicate["common"]

    # new_different should have NO duplicate metadata
    assert new_different._duplicate is None


def test_enrich_auto_search_duplicates_ignores_rejected(db):
    active_l = Listing(
        id=40,
        title="Appartement T2 Nantes",
        url="https://leboncoin.fr/ad/40004.htm",
        price=180000.0,
        area=45.0,
        city="Nantes",
        status=ListingStatus.ACTIVE,
        is_duplicate=False,
        source=Source.LEBONCOIN
    )
    new_l = Listing(
        id=50,
        title="Appartement T2 Nantes Centre",
        url="https://seloger.com/annonces/50005.htm",
        price=180000.0,
        area=45.0,
        city="Nantes",
        status=ListingStatus.NEW,
        is_duplicate=False,
        source=Source.SELOGER
    )
    # Add rejected duplicate pair
    rej = RejectedDuplicate(
        listing_a_id=min(40, 50),
        listing_b_id=max(40, 50)
    )
    db.add_all([active_l, new_l, rej])
    db.commit()

    enrich_auto_search_duplicates([new_l], db)
    assert new_l._duplicate is None


def test_merge_duplicate_updates_status_to_active(db):
    def override_get_db():
        yield db

    from app.main import login_required
    def override_login_required():
        return True

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[login_required] = override_login_required
    client = TestClient(app)

    active_parent = Listing(
        id=60,
        title="Maison Bordeaux",
        url="https://leboncoin.fr/ad/60006.htm",
        price=450000.0,
        area=120.0,
        city="Bordeaux",
        status=ListingStatus.ACTIVE,
        is_duplicate=False,
        source=Source.LEBONCOIN
    )
    new_dup = Listing(
        id=70,
        title="Belle maison Bordeaux",
        url="https://seloger.com/annonces/70007.htm",
        price=450000.0,
        area=120.0,
        city="Bordeaux",
        status=ListingStatus.NEW,
        is_duplicate=False,
        source=Source.SELOGER
    )
    db.add_all([active_parent, new_dup])
    db.commit()

    res = client.post(
        "/api/duplicates/merge",
        json={"listing_a_id": 70, "listing_b_id": 60}
    )
    assert res.status_code == 200
    
    db.refresh(new_dup)
    assert new_dup.is_duplicate is True
    assert new_dup.duplicate_of_id == 60
    assert new_dup.status == ListingStatus.ACTIVE

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(login_required, None)
