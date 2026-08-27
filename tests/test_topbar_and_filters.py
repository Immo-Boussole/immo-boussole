import pytest
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, get_db
from app.models import User
from app.main import app, login_required

TEST_DB_FILE = "test_topbar_and_filters.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except Exception:
            pass
    Base.metadata.create_all(bind=engine)
    yield
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
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


def test_dashboard_topbar_and_filters(db):
    def override_get_db():
        yield db

    def override_login_required():
        return True

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[login_required] = override_login_required
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Topbar layout assertions
    assert "topbar-left" in html
    assert "topbar-search" in html
    assert "topbar-search-input" in html
    assert "topbar-right" in html
    assert "btnRefreshTags" in html

    # Filter bar assertions
    assert "filter-bar" in html
    assert 'id="f-nouvelle"' in html or 'id="tbl-f-nouvelle"' in html
    assert "active" in html
    assert "filter-source" in html
    assert "filter-dpe" in html
    assert "filter-contacted" in html
    assert "filter-visit-status" in html
    assert "btn-reset-filter" in html
    assert "results-count" in html


def test_listings_table_topbar_and_filters(db):
    def override_get_db():
        yield db

    def override_login_required():
        return True

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[login_required] = override_login_required
    client = TestClient(app)

    response = client.get("/listings/table")
    assert response.status_code == 200
    html = response.text

    # Topbar layout assertions
    assert "topbar-left" in html
    assert "topbar-search" in html
    assert "topbar-search-input" in html
    assert "topbar-right" in html

    # Filter bar assertions
    assert "filter-bar" in html
    assert 'id="tbl-f-nouvelle"' in html
    assert 'class="tbl-filter-chip active"' in html
    assert "filter-source" in html
    assert "filter-dpe" in html
    assert "filter-contacted" in html
    assert "filter-visit-status" in html
    assert "btn-reset-filter" in html
    assert "results-count" in html

