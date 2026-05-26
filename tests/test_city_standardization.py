#!/usr/bin/env python3
"""
Test suite to verify the city standardization, deduplication, and DB maintenance.
"""
import sys
import os
import re
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base
from app.models import Listing, ListingStatus
from app.geo import standardize_and_enrich_city
from app.db_maintenance import identify_problems, repair_listings_batch_task, UNSTANDARDIZED_CITY
from app.services import create_listing_from_details, Source

SQLALCHEMY_DATABASE_URL = "sqlite:///test_city_std.db"
if os.path.exists("test_city_std.db"):
    try:
        os.remove("test_city_std.db")
    except Exception:
        pass

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

# Override the SessionLocal in db_maintenance to use the test database
import app.db_maintenance
app.db_maintenance.SessionLocal = TestingSessionLocal

def test_standardize_and_enrich_city():
    print("Testing city standardization and postal code retrieval...")
    
    # Test cases: (Input, Expected Base Name)
    test_cases = [
        ("saint-clair-du-rhône (38)", "Saint-Clair-du-Rhône"),
        ("Saint-Clair-du-Rhône", "Saint-Clair-du-Rhône"),
        ("Lyon", "Lyon"),
        ("Paris 15", "Paris"),
    ]
    
    for input_val, expected_base in test_cases:
        std_name, zip_code, _ = standardize_and_enrich_city(input_val)
        print(f"Input: '{input_val}' -> Std: '{std_name}' (Zip: {zip_code})")
        assert std_name is not None, f"Should standardize '{input_val}'"
        assert expected_base.lower() in std_name.lower(), f"Standardized name '{std_name}' should contain '{expected_base}'"
        assert zip_code is not None and re.match(r'^\d{5}$', zip_code), f"Postal code should be 5 digits, got '{zip_code}'"
        assert re.match(r'^.+\s\(\d{5}\)$', std_name), f"Standardized name should match Name (Zip) format, got '{std_name}'"

async def test_listing_creation_and_maintenance():
    print("\nTesting listing creation with automatic standardization...")
    db = TestingSessionLocal()
    db.query(Listing).delete()
    db.commit()
    
    # 1. Create a listing with raw city and location
    details = {
        "external_id": "figaro_123",
        "title": "Superbe Appartement",
        "price": 350000,
        "city": "saint-clair-du-rhône (38)",
        "location": "saint-clair-du-rhône (38)",
        "area": 85,
        "rooms": 4,
        "photo_urls": []
    }
    
    listing, is_new = await create_listing_from_details(
        db=db,
        details=details,
        source=Source.LEFIGARO,
        original_url="https://immobilier.lefigaro.fr/announces/123",
        download_photos=False
    )
    
    print(f"Created listing: city='{listing.city}', location='{listing.location}'")
    assert listing.city == "Saint-Clair-du-Rhône (38370)", "City should be standardized on import"
    assert listing.location == "Saint-Clair-du-Rhône (38370)", "Location should be synchronized with city"
    
    # 2. Add an unstandardized listing to database directly to test identification and repair
    unstd_listing = Listing(
        external_id="figaro_456",
        title="Maison de Campagne",
        url="https://immobilier.lefigaro.fr/announces/456",
        original_url="https://immobilier.lefigaro.fr/announces/456",
        price=180000,
        city="Chavanay (42)",
        location="Chavanay (42)",
        status=ListingStatus.ACTIVE
    )
    db.add(unstd_listing)
    db.commit()
    
    # Run identification
    problems = identify_problems(db)
    unstd_problems = problems.get(UNSTANDARDIZED_CITY, {})
    print(f"Identify problems: found {unstd_problems['count']} unstandardized listings")
    assert unstd_problems["count"] == 1, "Should find exactly 1 unstandardized listing (Chavanay)"
    assert unstd_problems["ids"][0] == unstd_listing.id, "Problem ID should match Chavanay listing"
    
    # Run repair
    print("Running batch repair for UNSTANDARDIZED_CITY...")
    await repair_listings_batch_task(UNSTANDARDIZED_CITY, is_part_of_sequence=True)
    
    # Re-fetch Chavanay listing
    db.refresh(unstd_listing)
    print(f"Repaired listing: city='{unstd_listing.city}', location='{unstd_listing.location}'")
    assert unstd_listing.city == "Chavanay (42410)", "City should be repaired to official standardized format with 5-digit zip"
    assert unstd_listing.location == "Chavanay (42410)", "Location should be repaired and synchronized"
    
    # Ensure problem count is now 0
    problems_after = identify_problems(db)
    print(f"Identify problems after repair: {problems_after[UNSTANDARDIZED_CITY]['count']} problems remaining")
    assert problems_after[UNSTANDARDIZED_CITY]["count"] == 0, "All unstandardized city problems should be repaired"
    
    db.close()

if __name__ == "__main__":
    import asyncio
    try:
        test_standardize_and_enrich_city()
        asyncio.run(test_listing_creation_and_maintenance())
        print("\nAll city standardization tests PASSED successfully!")
    finally:
        if os.path.exists("test_city_std.db"):
            try:
                os.remove("test_city_std.db")
            except Exception:
                pass
