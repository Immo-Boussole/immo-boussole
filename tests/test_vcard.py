import os
import sys
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.database import Base, get_db
from app.models import Agent, Agency
from app import vcard


@pytest.fixture
def db_session():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_vcard.db")
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)

        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_vcard_generation():
    agency = Agency(
        id=1,
        legal_name="Agence Immobilière Test SARL",
        commercial_name="Test Immo",
        address="10 Rue de la Paix",
        city="Paris",
        postal_code="75002",
        phone="0140000000",
        email="contact@test-immo.fr",
        website="https://www.test-immo.fr",
        reputation_notes="Excellente agence"
    )
    
    agent = Agent(
        id=1,
        first_name="Jean",
        last_name="Dupont",
        title="Agent Commercial",
        phone_mobile="0611223344",
        phone_landline="0140000001",
        email="j.dupont@test-immo.fr",
        agency=agency,
        internal_notes="Note interne agent"
    )

    agent_vcf = vcard.generate_agent_vcard(agent)
    assert "BEGIN:VCARD" in agent_vcf
    assert "VERSION:3.0" in agent_vcf
    assert "N:Dupont;Jean;;;" in agent_vcf
    assert "FN:Jean Dupont" in agent_vcf
    assert "TEL;TYPE=CELL:0611223344" in agent_vcf
    assert "EMAIL;TYPE=INTERNET:j.dupont@test-immo.fr" in agent_vcf
    assert "ORG:Test Immo" in agent_vcf
    assert "END:VCARD" in agent_vcf

    agency_vcf = vcard.generate_agency_vcard(agency)
    assert "BEGIN:VCARD" in agency_vcf
    assert "ORG:Test Immo" in agency_vcf
    assert "TEL;TYPE=WORK,VOICE:0140000000" in agency_vcf
    assert "URL:https://www.test-immo.fr" in agency_vcf
    assert "ADR;TYPE=WORK:;;10 Rue de la Paix;Paris;;75002;France" in agency_vcf


def test_vcard_parsing():
    sample_vcf = """BEGIN:VCARD
VERSION:3.0
N:Martin;Claire;;;
FN:Claire Martin
TITLE:Conseillère Immobilier
TEL;TYPE=CELL:0699887766
EMAIL;TYPE=INTERNET:c.martin@century21.fr
ORG:Century 21 Paris
NOTE:Contact réactif
END:VCARD
BEGIN:VCARD
VERSION:3.0
N:Orpi Paris 15;;;;
FN:Orpi Paris 15
ORG:Orpi Paris 15
TEL;TYPE=WORK,VOICE:0145000000
EMAIL;TYPE=INTERNET:paris15@orpi.com
URL:https://www.orpi.com
ADR;TYPE=WORK:;;50 Rue de Vaugirard;Paris;;75015;France
END:VCARD
"""

    parsed = vcard.parse_vcard_stream(sample_vcf)
    assert len(parsed) == 2

    # Item 1: Agent
    item1 = parsed[0]
    assert item1["type"] == "agent"
    assert item1["first_name"] == "Claire"
    assert item1["last_name"] == "Martin"
    assert item1["phone_mobile"] == "0699887766"
    assert item1["email"] == "c.martin@century21.fr"
    assert item1["agency_name"] == "Century 21 Paris"

    # Item 2: Agency
    item2 = parsed[1]
    assert item2["type"] == "agency"
    assert item2["name"] == "Orpi Paris 15"
    assert item2["phone"] == "0145000000"
    assert item2["email"] == "paris15@orpi.com"
    assert item2["city"] == "Paris"


def test_vcard_endpoints_export_and_import(client, db_session):
    # 1. Create initial DB records
    agency = Agency(
        legal_name="Immo Boussole Agence",
        commercial_name="Boussole Immo",
        phone="0199999999",
        email="contact@boussole.fr"
    )
    db_session.add(agency)
    db_session.commit()
    db_session.refresh(agency)

    agent = Agent(
        first_name="Sophie",
        last_name="Bernard",
        email="s.bernard@boussole.fr",
        phone_mobile="0600112233",
        agency_id=agency.id
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)

    # Test GET single agent VCF
    resp = client.get(f"/api/v1/agents/{agent.id}/vcf")
    assert resp.status_code == 200
    assert "text/vcard" in resp.headers["content-type"]
    assert "Bernard;Sophie" in resp.text

    # Test GET single agency VCF
    resp = client.get(f"/api/v1/agencies/{agency.id}/vcf")
    assert resp.status_code == 200
    assert "text/vcard" in resp.headers["content-type"]
    assert "Boussole Immo" in resp.text

    # Test GET export all VCF
    resp = client.get("/api/v1/contacts/export/vcf")
    assert resp.status_code == 200
    assert "text/vcard" in resp.headers["content-type"]
    assert "Bernard;Sophie" in resp.text
    assert "Boussole Immo" in resp.text

    # Test POST preview import with 1 new agent and 1 duplicate agent
    vcf_import_text = """BEGIN:VCARD
VERSION:3.0
N:Bernard;Sophie;;;
FN:Sophie Bernard
EMAIL;TYPE=INTERNET:s.bernard@boussole.fr
TEL;TYPE=CELL:0600112233
END:VCARD
BEGIN:VCARD
VERSION:3.0
N:Leroy;Thomas;;;
FN:Thomas Leroy
EMAIL;TYPE=INTERNET:t.leroy@nouveau.fr
TEL;TYPE=CELL:0677889900
ORG:Boussole Immo
END:VCARD
"""
    files = {"file": ("test.vcf", vcf_import_text.encode("utf-8"), "text/vcard")}
    resp = client.post("/api/v1/contacts/import/vcf/preview", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["total_detected"] == 2
    assert data["duplicates_count"] == 1

    items = data["items"]
    dup_item = [i for i in items if i["email"] == "s.bernard@boussole.fr"][0]
    new_item = [i for i in items if i["email"] == "t.leroy@nouveau.fr"][0]
    assert dup_item["is_duplicate"] is True
    assert new_item["is_duplicate"] is False

    # Test POST confirm import with strategy='ignore'
    confirm_payload = {
        "strategy": "ignore",
        "items": items
    }
    resp = client.post("/api/v1/contacts/import/vcf/confirm", json=confirm_payload)
    assert resp.status_code == 200
    confirm_data = resp.json()
    assert confirm_data["status"] == "success"
    assert confirm_data["imported_agents"] == 1

    # Verify Thomas Leroy is created in DB and linked to Boussole Immo
    thomas = db_session.query(Agent).filter(Agent.email == "t.leroy@nouveau.fr").first()
    assert thomas is not None
    assert thomas.agency_id == agency.id
