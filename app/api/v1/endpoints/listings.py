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

