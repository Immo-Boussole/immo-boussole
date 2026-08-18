import sys
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.geo import is_city_in_forbidden_set
from app.models import Base, Listing, ListingStatus, ZoneRule, User
from app.main import create_zone_rule, ZoneRuleRequest, listing_detail_page
from app.db_maintenance import identify_problems, FORBIDDEN_ZONE

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

    for city_str, expected in test_cases:
        res = is_city_in_forbidden_set(city_str, forbidden)
        assert res == expected, f"Failed for {city_str!r}: got {res}, expected {expected}"


def get_test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_create_zone_rule_retroactive_rejection():
    db = get_test_db()
    
    # Create test listings
    l1 = Listing(title="Maison Saint-Malo", city="Saint-Malo (35400)", location="Saint-Malo (35400)", status=ListingStatus.NEW, url="https://example.com/1")
    l2 = Listing(title="Appart Rennes", city="Rennes", location="Rennes", status=ListingStatus.ACTIVE, url="https://example.com/2")
    l3 = Listing(title="Maison Nantes", city="Nantes", location="Nantes", status=ListingStatus.NEW, url="https://example.com/3")
    l4 = Listing(title="Maison Proche Gare", city="Brest", location="Brest", nearest_sncf_station="Gare de Brest", status=ListingStatus.ACTIVE, url="https://example.com/4")
    
    db.add_all([l1, l2, l3, l4])
    db.commit()

    # Create dummy request
    scope = {
        "type": "http",
        "session": {"username": "admin", "role": "admin"},
        "headers": []
    }
    req = Request(scope)

    # 1. Add forbidden city rule for Saint-Malo
    body_city = ZoneRuleRequest(zone_type="city", name="Saint-Malo", rule="forbidden")
    res_city = create_zone_rule(request=req, body=body_city, db=db, _auth=True)
    assert res_city["name"] == "Saint-Malo"

    db.refresh(l1)
    db.refresh(l2)
    db.refresh(l3)
    db.refresh(l4)

    assert l1.status == ListingStatus.REJECTED
    assert l2.status == ListingStatus.ACTIVE
    assert l3.status == ListingStatus.NEW
    assert l4.status == ListingStatus.ACTIVE

    # 2. Add forbidden station rule for Gare de Brest
    body_station = ZoneRuleRequest(zone_type="station", name="Gare de Brest", rule="forbidden")
    create_zone_rule(request=req, body=body_station, db=db, _auth=True)

    db.refresh(l4)
    assert l4.status == ListingStatus.REJECTED


def test_listing_detail_auto_rejection():
    db = get_test_db()
    
    # Add forbidden zone rule
    rule = ZoneRule(zone_type="city", name="Fougères", rule="forbidden", created_by="admin")
    db.add(rule)
    db.commit()

    # Listing that was previously added as NEW before rule
    listing = Listing(title="Maison Fougères", city="Fougères (35300)", location="Fougères (35300)", status=ListingStatus.NEW, url="https://example.com/116")
    user = User(username="testuser", password_hash=b"hash", salt=b"salt", role="user")
    db.add_all([listing, user])
    db.commit()

    assert listing.status == ListingStatus.NEW

    scope = {
        "type": "http",
        "path": f"/listings/{listing.id}",
        "session": {"username": "testuser", "role": "user"},
        "headers": []
    }
    req = Request(scope)

    # Call listing_detail route
    response = listing_detail_page(request=req, listing_id=listing.id, db=db)
    
    db.refresh(listing)
    assert listing.status == ListingStatus.REJECTED


def test_db_maintenance_forbidden_zone_detection():
    db = get_test_db()

    rule_city = ZoneRule(zone_type="city", name="Dinan", rule="forbidden", created_by="admin")
    rule_station = ZoneRule(zone_type="station", name="Gare de Dol", rule="forbidden", created_by="admin")
    db.add_all([rule_city, rule_station])
    db.commit()

    l1 = Listing(title="Maison Dinan", city="Dinan (22100)", location="Dinan", status=ListingStatus.ACTIVE, url="https://example.com/10")
    l2 = Listing(title="Maison Dol", city="Dol", location="Dol", nearest_sncf_station="Gare de Dol", status=ListingStatus.NEW, url="https://example.com/11")
    l3 = Listing(title="Maison Rennes", city="Rennes", location="Rennes", status=ListingStatus.ACTIVE, url="https://example.com/12")
    db.add_all([l1, l2, l3])
    db.commit()

    problems = identify_problems(db)
    forbidden_problems = problems[FORBIDDEN_ZONE]
    
    assert forbidden_problems["count"] == 2
    assert l1.id in forbidden_problems["ids"]
    assert l2.id in forbidden_problems["ids"]
    assert l3.id not in forbidden_problems["ids"]
