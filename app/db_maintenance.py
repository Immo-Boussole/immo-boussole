from sqlalchemy.orm import Session
from typing import Optional
from app.models import Listing, ListingStatus, MapPin, Visit
from app.services import (
    refresh_listing_status,
    has_valid_local_photos,
    repair_listing_photos,
    is_missing_or_corrupt_photos,
    is_error_or_generic_title,
    repair_listing_title,
    is_search_page_title,
    is_valid_listing_url,
    split_or_purge_aggregate_listing
)
from app.database import SessionLocal
import asyncio
import re
from datetime import datetime, timezone


def _is_past_date(dt) -> bool:
    if not dt:
        return False
    if dt.tzinfo is not None:
        return dt < datetime.now(timezone.utc)
    return dt < datetime.now()


# Problem types
EMPTY_DESCRIPTION = "empty_description"
GENERIC_TITLE_FIGARO = "generic_title_figaro"
AGGREGATE_SEARCH_PAGE = "aggregate_search_page"
DUPLICATE_CITY_ZIP = "duplicate_city_zip"
ANOMALOUS_PRICE = "anomalous_price"
LINKED_ADS_NONE = "linked_ads_none"
MISSING_CITY_PINS = "missing_city_pins"
UNSTANDARDIZED_CITY = "unstandardized_city"
FORBIDDEN_DEPARTMENT = "forbidden_department"
FORBIDDEN_ZONE = "forbidden_zone"
INCORRECT_PRICE_PER_SQM = "incorrect_price_per_sqm"
MISSING_PHOTOS = "missing_photos"
PAST_FIRST_VISIT_NOT_DONE = "past_first_visit_not_done"



def identify_problems(db: Session):
    """
    Identifies problematic listings.
    Returns counts for each problem type and lists of IDs.
    """
    active_listings_all = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"])
    ).all()

    # Empty description
    empty_desc_listings = [
        l for l in active_listings_all if not l.description_text or not l.description_text.strip()
    ]
    
    # Generic / Error titles (e.g. "Annonce Le Figaro", "Annonce (...) - Erreur 403", "leboncoin.fr", etc.)
    generic_title_listings = [
        l for l in active_listings_all if is_error_or_generic_title(l.title)
    ]

    # Aggregate search pages (e.g. "685 Maisons à Vendre...", "Maisons en Vente", search URLs)
    all_listings_in_db = db.query(Listing).all()
    aggregate_search_listings = [
        l for l in all_listings_in_db if is_search_page_title(l.title) or (l.url and not is_valid_listing_url(l.url)[0])
    ]

    # Duplicate postal code in location (e.g., "Chavanay (42) (42)")
    # Broad SQL filter first
    dup_city_candidates = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"]),
        Listing.location.like("% (%) (%)")
    ).all()
    
    # Precise regex filter in Python
    duplicate_city_listings = []
    for l in dup_city_candidates:
        if l.location:
            # Matches " (42) (42)" at the end
            match = re.search(r'\s*\((\d{2,5})\)\s*\(\1\)$', l.location)
            if match:
                duplicate_city_listings.append(l)

    # Anomalous price (e.g. > 10M € or concatenated phone number)
    anomalous_price_listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"]),
        Listing.price > 10000000
    ).all()

    # Orphaned duplicates (is_duplicate=True but no parent)
    linked_ads_none_ids = [l.id for l in db.query(Listing).filter(
        Listing.is_duplicate == True,
        Listing.duplicate_of_id == None
    ).all()]

    # Missing city map pins
    cities_in_active_listings = db.query(Listing.city).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"]),
        Listing.city != None,
        Listing.city != ""
    ).distinct().all()
    
    existing_city_pins = db.query(MapPin).filter(MapPin.pin_type == "city").all()
    
    existing_pin_names = set()
    for pin in existing_city_pins:
        p_name = pin.title.lower().strip()
        existing_pin_names.add(p_name)
        # also match without postal code if there is one
        p_name_clean = re.sub(r'\s*\(\d+\)$', '', p_name).strip()
        existing_pin_names.add(p_name_clean)
        
    missing_city_names = []
    for (city_val,) in cities_in_active_listings:
        c_clean = city_val.strip()
        if not c_clean:
            continue
        c_lower = c_clean.lower()
        c_lower_clean = re.sub(r'\s*\(\d+\)$', '', c_lower).strip()
        if c_lower not in existing_pin_names and c_lower_clean not in existing_pin_names:
            missing_city_names.append(c_clean)
                
    # Unstandardized cities (missing official zip code or standardized format in either city or location)
    unstd_city_candidates = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"]),
        ((Listing.city != None) & (Listing.city != "")) | ((Listing.location != None) & (Listing.location != ""))
    ).all()
    unstd_city_listings = []
    for l in unstd_city_candidates:
        city_val = l.city.strip() if l.city else ""
        loc_val = l.location.strip() if l.location else ""
        
        city_ok = bool(city_val and re.match(r'^.+\s\(\d{5}\)$', city_val))
        loc_ok = bool(loc_val and re.match(r'^.+\s\(\d{5}\)$', loc_val))
        
        if not city_ok or not loc_ok:
            unstd_city_listings.append(l)

    # Forbidden Department
    forbidden_dept_listings = []
    from app.main import _is_city_in_allowed_departments
    active_listings_all = db.query(Listing).filter(Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"])).all()
    for l in empty_desc_listings + generic_title_listings + duplicate_city_listings + anomalous_price_listings + unstd_city_listings + active_listings_all:
        city_to_check = l.location or l.city
        if city_to_check and not _is_city_in_allowed_departments(city_to_check, db):
            if l not in forbidden_dept_listings:
                forbidden_dept_listings.append(l)

    # Forbidden Zones
    from app.models import ZoneRule
    from app.geo import is_city_in_forbidden_set
    forbidden_cities = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
        ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
    ).all()}
    forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
        ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
    ).all()}

    forbidden_zone_listings = []
    for l in active_listings_all:
        if l.to_visit:
            continue
        zone_match = False
        if l.city and is_city_in_forbidden_set(l.city, forbidden_cities):
            zone_match = True
        elif l.location and is_city_in_forbidden_set(l.location, forbidden_cities):
            zone_match = True
        elif forbidden_stations:
            s1 = (l.nearest_sncf_station or "").strip().lower()
            s2 = (l.second_sncf_station or "").strip().lower()
            if any(fs in s1 or fs == s1 for fs in forbidden_stations) or any(fs in s2 or fs == s2 for fs in forbidden_stations):
                zone_match = True

        if zone_match:
            forbidden_zone_listings.append(l)

    # Incorrect price per sqm
    incorrect_price_sqm_listings = []
    for l in active_listings_all:
        if l.price and l.area and l.price > 0 and l.area > 0:
            expected = round(l.price / l.area, 2)
            if l.price_per_sqm is None or l.price_per_sqm <= 0 or abs(l.price_per_sqm - expected) > 0.02:
                incorrect_price_sqm_listings.append(l)

    # Missing or corrupted photos
    missing_photos_listings = []
    for l in active_listings_all:
        if is_missing_or_corrupt_photos(l):
            missing_photos_listings.append(l)

    # Past 1st visits not marked as done / validated
    all_visits = db.query(Visit).all()
    past_first_visits = [
        v for v in all_visits
        if (v.step in ("1ere_visite", "1ère visite effectuée", "1ère Visite effectuée") or
            (v.step_family == "visite" and v.step in ("1ere_visite", None, "")))
        and v.status != "effectuee"
        and _is_past_date(v.scheduled_at)
    ]
    past_first_visit_listing_ids = list(dict.fromkeys(v.listing_id for v in past_first_visits if v.listing_id))

    return {
        EMPTY_DESCRIPTION: {
            "count": len(empty_desc_listings),
            "ids": [l.id for l in empty_desc_listings]
        },
        GENERIC_TITLE_FIGARO: {
            "count": len(generic_title_listings),
            "ids": [l.id for l in generic_title_listings]
        },
        AGGREGATE_SEARCH_PAGE: {
            "count": len(aggregate_search_listings),
            "ids": [l.id for l in aggregate_search_listings]
        },
        DUPLICATE_CITY_ZIP: {
            "count": len(duplicate_city_listings),
            "ids": [l.id for l in duplicate_city_listings]
        },
        ANOMALOUS_PRICE: {
            "count": len(anomalous_price_listings),
            "ids": [l.id for l in anomalous_price_listings]
        },
        LINKED_ADS_NONE: {
            "count": len(linked_ads_none_ids),
            "ids": linked_ads_none_ids
        },
        MISSING_CITY_PINS: {
            "count": len(missing_city_names),
            "ids": missing_city_names
        },
        UNSTANDARDIZED_CITY: {
            "count": len(unstd_city_listings),
            "ids": [l.id for l in unstd_city_listings]
        },
        FORBIDDEN_DEPARTMENT: {
            "count": len(forbidden_dept_listings),
            "ids": [l.id for l in forbidden_dept_listings]
        },
        FORBIDDEN_ZONE: {
            "count": len(forbidden_zone_listings),
            "ids": [l.id for l in forbidden_zone_listings]
        },
        INCORRECT_PRICE_PER_SQM: {
            "count": len(incorrect_price_sqm_listings),
            "ids": [l.id for l in incorrect_price_sqm_listings]
        },
        MISSING_PHOTOS: {
            "count": len(missing_photos_listings),
            "ids": [l.id for l in missing_photos_listings]
        },
        PAST_FIRST_VISIT_NOT_DONE: {
            "count": len(past_first_visits),
            "ids": past_first_visit_listing_ids
        }
    }


# Problem types that are safe for all authenticated users (non-destructive repairs)
SAFE_PROBLEM_TYPES = [
    EMPTY_DESCRIPTION,
    GENERIC_TITLE_FIGARO,
    AGGREGATE_SEARCH_PAGE,
    DUPLICATE_CITY_ZIP,
    ANOMALOUS_PRICE,
    LINKED_ADS_NONE,
    MISSING_CITY_PINS,
    UNSTANDARDIZED_CITY,
    INCORRECT_PRICE_PER_SQM,
    MISSING_PHOTOS,
    PAST_FIRST_VISIT_NOT_DONE,
]

# Problem types reserved for admins only (potentially destructive)
DANGEROUS_PROBLEM_TYPES = [
    FORBIDDEN_DEPARTMENT,
    FORBIDDEN_ZONE,
]


def _listing_summary(listing) -> dict:
    """Return a minimal dict with listing info for display in repair views."""
    return {
        "id": listing.id,
        "title": listing.title or "Sans titre",
        "city": listing.city or listing.location or "",
        "url": f"/listing/{listing.id}",
    }


def identify_problems_with_details(db: Session) -> dict:
    """
    Like identify_problems() but enriches each problem type with listing details
    (title, city, url) suitable for display in the user-facing repair view.
    MISSING_CITY_PINS is special: ids are city name strings, not listing IDs.
    """
    raw = identify_problems(db)
    result = {}

    for problem_type, data in raw.items():
        count = data["count"]
        ids = data["ids"]

        if problem_type == MISSING_CITY_PINS:
            # ids are city name strings
            listings_info = [
                {"id": None, "title": city, "city": city, "url": None}
                for city in ids
            ]
        else:
            # ids are listing IDs — fetch details in one query
            if ids:
                listings = db.query(Listing).filter(Listing.id.in_(ids)).all()
                id_to_listing = {l.id: l for l in listings}
                listings_info = [
                    _listing_summary(id_to_listing[lid])
                    for lid in ids
                    if lid in id_to_listing
                ]
            else:
                listings_info = []

        result[problem_type] = {
            "count": count,
            "ids": ids,
            "listings": listings_info,
        }

    return result


# Global state to track repair progress
repair_progress = {
    "total": 0,
    "processed": 0,
    "is_running": False,
    "problem_type": None
}

async def repair_listings_batch_task(problem_type: str, is_part_of_sequence: bool = False):
    """
    Background task to repair listings in batches.
    Manages its own database session.
    """
    global repair_progress
    
    db = SessionLocal()
    try:
        problems = identify_problems(db)
        if problem_type not in problems:
            if not is_part_of_sequence:
                repair_progress["is_running"] = False
            return

        ids_to_repair = problems[problem_type]["ids"]
        repair_progress["total"] = len(ids_to_repair)
        repair_progress["processed"] = 0
        if not is_part_of_sequence:
            repair_progress["is_running"] = True
        repair_progress["problem_type"] = problem_type

        # Update last repair timestamp in GlobalSettings
        from app.models import GlobalSettings
        from datetime import datetime, timezone
        import json
        settings = db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings()
            db.add(settings)
            db.commit()
            db.refresh(settings)
        
        try:
            repairs = json.loads(settings.last_repairs_json or "{}")
        except Exception:
            repairs = {}
        repairs[problem_type] = datetime.now(timezone.utc).isoformat()
        settings.last_repairs_json = json.dumps(repairs)
        db.commit()

        batch_size = 5
        delay_between_batches = 5
        
        for i in range(0, len(ids_to_repair), batch_size):
            batch_ids = ids_to_repair[i:i + batch_size]
            
            for lid in batch_ids:
                if problem_type == MISSING_CITY_PINS:
                    city_name = lid
                    try:
                        from app.services import ensure_city_map_pin
                        ensure_city_map_pin(city_name, db)
                    except Exception as e:
                        print(f"[DB Maintenance] Error creating map pin for city {city_name}: {e}")
                else:
                    listing = db.query(Listing).filter(Listing.id == lid).first()
                    if listing:
                        try:
                            if problem_type == LINKED_ADS_NONE:
                                # If it's a broken duplicate, reset the flag so it reappears in dashboard
                                listing.is_duplicate = False
                                db.commit()
                            elif problem_type == UNSTANDARDIZED_CITY:
                                from app.geo import standardize_and_enrich_city, get_coordinates
                                std_city, _, _ = standardize_and_enrich_city(listing.city or listing.location)
                                if std_city:
                                    listing.city = std_city
                                    listing.location = std_city
                                    # Also re-geocode
                                    coords = get_coordinates(std_city)
                                    if coords:
                                        listing.latitude, listing.longitude = coords
                                    db.commit()
                            elif problem_type == FORBIDDEN_DEPARTMENT:
                                listing.status = ListingStatus.REJECTED
                                db.commit()
                            elif problem_type == FORBIDDEN_ZONE:
                                if not listing.to_visit:
                                    listing.status = ListingStatus.REJECTED
                                    db.commit()
                            elif problem_type == INCORRECT_PRICE_PER_SQM:
                                listing.update_price_per_sqm()
                                db.commit()
                            elif problem_type == MISSING_PHOTOS:
                                await repair_listing_photos(listing, db)
                            elif problem_type == PAST_FIRST_VISIT_NOT_DONE:
                                visits_for_listing = db.query(Visit).filter(
                                    Visit.listing_id == lid,
                                    Visit.status != "effectuee"
                                ).all()
                                repaired_any = False
                                for v in visits_for_listing:
                                    if (v.step in ("1ere_visite", "1ère visite effectuée", "1ère Visite effectuée") or
                                        (v.step_family == "visite" and v.step in ("1ere_visite", None, ""))) and _is_past_date(v.scheduled_at):
                                        v.status = "effectuee"
                                        repaired_any = True
                                        try:
                                            from app import google_service
                                            google_service.sync_visit_to_google_calendar(db, v)
                                        except Exception as e:
                                            print(f"[DB Maintenance] Error syncing visit {v.id} to Google Calendar: {e}")
                                if repaired_any:
                                    from app.main import _derive_visit_status_from_visit
                                    latest_visit = db.query(Visit).filter(Visit.listing_id == lid).order_by(Visit.scheduled_at.desc()).first()
                                    if latest_visit:
                                        derived = _derive_visit_status_from_visit(latest_visit)
                                        if derived:
                                            listing.last_visit_status = derived
                                    db.commit()
                            elif problem_type == GENERIC_TITLE_FIGARO:
                                await repair_listing_title(listing, db)
                                await refresh_listing_status(listing, db, force_update=True)
                            elif problem_type == AGGREGATE_SEARCH_PAGE:
                                await split_or_purge_aggregate_listing(db, listing.id)
                            else:
                                await refresh_listing_status(listing, db, force_update=True)
                        except Exception as e:
                            print(f"[DB Maintenance] Error repairing listing {lid}: {e}")
                
                repair_progress["processed"] += 1
                db.commit()
                
            if i + batch_size < len(ids_to_repair):
                await asyncio.sleep(delay_between_batches)
    finally:
        if not is_part_of_sequence:
            repair_progress["is_running"] = False
        db.close()


async def repair_all_sequential_task():
    """
    Finds all outstanding problems, sorts them by count ASC (excluding 0 count),
    and repairs them sequentially one after another.
    """
    global repair_progress
    
    db = SessionLocal()
    try:
        problems = identify_problems(db)
        
        # Get list of (type, count) for types that have count > 0, sorted by count ascending
        sorted_types = sorted(
            [(k, v["count"]) for k, v in problems.items() if v["count"] > 0],
            key=lambda x: x[1]
        )
        
        if not sorted_types:
            repair_progress["is_running"] = False
            return
            
        print(f"[DB Maintenance] Starting sequential repair of all: {sorted_types}")
        
        repair_progress["is_running"] = True
        
        for p_type, count in sorted_types:
            await repair_listings_batch_task(p_type, is_part_of_sequence=True)
            await asyncio.sleep(2)
            
    finally:
        repair_progress["is_running"] = False
        db.close()

async def repair_selected_sequential_task(problem_types: list[str]):
    """
    Repairs the selected problem types sequentially one after another.
    """
    global repair_progress
    
    db = SessionLocal()
    try:
        if not problem_types:
            repair_progress["is_running"] = False
            return
            
        print(f"[DB Maintenance] Starting sequential repair of selected: {problem_types}")
        
        repair_progress["is_running"] = True
        
        for p_type in problem_types:
            await repair_listings_batch_task(p_type, is_part_of_sequence=True)
            await asyncio.sleep(1)
            
    finally:
        repair_progress["is_running"] = False
        db.close()


def get_repair_status():
    global repair_progress
    return repair_progress


def get_db_file_path() -> Optional[str]:
    """Resolves local SQLite file path from DATABASE_URL."""
    from app.config import settings
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "")
    return None


def get_db_stats() -> dict:
    """Calculates database file size, WAL size, and total SQLite footprint."""
    import os
    from app.media import format_bytes_human

    db_path = get_db_file_path()
    size_bytes = 0
    wal_size_bytes = 0
    if db_path and os.path.exists(db_path):
        size_bytes = os.path.getsize(db_path)
        wal_path = f"{db_path}-wal"
        if os.path.exists(wal_path):
            wal_size_bytes = os.path.getsize(wal_path)

    return {
        "db_size_bytes": size_bytes,
        "db_size_human": format_bytes_human(size_bytes),
        "wal_size_bytes": wal_size_bytes,
        "wal_size_human": format_bytes_human(wal_size_bytes),
        "total_db_size_bytes": size_bytes + wal_size_bytes,
        "total_db_size_human": format_bytes_human(size_bytes + wal_size_bytes),
    }


def optimize_sqlite_database() -> dict:
    """
    Executes SQLite database optimizations:
    1. VACUUM to defragment pages and reclaim unallocated disk space
    2. ANALYZE & PRAGMA optimize to refresh query planner statistics
    3. PRAGMA wal_checkpoint(TRUNCATE) to flush and truncate the WAL journal
    4. PRAGMA integrity_check to verify database health
    """
    import os
    import time
    import sqlite3
    from sqlalchemy import text
    from app.database import engine
    from app.media import format_bytes_human

    t0 = time.time()
    initial_stats = get_db_stats()
    initial_total = initial_stats["total_db_size_bytes"]

    integrity_result = "ok"

    db_path = get_db_file_path()
    if db_path and os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path, isolation_level=None)
            cursor = conn.cursor()
            cursor.execute("VACUUM;")
            cursor.execute("ANALYZE;")
            cursor.execute("PRAGMA optimize;")
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            cursor.execute("PRAGMA integrity_check;")
            row = cursor.fetchone()
            if row and row[0]:
                integrity_result = str(row[0])
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"[DB Maintenance] Error during SQLite VACUUM/optimize: {e}")
            integrity_result = f"error: {e}"
    else:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text("VACUUM;"))
                conn.execute(text("ANALYZE;"))
                conn.execute(text("PRAGMA optimize;"))
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
                res = conn.execute(text("PRAGMA integrity_check;")).scalar()
                if res:
                    integrity_result = str(res)
        except Exception as e:
            print(f"[DB Maintenance] Fallback optimize error: {e}")
            integrity_result = f"error: {e}"

    duration = round(time.time() - t0, 2)
    final_stats = get_db_stats()
    final_total = final_stats["total_db_size_bytes"]
    freed_bytes = max(0, initial_total - final_total)

    return {
        "status": "success" if "ok" in str(integrity_result).lower() else "warning",
        "integrity": integrity_result,
        "duration_seconds": duration,
        "initial_size_bytes": initial_total,
        "initial_size_human": format_bytes_human(initial_total),
        "final_size_bytes": final_total,
        "final_size_human": format_bytes_human(final_total),
        "freed_bytes": freed_bytes,
        "freed_human": format_bytes_human(freed_bytes),
    }


