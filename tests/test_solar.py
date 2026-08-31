"""
Tests for app.solar module.
"""

from unittest.mock import patch, MagicMock
from app.solar import (
    extract_orientation,
    get_orientation_efficiency_factor,
    calculate_french_solar_baseline,
    calculate_solar_potential,
    fetch_pvgis_solar_data,
    fetch_open_meteo_sunshine,
)


def test_extract_orientation():
    # Test South
    assert extract_orientation("Magnifique maison plein sud avec grand jardin") == "Sud"
    assert extract_orientation("Séjour lumineux avec exposition plein sud") == "Sud"
    assert extract_orientation("Villa orientée sud avec piscine") == "Sud"

    # Test South-East / South-West
    assert extract_orientation("Belle terrasse exposée Sud-Ouest sans vis-à-vis") == "Sud-Ouest"
    assert extract_orientation("Appartement traversant plein sud-est") == "Sud-Est"
    assert extract_orientation("Orientation sud ouest idéale") == "Sud-Ouest"

    # Test West / East
    assert extract_orientation("Salon donnant sur balcon plein ouest") == "Ouest"
    assert extract_orientation("Chambres avec orientation à l'est") == "Est"

    # Test North
    assert extract_orientation("Façade exposée nord") == "Nord"
    assert extract_orientation("Exposition: Nord-Ouest") == "Nord-Ouest"

    # None cases
    assert extract_orientation(None) is None
    assert extract_orientation("") is None
    assert extract_orientation("Maison 5 pièces 120m² sans mention") is None


def test_get_orientation_efficiency_factor():
    assert get_orientation_efficiency_factor("Sud") == 1.0
    assert get_orientation_efficiency_factor("Sud-Ouest") == 0.95
    assert get_orientation_efficiency_factor("Sud-Est") == 0.95
    assert get_orientation_efficiency_factor("Ouest") == 0.82
    assert get_orientation_efficiency_factor("Est") == 0.82
    assert get_orientation_efficiency_factor("Nord") == 0.55
    assert get_orientation_efficiency_factor(None) == 1.0


def test_calculate_french_solar_baseline():
    # North (e.g. Lille: ~50.6° lat)
    sun_lille, irrad_lille, yield_lille = calculate_french_solar_baseline(50.63, 3.06)
    assert 1500 <= sun_lille <= 1750
    assert 1000 <= irrad_lille <= 1200
    assert yield_lille > 0

    # South (e.g. Nice/Marseille: ~43.7° lat)
    sun_nice, irrad_nice, yield_nice = calculate_french_solar_baseline(43.70, 7.26)
    assert sun_nice > 2400
    assert irrad_nice > 1400
    assert yield_nice > yield_lille


def test_calculate_solar_potential_with_mock_pvgis():
    pvgis_mock = {
        "source": "pvgis",
        "annual_production_1kwc": 1250.0,
        "annual_irradiation_kwh_m2": 1450.0,
        "optimal_tilt_deg": 35,
        "optimal_azimuth_deg": 0,
        "monthly": [],
    }

    with patch("app.solar.fetch_pvgis_solar_data", return_value=pvgis_mock), \
         patch("app.solar.fetch_open_meteo_sunshine", return_value=2100):
        # Lyon coords (lat=45.76, lon=4.83)
        res = calculate_solar_potential(45.76, 4.83, orientation="Sud", property_type="Maison")

        assert res["sunshine_hours_per_year"] == 2100
        assert res["solar_irradiation_kwh_m2"] == 1450.0
        assert res["pv_yield_per_kwc_annual"] == 1250.0
        assert res["pv_production_3kwc"] == 3750  # 3 * 1250 * 1.0
        assert res["pv_production_6kwc"] == 7500  # 6 * 1250 * 1.0
        assert res["estimated_savings_3kwc"] > 0
        assert res["estimated_savings_6kwc"] > res["estimated_savings_3kwc"]
        assert res["is_house"] is True
        assert res["solar_score"] in ["Très bon", "Exceptionnel"]


def test_calculate_solar_potential_apartment_orientation():
    with patch("app.solar.fetch_pvgis_solar_data", return_value=None), \
         patch("app.solar.fetch_open_meteo_sunshine", return_value=1850):
        res = calculate_solar_potential(48.85, 2.35, orientation="Est", property_type="Appartement")

        assert res["is_house"] is False
        assert "Copropriété" in res["suitability_label"]
        assert res["detected_orientation"] == "Est"
        assert res["orientation_efficiency_pct"] == 82


def test_solar_cache_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, SolarCache
    import json

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    pvgis_mock = {
        "source": "pvgis",
        "annual_production_1kwc": 1300.0,
        "annual_irradiation_kwh_m2": 1500.0,
        "optimal_tilt_deg": 34,
        "optimal_azimuth_deg": 0,
        "monthly": [],
    }

    with patch("app.solar.fetch_pvgis_solar_data", return_value=pvgis_mock) as mock_pvgis, \
         patch("app.solar.fetch_open_meteo_sunshine", return_value=2200) as mock_meteo:
        # First call: populates cache
        res1 = calculate_solar_potential(43.60, 1.44, orientation="Sud", property_type="Maison", db=db)
        assert mock_pvgis.call_count == 1
        assert mock_meteo.call_count == 1

        # Check DB row created
        cache_row = db.query(SolarCache).first()
        assert cache_row is not None
        assert cache_row.sunshine_hours == 2200

        # Second call: uses cache, no external API calls
        mock_pvgis.reset_mock()
        mock_meteo.reset_mock()
        res2 = calculate_solar_potential(43.60, 1.44, orientation="Sud", property_type="Maison", db=db)
        assert mock_pvgis.call_count == 0
        assert mock_meteo.call_count == 0
        assert res2["sunshine_hours_per_year"] == res1["sunshine_hours_per_year"]
        assert res2["pv_production_3kwc"] == res1["pv_production_3kwc"]

