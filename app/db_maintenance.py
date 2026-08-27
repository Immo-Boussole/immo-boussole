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
MISSING_LOCATION = "missing_location"
FORBIDDEN_DEPARTMENT = "forbidden_department"
FORBIDDEN_ZONE = "forbidden_zone"
INCORRECT_PRICE_PER_SQM = "incorrect_price_per_sqm"
MISSING_PHOTOS = "missing_photos"
PAST_FIRST_VISIT_NOT_DONE = "past_first_visit_not_done"


def is_missing_location(listing) -> bool:
    """Checks if a listing lacks city and location data."""
    c = (listing.city or "").strip()
    loc = (listing.location or "").strip()
    placeholders = {"inconnu", "unknown", "france", "none", "null", "undefined", ""}
    return c.lower() in placeholders and loc.lower() in placeholders



def identify_problems(db: Session, hide_rejected: bool = True):
    """
    Identifies problematic listings.
    If hide_rejected is True (default), only active/new listings are analyzed.
    If hide_rejected is False, all listings (including rejected) are analyzed.
    Returns counts for each problem type and lists of IDs.
    """
    if hide_rejected:
        target_listings = db.query(Listing).filter(
            Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"])
        ).all()
    else:
        target_listings = db.query(Listing).all()

    target_listing_ids = {l.id for l in target_listings}

    # Empty description
    empty_desc_listings = [
        l for l in target_listings if not l.description_text or not l.description_text.strip()
    ]
    
    # Generic / Error titles (e.g. "Annonce Le Figaro", "Annonce (...) - Erreur 403", "leboncoin.fr", etc.)
    generic_title_listings = [
        l for l in target_listings if is_error_or_generic_title(l.title)
    ]

    # Aggregate search pages (e.g. "685 Maisons à Vendre...", "Maisons en Vente", search URLs)
    aggregate_search_listings = [
        l for l in target_listings if is_search_page_title(l.title) or (l.url and not is_valid_listing_url(l.url)[0])
    ]

    # Duplicate postal code in location (e.g., "Chavanay (42) (42)")
    duplicate_city_listings = []
    for l in target_listings:
        if l.location and (" (" in l.location):
            match = re.search(r'\s*\((\d{2,5})\)\s*\(\1\)$', l.location)
            if match:
                duplicate_city_listings.append(l)

    # Anomalous price (e.g. > 10M € or concatenated phone number)
    anomalous_price_listings = [
        l for l in target_listings if l.price and l.price > 10000000
    ]

    # Orphaned duplicates (is_duplicate=True but no parent)
    linked_ads_none_ids = [
        l.id for l in target_listings
        if l.is_duplicate and l.duplicate_of_id is None
    ]

    # Missing city map pins
    cities_in_target_listings = {
        l.city.strip() for l in target_listings
        if l.city and l.city.strip()
    }
    
    existing_city_pins = db.query(MapPin).filter(MapPin.pin_type == "city").all()
    
    existing_pin_names = set()
    for pin in existing_city_pins:
        p_name = pin.title.lower().strip()
        existing_pin_names.add(p_name)
        # also match without postal code if there is one
        p_name_clean = re.sub(r'\s*\(\d+\)$', '', p_name).strip()
        existing_pin_names.add(p_name_clean)
        
    missing_city_names = []
    missing_city_pin_listing_ids = []
    for city_val in cities_in_target_listings:
        c_lower = city_val.lower()
        c_lower_clean = re.sub(r'\s*\(\d+\)$', '', c_lower).strip()
        if c_lower not in existing_pin_names and c_lower_clean not in existing_pin_names:
            missing_city_names.append(city_val)
            # collect listing IDs for this city (for repair_tags tagging)
            for l in target_listings:
                if l.city and l.city.strip() == city_val:
                    missing_city_pin_listing_ids.append(l.id)
                
    # Unstandardized cities (missing official zip code or standardized format in either city or location)
    unstd_city_listings = []
    for l in target_listings:
        if (l.city and l.city.strip()) or (l.location and l.location.strip()):
            city_val = l.city.strip() if l.city else ""
            loc_val = l.location.strip() if l.location else ""
            
            city_ok = bool(city_val and re.match(r'^.+\s\(\d{5}\)$', city_val))
            loc_ok = bool(loc_val and re.match(r'^.+\s\(\d{5}\)$', loc_val))
            
            if not city_ok or not loc_ok:
                unstd_city_listings.append(l)

    # Forbidden Department
    forbidden_dept_listings = []
    from app.main import _is_city_in_allowed_departments
    for l in target_listings:
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
    for l in target_listings:
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
    for l in target_listings:
        if l.price and l.area and l.price > 0 and l.area > 0:
            expected = round(l.price / l.area, 2)
            if l.price_per_sqm is None or l.price_per_sqm <= 0 or abs(l.price_per_sqm - expected) > 0.02:
                incorrect_price_sqm_listings.append(l)

    # Missing location (city and location are empty or placeholders)
    missing_loc_listings = [
        l for l in target_listings if is_missing_location(l)
    ]

    # Missing or corrupted photos
    missing_photos_listings = []
    for l in target_listings:
        if is_missing_or_corrupt_photos(l):
            missing_photos_listings.append(l)

    # Past 1st visits not marked as done / validated
    all_visits = db.query(Visit).all()
    past_first_visits = [
        v for v in all_visits
        if (not hide_rejected or v.listing_id in target_listing_ids)
        and (v.step in ("1ere_visite", "1ère visite effectuée", "1ère Visite effectuée") or
            (v.step_family == "visite" and v.step in ("1ere_visite", None, "")))
        and v.status != "effectuee"
        and _is_past_date(v.scheduled_at)
    ]
    past_first_visit_listing_ids = list(dict.fromkeys(v.listing_id for v in past_first_visits if v.listing_id))

    result = {
        MISSING_LOCATION: {
            "count": len(missing_loc_listings),
            "ids": [l.id for l in missing_loc_listings]
        },
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
            "ids": missing_city_names,  # city name strings (for display)
            "listing_ids": missing_city_pin_listing_ids,  # actual listing IDs (for repair_tags)
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

    # ── Update repair_tags on each listing ────────────────────────────────────
    # Build a mapping: listing_id -> set of active error types
    import json as _json
    repair_tags_by_id: dict[int, list[str]] = {}

    for problem_type, data in result.items():
        # Use listing_ids for missing_city_pins (not city name strings)
        if problem_type == MISSING_CITY_PINS:
            ids = data.get("listing_ids", [])
        else:
            ids = data.get("ids", [])

        for lid in ids:
            if not isinstance(lid, int):
                continue
            if lid not in repair_tags_by_id:
                repair_tags_by_id[lid] = []
            if problem_type not in repair_tags_by_id[lid]:
                repair_tags_by_id[lid].append(problem_type)

    # Apply to all target listings (clear tags for listings with no errors)
    try:
        for listing in target_listings:
            new_tags = repair_tags_by_id.get(listing.id, [])
            new_tags_json = _json.dumps(new_tags) if new_tags else None
            if listing.repair_tags != new_tags_json:
                listing.repair_tags = new_tags_json
        db.commit()
    except Exception as e:
        print(f"[identify_problems] Warning: could not update repair_tags: {e}")
        db.rollback()

    return result



# Problem types that are safe for all authenticated users (non-destructive repairs)
SAFE_PROBLEM_TYPES = [
    MISSING_LOCATION,
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
    photo_url = None
    all_photos = []
    if listing.photos_local:
        try:
            import json
            photos = json.loads(listing.photos_local)
            if photos and isinstance(photos, list):
                all_photos = [p for p in photos if p]
                if len(all_photos) > 0:
                    photo_url = all_photos[0]
        except Exception:
            pass
    if not photo_url and listing.original_photo_urls:
        try:
            import json
            photos = json.loads(listing.original_photo_urls)
            if photos and isinstance(photos, list):
                if not all_photos:
                    all_photos = [p for p in photos if p]
                if len(all_photos) > 0 and not photo_url:
                    photo_url = all_photos[0]
        except Exception:
            pass

    status_val = listing.status.value if hasattr(listing.status, "value") else str(listing.status or "")

    return {
        "id": listing.id,
        "title": listing.title or "Sans titre",
        "city": listing.city or listing.location or "",
        "url": f"/listing/{listing.id}",
        "original_url": listing.original_url or listing.url or "",
        "source": listing.source.value if hasattr(listing.source, "value") else str(listing.source or ""),
        "price": listing.price,
        "area": listing.area,
        "rooms": listing.rooms,
        "property_type": listing.property_type,
        "description": listing.description_text or "",
        "photo": photo_url,
        "photos": all_photos,
        "status": status_val,
    }


def get_missing_location_summary(db: Session, current_user = None) -> dict:
    """
    Returns statistics and state for missing location notification overlay:
    - total count of affected listings
    - delta since user's last connection
    - distribution per source portal
    - snooze status
    - pre-filled GitHub issue URL
    """
    active_listings_all = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"])
    ).all()

    missing_loc_listings = [l for l in active_listings_all if is_missing_location(l)]
    total_count = len(missing_loc_listings)

    # Source breakdown
    sources_breakdown = {}
    for l in missing_loc_listings:
        src = l.source.value if hasattr(l.source, "value") else str(l.source or "inconnu")
        sources_breakdown[src] = sources_breakdown.get(src, 0) + 1

    # Check user snooze and delta
    is_snoozed = False
    prev_count = 0
    delta = total_count
    if current_user:
        prev_count = getattr(current_user, "last_seen_missing_loc_count", 0) or 0
        delta = total_count - prev_count
        snooze_until = getattr(current_user, "missing_loc_snooze_until", None)
        if snooze_until:
            now_utc = datetime.now(timezone.utc)
            if snooze_until.tzinfo is None:
                snooze_until = snooze_until.replace(tzinfo=timezone.utc)
            if snooze_until > now_utc:
                is_snoozed = True

    # Pre-filled GitHub issue URL with diagnostic report
    sources_str = ", ".join([f"{k}: {v}" for k, v in sources_breakdown.items()]) if sources_breakdown else "N/A"
    issue_title = f"[Scraping] Erreur de localisation manquante ({total_count} annonce{'s' if total_count > 1 else ''})"
    issue_body = (
        f"### Description du problème\n\n"
        f"Le scraping n'a pas pu extraire la localisation (ville / code postal) pour **{total_count} annonce(s)** active(s).\n\n"
        f"**Répartition par portail :**\n{sources_str}\n\n"
        f"### Impact\n"
        f"- Les règles de filtrage par départements et zones interdites ne peuvent pas être appliquées automatiquement.\n"
        f"- Le positionnement cartographique et le calcul des temps de trajet sont indisponibles.\n\n"
        f"---\n*Signalé automatiquement depuis l'instance Immo-Boussole.*"
    )
    import urllib.parse
    params = {
        "title": issue_title,
        "body": issue_body,
        "labels": "bug,scraping"
    }
    github_issue_url = f"https://github.com/Immo-Boussole/immo-boussole/issues/new?{urllib.parse.urlencode(params)}"

    return {
        "count": total_count,
        "prev_count": prev_count,
        "delta": delta,
        "sources": sources_breakdown,
        "is_snoozed": is_snoozed,
        "github_issue_url": github_issue_url,
    }


def identify_problems_with_details(db: Session, hide_rejected: bool = True) -> dict:
    """
    Like identify_problems() but enriches each problem type with listing details
    (title, city, url, status) suitable for display in the user-facing repair view.
    MISSING_CITY_PINS is special: ids are city name strings, not listing IDs.
    """
    raw = identify_problems(db, hide_rejected=hide_rejected)
    result = {}

    for problem_type, data in raw.items():
        count = data["count"]
        ids = data["ids"]

        if problem_type == MISSING_CITY_PINS:
            # ids are city name strings; listing_ids are actual listing IDs
            listing_ids_for_cities = data.get("listing_ids", [])
            if listing_ids_for_cities:
                city_listings = db.query(Listing).filter(Listing.id.in_(listing_ids_for_cities)).all()
                # Group by city name to preserve city context in each item
                listings_info = [_listing_summary(l) for l in city_listings]
                # Attach the missing city name to each entry for display
                city_by_id = {l.id: (l.city or l.location or "") for l in city_listings}
                for info in listings_info:
                    info["missing_city"] = city_by_id.get(info["id"], "")
            else:
                # Fallback: show city names only (no listing IDs available)
                listings_info = [
                    {"id": None, "title": city, "city": city, "url": None, "status": "active"}
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

async def repair_listings_batch_task(problem_type: str, is_part_of_sequence: bool = False, hide_rejected: bool = True):
    """
    Background task to repair listings in batches.
    Manages its own database session.
    """
    global repair_progress
    
    db = SessionLocal()
    try:
        problems = identify_problems(db, hide_rejected=hide_rejected)
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
                            elif problem_type == MISSING_LOCATION:
                                from app.geo import standardize_and_enrich_city, get_coordinates
                                found_city = None
                                if listing.title:
                                    zip_match = re.search(r'\b(0[1-9]|[1-8]\d|9[0-5]|97[1-8]|2[ABab])\d{3}\b', listing.title)
                                    if zip_match:
                                        std_city, _, _ = standardize_and_enrich_city(zip_match.group(0))
                                        if std_city:
                                            found_city = std_city
                                if not found_city and listing.description_text:
                                    zip_match = re.search(r'\b(0[1-9]|[1-8]\d|9[0-5]|97[1-8]|2[ABab])\d{3}\b', listing.description_text[:500])
                                    if zip_match:
                                        std_city, _, _ = standardize_and_enrich_city(zip_match.group(0))
                                        if std_city:
                                            found_city = std_city
                                if found_city:
                                    listing.city = found_city
                                    listing.location = found_city
                                    coords = get_coordinates(found_city)
                                    if coords:
                                        listing.latitude, listing.longitude = coords
                                    db.commit()
                                else:
                                    await refresh_listing_status(listing, db, force_update=True)
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


async def repair_all_sequential_task(hide_rejected: bool = True):
    """
    Finds all outstanding problems, sorts them by count ASC (excluding 0 count),
    and repairs them sequentially one after another.
    """
    global repair_progress
    
    db = SessionLocal()
    try:
        problems = identify_problems(db, hide_rejected=hide_rejected)
        
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
            await repair_listings_batch_task(p_type, is_part_of_sequence=True, hide_rejected=hide_rejected)
            await asyncio.sleep(2)
            
    finally:
        repair_progress["is_running"] = False
        db.close()

async def repair_selected_sequential_task(problem_types: list[str], hide_rejected: bool = True):
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
            await repair_listings_batch_task(p_type, is_part_of_sequence=True, hide_rejected=hide_rejected)
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


