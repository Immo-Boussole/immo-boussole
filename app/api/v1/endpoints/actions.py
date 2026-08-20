from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.api.deps import get_current_user_api
from app.services import create_listing_from_details

router = APIRouter()

@router.post("/submit-url", response_model=schemas.ActionResponse)
async def submit_url_api(
    request: schemas.SubmitUrlRequest,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Trigger scraping for a given URL.
    Returns immediately, task runs in background.
    """
    if request.skip_scraping:
        create_listing_from_details(request.url, db)
        return schemas.ActionResponse(status="success", message="Listing added manually without scraping.")
    
    background_tasks.add_task(create_listing_from_details, request.url, db)
    return schemas.ActionResponse(status="accepted", message="Scraping task started in background.")


async def _enrich_external_listing(url: str, db: Session):
    try:
        from app.services import fetch_basic_metadata
        await fetch_basic_metadata(url)
    except Exception as e:
        print(f"[API] Background enrichment error for {url}: {e}")

@router.post("/submit-external-listing", response_model=schemas.ActionResponse)
async def submit_external_listing_api(
    request: schemas.ExternalListingSubmitRequest,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Add or update a listing with pre-extracted data from the browser extension.
    Also queues a background scraping job to enrich full details if possible.
    """
    # Check if listing already exists by URL
    existing = db.query(models.Listing).filter(
        (models.Listing.url == request.url) | (models.Listing.original_url == request.url)
    ).first()

    if not existing:
        # Determine source
        source_val = models.Source.MANUAL.value
        if request.source:
            source_val = request.source
        elif "leboncoin.fr" in request.url:
            source_val = models.Source.LEBONCOIN.value
        elif "lefigaro.fr" in request.url:
            source_val = models.Source.LEFIGARO.value
        elif "seloger.com" in request.url:
            source_val = models.Source.SELOGER.value
        elif "bienici.com" in request.url:
            source_val = models.Source.BIENICI.value

        price_per_sqm = None
        if request.price and request.area and request.area > 0:
            price_per_sqm = round(request.price / request.area, 2)

        listing = models.Listing(
            url=request.url,
            original_url=request.url,
            title=request.title or "Annonce sans titre",
            price=request.price,
            area=request.area,
            rooms=request.rooms,
            bedrooms=request.bedrooms,
            city=request.city,
            postal_code=request.postal_code,
            location=request.location or request.city or "Inconnu",
            description_text=request.description,
            source=source_val,
            status=models.ListingStatus.NEW.value,
            price_per_sqm=price_per_sqm
        )

        if request.photos:
            import json
            listing.photos_json = json.dumps(request.photos)

        db.add(listing)
        db.commit()
        db.refresh(listing)
        msg = f"Annonce '{listing.title}' ajoutée avec succès."
    else:
        # Update fields if provided
        if request.title:
            existing.title = request.title
        if request.price:
            existing.price = request.price
        if request.area:
            existing.area = request.area
        if request.city:
            existing.city = request.city
        if request.photos:
            import json
            existing.photos_json = json.dumps(request.photos)
        db.commit()
        msg = f"Annonce '{existing.title}' mise à jour avec succès."

    # Launch background scrape for full enrichment if possible
    background_tasks.add_task(_enrich_external_listing, request.url, db)

    return schemas.ActionResponse(status="success", message=msg)



