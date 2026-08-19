import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.geo import search_places_unified, calculate_multi_route, format_duration

client = TestClient(app)

def test_format_duration():
    assert format_duration(15) == "15 min"
    assert format_duration(60) == "1h"
    assert format_duration(75) == "1h 15 min"
    assert format_duration(130) == "2h 10 min"
    assert format_duration(0) == "1 min"


def test_calculate_multi_route_structure():
    # Paris (48.8566, 2.3522) to Lyon (45.7640, 4.8357)
    res = calculate_multi_route(48.8566, 2.3522, 45.7640, 4.8357, "Paris", "Lyon")
    
    assert res["success"] is True
    assert res["distance_km"] > 350
    assert "modes" in res
    assert "car" in res["modes"]
    assert "bike" in res["modes"]
    assert "walk" in res["modes"]
    
    car = res["modes"]["car"]
    assert car["duration_minutes"] > 0
    assert "https://www.google.com/maps/dir/" in car["gmaps_url"]
    assert "travelmode=driving" in car["gmaps_url"]
    
    bike = res["modes"]["bike"]
    assert bike["duration_minutes"] > car["duration_minutes"]
    assert "travelmode=bicycling" in bike["gmaps_url"]
    
    walk = res["modes"]["walk"]
    assert walk["duration_minutes"] > bike["duration_minutes"]
    assert "travelmode=walking" in walk["gmaps_url"]
    
    assert len(res["polyline"]) >= 2


def test_search_places_unified():
    # Search for Paris or Lyon
    results = search_places_unified("Lyon", limit=5)
    assert isinstance(results, list)
    if results:
        first = results[0]
        assert "lat" in first
        assert "lon" in first
        assert "label" in first
        assert "type" in first


def test_distance_temps_routes_require_auth():
    # GET /distance-temps without auth should redirect to login or 401
    resp = client.get("/distance-temps", follow_redirects=False)
    assert resp.status_code in [302, 303, 307, 401]

    # POST /api/geo/route-calc without auth
    resp_calc = client.post("/api/geo/route-calc", json={
        "start_lat": 48.8566,
        "start_lon": 2.3522,
        "end_lat": 45.7640,
        "end_lon": 4.8357
    })
    assert resp_calc.status_code in [302, 303, 307, 401]


if __name__ == "__main__":
    test_format_duration()
    test_calculate_multi_route_structure()
    test_search_places_unified()
    print("All Distance & Temps unit tests passed!")
