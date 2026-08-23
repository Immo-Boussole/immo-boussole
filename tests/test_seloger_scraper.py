import pytest
import json
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.scrapers.seloger import SelogerScraper
from app.database import SessionLocal, run_migrations
from app.models import Listing, ListingAttachment, Source
from app.services import create_listing_from_details
import asyncio

SAMPLE_SELOGER_JSON = {
    "app_cldp": {
        "data": {
            "classified": {
                "id": "269W7APVLTZA",
                "customTitle": "Maison individuelle 5 pièces avec appartement T2",
                "headline": "Maison 5 pièces 140 m²",
                "title": "Maison à vendre 140m² - Saint-Clair-du-Rhône",
                "description": "Maison individuelle rénovée avec appartement indépendant et forte rentabilité locative\n\nPietrapolis Immobilier vous propose en exclusivité dans le secteur très calme de saint Maurice l'Exil, cette charmante maison individuelle de 5 pièces, entièrement rénovée entre 2020 et 2025, édifiée sur un terrain clos, arboré et piscinable de 629 m².",
                "livingArea": 140.0,
                "landSurface": 629.0,
                "propertyType": "Maison",
                "rooms": {
                    "total": 5,
                    "bedrooms": 3,
                    "bathRooms": 1,
                    "showerRooms": 1,
                    "toilets": 2
                },
                "pricing": {
                    "amount": 349000.0,
                    "charges": 0.0,
                    "landTax": 1170.0
                },
                "location": {
                    "city": "Saint-Clair-du-Rhône",
                    "zipCode": "38370",
                    "tags": ["Saint-Clair-du-Rhône (38370)", "Isère"]
                },
                "energy": {
                    "dpe": {
                        "grade": "A",
                        "consumption": 50.0
                    },
                    "ges": {
                        "grade": "A",
                        "emission": 2.0
                    }
                },
                "domains": {
                    "medias": {
                        "images": [
                            {"url": "https://img.seloger.com/photo1.jpg"},
                            {"url": "https://img.seloger.com/photo2.jpg"}
                        ],
                        "floorplans": [
                            {"url": "https://img.seloger.com/floorplan1.jpg"}
                        ]
                    }
                }
            }
        }
    }
}


def test_seloger_json_extraction():
    scraper = SelogerScraper()
    details = scraper._extract_detail_from_json(SAMPLE_SELOGER_JSON)
    
    assert details["title"] == "Maison individuelle 5 pièces avec appartement T2"
    assert details["area"] == 140.0
    assert details["land_area"] == 629.0
    assert details["rooms"] == 5
    assert details["bedrooms"] == 3
    assert details["bathroom_count"] == 2
    assert details["toilet_count"] == 2
    assert details["city"] == "Saint-Clair-du-Rhone" or details["city"] == "Saint-Clair-du-Rhône"
    assert details["postal_code"] == "38370"
    assert details["price"] == 349000.0
    assert details["land_tax"] == 1170.0
    assert details["dpe_rating"] == "A"
    assert details["ges_rating"] == "A"
    assert "floorplans" in details
    assert "https://img.seloger.com/floorplan1.jpg" in details["floorplans"]
    assert "https://img.seloger.com/floorplan1.jpg" in details["photo_urls"]
    assert "https://img.seloger.com/photo1.jpg" in details["photo_urls"]


def test_create_listing_with_floorplans():
    run_migrations()
    db = SessionLocal()
    
    scraper = SelogerScraper()
    details = scraper._extract_detail_from_json(SAMPLE_SELOGER_JSON)
    test_url = "https://www.seloger.com/annonce/achat/auvergne-rhone-alpes/isere-38/saint-clair-du-rhone-38370/269W7APVLTZA"
    
    # Cleanup previous test data
    db.query(Listing).filter((Listing.url.like('%269W7APVLTZA%')) | (Listing.external_id == "sl_269W7APVLTZA")).delete(synchronize_session=False)
    db.commit()

    listing, is_new = asyncio.run(create_listing_from_details(
        db=db,
        details=details,
        source=Source.SELOGER,
        original_url=test_url,
        download_photos=False
    ))

    assert listing is not None
    assert listing.title == "Maison individuelle 5 pièces avec appartement T2"
    assert listing.area == 140.0
    assert listing.land_area == 629.0
    assert listing.rooms == 5
    assert listing.price == 349000.0
    assert listing.price_per_sqm == round(349000.0 / 140.0, 2)
    assert listing.postal_code == "38370"
    assert "floorplan1.jpg" in listing.original_photo_urls

    db.close()


def test_external_listing_submit_with_floorplans_and_details():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import User
    import hashlib

    client = TestClient(app)
    db = SessionLocal()

    raw_key = "test_seloger_api_key_123"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    user = db.query(User).filter(User.username == "test_seloger_user").first()
    if not user:
        user = User(
            username="test_seloger_user",
            password_hash=b"fakehash",
            salt=b"fakesalt",
            role="admin",
            api_key_hash=key_hash,
            can_create_api_key=True
        )
        db.add(user)
        db.commit()
    else:
        user.api_key_hash = key_hash
        db.commit()

    test_url = "https://www.seloger.com/annonce/achat/auvergne-rhone-alpes/isere-38/saint-clair-du-rhone-38370/269W7APVLTZA_API"
    db.query(Listing).filter(Listing.url == test_url).delete(synchronize_session=False)
    db.commit()
    db.close()

    headers = {"Authorization": f"Bearer {raw_key}"}
    payload = {
        "url": test_url,
        "external_id": "sl_269W7APVLTZA_API",
        "title": "Maison individuelle 5 pièces avec appartement T2",
        "price": 349000.0,
        "area": 140.0,
        "land_area": 629.0,
        "rooms": 5,
        "bedrooms": 3,
        "bathroom_count": 2,
        "city": "Saint-Clair-du-Rhône",
        "postal_code": "38370",
        "location": "Saint-Clair-du-Rhône (38370)",
        "description": "Maison individuelle rénovée avec appartement indépendant...",
        "photos": ["https://img.seloger.com/photo1.jpg", "https://img.seloger.com/photo2.jpg"],
        "floorplans": ["https://img.seloger.com/floorplan1.jpg"],
        "dpe_rating": "A",
        "ges_rating": "A",
        "land_tax": 1170.0,
        "charges": 0.0,
        "source": "seloger"
    }

    res = client.post("/api/v1/actions/submit-external-listing", json=payload, headers=headers)
    assert res.status_code == 200, f"Error {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "success"

    db2 = SessionLocal()
    listing = db2.query(Listing).filter(Listing.url == test_url).first()
    assert listing is not None
    assert listing.title == "Maison individuelle 5 pièces avec appartement T2"
    assert listing.area == 140.0
    assert listing.land_area == 629.0
    assert listing.rooms == 5
    assert listing.bedrooms == 3
    assert listing.bathroom_count == 2
    assert listing.city == "Saint-Clair-du-Rhône"
    assert listing.postal_code == "38370"
    assert listing.land_tax == 1170.0
    assert listing.dpe_rating == "A"
    assert listing.ges_rating == "A"
    assert "floorplan1.jpg" in listing.original_photo_urls
    db2.close()

