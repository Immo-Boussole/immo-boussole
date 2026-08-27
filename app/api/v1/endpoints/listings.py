from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app import models, schemas
from app.database import get_db
from app.api.deps import get_current_user_api

router = APIRouter()

@router.get("/", response_model=List[schemas.ListingResponse])
def get_listings(
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Get listings.
    """
    listings = db.query(models.Listing).order_by(models.Listing.date_added.desc()).offset(skip).limit(limit).all()
    return listings

@router.get("/{listing_id}", response_model=schemas.ListingResponse)
def get_listing(
    listing_id: int,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


@router.get("/{listing_id}/attachments", response_model=List[schemas.ListingAttachmentResponse])
def get_listing_attachments_v1(
    listing_id: int,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return db.query(models.ListingAttachment).filter(
        models.ListingAttachment.listing_id == listing_id
    ).order_by(models.ListingAttachment.created_at.desc()).all()


@router.get("/{listing_id}/links", response_model=List[schemas.ListingLinkResponse])
def get_listing_links_v1(
    listing_id: int,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return db.query(models.ListingLink).filter(
        models.ListingLink.listing_id == listing_id
    ).order_by(models.ListingLink.created_at.asc()).all()


@router.post("/{listing_id}/set-location")
def set_listing_location_v1(
    listing_id: int,
    payload: dict,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """Update listing location via API v1."""
    location = (payload.get("location") or "").strip()
    if not location:
        raise HTTPException(status_code=400, detail="Location is required")

    listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    from app.geo import standardize_and_enrich_city, get_coordinates
    from app.main import _is_city_in_allowed_departments
    from app.models import ZoneRule, ListingStatus
    from app.geo import is_city_in_forbidden_set

    std_city, std_postal_code, _ = standardize_and_enrich_city(location)
    final_city = std_city or location

    listing.city = final_city
    listing.location = final_city
    if payload.get("postal_code"):
        listing.postal_code = payload["postal_code"].strip()
    elif std_postal_code:
        listing.postal_code = std_postal_code

    listing.address_precision = "city"
    listing.manual_address_override = True

    if payload.get("latitude") is not None and payload.get("longitude") is not None:
        listing.latitude = float(payload["latitude"])
        listing.longitude = float(payload["longitude"])
    else:
        coords = get_coordinates(final_city)
        if coords:
            listing.latitude, listing.longitude = coords

    was_rejected = False
    if not listing.to_visit:
        if not _is_city_in_allowed_departments(final_city, db):
            listing.status = ListingStatus.REJECTED
            was_rejected = True
        else:
            forbidden_cities = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
                ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
            ).all()}
            if is_city_in_forbidden_set(final_city, forbidden_cities):
                listing.status = ListingStatus.REJECTED
                was_rejected = True

    listing.update_price_per_sqm()
    db.commit()
    db.refresh(listing)

    return {
        "success": True,
        "listing_id": listing.id,
        "city": listing.city,
        "location": listing.location,
        "postal_code": listing.postal_code,
        "latitude": listing.latitude,
        "longitude": listing.longitude,
        "status": listing.status.value if hasattr(listing.status, 'value') else str(listing.status),
        "is_rejected": was_rejected,
        "listing": {
            "id": listing.id,
            "title": listing.title,
            "city": listing.city,
            "location": listing.location,
            "postal_code": listing.postal_code,
            "latitude": listing.latitude,
            "longitude": listing.longitude,
            "status": listing.status.value if hasattr(listing.status, 'value') else str(listing.status),
            "is_rejected": was_rejected
        }
    }


