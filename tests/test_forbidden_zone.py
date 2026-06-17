import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.geo import is_city_in_forbidden_set

def test_is_city_in_forbidden_set():
    forbidden = {"saint-malo (35400)", "rennes", "paris"}

    # Test cases: (Input, Expected Result)
    test_cases = [
        # Match exact
        ("Saint-Malo (35400)", True),
        ("saint-malo (35400)", True),
        ("Rennes", True),
        ("Paris", True),
        
        # Match without zip code in input
        ("Saint-Malo", True),
        ("saint-malo", True),
        
        # Match with different casing/spacing
        ("  Saint-Malo  ", True),
        ("Paris (75015)", True),
        
        # Substring/partial match cases
        ("Saint-Malo de Guersac", False), # different city
        ("Saint-Malo (35)", True), # matching prefix
        
        # Non-matching cases
        ("Nantes", False),
        ("Brest (29200)", False),
        ("", False),
        (None, False)
    ]

    print("Running is_city_in_forbidden_set tests...")
    for city_str, expected in test_cases:
        res = is_city_in_forbidden_set(city_str, forbidden)
        print(f"Input: {city_str!r} -> Result: {res} (Expected: {expected})")
        assert res == expected, f"Failed for {city_str!r}: got {res}, expected {expected}"

    print("All tests passed!")

if __name__ == "__main__":
    test_is_city_in_forbidden_set()
