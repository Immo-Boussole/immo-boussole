import pytest
import os
import sys
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, get_db
from app.models import Listing, ListingStatus, ReadySearch, User, Source
from app.main import app, login_required


import tempfile

temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
TEST_DB_FILE = os.path.join(temp_dir.name, "test_auto_searches_page.db")
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


def test_auto_searches_page_rendering_and_stats(db):
    def override_get_db():
        yield db

    def override_login_required():
        return True

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[login_required] = override_login_required
    client = TestClient(app)

    # 1. Create Ready Searches
    rs_lbc = ReadySearch(
        id=1,
        platform="leboncoin",
        criteria="Maison 5p jardin",
        url="https://www.leboncoin.fr/recherche?category=9"
    )
    rs_seloger = ReadySearch(
        id=2,
        platform="seloger",
        criteria="Appartement T3",
        url="https://www.seloger.com/recherche"
    )
    db.add_all([rs_lbc, rs_seloger])
    db.commit()

    # 2. Create New Listings associated with Ready Searches
    now = datetime.now(timezone.utc)
    l1 = Listing(
        id=101,
        title="Belle maison LBC",
        url="https://leboncoin.fr/ad/101.htm",
        price=320000.0,
        area=110.0,
        city="Lyon",
        status=ListingStatus.NEW,
        source=Source.LEBONCOIN,
        source_ready_search_id=1,
        date_added=now - timedelta(hours=2)
    )
    l2 = Listing(
        id=102,
        title="Appartement SeLoger",
        url="https://seloger.com/ad/102.htm",
        price=210000.0,
        area=65.0,
        city="Villeurbanne",
        status=ListingStatus.NEW,
        source=Source.SELOGER,
        source_ready_search_id=2,
        date_added=now - timedelta(minutes=30)
    )
    db.add_all([l1, l2])
    db.commit()

    # 3. Request /searches/auto
    res = client.get("/searches/auto")
    assert res.status_code == 200
    html = res.text

    # Verify title is cleaned (no ' — Immo-Boussole' in h1)
    import re
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    assert h1_match is not None
    assert "Immo-Boussole" not in h1_match.group(1)
    assert "Automatic Searches" in h1_match.group(1) or "Recherches Automatiques" in h1_match.group(1)

    # Test with French language
    client.get("/lang/fr")
    res_fr = client.get("/searches/auto")
    h1_fr_match = re.search(r"<h1[^>]*>(.*?)</h1>", res_fr.text, re.DOTALL)
    assert h1_fr_match is not None
    assert "Recherches Automatiques" in h1_fr_match.group(1)
    assert "Immo-Boussole" not in h1_fr_match.group(1)

    # Verify source pills and counts are rendered
    assert "sourcePill-leboncoin" in html
    assert "sourcePill-seloger" in html
    assert "LeBonCoin" in html
    assert "SeLoger" in html

    # Verify ReadySearch dropdown options are rendered
    assert 'id="readySearchSelect"' in html
    assert "Maison 5p jardin" in html
    assert "Appartement T3" in html

    # Verify card data attributes for filtering
    assert 'data-platform="leboncoin"' in html
    assert 'data-platform="seloger"' in html
    assert 'data-ready-search-id="1"' in html
    assert 'data-ready-search-id="2"' in html

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(login_required, None)
