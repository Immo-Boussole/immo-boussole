import os
import shutil
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.database import SessionLocal, engine, run_migrations
from app import models
from app.models import Listing, ListingStatus, ListingAttachment, GlobalSettings, User
from app.media import get_storage_metrics, purge_orphaned_and_rejected_media, MEDIA_BASE_DIR
from app.db_maintenance import optimize_sqlite_database, get_db_stats
from app.scheduler import nightly_system_maintenance_job, sync_db_maintenance_jobs
from apscheduler.schedulers.background import BackgroundScheduler


@pytest.fixture
def db_session():
    run_migrations()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_storage_metrics_and_purge(db_session):
    # Ensure test media dir structure
    test_media_dir = MEDIA_BASE_DIR
    test_media_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create an active listing
    active_listing = Listing(
        title="Appartement Lyon Actif",
        url="https://test.example.com/actif",
        status=ListingStatus.ACTIVE,
        price=250000.0,
        area=65.0,
        city="Lyon",
    )
    db_session.add(active_listing)
    db_session.commit()
    db_session.refresh(active_listing)

    # 2. Create a rejected listing
    rejected_listing = Listing(
        title="Maison Rejetée",
        url="https://test.example.com/rejetee",
        status=ListingStatus.REJECTED,
        price=150000.0,
        area=80.0,
        city="Saint-Étienne",
        photos_local='["static/media/' + str(999999) + '/photo_0.jpg"]',
    )
    db_session.add(rejected_listing)
    db_session.commit()
    db_session.refresh(rejected_listing)

    # Populate media directories
    active_dir = test_media_dir / str(active_listing.id)
    active_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "photo_0.jpg").write_bytes(b"active photo content 12345")

    # Add attachment to active listing
    att_dir = active_dir / "attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    valid_att_file = att_dir / "doc_valid.pdf"
    valid_att_file.write_bytes(b"valid doc content")
    orphaned_att_file = att_dir / "doc_orphan.pdf"
    orphaned_att_file.write_bytes(b"orphan doc content")

    att_row = ListingAttachment(
        listing_id=active_listing.id,
        filename="doc_valid.pdf",
        original_filename="doc_valid.pdf",
        file_path=f"static/media/{active_listing.id}/attachments/doc_valid.pdf",
        file_type="pdf",
        title="Document Valide",
    )
    db_session.add(att_row)
    db_session.commit()

    # Rejected listing directory
    rejected_dir = test_media_dir / str(rejected_listing.id)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    (rejected_dir / "photo_0.jpg").write_bytes(b"rejected photo content")

    # Orphaned directory (listing ID 8888888 does not exist in DB)
    orphaned_lid = 8888888
    orphan_dir = test_media_dir / str(orphaned_lid)
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "photo_orphan.jpg").write_bytes(b"orphan photo content 98765")

    # Audit storage metrics
    metrics = get_storage_metrics(db_session)
    assert metrics["orphaned_dirs_count"] >= 1
    assert metrics["rejected_listings_count"] >= 1
    assert metrics["reclaimable_size_bytes"] > 0

    # Purge orphaned and rejected media
    purge_res = purge_orphaned_and_rejected_media(db_session, purge_rejected=True)
    assert purge_res["purged_orphaned_dirs"] >= 1
    assert purge_res["purged_rejected_listings"] >= 1
    assert purge_res["freed_bytes"] > 0

    # Verify orphan directory is gone
    assert not orphan_dir.exists()
    # Verify rejected directory is gone
    assert not rejected_dir.exists()
    # Verify rejected listing in DB now has photos_local cleared
    db_session.refresh(rejected_listing)
    assert rejected_listing.photos_local in ("[]", None)

    # Verify active listing files are still intact
    assert active_dir.exists()
    assert (active_dir / "photo_0.jpg").exists()
    assert valid_att_file.exists()
    assert not orphaned_att_file.exists()

    # Clean up test records
    db_session.delete(att_row)
    db_session.delete(active_listing)
    db_session.delete(rejected_listing)
    db_session.commit()
    shutil.rmtree(active_dir, ignore_errors=True)


def test_sqlite_optimization():
    stats_before = get_db_stats()
    assert "total_db_size_bytes" in stats_before
    assert "total_db_size_human" in stats_before

    res = optimize_sqlite_database()
    assert res["status"] in ("success", "warning")
    assert "ok" in res["integrity"].lower() or "error" not in res["integrity"].lower()
    assert res["duration_seconds"] >= 0


def test_nightly_maintenance_job_execution(db_session):
    # Ensure GlobalSettings exists
    settings = db_session.query(GlobalSettings).first()
    if not settings:
        settings = GlobalSettings()
        db_session.add(settings)
        db_session.commit()
        db_session.refresh(settings)

    # Run the nightly maintenance job
    nightly_system_maintenance_job()

    db_session.refresh(settings)
    assert settings.last_storage_cleanup is not None
    assert settings.last_db_optimization is not None
    assert settings.last_maintenance_metrics_json is not None


def test_scheduler_sync_nightly_job(db_session):
    scheduler = BackgroundScheduler()
    settings = db_session.query(GlobalSettings).first()
    if not settings:
        settings = GlobalSettings()
        db_session.add(settings)

    settings.auto_maintenance_enabled = True
    settings.auto_maintenance_time = "03:30"
    db_session.commit()

    sync_db_maintenance_jobs(scheduler)
    job = scheduler.get_job("nightly_system_maintenance_job")
    assert job is not None

    # Disable maintenance job
    settings.auto_maintenance_enabled = False
    db_session.commit()

    sync_db_maintenance_jobs(scheduler)
    job_disabled = scheduler.get_job("nightly_system_maintenance_job")
    assert job_disabled is None


def test_http_gzip_and_cache_headers():
    from app.main import app
    client = TestClient(app)

    # Test static Cache-Control
    resp = client.get("/favicon.ico")
    # For /static/ or /favicon.ico
    resp_static = client.get("/static/manifest.json")
    if resp_static.status_code == 200:
        assert "Cache-Control" in resp_static.headers
        assert "max-age=86400" in resp_static.headers["Cache-Control"]

    # Test GZip header acceptance on large responses
    resp_gzip = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert resp_gzip.status_code in (200, 302, 307)
