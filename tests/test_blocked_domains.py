import sys
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.blocked_domains import is_domain_blocked, load_blocked_domains
from scripts.add_blocked_domain import add_blocked_domain, parse_issue_body


def test_is_domain_blocked_unit():
    # Reload domains from CSV
    load_blocked_domains(force_reload=True)

    # Test pretto.fr
    blocked, domain, desc = is_domain_blocked("https://pretto.fr/simulation-pret")
    assert blocked is True
    assert domain == "pretto.fr"
    assert "Simulation" in (desc or "")

    # Test subdomain www.pretto.fr
    blocked, domain, desc = is_domain_blocked("http://www.pretto.fr/courtier")
    assert blocked is True
    assert domain == "pretto.fr"

    # Test fcms.typeform.com
    blocked, domain, desc = is_domain_blocked("https://fcms.typeform.com/to/xyz123")
    assert blocked is True
    assert domain == "fcms.typeform.com"

    # Test valid property listing URL
    blocked, domain, desc = is_domain_blocked("https://www.leboncoin.fr/ad/ventes_immobilieres/123456789")
    assert blocked is False
    assert domain is None
    assert desc is None


def test_parse_issue_body():
    issue_body = """
### Domain name / Nom de domaine
test-simulator.org

### Description / Reason
Test simulator site
    """
    d, desc = parse_issue_body(issue_body)
    assert d == "test-simulator.org"
    assert desc == "Test simulator site"


def test_api_check_listing_and_submit_url_blocked(monkeypatch):
    from app.database import get_db
    from app.api.deps import get_current_user_api
    from app.models import User

    # Create dummy user for auth dependency override
    dummy_user = User(id=1, username="test_user", role="admin")

    app.dependency_overrides[get_current_user_api] = lambda: dummy_user

    client = TestClient(app)

    try:
        # Check listing GET endpoint with blocked domain
        res_check = client.get("/api/v1/actions/check-listing?url=https://pretto.fr/simulation-pret")
        assert res_check.status_code == 200
        data_check = res_check.json()
        assert data_check.get("exists") is False
        assert data_check.get("blocked") is True
        assert data_check.get("domain") == "pretto.fr"

        # Submit URL POST endpoint with blocked domain
        res_submit = client.post("/api/v1/actions/submit-url", json={"url": "https://fcms.typeform.com/to/xyz"})
        assert res_submit.status_code == 400
        data_submit = res_submit.json()
        assert "Import forbidden for domain 'fcms.typeform.com'" in data_submit.get("detail", "")

        # Submit URL POST endpoint with normal listing domain
        res_normal = client.post("/api/v1/actions/submit-url", json={"url": "https://www.leboncoin.fr/ad/ventes_immobilieres/999999999", "skip_scraping": True})
        assert res_normal.status_code != 400 or "Import forbidden" not in res_normal.text
    finally:
        app.dependency_overrides.clear()
