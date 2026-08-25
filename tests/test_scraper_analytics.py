import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base
from app.models import Listing, ListingStatus, Source, User
from app.main import app, get_db
from app.scraper_analytics import (
    compute_scraper_analytics,
    get_scraper_analytics,
    clear_scraper_analytics_cache,
    _calculate_percentiles,
    _has_html_residue,
    _has_duplicate_zip,
    _is_valid_dpe,
    _is_city_standardized,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_percentile_calculations():
    # Empty list
    res_empty = _calculate_percentiles([])
    assert res_empty["min"] is None
    assert res_empty["median"] is None

    # Single value
    res_single = _calculate_percentiles([100.0])
    assert res_single["min"] == 100.0
    assert res_single["max"] == 100.0
    assert res_single["median"] == 100.0
    assert res_single["iqr"] == 0.0

    # Multiple values
    vals = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
    res = _calculate_percentiles(vals)
    assert res["min"] == 1000.0
    assert res["max"] == 5000.0
    assert res["median"] == 3000.0
    assert res["q25"] == 2000.0
    assert res["q75"] == 4000.0
    assert res["iqr"] == 2000.0


def test_helper_validators():
    # HTML residue
    assert _has_html_residue("<div>Texte avec balise</div>") is True
    assert _has_html_residue("Belle maison de plain-pied avec jardin.") is False
    assert _has_html_residue("Prix net &nbsp; vendeur") is True

    # Duplicate zip
    assert _has_duplicate_zip("Chavanay (42) (42)") is True
    assert _has_duplicate_zip("Lyon 2e Arrondissement (69002)") is False

    # Valid DPE
    assert _is_valid_dpe("D") is True
    assert _is_valid_dpe("A") is True
    assert _is_valid_dpe("NC") is False
    assert _is_valid_dpe(None) is False

    # Standardized city
    assert _is_city_standardized("Condrieu (69420)") is True
    assert _is_city_standardized("Condrieu") is False
    assert _is_city_standardized(None) is False


def test_compute_scraper_analytics(db_session):
    clear_scraper_analytics_cache()
    now = datetime.now(timezone.utc)

    # 1. Healthy LeBonCoin listing
    lbc_healthy = Listing(
        url="https://leboncoin.fr/1",
        external_id="lbc-1",
        title="Maison T4 avec grand jardin",
        source=Source.LEBONCOIN,
        status=ListingStatus.ACTIVE,
        price=250000.0,
        area=100.0,
        price_per_sqm=2500.0,
        city="Chavanay (42410)",
        location="Chavanay (42410)",
        dpe_rating="C",
        ges_rating="C",
        rooms=4,
        bedrooms=3,
        description_text="Belle maison familiale de 100m² sans travaux avec garage.",
        photos_local='["photo1.jpg", "photo2.jpg"]',
        date_added=now - timedelta(days=2),
    )

    # 2. Defective SeLoger listing (missing DPE, generic title, html residue, price outlier)
    seloger_defective = Listing(
        url="https://seloger.com/2",
        external_id="seloger-2",
        title="Annonce SeLoger - Erreur 403",
        source=Source.SELOGER,
        status=ListingStatus.ACTIVE,
        price=15000000.0, # Phone number error
        area=5.0,        # Outlier area < 9
        price_per_sqm=3000000.0,
        city="Paris",    # Non-standardized
        location="Paris (75) (75)", # Duplicate zip
        dpe_rating=None,
        ges_rating=None,
        rooms=0,
        description_text="<p>Annonce brute sans DPE</p>",
        photos_local=None,
        date_added=now - timedelta(days=1),
    )

    db_session.add_all([lbc_healthy, seloger_defective])
    db_session.commit()

    analytics = compute_scraper_analytics(db_session)

    assert analytics["summary"]["total_listings"] == 2
    assert analytics["summary"]["active_listings"] == 2

    # Verify Leboncoin stats
    lbc_stats = analytics["scrapers"]["leboncoin"]
    assert lbc_stats["counts"]["total"] == 1
    assert lbc_stats["counts"]["active"] == 1
    assert lbc_stats["health"]["score"] >= 80.0
    assert lbc_stats["health"]["status"] == "healthy"
    assert lbc_stats["completeness_rates"]["price"] == 100.0
    assert lbc_stats["completeness_rates"]["energy_class"] == 100.0

    # Verify SeLoger stats
    seloger_stats = analytics["scrapers"]["seloger"]
    assert seloger_stats["counts"]["total"] == 1
    assert seloger_stats["health"]["status"] in ("broken", "degraded")
    assert seloger_stats["anomalies"]["generic_titles"]["count"] == 1
    assert seloger_stats["anomalies"]["missing_dpe"]["count"] == 1
    assert seloger_stats["anomalies"]["html_residue"]["count"] == 1
    assert seloger_stats["anomalies"]["duplicate_city_zip"]["count"] == 1
    assert seloger_stats["anomalies"]["price_outliers"]["count"] == 1
    assert seloger_stats["anomalies"]["area_outliers"]["count"] == 1


def test_flux_drop_detection(db_session):
    clear_scraper_analytics_cache()
    now = datetime.now(timezone.utc)

    # Add 30 listings in previous 30 days (1/day) on Hektor
    for i in range(15):
        l = Listing(
            url=f"https://hektor.immo/prev-{i}",
            external_id=f"hek-prev-{i}",
            title=f"Maison {i}",
            source=Source.HEKTOR,
            status=ListingStatus.ACTIVE,
            price=200000.0,
            area=80.0,
            price_per_sqm=2500.0,
            city="Vienne (38200)",
            dpe_rating="D",
            photos_local='["p.jpg"]',
            description_text="Maison de ville avec cour et garage sans travaux.",
            date_added=now - timedelta(days=15 + i),
        )
        db_session.add(l)

    # Only 0 or 1 listing in the last 7 days -> should trigger flux drop warning
    l_recent = Listing(
        url="https://hektor.immo/rec-1",
        external_id="hek-rec-1",
        title="Maison recente",
        source=Source.HEKTOR,
        status=ListingStatus.ACTIVE,
        price=210000.0,
        area=85.0,
        price_per_sqm=2470.0,
        city="Vienne (38200)",
        dpe_rating="D",
        photos_local='["p.jpg"]',
        description_text="Maison contemporaine avec jardin et vue dégagée.",
        date_added=now - timedelta(days=1),
    )
    db_session.add(l_recent)
    db_session.commit()

    analytics = compute_scraper_analytics(db_session)
    hektor_stats = analytics["scrapers"]["hektor"]
    assert hektor_stats["counts"]["flux_drop_warning"] is True
    assert hektor_stats["health"]["status"] in ("degraded", "broken")


def test_reparse_endpoint(db_session):
    clear_scraper_analytics_cache()

    from app.main import login_required
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[login_required] = lambda: None

    # Create listing with generic title
    l = Listing(
        url="https://lefigaro.fr/fig-1",
        external_id="fig-1",
        title="Annonce Le Figaro",
        source=Source.LEFIGARO,
        status=ListingStatus.ACTIVE,
        price=300000.0,
        area=100.0,
        price_per_sqm=3000.0,
        city="Lyon (69000)",
        dpe_rating="C",
        photos_local=None,
        description_text="Superbe appartement 4 pièces lumineux.",
    )
    db_session.add(l)
    db_session.commit()
    db_session.refresh(l)

    client = TestClient(app)
    res = client.post(f"/api/scrapers/reparse-listing/{l.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["listing_id"] == l.id

    # 404 for non-existent
    res_404 = client.post("/api/scrapers/reparse-listing/999999")
    assert res_404.status_code == 404

    app.dependency_overrides.clear()


def test_cache_and_endpoints(db_session):
    clear_scraper_analytics_cache()

    from app.main import login_required
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[login_required] = lambda: None

    # Create dummy listing
    l = Listing(
        url="https://bienici.com/10",
        external_id="bi-10",
        title="Appartement T2 lumineux",
        source=Source.BIENICI,
        status=ListingStatus.ACTIVE,
        price=180000.0,
        area=50.0,
        price_per_sqm=3600.0,
        city="Lyon 7e Arrondissement (69007)",
        dpe_rating="D",
        photos_local='["p1.jpg"]',
        description_text="Appartement traversant et lumineux au 2ème étage.",
    )
    db_session.add(l)
    db_session.commit()
    db_session.refresh(l)

    client = TestClient(app)

    # Check get_scraper_analytics caching
    data1 = get_scraper_analytics(db_session, force_refresh=False)
    data2 = get_scraper_analytics(db_session, force_refresh=False)
    assert data1["generated_at"] == data2["generated_at"]

    # Force refresh updates
    data3 = get_scraper_analytics(db_session, force_refresh=True)
    assert "summary" in data3
    assert data3["summary"]["total_listings"] >= 1

    # Test GET /api/scrapers/analytics
    res = client.get("/api/scrapers/analytics")
    assert res.status_code == 200
    api_data = res.json()
    assert "summary" in api_data
    assert "scrapers" in api_data

    app.dependency_overrides.clear()


