import os
import sys
import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.geo import is_city_in_forbidden_set, standardize_and_enrich_city


def test_is_city_in_forbidden_set_variations():
    forbidden = {"epinouze"}
    assert is_city_in_forbidden_set("Épinouze", forbidden)
    assert is_city_in_forbidden_set("Epinouze (26210)", forbidden)
    assert is_city_in_forbidden_set("26210 Épinouze", forbidden)
    assert is_city_in_forbidden_set("Épinouze 26210", forbidden)

    forbidden_accents = {"Épinouze (26210)"}
    assert is_city_in_forbidden_set("epinouze", forbidden_accents)
    assert is_city_in_forbidden_set("Épinouze", forbidden_accents)
    assert is_city_in_forbidden_set("26210 epinouze", forbidden_accents)


def test_standardize_and_enrich_city_epinouze():
    std_name, zip_code, insee = standardize_and_enrich_city("Epinouze")
    assert "Épinouze" in std_name or "Epinouze" in std_name
    assert zip_code == "26210"
