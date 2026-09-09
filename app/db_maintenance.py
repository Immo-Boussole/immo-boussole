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
import json
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
MISSING_COMPROMIS_TAG = "missing_compromis_tag"


def is_missing_location(listing) -> bool:
    """Checks if a listing lacks city and location data."""
    c = (listing.city or "").strip()
    loc = (listing.location or "").strip()
    placeholders = {"inconnu", "unknown", "france", "none", "null", "undefined", ""}
    return c.lower() in placeholders and loc.lower() in placeholders


def get_listing_repair_issues(listing) -> list[dict]:
    """
    Returns a list of structured repair issues for a given listing.
    Each item is a dict with 'key', 'label', and 'icon'.
    """
    issues = []
    seen_keys = set()

    tags = []
    raw_tags = getattr(listing, 'repair_tags', None)
    if raw_tags:
        if isinstance(raw_tags, list):
            tags = raw_tags
        elif isinstance(raw_tags, str):
            try:
                tags = json.loads(raw_tags)
                if not isinstance(tags, list):
                    tags = []
            except Exception:
                tags = []

    meta_map = {
        "missing_location": {"label": "Localisation manquante", "icon": "fa-location-dot"},
        "empty_description": {"label": "Description vide", "icon": "fa-file-lines"},
        "generic_title_figaro": {"label": "Titre générique", "icon": "fa-heading"},
        "aggregate_search_page": {"label": "Page de recherche agrégée", "icon": "fa-layer-group"},
        "duplicate_city_zip": {"label": "Code postal dupliqué", "icon": "fa-map-pin"},
        "anomalous_price": {"label": "Prix anormal", "icon": "fa-tag"},
        "unstandardized_city": {"label": "Ville non standardisée", "icon": "fa-city"},
        "incorrect_price_per_sqm": {"label": "Prix/m² incorrect", "icon": "fa-calculator"},
        "missing_photos": {"label": "Photos manquantes", "icon": "fa-image"},
        "past_first_visit_not_done": {"label": "Visite non validée", "icon": "fa-calendar-xmark"},
        "missing_compromis_tag": {"label": "Sous compromis non tagué", "icon": "fa-handshake"},
    }

    excluded_keys = {"forbidden_zone", "forbidden_department"}

    for t in tags:
        if t in meta_map and t not in seen_keys and t not in excluded_keys:
            issues.append({"key": t, "label": meta_map[t]["label"], "icon": meta_map[t]["icon"]})
            seen_keys.add(t)

    # Dynamic check for missing location if not yet tagged
    if is_missing_location(listing) and "missing_location" not in seen_keys:
        issues.append({"key": "missing_location", "label": "Localisation manquante", "icon": "fa-location-dot"})
        seen_keys.add("missing_location")

    return issues




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

    # Missing compromis tag (mentions of compromis/offre in description, but listing.is_under_compromis is False)
    missing_compromis_tag_listings = []
    from app.compromis import detect_compromis_in_text
    for l in target_listings:
        if not l.is_under_compromis and l.compromis_detected_by != "manual":
            is_comp, _ = detect_compromis_in_text(l.description_text)
            if is_comp:
                missing_compromis_tag_listings.append(l)

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
        },
        MISSING_COMPROMIS_TAG: {
            "count": len(missing_compromis_tag_listings),
            "ids": [l.id for l in missing_compromis_tag_listings]
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
    MISSING_COMPROMIS_TAG,
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
                            elif problem_type == MISSING_COMPROMIS_TAG:
                                from app.compromis import analyze_listing_compromis
                                from app.media import json_to_photos
                                first_p = None
                                if listing.photos_local:
                                    p_list = json_to_photos(listing.photos_local)
                                    if p_list:
                                        first_p = p_list[0]
                                is_comp, det_by = analyze_listing_compromis(listing.description_text, first_p)
                                if is_comp:
                                    listing.is_under_compromis = True
                                    listing.compromis_detected_by = det_by
                                    db.commit()
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


def scan_all_listings_for_compromis(db: Session) -> dict:
    """
    Parcourt toutes les annonces de la base de données pour détecter les mentions
    de 'sous compromis' ou 'sous offre' dans la description et via OCR sur la première photo locale.
    Préserve formellement les annonces dont le statut a été défini manuellement par l'utilisateur.
    """
    from app.compromis import analyze_listing_compromis
    from app.media import json_to_photos

    listings = db.query(Listing).filter(Listing.status != ListingStatus.REJECTED).all()
    scanned_count = 0
    detected_count = 0
    cleared_count = 0

    for l in listings:
        scanned_count += 1
        # Préserver les saisies manuelles
        if l.compromis_detected_by == "manual":
            continue

        first_photo = None
        if l.photos_local:
            p_list = json_to_photos(l.photos_local)
            if p_list:
                first_photo = p_list[0]

        is_comp, det_by = analyze_listing_compromis(
            description=l.description_text,
            first_photo_path=first_photo
        )

        if is_comp and not l.is_under_compromis:
            l.is_under_compromis = True
            l.compromis_detected_by = det_by
            detected_count += 1
        elif not is_comp and l.is_under_compromis and l.compromis_detected_by in ("description", "ocr"):
            l.is_under_compromis = False
            l.compromis_detected_by = None
            cleared_count += 1

    db.commit()
    return {
        "scanned": scanned_count,
        "detected": detected_count,
        "cleared": cleared_count
    }


def evaluate_single_listing_health(listing: Listing, db: Session) -> dict:
    """
    Évalue la santé complète d'une annonce individuelle et retourne un bilan structuré
    avec l'état de chaque dimension de réparation possible et le statut d'anomalie.
    """
    from app.media import json_to_photos
    from app.compromis import analyze_listing_compromis
    from app.services import fetch_sncf_times_for_city
    from app.models import ZoneRule

    photos_list = json_to_photos(listing.photos_local) if listing.photos_local else []
    first_photo = photos_list[0] if photos_list else None
    
    # 1. Photos check
    photos_anomaly = False
    photos_details = ""
    if is_missing_or_corrupt_photos(listing):
        photos_anomaly = True
        photos_details = "Photos manquantes ou fichiers locaux introuvables"
    elif photos_list:
        photos_details = f"{len(photos_list)} photo(s) locale(s) valide(s)"
    else:
        photos_anomaly = True
        photos_details = "Aucune photo associée à l'annonce"

    # 2. Title check
    title_anomaly = False
    title_details = ""
    if not listing.title or not listing.title.strip():
        title_anomaly = True
        title_details = "Titre complètement vide"
    elif is_error_or_generic_title(listing.title):
        title_anomaly = True
        title_details = "Titre générique ou message d'erreur détecté"
    else:
        title_details = "Titre valide et informatif"

    # 3. Location check
    loc_anomaly = False
    loc_details = ""
    if is_missing_location(listing):
        loc_anomaly = True
        loc_details = "Localisation inconnue ou manquante"
    else:
        city_str = (listing.city or "").strip()
        is_std = bool(re.match(r'^.+\s\(\d{5}\)$', city_str)) if city_str else False
        has_coords = bool(listing.latitude is not None and listing.longitude is not None)
        if not is_std or not has_coords:
            loc_anomaly = True
            loc_details = "Commune non standardisée ou coordonnées GPS manquantes"
        else:
            loc_details = f"{city_str} ({listing.latitude:.4f}, {listing.longitude:.4f})"

    # 4. Stations SNCF check
    stations_anomaly = False
    stations_details = ""
    if listing.city and not is_missing_location(listing):
        if listing.nearest_sncf_station is None or listing.walk_time_sncf is None:
            stations_anomaly = True
            stations_details = "Gare SNCF la plus proche ou temps de trajet non calculés"
        else:
            stations_details = f"Gare : {listing.nearest_sncf_station} (à pied : {listing.walk_time_sncf} min)"
    else:
        stations_details = "Localisation requise pour calculer les gares"

    # 5. Price per sqm check
    price_sqm_anomaly = False
    price_sqm_details = ""
    listing_area = getattr(listing, 'area', None)
    if listing.price and listing_area and listing_area > 0 and listing.price > 0:
        expected_sqm = round(listing.price / listing_area)
        if listing.price_per_sqm is None or abs(listing.price_per_sqm - expected_sqm) > 1:
            price_sqm_anomaly = True
            price_sqm_details = f"Prix/m² ({listing.price_per_sqm or 'non calculé'}) différent de l'attendu ({expected_sqm} €/m²)"
        else:
            price_sqm_details = f"{listing.price_per_sqm} €/m² (conforme)"
    else:
        price_sqm_details = "Surface ou prix non renseignés"

    # 6. Visits check
    visits_anomaly = False
    visits_details = ""
    overdue_visits = []
    listing_visits = db.query(Visit).filter(Visit.listing_id == listing.id).all()
    for v in listing_visits:
        if v.status != "effectuee" and _is_past_date(v.scheduled_at):
            overdue_visits.append(v)
    if overdue_visits:
        visits_anomaly = True
        visits_details = f"{len(overdue_visits)} visite(s) passée(s) non marquée(s) 'effectuée'"
    elif listing_visits:
        visits_details = f"{len(listing_visits)} visite(s) à jour"
    else:
        visits_details = "Aucune visite enregistrée"

    # 7. Compromis check
    compromis_anomaly = False
    compromis_details = ""
    is_comp, det_by = analyze_listing_compromis(
        description=listing.description_text,
        first_photo_path=first_photo
    )
    if is_comp and not listing.is_under_compromis:
        compromis_anomaly = True
        compromis_details = f"Mention de compromis détectée ({det_by}) mais statut non mis à jour"
    elif listing.is_under_compromis:
        compromis_details = f"Bien sous compromis (identifié par {listing.compromis_detected_by or 'manuel'})"
    else:
        compromis_details = "Aucune mention de compromis détectée"

    # 8. Rescrape check
    rescrape_anomaly = False
    rescrape_details = ""
    if not listing.description_text or not listing.description_text.strip():
        rescrape_anomaly = True
        rescrape_details = "Description textuelle vide — re-scraping conseillé"
    elif title_anomaly and listing.url:
        rescrape_anomaly = True
        rescrape_details = "Titre d'erreur ou incomplet — re-scraping conseillé"
    else:
        rescrape_details = "Données textuelles et description présentes"

    # Actions dictionary
    actions = {
        "photos": {
            "key": "photos",
            "label": "Photos & Médias",
            "icon": "fa-camera",
            "description": "Télécharger ou réparer les photos manquantes et corrompues",
            "is_anomaly": photos_anomaly,
            "details": photos_details,
        },
        "title": {
            "key": "title",
            "label": "Titre de l'annonce",
            "icon": "fa-heading",
            "description": "Régénérer un titre propre à partir de la description ou du portail",
            "is_anomaly": title_anomaly,
            "details": title_details,
        },
        "location": {
            "key": "location",
            "label": "Commune & Géocodage",
            "icon": "fa-location-dot",
            "description": "Extraire le code postal, standardiser la commune et géocoder",
            "is_anomaly": loc_anomaly,
            "details": loc_details,
        },
        "stations": {
            "key": "stations",
            "label": "Gares SNCF & Trajets",
            "icon": "fa-train",
            "description": "Calculer la gare la plus proche et les temps de trajet (marche/vélo/voiture)",
            "is_anomaly": stations_anomaly,
            "details": stations_details,
        },
        "price_sqm": {
            "key": "price_sqm",
            "label": "Prix au m²",
            "icon": "fa-calculator",
            "description": "Recalculer le prix au mètre carré à partir du prix et de la surface",
            "is_anomaly": price_sqm_anomaly,
            "details": price_sqm_details,
        },
        "visits": {
            "key": "visits",
            "label": "Statut des visites",
            "icon": "fa-calendar-check",
            "description": "Valider et passer à 'effectuée' les visites planifiées antérieures",
            "is_anomaly": visits_anomaly,
            "details": visits_details,
        },
        "compromis": {
            "key": "compromis",
            "label": "Détection 'Sous compromis'",
            "icon": "fa-signature",
            "description": "Analyser la description et l'image pour détecter les compromis ou offres",
            "is_anomaly": compromis_anomaly,
            "details": compromis_details,
        },
        "rescrape": {
            "key": "rescrape",
            "label": "Re-scraping source web",
            "icon": "fa-rotate",
            "description": "Re-télécharger la page source complète depuis le portail immobilier",
            "is_anomaly": rescrape_anomaly,
            "details": rescrape_details,
        },
    }

    anomaly_count = sum(1 for a in actions.values() if a["is_anomaly"])

    first_photo_url = f"/{first_photo}" if first_photo else None

    return {
        "listing_id": listing.id,
        "title": listing.title or f"Annonce #{listing.id}",
        "price": listing.price,
        "surface": getattr(listing, 'area', None),
        "city": listing.city or listing.location or "Ville inconnue",
        "location": listing.location or "",
        "source": listing.source.value if hasattr(listing.source, 'value') else str(listing.source or ""),
        "status": listing.status.value if hasattr(listing.status, 'value') else str(listing.status or ""),
        "url": listing.url or "",
        "first_photo": first_photo_url,
        "is_healthy": anomaly_count == 0,
        "anomaly_count": anomaly_count,
        "is_under_compromis": bool(listing.is_under_compromis),
        "actions": actions,
    }


async def apply_listing_repair_actions(listing_id: int, actions: list[str], db: Session) -> dict:
    """
    Applique les actions de réparation sélectionnées à une annonce spécifique,
    persiste les modifications et renvoie le rapport de santé actualisé.
    """
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        return {"error": "Listing not found", "success": False}

    repaired_actions = []
    errors = []

    for act in actions:
        try:
            if act == "photos":
                await repair_listing_photos(listing, db)
                repaired_actions.append("photos")

            elif act == "title":
                await repair_listing_title(listing, db)
                repaired_actions.append("title")

            elif act == "location":
                from app.geo import standardize_and_enrich_city, get_coordinates
                from app.services import ensure_city_map_pin
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
                if not found_city and (listing.city or listing.location):
                    std_city, _, _ = standardize_and_enrich_city(listing.city or listing.location)
                    if std_city:
                        found_city = std_city

                if found_city:
                    listing.city = found_city
                    listing.location = found_city
                    coords = get_coordinates(found_city)
                    if coords:
                        listing.latitude, listing.longitude = coords
                    ensure_city_map_pin(found_city, db)
                    db.commit()
                repaired_actions.append("location")

            elif act == "stations":
                if listing.city:
                    from app.models import ZoneRule
                    from app.services import fetch_sncf_times_for_city
                    forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
                        ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
                    ).all()}
                    sncf_data = fetch_sncf_times_for_city(listing.city, forbidden_stations)
                    if sncf_data:
                        listing.nearest_sncf_station = sncf_data.get('nearest_sncf_station')
                        listing.walk_time_sncf = sncf_data.get('walk_time_sncf')
                        listing.bike_time_sncf = sncf_data.get('bike_time_sncf')
                        listing.car_time_sncf = sncf_data.get('car_time_sncf')
                        listing.second_sncf_station = sncf_data.get('second_sncf_station')
                        listing.walk_time_second_sncf = sncf_data.get('walk_time_second_sncf')
                        listing.bike_time_second_sncf = sncf_data.get('bike_time_second_sncf')
                        listing.car_time_second_sncf = sncf_data.get('car_time_second_sncf')
                        db.commit()
                repaired_actions.append("stations")

            elif act == "price_sqm":
                listing.update_price_per_sqm()
                db.commit()
                repaired_actions.append("price_sqm")

            elif act == "visits":
                visits = db.query(Visit).filter(Visit.listing_id == listing.id, Visit.status != "effectuee").all()
                repaired_any = False
                for v in visits:
                    if _is_past_date(v.scheduled_at):
                        v.status = "effectuee"
                        repaired_any = True
                        try:
                            from app import google_service
                            google_service.sync_visit_to_google_calendar(db, v)
                        except Exception as eg:
                            pass
                if repaired_any:
                    from app.main import _derive_visit_status_from_visit
                    latest_visit = db.query(Visit).filter(Visit.listing_id == listing.id).order_by(Visit.scheduled_at.desc()).first()
                    if latest_visit:
                        derived = _derive_visit_status_from_visit(latest_visit)
                        if derived:
                            listing.last_visit_status = derived
                    db.commit()
                repaired_actions.append("visits")

            elif act == "compromis":
                from app.media import json_to_photos
                from app.compromis import analyze_listing_compromis
                photos_list = json_to_photos(listing.photos_local) if listing.photos_local else []
                first_p = photos_list[0] if photos_list else None
                is_comp, det_by = analyze_listing_compromis(listing.description_text, first_p)
                if is_comp:
                    listing.is_under_compromis = True
                    listing.compromis_detected_by = det_by
                elif listing.compromis_detected_by != "manual":
                    listing.is_under_compromis = False
                    listing.compromis_detected_by = None
                db.commit()
                repaired_actions.append("compromis")

            elif act == "rescrape":
                await refresh_listing_status(listing, db, force_update=True)
                repaired_actions.append("rescrape")

        except Exception as e:
            errors.append(f"Erreur sur l'action '{act}': {str(e)}")

    db.commit()
    db.refresh(listing)

    # Ré-évaluer la santé mise à jour
    new_health = evaluate_single_listing_health(listing, db)

    return {
        "success": len(errors) == 0,
        "repaired_actions": repaired_actions,
        "errors": errors,
        "health": new_health,
    }



