import pytest
import os
import sys
import asyncio

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.models import Source
from app.main import _resolve_scraper
from app.scrapers.hektor import HektorScraper


def test_resolve_scraper_hektor():
    urls = [
        "https://www.immoreve.fr/admin/crm/index.php?uri=property&id=953&senderUserId=8&token=xyz",
        "https://www.immoreve.fr/vente/69-clonas-sur-vareze/maison/919-villa",
        "https://agency.ma-boite-immo.com/admin/crm/index.php?id=123",
        "https://hektor-site.fr/property/456",
    ]
    for u in urls:
        src, scraper = _resolve_scraper(u)
        assert src == Source.HEKTOR
        assert isinstance(scraper, HektorScraper)


def test_hektor_parse_graphql_property():
    scraper = HektorScraper()
    mock_prop = {
        "id": "953",
        "price": 230000,
        "surface": 121,
        "carrezSurface": 118.5,
        "landSurface": 850,
        "roomCount": 4,
        "bedroomCount": 3,
        "bathroomCount": 1,
        "showerCount": 1,
        "toiletCount": 2,
        "floorLevel": 1,
        "totalFloors": 2,
        "hasElevator": False,
        "hasBalcony": True,
        "hasTerrace": True,
        "hasGarden": True,
        "hasPool": False,
        "hasCellar": True,
        "garageCount": 1,
        "exteriorParkingCount": 2,
        "interiorParkingCount": 0,
        "condominiumAnnualCharges": 1200,
        "propertyTax": 950,
        "energeticGrade": {"score": "D", "color": "#f1c40f"},
        "photos": [
            {"id": "1", "url": "https://immoreve.staticlbi.com/original/images/biens/1/photo_1.png"},
            {"id": "2", "url": "https://immoreve.staticlbi.com/original/images/biens/1/photo_2.png"},
        ],
        "description": "Superbe maison 4 pièces à Saint-Alban-du-Rhône.",
        "type": {"name": "Maison"},
        "ville": {"nom": "Saint-Alban-du-Rhône 38370"},
        "officialDistricts": [
            {
                "name": "Saint-Alban-du-Rhône",
                "code": "383530000",
                "centroid": {"latitude": 45.41837, "longitude": 4.75466}
            }
        ],
        "agency": {"site": "www.immoreve.fr"}
    }
    mock_sender = {
        "userObject": {
            "displayName": "Agent Immo",
            "phoneNumber": "0474000000",
            "email": "contact@immoreve.fr"
        }
    }
    url = "https://www.immoreve.fr/admin/crm/index.php?uri=property&id=953&senderUserId=8&token=xyz"

    details = scraper._parse_graphql_property(mock_prop, mock_sender, url)

    assert details["external_id"] == "hektor_953"
    assert details["price"] == 230000.0
    assert details["area"] == 121.0
    assert details["carrez_surface"] == 118.5
    assert details["land_area"] == 850.0
    assert details["rooms"] == 4
    assert details["bedrooms"] == 3
    assert details["bathroom_count"] == 2
    assert details["toilets"] == 2
    assert details["parking_count"] == 3
    assert details["balcony"] is True
    assert details["terrace"] is True
    assert details["garden"] is True
    assert details["cellar"] is True
    assert details["elevator"] is False
    assert details["charges"] == 1200.0
    assert details["land_tax"] == 950.0
    assert details["dpe_rating"] == "D"
    assert details["postal_code"] == "38370"
    assert details["city"] == "Saint-Alban-du-Rhône"
    assert details["latitude"] == 45.41837
    assert details["longitude"] == 4.75466
    assert len(details["photo_urls"]) == 2
    assert details["contact_name"] == "Agent Immo"
    assert details["contact_phone"] == "0474000000"
    assert details["contact_email"] == "contact@immoreve.fr"
    assert details["agency_name"] == "www.immoreve.fr"
    assert "Maison" in details["title"]
    assert "Saint-Alban-du-Rhône" in details["title"]


def test_hektor_parse_html_property():
    scraper = HektorScraper()
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:title" content="Villa à CHAVANAY 86 m2 habitables élevée sur sous-sol complet et 1474 m2 de terrain" />
        <meta property="og:description" content="Fort potentiel ! Alan BEHEREC agence Immorêve vous invite à découvrir cette villa..." />
    </head>
    <body>
        <div class="properties-detail__city">Chavanay (42410)</div>
        <div class="properties-detail__price">245 000 €</div>
        <h1>Maison 4 pièce(s) 3 chambre(s) 86 m²</h1>
        <section class="detail_caracteristiques_v1">
            <li class="list_item surf">Surface 86 m²</li>
            <li class="list_item surf_carrez">carrez 86 m²</li>
            <li class="list_item surfterrn">terrain 1 474 m²</li>
            <li class="list_item">3 chambre(s)</li>
            <li class="list_item">1 salle(s) de bain</li>
            <li class="list_item">1 garage(s)</li>
            <li class="list_item">2 niveau(x)</li>
            <li class="list_item">terrasse</li>
            <li class="list_item">arboré</li>
            <li class="list_item">piscinable</li>
        </section>
        <div class="card-contact__title">IMMORÊVE</div>
        <div class="card-contact__coords">04 37 04 32 17 contact@immoreve.fr</div>
        <div class="properties-detail-v2__media">
            <div class="slider__main">
                <img src="//immoreve.staticlbi.com/1200xauto/images/biens/1/f3d09/photo_1.png" />
                <img src="//immoreve.staticlbi.com/1200xauto/images/biens/1/f3d09/photo_2.png" />
            </div>
        </div>
    </body>
    </html>
    """
    url = "https://www.immoreve.fr/vente/160-chavanay/maison/882-villa-a-chavanay-86-m2-habitables-elevee-sur-sous-sol-complet-et-1474-m2-de-terrain"
    details = scraper._parse_html_property(sample_html, url)

    assert details["external_id"] == "hektor_882"
    assert details["price"] == 245000.0
    assert details["area"] == 86.0
    assert details["carrez_surface"] == 86.0
    assert details["land_area"] == 1474.0
    assert details["rooms"] == 4
    assert details["bedrooms"] == 3
    assert details["bathroom_count"] == 1
    assert details["parking_count"] == 1
    assert details["total_floors"] == 2
    assert details["city"] == "Chavanay"
    assert details["postal_code"] == "42410"
    assert details["location"] == "Chavanay (42410)"
    assert details["terrace"] is True
    assert details["garden"] is True
    assert details["pool"] is True
    assert details["cellar"] is True
    assert details["property_type"] == "Maison"
    assert details["agency_name"] == "IMMORÊVE"
    assert details["contact_phone"] == "04 37 04 32 17"
    assert details["contact_email"] == "contact@immoreve.fr"
    assert len(details["photo_urls"]) == 2
    assert "original" in details["photo_urls"][0]


def test_hektor_live_sample():
    scraper = HektorScraper()
    url = "https://www.immoreve.fr/admin/crm/index.php?uri=property&id=953&senderUserId=8&token=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ0eXBlIjoiZ3JhcGhxbF9wdWJsaWNfYWNjZXNzIiwiZW50aXRpZXMiOlt7InR5cGUiOiJQUk9QRVJUWSIsImlkcyI6WyI5NTMiXSwic2NvcGVzIjpbIlBST1BFUlRZX1BVQkxJQyJdfSx7InR5cGUiOiJVU0VSIiwiaWRzIjpbIjgiXSwic2NvcGVzIjpbIlVTRVJfUFVCTElDIl19XSwiaWF0IjoxNzg3NTcxMDMzLCJpc3MiOiJpbW1vcmV2ZSJ9.AtKcJb0NNCMpqOudkeXV6SjrKB2GORrOUXbgF4MwJmY"

    details = asyncio.run(scraper.get_listing_details(url))
    assert details.get("external_id") == "hektor_953"
    assert details.get("price") == 230000.0
    assert details.get("area") == 121.0
    assert details.get("rooms") == 4
    assert details.get("city") == "Saint-Alban-du-Rhône"
    assert details.get("postal_code") == "38370"
    assert len(details.get("photo_urls", [])) > 0

