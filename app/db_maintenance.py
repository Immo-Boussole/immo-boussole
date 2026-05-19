from sqlalchemy.orm import Session
from app.models import Listing, ListingStatus, MapPin
from app.services import refresh_listing_status
from app.database import SessionLocal
import asyncio
import re


# Problem types
EMPTY_DESCRIPTION = "empty_description"
GENERIC_TITLE_FIGARO = "generic_title_figaro"
DUPLICATE_CITY_ZIP = "duplicate_city_zip"
ANOMALOUS_PRICE = "anomalous_price"
LINKED_ADS_NONE = "linked_ads_none"
MISSING_CITY_PINS = "missing_city_pins"



def identify_problems(db: Session):
    """
    Identifies problematic listings.
    Returns counts for each problem type and lists of IDs.
    """
    # Empty description
    empty_desc_listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"]),
        (Listing.description_text == None) | (Listing.description_text == "")
    ).all()
    
    # Generic title "Annonce Le Figaro"
    generic_title_listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, "active", "nouvelle"]),
        Listing.title == "Annonce Le Figaro"
    ).all()

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
        p_name_clean = re.sub(r'\s*\(\d{5}\)$', '', p_name).strip()
        existing_pin_names.add(p_name_clean)
        
    missing_city_names = []
    for (city_val,) in cities_in_active_listings:
        c_clean = city_val.strip()
        if not c_clean:
            continue
        c_lower = c_clean.lower()
        if c_lower not in existing_pin_names:
            c_lower_clean = re.sub(r'\s*\(\d{5}\)$', '', c_lower).strip()
            if c_lower_clean not in existing_pin_names:
                missing_city_names.append(c_clean)
    
    return {
        EMPTY_DESCRIPTION: {
            "count": len(empty_desc_listings),
            "ids": [l.id for l in empty_desc_listings]
        },
        GENERIC_TITLE_FIGARO: {
            "count": len(generic_title_listings),
            "ids": [l.id for l in generic_title_listings]
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
        }
    }


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
                        # Find coordinates from an active listing in same city
                        listing_with_coords = db.query(Listing).filter(
                            Listing.city == city_name,
                            Listing.latitude.isnot(None),
                            Listing.longitude.isnot(None)
                        ).first()
                        
                        lat, lon = None, None
                        if listing_with_coords:
                            lat, lon = listing_with_coords.latitude, listing_with_coords.longitude
                        else:
                            from app.geo import get_coordinates
                            coords = get_coordinates(f"{city_name}, France")
                            if coords:
                                lat, lon = coords
                                
                        if lat is not None and lon is not None:
                            pin = MapPin(
                                title=city_name.title(),
                                address=f"{city_name.title()}, France",
                                lat=lat,
                                lon=lon,
                                created_by="system",
                                pin_type="city"
                            )
                            db.add(pin)
                            db.commit()
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

def get_repair_status():
    global repair_progress
    return repair_progress

