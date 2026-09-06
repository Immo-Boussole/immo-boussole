"""Unit and integration tests for HeaderEnforcementMiddleware (Cloudflare Tunnel protection)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings

client = TestClient(app)


def test_headers_disabled_by_default():
    """When REQUIRED_HEADERS is empty, requests without headers pass normally."""
    orig_headers = settings.REQUIRED_HEADERS
    try:
        settings.REQUIRED_HEADERS = ""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
    finally:
        settings.REQUIRED_HEADERS = orig_headers


def test_header_presence_enforcement():
    """Verify presence-only required header blocks when missing, allows when present."""
    orig_headers = settings.REQUIRED_HEADERS
    try:
        settings.REQUIRED_HEADERS = "CF-Ray"

        # Missing header -> 403 Forbidden
        res_missing = client.get("/")
        assert res_missing.status_code == 403
        assert res_missing.json() == {"detail": "Access Denied: Direct origin connection prohibited"}

        # Present header -> Request proceeds (e.g. 200 or redirect to /login)
        res_present = client.get("/", headers={"CF-Ray": "89abcdef12345678-CDG"})
        assert res_present.status_code in (200, 302, 303, 307)
    finally:
        settings.REQUIRED_HEADERS = orig_headers


def test_header_exact_value_match_enforcement():
    """Verify exact-match secret header blocks missing or wrong value, allows valid secret."""
    orig_headers = settings.REQUIRED_HEADERS
    try:
        settings.REQUIRED_HEADERS = "X-Origin-Verify:super-secret-token-12345"

        # 1. Missing header -> 403
        res_missing = client.get("/")
        assert res_missing.status_code == 403

        # 2. Wrong secret value -> 403
        res_wrong = client.get("/", headers={"X-Origin-Verify": "invalid-secret"})
        assert res_wrong.status_code == 403

        # 3. Exact matching secret -> Allowed
        res_ok = client.get("/", headers={"X-Origin-Verify": "super-secret-token-12345"})
        assert res_ok.status_code in (200, 302, 303, 307)
    finally:
        settings.REQUIRED_HEADERS = orig_headers


def test_combined_multiple_headers():
    """Verify multiple headers: one presence check and one exact secret match."""
    orig_headers = settings.REQUIRED_HEADERS
    try:
        settings.REQUIRED_HEADERS = "CF-Ray,X-Origin-Verify:token-abc"

        # Only CF-Ray present -> 403 (missing secret)
        res1 = client.get("/", headers={"CF-Ray": "ray-1"})
        assert res1.status_code == 403

        # Only secret present -> 403 (missing CF-Ray)
        res2 = client.get("/", headers={"X-Origin-Verify": "token-abc"})
        assert res2.status_code == 403

        # Both present and valid -> Allowed
        res3 = client.get("/", headers={"CF-Ray": "ray-1", "X-Origin-Verify": "token-abc"})
        assert res3.status_code in (200, 302, 303, 307)
    finally:
        settings.REQUIRED_HEADERS = orig_headers


def test_health_check_exempted():
    """Container health check endpoint /health must remain accessible without headers."""
    orig_headers = settings.REQUIRED_HEADERS
    try:
        settings.REQUIRED_HEADERS = "X-Origin-Verify:token-xyz"

        # Even with header enforcement active, /health must respond 200 without headers
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json().get("status") == "ok"
    finally:
        settings.REQUIRED_HEADERS = orig_headers


def test_cors_options_preflight_exempted():
    """CORS OPTIONS preflight requests must remain exempted from header enforcement."""
    orig_headers = settings.REQUIRED_HEADERS
    try:
        settings.REQUIRED_HEADERS = "X-Origin-Verify:token-xyz"

        # OPTIONS preflight request without the secret header
        res = client.options("/api/listings/import", headers={
            "Origin": "chrome-extension://abcdef",
            "Access-Control-Request-Method": "POST",
        })
        # Must not be 403 Forbidden
        assert res.status_code in (200, 204)
    finally:
        settings.REQUIRED_HEADERS = orig_headers


if __name__ == "__main__":
    test_headers_disabled_by_default()
    test_header_presence_enforcement()
    test_header_exact_value_match_enforcement()
    test_combined_multiple_headers()
    test_health_check_exempted()
    test_cors_options_preflight_exempted()
    print("ALL HEADER ENFORCEMENT TESTS PASSED!")
