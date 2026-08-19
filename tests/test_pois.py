import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.geo import POI_CATEGORIES, fetch_pois_around

client = TestClient(app)

def test_poi_categories():
    assert "highway" in POI_CATEGORIES
    assert "cinema" in POI_CATEGORIES
    assert "swimming" in POI_CATEGORIES
    assert "mall" in POI_CATEGORIES
    assert "bakery" in POI_CATEGORIES
    assert "school" in POI_CATEGORIES
    assert "health" in POI_CATEGORIES
    assert "station" in POI_CATEGORIES
    assert "park" in POI_CATEGORIES
    assert "charging" in POI_CATEGORIES
    assert len(POI_CATEGORIES) == 10


def test_fetch_pois_around():
    # Test around Paris center (Place de la Bastille: 48.8532, 2.3698)
    res = fetch_pois_around(
        lat=48.8532,
        lon=2.3698,
        radius_meters=1500,
        categories=["bakery", "station"],
        limit_per_category=5
    )
    assert res["success"] is True
    assert "pois" in res
    assert "category_counts" in res
    assert "center" in res
    assert res["center"]["lat"] == 48.8532
    assert res["radius_meters"] == 1500


def test_points_interet_auth_required():
    res = client.get("/points-interet", follow_redirects=False)
    assert res.status_code in [302, 303, 307, 401]


def test_api_geo_pois_auth_required():
    res = client.get("/api/geo/pois?lat=48.85&lon=2.35&radius=1000", follow_redirects=False)
    assert res.status_code == 401
