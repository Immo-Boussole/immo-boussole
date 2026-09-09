import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure pytesseract is mocked if not installed
if "pytesseract" not in sys.modules:
    sys.modules["pytesseract"] = MagicMock()

import pytest
from fastapi.testclient import TestClient

from app.models import Listing, ListingStatus, Source
from app.db_maintenance import (
    evaluate_single_listing_health,
    apply_listing_repair_actions,
    identify_problems,
    repair_listings_batch_task,
    MISSING_COMPROMIS_TAG,
)
from app.main import app, login_required, user_required, admin_required
from app.database import SessionLocal, run_migrations, get_db


@pytest.fixture(scope="module", autouse=True)
def init_db():
    run_migrations()


def test_evaluate_single_listing_health_anomalies_and_clean():
    db = SessionLocal()

    try:
        # 1. Listing with multiple anomalies (missing photos, generic title, uncalculated price_sqm)
        l_anomaly = Listing(
            url="https://example.com/ad1",
            title="Annonce Le Figaro - Erreur 403",
            description_text="Charmante maison avec jardin.",
            price=200000.0,
            area=100.0,
            price_per_sqm=None,  # Anomaly: should be 2000
            city="Lyon (69001)",
            latitude=45.7640,
            longitude=4.8357,
            photos_local=None,  # Anomaly: missing photos
            status=ListingStatus.ACTIVE,
            source=Source.LEFIGARO,
        )
        db.add(l_anomaly)

        # 2. Clean healthy listing
        l_clean = Listing(
            url="https://example.com/ad2",
            title="Maison contemporaine 5 pièces",
            description_text="Belle maison familiale sans travaux.",
            price=300000.0,
            area=150.0,
            price_per_sqm=2000,
            city="Lyon (69001)",
            latitude=45.7640,
            longitude=4.8357,
            nearest_sncf_station="Gare de Lyon-Part-Dieu",
            walk_time_sncf=15,
            photos_local='["static/media/dummy/photo_0.jpg"]',
            status=ListingStatus.ACTIVE,
            source=Source.LEBONCOIN,
        )
        db.add(l_clean)
        db.commit()
        db.refresh(l_anomaly)
        db.refresh(l_clean)

        # Mock disk file existence for clean listing photos
        with patch("app.db_maintenance.is_missing_or_corrupt_photos", return_value=False):
            health_anomaly = evaluate_single_listing_health(l_anomaly, db)
            health_clean = evaluate_single_listing_health(l_clean, db)

        # Asserts for anomalous listing
        assert health_anomaly["is_healthy"] is False
        assert health_anomaly["anomaly_count"] >= 2
        assert health_anomaly["actions"]["title"]["is_anomaly"] is True
        assert health_anomaly["actions"]["price_sqm"]["is_anomaly"] is True

        # Asserts for clean listing
        assert health_clean["is_healthy"] is True
        assert health_clean["anomaly_count"] == 0
        assert health_clean["actions"]["title"]["is_anomaly"] is False
        assert health_clean["actions"]["price_sqm"]["is_anomaly"] is False

    finally:
        # Cleanup
        try:
            db.query(Listing).filter(Listing.url.in_(["https://example.com/ad1", "https://example.com/ad2"])).delete(synchronize_session=False)
            db.commit()
        except Exception:
            pass
        db.close()


@pytest.mark.asyncio
async def test_apply_listing_repair_actions():
    db = SessionLocal()

    try:
        l = Listing(
            url="https://example.com/ad3",
            title="Maison de plain-pied",
            description_text="Beau séjour, cuisine ouverte.",
            price=180000.0,
            area=90.0,
            price_per_sqm=None,  # Missing price_sqm
            city="Valence (26000)",
            latitude=44.9333,
            longitude=4.8917,
            status=ListingStatus.ACTIVE,
            source=Source.LEBONCOIN,
        )
        db.add(l)
        db.commit()
        db.refresh(l)

        # Apply price_sqm repair action
        res = await apply_listing_repair_actions(l.id, ["price_sqm"], db)
        assert res["success"] is True
        assert "price_sqm" in res["repaired_actions"]

        db.refresh(l)
        assert l.price_per_sqm == 2000
        assert res["health"]["actions"]["price_sqm"]["is_anomaly"] is False

    finally:
        try:
            db.query(Listing).filter(Listing.url == "https://example.com/ad3").delete(synchronize_session=False)
            db.commit()
        except Exception:
            pass
        db.close()


def test_api_health_endpoints_integration():
    db = SessionLocal()

    try:
        l1 = Listing(
            url="https://example.com/api-test-1",
            title="Villa avec piscine Grenoble",
            description_text="Superbe villa.",
            price=450000.0,
            area=150.0,
            city="Grenoble (38000)",
            status=ListingStatus.ACTIVE,
            source=Source.LEBONCOIN,
        )
        db.add(l1)
        db.commit()
        db.refresh(l1)

        app.dependency_overrides[login_required] = lambda: {"username": "tester", "role": "admin"}
        app.dependency_overrides[user_required] = lambda: {"username": "tester", "role": "admin"}
        app.dependency_overrides[admin_required] = lambda: {"username": "tester", "role": "admin"}

        client = TestClient(app)

        # 1. Test Search Endpoint
        res_search = client.get("/api/listings/health/search?q=Grenoble")
        assert res_search.status_code == 200
        search_data = res_search.json()
        assert search_data["total"] >= 1
        found_target = any(r["listing_id"] == l1.id for r in search_data["results"])
        assert found_target is True

        # 2. Test Quick-List Endpoint
        res_quick = client.get("/api/listings/health/quick-list?filter_type=all")
        assert res_quick.status_code == 200
        quick_data = res_quick.json()
        assert quick_data["total"] >= 1

        # 3. Test Single Health Endpoint
        res_single = client.get(f"/api/listings/{l1.id}/health")
        assert res_single.status_code == 200
        single_data = res_single.json()
        assert single_data["listing_id"] == l1.id
        assert "actions" in single_data

        # 4. Test Repair Actions Endpoint
        res_repair = client.post(
            f"/api/listings/{l1.id}/repair-actions",
            json={"actions": ["price_sqm"]}
        )
        assert res_repair.status_code == 200
        repair_data = res_repair.json()
        assert repair_data["success"] is True
        assert "price_sqm" in repair_data["repaired_actions"]

        # 5. Test Bulk Repair Endpoint
        res_bulk = client.post(
            "/api/listings/health/bulk-repair",
            json={"items": [{"listing_id": l1.id, "actions": ["price_sqm"]}]}
        )
        assert res_bulk.status_code == 200
        bulk_data = res_bulk.json()
        assert bulk_data["success"] is True
        assert len(bulk_data["results"]) >= 1

    finally:
        app.dependency_overrides.clear()
        try:
            db.query(Listing).filter(Listing.url == "https://example.com/api-test-1").delete(synchronize_session=False)
            db.commit()
        except Exception:
            pass
        db.close()


@pytest.mark.asyncio
async def test_missing_compromis_tag_detection_and_repair():
    db = SessionLocal()
    try:
        l_comp = Listing(
            url="https://example.com/ad-compromis-test",
            title="Maison de village avec terrasse",
            description_text="Vente urgente : bien actuellement sous compromis de vente.",
            price=150000.0,
            area=80.0,
            city="Vienne (38200)",
            status=ListingStatus.ACTIVE,
            source=Source.LEBONCOIN,
            is_under_compromis=False,
            compromis_detected_by=None,
        )
        db.add(l_comp)
        db.commit()
        db.refresh(l_comp)

        # 1. Check identify_problems detects the missing compromis tag
        problems = identify_problems(db, hide_rejected=True)
        assert MISSING_COMPROMIS_TAG in problems
        assert l_comp.id in problems[MISSING_COMPROMIS_TAG]["ids"]

        # 2. Repair via batch task
        await repair_listings_batch_task(MISSING_COMPROMIS_TAG, hide_rejected=True)

        # 3. Verify listing is now tagged
        db.refresh(l_comp)
        assert l_comp.is_under_compromis is True
        assert l_comp.compromis_detected_by == "description"

        # 4. Check identify_problems again: listing no longer present
        problems_after = identify_problems(db, hide_rejected=True)
        assert l_comp.id not in problems_after[MISSING_COMPROMIS_TAG]["ids"]

    finally:
        try:
            db.query(Listing).filter(Listing.url == "https://example.com/ad-compromis-test").delete(synchronize_session=False)
            db.commit()
        except Exception:
            pass
        db.close()


if __name__ == "__main__":
    test_evaluate_single_listing_health_anomalies_and_clean()
    import asyncio
    asyncio.run(test_apply_listing_repair_actions())
    test_api_health_endpoints_integration()
    asyncio.run(test_missing_compromis_tag_detection_and_repair())
    print("ALL LISTING HEALTH & REPAIR TESTS PASSED!")

