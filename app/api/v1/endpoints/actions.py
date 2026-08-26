import re
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import Optional, List

from app import models, schemas
from app.database import get_db
from app.api.deps import get_current_user_api
from app.services import normalize_listing_url
from app.translations import get_text

router = APIRouter()

def extract_platform_id(url: str) -> Optional[str]:
    """
    Extract unique listing identifier from supported property portal URLs.
    Extracts strictly from path segments (ignoring domain names and schemes).
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip('/')
        last_seg = path.split('/')[-1] if path else ""
        
        # 1. LeBonCoin (e.g. /ad/ventes_immobilieres/3224009953)
        if "leboncoin.fr" in netloc:
            m = re.search(r'/(\d{6,})(?:[/?#]|$)', path)
            if m:
                return m.group(1)

        # 2. SeLoger (e.g. /annonce/.../26H129BK5GHE or /annonces/.../12345678.htm)
        if "seloger.com" in netloc:
            clean_last = re.sub(r'\.htm.*$', '', last_seg)
            if re.match(r'^[A-Za-z0-9]{8,}$', clean_last) or re.match(r'^\d{6,}$', clean_last):
                return clean_last

        # 3. Figaro Immobilier (e.g. /annonces/annonce-59483021.html or /59483021/)
        if "lefigaro.fr" in netloc:
            m = re.search(r'annonce-(\d+)\.html', path) or re.search(r'/(\d{6,})(?:[/?#]|$)', path)
            if m:
                return m.group(1)

        # 4. BienIci (e.g. /annonce/vente/.../bienici-123 or /annonce/123)
        if "bienici.com" in netloc:
            m = re.search(r'/annonce/(?:vente/[^/]+/)?([a-zA-Z0-9_-]+)', path)
            if m and m.group(1) not in ("vente", "location", "neuf", "terrain"):
                return m.group(1)

        # 5. PAP (e.g. /annonces/...-r12345678)
        if "pap.fr" in netloc:
            m = re.search(r'-r(\d+)', path)
            if m:
                return m.group(1)

        # 6. Logic-Immo (e.g. /detail-vente/.../12345678.htm)
        if "logic-immo.com" in netloc:
            m = re.search(r'/detail-[^/]+/(\d+)\.htm', path)
            if m:
                return m.group(1)

    except Exception:
        pass
    return None


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

    # 2. Exact Canonical URL prefix match (path must match)
    if len(clean_base_url) > 20:
        existing = db.query(models.Listing).filter(
            (models.Listing.url.like(f"{clean_base_url}%")) |
            (models.Listing.original_url.like(f"{clean_base_url}%"))
        ).first()
        if existing:
            return existing

    # 3. Platform ID extraction (strictly from portal path identifier)
    platform_id = extract_platform_id(url)
    if platform_id and len(platform_id) >= 6:
        existing = db.query(models.Listing).filter(
            (models.Listing.url.like(f"%{platform_id}%")) | 
            (models.Listing.original_url.like(f"%{platform_id}%"))
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


async def _run_background_scrape(url: str):
    try:
        from app.services import fetch_basic_metadata
        await fetch_basic_metadata(url)
    except Exception as e:
        print(f"[API] Background scrape error for {url}: {e}")


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
    
    background_tasks.add_task(_run_background_scrape, request.url)
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


async def _enrich_external_listing(url: str, listing_id: Optional[int] = None, floorplan_urls: Optional[List[str]] = None):
    try:
        from app.database import SessionLocal
        from app.services import fetch_basic_metadata, repair_listing_photos
        from app.media import download_listing_photos, photos_to_json, save_floorplans_as_attachments
        from app.geo import get_coordinates, fetch_sncf_times_for_city
        import json

        db = SessionLocal()
        try:
            listing = None
            if listing_id:
                listing = db.query(models.Listing).filter(models.Listing.id == listing_id).first()
            if not listing and url:
                listing = find_existing_listing(url, db)

            if listing:
                # 1. Download photos if original_photo_urls is present and local photos are missing or incomplete
                if listing.original_photo_urls:
                    try:
                        urls = json.loads(listing.original_photo_urls)
                        local_list = json.loads(listing.photos_local) if listing.photos_local else []
                        if urls and isinstance(urls, list) and (not local_list or len(urls) > len(local_list)):
                            downloaded = await download_listing_photos(listing.id, urls)
                            if downloaded:
                                listing.photos_local = photos_to_json(downloaded)
                                db.commit()
                    except Exception as e:
                        print(f"[API] Photo download error for listing {listing.id}: {e}")

                # 1b. Floorplans attachments
                if floorplan_urls:
                    try:
                        await save_floorplans_as_attachments(listing.id, floorplan_urls, db)
                    except Exception as e:
                        print(f"[API] Floorplan attachment error for listing {listing.id}: {e}")

                # 2. Geocoding if coordinates are missing
                if listing.latitude is None and (listing.location or listing.city):
                    loc = listing.location or listing.city
                    try:
                        coords = get_coordinates(loc)
                        if coords:
                            listing.latitude, listing.longitude = coords
                            db.commit()
                    except Exception as e:
                        print(f"[API] Geocoding error for listing {listing.id}: {e}")

                # 3. SNCF times if city is present
                if listing.city and not listing.nearest_sncf_station:
                    try:
                        sncf_data = fetch_sncf_times_for_city(listing.city)
                        if sncf_data:
                            listing.nearest_sncf_station = sncf_data.get("nearest_sncf_station")
                            listing.car_time_sncf = sncf_data.get("car_time_sncf")
                            listing.bike_time_sncf = sncf_data.get("bike_time_sncf")
                            listing.walk_time_sncf = sncf_data.get("walk_time_sncf")
                            db.commit()
                    except Exception as e:
                        print(f"[API] SNCF enrichment error for listing {listing.id}: {e}")

            # 4. Optional fallback metadata fetch only if listing data is incomplete
            if url and (not listing or not listing.title or listing.title == "Annonce sans titre" or not listing.description_text):
                try:
                    await fetch_basic_metadata(url)
                except Exception as e:
                    print(f"[API] Fallback metadata fetch error: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[API] _enrich_external_listing failed for {url}: {e}")


def _determine_source(url: str, explicit_source: Optional[str] = None) -> models.Source:
    if explicit_source:
        for s in models.Source:
            if s.value == explicit_source.lower():
                return s
    if "leboncoin.fr" in url:
        return models.Source.LEBONCOIN
    elif "lefigaro.fr" in url:
        return models.Source.LEFIGARO
    elif "seloger.com" in url:
        return models.Source.SELOGER
    elif "bienici.com" in url:
        return models.Source.BIENICI
    elif "pap.fr" in url:
        return models.Source.MANUAL
    return models.Source.MANUAL


@router.post("/check-external-listings", response_model=schemas.ExternalListingCheckResponse)
def check_external_listings_api(
    request: schemas.ExternalListingCheckRequest,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Check a list of URLs and external IDs against existing listings in the database
    to inform the bookmarklet/browser extension which items already exist.
    """
    existing_urls = []
    existing_ext_ids = []

    for u in request.urls:
        if find_existing_listing(u, db):
            existing_urls.append(u)

    if request.external_ids:
        found_ext = db.query(models.Listing.external_id).filter(
            models.Listing.external_id.in_(request.external_ids)
        ).all()
        existing_ext_ids = [r[0] for r in found_ext if r[0]]

    return schemas.ExternalListingCheckResponse(
        existing_urls=existing_urls,
        existing_external_ids=existing_ext_ids
    )


@router.post("/submit-external-listing", response_model=schemas.ActionResponse)
async def submit_external_listing_api(
    request: schemas.ExternalListingSubmitRequest,
    background_tasks: BackgroundTasks,
    req: Request,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Add or update a listing with pre-extracted data from the browser bookmarklet/extension.
    Also queues a background task to enrich photos and coordinates if needed.
    """
    # Validate URL structure and title
    from app.services import is_valid_listing_url, is_search_page_title
    is_valid, err_msg = is_valid_listing_url(request.url)
    if not is_valid:
        raise HTTPException(
            status_code=422,
            detail=err_msg or "L'URL fournie correspond à une page de recherche ou de résultats et ne peut être importée comme une annonce unitaire."
        )
    if is_search_page_title(request.title):
        raise HTTPException(
            status_code=422,
            detail="Le titre de l'annonce indique une page de résultats agrégée plutôt qu'une annonce unique."
        )

    import json
    existing = find_existing_listing(request.url, db)
    is_already_exists = False

    source_val = _determine_source(request.url, request.source)

    price_per_sqm = None
    if request.price and request.area and request.area > 0:
        price_per_sqm = round(request.price / request.area, 2)

    photos_to_store = list(request.photos or [])
    if request.floorplans:
        for fp in request.floorplans:
            if fp not in photos_to_store:
                photos_to_store.append(fp)

    if not existing:
        listing = models.Listing(
            url=request.url,
            original_url=request.url,
            external_id=request.external_id,
            title=request.title or "Annonce sans titre",
            price=request.price,
            area=request.area,
            land_area=request.land_area,
            rooms=request.rooms,
            bedrooms=request.bedrooms,
            bathroom_count=request.bathroom_count,
            city=request.city,
            postal_code=request.postal_code,
            location=request.location or request.city or "Inconnu",
            description_text=request.description,
            property_type=request.property_type,
            dpe_rating=request.dpe_rating,
            ges_rating=request.ges_rating,
            land_tax=request.land_tax,
            charges=request.charges,
            heating_type=request.heating_type,
            heating_mode=request.heating_mode,
            building_year=request.building_year,
            source=source_val,
            status=models.ListingStatus.NEW,
            price_per_sqm=price_per_sqm
        )

        if photos_to_store:
            listing.original_photo_urls = json.dumps(photos_to_store)

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
        if request.price is not None and request.price > 0:
            existing.price = request.price
        if request.area is not None and request.area > 0:
            existing.area = request.area
        if request.land_area is not None:
            existing.land_area = request.land_area
        if price_per_sqm is not None:
            existing.price_per_sqm = price_per_sqm
        if request.city:
            existing.city = request.city
        if request.postal_code:
            existing.postal_code = request.postal_code
        if request.location:
            existing.location = request.location
        elif request.city:
            existing.location = f"{request.city} ({request.postal_code})" if request.postal_code else request.city
        if request.rooms is not None:
            existing.rooms = request.rooms
        if request.bedrooms is not None:
            existing.bedrooms = request.bedrooms
        if request.bathroom_count is not None:
            existing.bathroom_count = request.bathroom_count
        if request.description is not None:
            existing.description_text = request.description
        if request.property_type:
            existing.property_type = request.property_type
        if request.dpe_rating:
            existing.dpe_rating = request.dpe_rating
        if request.ges_rating:
            existing.ges_rating = request.ges_rating
        if request.land_tax is not None:
            existing.land_tax = request.land_tax
        if request.charges is not None:
            existing.charges = request.charges
        if request.heating_type:
            existing.heating_type = request.heating_type
        if request.heating_mode:
            existing.heating_mode = request.heating_mode
        if request.building_year is not None:
            existing.building_year = request.building_year
        if photos_to_store:
            existing.original_photo_urls = json.dumps(photos_to_store)

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

    # Launch background enrichment
    background_tasks.add_task(_enrich_external_listing, request.url, target_listing.id, request.floorplans)

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


@router.post("/submit-external-listings-batch", response_model=schemas.ExternalListingBatchResponse)
async def submit_external_listings_batch_api(
    batch: schemas.ExternalListingBatchRequest,
    background_tasks: BackgroundTasks,
    req: Request,
    current_user: models.User = Depends(get_current_user_api),
    db: Session = Depends(get_db)
):
    """
    Add or update a batch of listings extracted from a search page via bookmarklet or extension.
    Queues background tasks for each new or updated listing.
    """
    import json
    results = []
    created_count = 0
    already_exists_count = 0
    error_count = 0

    from app.services import is_valid_listing_url, is_search_page_title

    for item in batch.listings:
        try:
            is_valid, _ = is_valid_listing_url(item.url)
            if not is_valid or is_search_page_title(item.title):
                error_count += 1
                results.append(schemas.ExternalListingBatchItemResult(
                    url=item.url,
                    success=False,
                    message="Page de recherche ignorée.",
                ))
                continue

            existing = find_existing_listing(item.url, db)
            source_val = _determine_source(item.url, item.source)

            price_per_sqm = None
            if item.price and item.area and item.area > 0:
                price_per_sqm = round(item.price / item.area, 2)

            item_photos = list(item.photos or [])
            if item.floorplans:
                for fp in item.floorplans:
                    if fp not in item_photos:
                        item_photos.append(fp)

            if not existing:
                listing = models.Listing(
                    url=item.url,
                    original_url=item.url,
                    external_id=item.external_id,
                    title=item.title or "Annonce sans titre",
                    price=item.price,
                    area=item.area,
                    land_area=item.land_area,
                    rooms=item.rooms,
                    bedrooms=item.bedrooms,
                    bathroom_count=item.bathroom_count,
                    city=item.city,
                    postal_code=item.postal_code,
                    location=item.location or item.city or "Inconnu",
                    description_text=item.description,
                    property_type=item.property_type,
                    dpe_rating=item.dpe_rating,
                    ges_rating=item.ges_rating,
                    land_tax=item.land_tax,
                    charges=item.charges,
                    source=source_val,
                    status=models.ListingStatus.NEW,
                    price_per_sqm=price_per_sqm
                )

                if item_photos:
                    listing.original_photo_urls = json.dumps(item_photos)

                db.add(listing)
                db.commit()
                db.refresh(listing)
                created_count += 1
                target_listing = listing
                status_str = "created"
            else:
                # Update basic fields if provided
                if item.title:
                    existing.title = item.title
                if item.price is not None and item.price > 0:
                    existing.price = item.price
                if item.area is not None and item.area > 0:
                    existing.area = item.area
                if item.land_area is not None:
                    existing.land_area = item.land_area
                if price_per_sqm is not None:
                    existing.price_per_sqm = price_per_sqm
                if item.city:
                    existing.city = item.city
                if item.postal_code:
                    existing.postal_code = item.postal_code
                if item.location:
                    existing.location = item.location
                elif item.city:
                    existing.location = f"{item.city} ({item.postal_code})" if item.postal_code else item.city
                if item.rooms is not None:
                    existing.rooms = item.rooms
                if item.bedrooms is not None:
                    existing.bedrooms = item.bedrooms
                if item.bathroom_count is not None:
                    existing.bathroom_count = item.bathroom_count
                if item.description and (not existing.description_text or len(item.description) > len(existing.description_text)):
                    existing.description_text = item.description
                if item.property_type:
                    existing.property_type = item.property_type
                if item.dpe_rating:
                    existing.dpe_rating = item.dpe_rating
                if item.ges_rating:
                    existing.ges_rating = item.ges_rating
                if item.land_tax is not None:
                    existing.land_tax = item.land_tax
                if item.charges is not None:
                    existing.charges = item.charges
                if item_photos:
                    existing.original_photo_urls = json.dumps(item_photos)

                db.commit()
                db.refresh(existing)
                already_exists_count += 1
                target_listing = existing
                status_str = "already_exists"

            results.append(schemas.ExternalListingBatchItemResult(
                url=item.url,
                status=status_str,
                listing_id=target_listing.id,
                title=target_listing.title,
                message="OK"
            ))

            # Queue background enrichment
            background_tasks.add_task(_enrich_external_listing, item.url, target_listing.id, item.floorplans)

        except Exception as e:
            error_count += 1
            results.append(schemas.ExternalListingBatchItemResult(
                url=item.url,
                status="error",
                listing_id=None,
                title=item.title,
                error=str(e)
            ))

    message = f"Traitement terminé : {created_count} créée(s), {already_exists_count} déjà existante(s), {error_count} erreur(s)."

    return schemas.ExternalListingBatchResponse(
        status="success",
        message=message,
        total_received=len(batch.listings),
        created_count=created_count,
        already_exists_count=already_exists_count,
        error_count=error_count,
        results=results
    )
