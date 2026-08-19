import pytest
from app.geo import haversine_km, format_duration, calculate_multi_route, search_places_unified

def test_haversine():
    # Paris to Lyon is approx 390-400 km as the crow flies
    d = haversine_km(48.8566, 2.3522, 45.7640, 4.8357)
    assert 380 < d < 410


def test_format_duration():
    assert format_duration(5) == "5 min"
    assert format_duration(60) == "1h"
    assert format_duration(90) == "1h 30 min"


def test_calculate_multi_route():
    res = calculate_multi_route(48.8566, 2.3522, 48.8600, 2.3500)
    assert res["success"] is True
    assert "car" in res["modes"]
    assert "bike" in res["modes"]
    assert "walk" in res["modes"]
    assert len(res["polyline"]) >= 2
