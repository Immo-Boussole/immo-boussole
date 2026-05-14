from sqlalchemy.orm import Session
from app.models import Listing, ListingStatus
from app.services import refresh_listing_status
from app.database import SessionLocal
import asyncio
import re


# Problem types
EMPTY_DESCRIPTION = "empty_description"
GENERIC_TITLE_FIGARO = "generic_title_figaro"
DUPLICATE_CITY_ZIP = "duplicate_city_zip"


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
        }
    }


# Global state to track repair progress
repair_progress = {
    "total": 0,
    "processed": 0,
    "is_running": False,
    "problem_type": None
}

async def repair_listings_batch_task(problem_type: str):
    """
    Background task to repair listings in batches.
    Manages its own database session.
    """
    global repair_progress
    
    db = SessionLocal()
    try:
        problems = identify_problems(db)
        if problem_type not in problems:
            repair_progress["is_running"] = False
            return

        ids_to_repair = problems[problem_type]["ids"]
        repair_progress["total"] = len(ids_to_repair)
        repair_progress["processed"] = 0
        repair_progress["is_running"] = True
        repair_progress["problem_type"] = problem_type

        batch_size = 5
        delay_between_batches = 5
        
        for i in range(0, len(ids_to_repair), batch_size):
            batch_ids = ids_to_repair[i:i + batch_size]
            
            for lid in batch_ids:
                listing = db.query(Listing).filter(Listing.id == lid).first()
                if listing:
                    try:
                        await refresh_listing_status(listing, db, force_update=True)
                    except Exception as e:
                        print(f"[DB Maintenance] Error repairing listing {lid}: {e}")
                
                repair_progress["processed"] += 1
                db.commit()
                
            if i + batch_size < len(ids_to_repair):
                await asyncio.sleep(delay_between_batches)
    finally:
        repair_progress["is_running"] = False
        db.close()

def get_repair_status():
    global repair_progress
    return repair_progress
