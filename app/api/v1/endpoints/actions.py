import re
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import Optional

from app import models, schemas
from app.database import get_db
from app.api.deps import get_current_user_api
from app.services import create_listing_from_details, normalize_listing_url
from app.translations import get_text

router = APIRouter()

def find_existing_listing(url: str, db: Session) -> Optional[models.Listing]:
    """Find a listing by URL with canonical prefix normalization and platform-specific ID matching."""
    if not url:
        return None
        
    norm_url = normalize_listing_url(url)
    clean_base_url = url.split('?')[0].split('#')[0].rstrip('/')
    
    # 1. Exact or normalized URL match
    existing = db.query(models.Listing).filter(
        (models.Listing.url == url) | 
        (models.Listing.original_url == url) |
        (models.Listing.url == norm_url) |
        (models.Listing.original_url == norm_url) |
        (models.Listing.url == clean_base_url) |
        (models.Listing.original_url == clean_base_url)
    ).first()
    
    if existing:
        return existing

    # 2. Canonical prefix match (if DB has clean short URL and incoming is long with query params, or vice-versa)
    if len(clean_base_url) > 15:
        existing = db.query(models.Listing).filter(
            (models.Listing.url.like(f"{clean_base_url}%")) |
            (models.Listing.original_url.like(f"{clean_base_url}%"))
        ).first()
        if existing:
            return existing

    # 3. SeLoger matching: token ID (e.g. 269W7APVLTZA or 12345678.htm)
    if "seloger.com" in url:
        # Match alphanumeric listing token at end of path (e.g. /269W7APVLTZA)
        match_token = re.search(r'/([A-Za-z0-9]{8,})(?:[/?#]|$)', url)
        if match_token:
            token = match_token.group(1)
            existing = db.query(models.Listing).filter(
                (models.Listing.url.like(f"%{token}%")) | 
                (models.Listing.original_url.like(f"%{token}%"))
            ).first()
            if existing:
                return existing
        # Match legacy numeric ID (e.g. /12345678.htm)
        match_legacy = re.search(r'/(\d{6,})\.htm', url)
        if match_legacy:
            legacy_id = match_legacy.group(1)
            existing = db.query(models.Listing).filter(
                (models.Listing.url.like(f"%{legacy_id}%")) | 
                (models.Listing.original_url.like(f"%{legacy_id}%"))
            ).first()
            if existing:
                return existing

    # 4. LeBonCoin numeric ad ID match (e.g. 3224009953)
    if "leboncoin.fr" in url:
        match_id = re.search(r'/(\d{6,})', url)
        if match_id:
            ad_id = match_id.group(1)
            existing = db.query(models.Listing).filter(
                (models.Listing.url.like(f"%{ad_id}%")) | 
                (models.Listing.original_url.like(f"%{ad_id}%"))
            ).first()
            if existing:
                return existing

    # 5. Figaro Immobilier ad ID match
    if "lefigaro.fr" in url:
        match_id = re.search(r'annonces/[^/]+-(\d+)\.html', url) or re.search(r'/(\d{6,})', url)
        if match_id:
            ad_id = match_id.group(1)
            existing = db.query(models.Listing).filter(
                (models.Listing.url.like(f"%{ad_id}%")) | 
                (models.Listing.original_url.like(f"%{ad_id}%"))
            ).first()
            if existing:
                return existing

    # 6. BienIci ID match (e.g. bienici-123 or UUID)
    if "bienici.com" in url:
        match_id = re.search(r'/annonce/(?:vente/[^/]+/)?([a-zA-Z0-9_-]+)', url)
        if match_id:
            ad_id = match_id.group(1)
            existing = db.query(models.Listing).filter(
                (models.Listing.url.like(f"%{ad_id}%")) | 
                (models.Listing.original_url.like(f"%{ad_id}%"))
            ).first()
            if existing:
                return existing

    # 7. PAP ad reference match (e.g. -r12345678)
    if "pap.fr" in url:
        match_id = re.search(r'-r(\d+)', url)
        if match_id:
            ad_id = match_id.group(1)
            existing = db.query(models.Listing).filter(
                (models.Listing.url.like(f"%{ad_id}%")) | 
                (models.Listing.original_url.like(f"%{ad_id}%"))
            ).first()
            if existing:
                return existing

    return None


@router.get("/check-listing")
def check_listing_api(
    url: str,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Check if a listing already exists in Immo-Boussole database.
    """
    existing = find_existing_listing(url, db)
    if existing:
        return {
            "exists": True,
            "listing_id": existing.id,
            "immo_boussole_url": f"/listings/{existing.id}",
            "title": existing.title,
            "status": existing.status.value if hasattr(existing.status, 'value') else existing.status
        }
    return {
        "exists": False,
        "listing_id": None,
        "immo_boussole_url": None
    }


@router.post("/submit-url", response_model=schemas.ActionResponse)
async def submit_url_api(
    request: schemas.SubmitUrlRequest,
    background_tasks: BackgroundTasks,
    req: Request,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Trigger scraping for a given URL.
    Returns immediately, task runs in background.
    """
    existing = find_existing_listing(request.url, db)
    is_already_exists = False

    if not existing:
        source_val = models.Source.MANUAL.value
        if "leboncoin.fr" in request.url:
            source_val = models.Source.LEBONCOIN.value
        elif "lefigaro.fr" in request.url:
            source_val = models.Source.LEFIGARO.value
        elif "seloger.com" in request.url:
            source_val = models.Source.SELOGER.value
        elif "bienici.com" in request.url:
            source_val = models.Source.BIENICI.value

        listing = models.Listing(
            url=request.url,
            original_url=request.url,
            title="Annonce en cours d'analyse...",
            source=source_val,
            status=models.ListingStatus.NEW,
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)
        target_listing = listing
    else:
        target_listing = existing
        is_already_exists = True

    if request.skip_scraping:
        create_listing_from_details(request.url, db)
        return schemas.ActionResponse(
            status="success",
            message=get_text(req, "api.listing_added_manually", default="Listing added manually without scraping."),
            data={
                "listing_id": target_listing.id,
                "immo_boussole_url": f"/listings/{target_listing.id}",
                "already_exists": is_already_exists,
                "status": "nouvelle"
            }
        )
    
    background_tasks.add_task(create_listing_from_details, request.url, db)
    return schemas.ActionResponse(
        status="accepted",
        message=get_text(req, "api.scraping_task_started", default="Scraping task started in background."),
        data={
            "listing_id": target_listing.id,
            "immo_boussole_url": f"/listings/{target_listing.id}",
            "already_exists": is_already_exists,
            "status": "nouvelle"
        }
    )


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
    req: Request,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Add or update a listing with pre-extracted data from the browser extension.
    Also queues a background scraping job to enrich full details if possible.
    """
    existing = find_existing_listing(request.url, db)
    is_already_exists = False

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
            status=models.ListingStatus.NEW,
            price_per_sqm=price_per_sqm
        )

        if request.photos:
            import json
            listing.photos_json = json.dumps(request.photos)

        db.add(listing)
        db.commit()
        db.refresh(listing)
        target_listing = listing
        msg = get_text(
            req,
            "api.listing_added_success",
            default=f"Annonce '{listing.title}' ajoutée avec succès.",
            title=listing.title
        )
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
        db.refresh(existing)
        target_listing = existing
        is_already_exists = True
        msg = get_text(
            req,
            "api.listing_already_exists_updated",
            default=f"Annonce '{existing.title}' déjà présente dans la base (mise à jour avec succès).",
            title=existing.title
        )

    # Launch background scrape for full enrichment if possible
    background_tasks.add_task(_enrich_external_listing, request.url, db)

    return schemas.ActionResponse(
        status="success",
        message=msg,
        data={
            "listing_id": target_listing.id,
            "immo_boussole_url": f"/listings/{target_listing.id}",
            "already_exists": is_already_exists,
            "status": "nouvelle"
        }
    )
