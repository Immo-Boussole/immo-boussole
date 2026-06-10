"""
Business logic services: scraping, duplicate detection, listing creation.
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Listing, ListingStatus, SearchQuery, Source, Review
from app.scrapers import (
    LeboncoinScraper, SelogerScraper, LeFigaroScraper,
    LogicimmoScraper, BieniciScraper, IadfranceScraper,
    NotairesScraper, VinciScraper, ImmobilierFranceScraper,
    OrpiScraper
)
from app.media import download_listing_photos, photos_to_json, json_to_photos, calculate_images_similarity, compute_image_dhash, compute_image_ahash
from app.geo import fetch_sncf_times_for_city, get_coordinates, get_insee_code, fetch_georisques_data
from app.notifications import send_new_listing_notifications
import httpx
from bs4 import BeautifulSoup




# ─── Basic Metadata Extraction ────────────────────────────────────────────────

async def fetch_basic_metadata(url: str) -> dict:
    """
    Attempts to retrieve listing metadata (title, description, image) 
    using basic HTTP requests and OpenGraph meta tags.
    For LeBonCoin, injects WhatsApp User-Agent and extracts full __NEXT_DATA__ payload to bypass Datadome.
    """
    details = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    
    # Bypass Datadome for LeBonCoin
    if "leboncoin.fr" in url:
        headers["User-Agent"] = "WhatsApp/2.21.19.21 A"

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            html_content = resp.text
            
            # ── LeBonCoin __NEXT_DATA__ bypass ──
            if "leboncoin.fr" in url:
                import re
                match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    html_content, re.DOTALL
                )
                if match:
                    try:
                        data = json.loads(match.group(1))
                        ad = data.get("props", {}).get("pageProps", {}).get("ad", {})
                        if ad:
                            details["title"] = ad.get("subject", "")
                            details["description_text"] = ad.get("body", "")
                            price_list = ad.get("price", [0])
                            details["price"] = float(price_list[0]) if price_list else 0.0
                            
                            location = ad.get("location", {})
                            city = location.get("city", "")
                            zipcode = location.get("zipcode", "")
                            details["location"] = f"{city} {zipcode}".strip()
                            details["city"] = city
                            
                            images = ad.get("images", {})
                            urls = images.get("urls_large") or images.get("urls")
                            if isinstance(urls, list):
                                details["photo_urls"] = [u for u in urls if isinstance(u, str)]
                            elif isinstance(urls, str):
                                details["photo_urls"] = [urls]
                                
                            # Attributes
                            for attr in ad.get("attributes", []):
                                key = attr.get("key")
                                val = attr.get("value")
                                if key == "square":
                                    try: details["area"] = float(str(val).replace(",", "."))
                                    except (ValueError, TypeError): pass
                                elif key == "rooms":
                                    try: details["rooms"] = int(val)
                                    except (ValueError, TypeError): pass
                                elif key == "energy_rate":
                                    details["dpe_rating"] = str(val).upper()[:1] if val else None
                                elif key == "ges":
                                    details["ges_rating"] = str(val).upper()[:1] if val else None
                                elif key in ("annual_charges", "charges"):
                                    try: details["charges"] = float(str(val).replace(",", "."))
                                    except (ValueError, TypeError): pass
                            
                            print(f"[Services] LBC Fast Scrape OK: {details['title']} ({len(details.get('photo_urls', []))} photos)")
                            return details
                    except Exception as e:
                        print(f"[Services] LBC __NEXT_DATA__ fast extraction failed: {e}")

            # ── Fallback standard OpenGraph ──
            soup = BeautifulSoup(html_content, "html.parser")
            og_title = soup.find("meta", attrs={"property": "og:title"})
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            page_title = soup.find("title")

            fb_title = (
                og_title.get("content") if og_title else
                page_title.text.strip() if page_title else
                f"Annonce ({url[:40]}…)"
            )
            details["title"] = fb_title
            if og_desc:
                details["description_text"] = og_desc.get("content", "")
            
            # Multiple photos from OpenGraph and Twitter tags
            photo_urls = []
            for og_img in soup.find_all("meta", attrs={"property": "og:image"}):
                content = og_img.get("content")
                if content: photo_urls.append(content)
            
            for tw_img in soup.find_all("meta", attrs={"name": "twitter:image"}):
                content = tw_img.get("content")
                if content: photo_urls.append(content)

            # Fallback to certain <img> tags if no meta images found
            if not photo_urls:
                import re
                img_tags = soup.find_all("img", src=re.compile(r'ad-image|listing|property|photo|gallery', re.I))
                for img in img_tags:
                    src = img.get("src") or img.get("data-src")
                    if src and src.startswith("http"):
                        photo_urls.append(src)
            
            if photo_urls:
                details["photo_urls"] = list(dict.fromkeys(photo_urls))
            
            print(f"[Services] Basic metadata OK: {fb_title!r} ({len(photo_urls)} photos)")
        else:
            details["title"] = f"Annonce ({url[:40]}…) - Erreur {resp.status_code}"
    except Exception as e:
        print(f"[Services] Error fetching basic metadata for {url}: {e}")
        details["title"] = f"Annonce ({url[:40]}…)"
    
    return details


# ─── Listing Creation from Scraped Data ───────────────────────────────────────

def ensure_city_map_pin(city_name: str, db: Session):
    """
    Checks if a MapPin of type 'city' exists for the given city name (case-insensitive, cleaned).
    If not, geocodes the city name and creates the MapPin.
    """
    if not city_name:
        return
    
    import re
    cleaned = city_name.strip()
    cleaned = re.sub(r'\s*\(\d+\)\s*', '', cleaned)
    cleaned = re.sub(r'\b\d{5}\b', '', cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return
    
    from sqlalchemy import func
    from app.models import MapPin
    existing_pin = db.query(MapPin).filter(
        MapPin.pin_type == "city",
        func.lower(MapPin.title) == cleaned.lower()
    ).first()
    
    if not existing_pin:
        coords = get_coordinates(cleaned)
        if coords:
            lat, lon = coords
            new_pin = MapPin(
                title=cleaned.title(),
                address=cleaned.title(),
                lat=lat,
                lon=lon,
                pin_type="city",
                created_by="System"
            )
            db.add(new_pin)
            db.commit()
            print(f"[Services] Automatically created MapPin for city: {cleaned.title()} at {lat}, {lon}")


async def create_listing_from_details(
    db: Session,
    details: dict,
    source: Source,
    original_url: str,
    download_photos: bool = True,
    status: Optional[ListingStatus] = None,
) -> Tuple[Listing, bool]:
    """
    Creates or updates a listing from scraped details.
    Also checks for duplicates and downloads photos asynchronously.

    Returns:
        (listing, is_new): the created/found listing and whether it's newly created
    """
    external_id = details.get("external_id", f"manual_{hash(original_url)}")
    local_paths = [] # Initialize here to ensure it's always defined

    # Check if already exists by external_id or URL
    existing = db.query(Listing).filter(
        (Listing.external_id == external_id) | (Listing.url == original_url)
    ).first()

    listing = existing if existing else Listing(
        external_id=external_id,
        url=original_url,
        original_url=original_url,
        date_added=datetime.now(timezone.utc)
    )

    # ── Update / Set Fields ──────────────────────────────────────────────
    for key, value in details.items():
        if hasattr(listing, key) and value is not None:
            # Skip fields handled specially or problematic
            if key in ("id", "external_id", "url", "source", "status", "scraped_at", "photo_urls"):
                continue
            if key in ("city", "location"):
                from app.geo import standardize_and_enrich_city
                std_city, _, _ = standardize_and_enrich_city(value)
                if std_city:
                    value = std_city
            setattr(listing, key, value)

    # Ensure both listing.city and listing.location are standardized and synchronized
    if listing.city or listing.location:
        from app.geo import standardize_and_enrich_city
        src_val = listing.city or listing.location
        std_city, _, _ = standardize_and_enrich_city(src_val)
        if std_city:
            listing.city = std_city
            listing.location = std_city
    
    if details.get("photo_urls"):
        listing.original_photo_urls = json.dumps(details.get("photo_urls"))

    # Store source and update timestamp
    listing.source = source
    listing.scraped_at = datetime.now(timezone.utc)
    
    # Set status only for new listings or if explicitly provided
    if status:
        listing.status = status
    elif not existing:
        listing.status = ListingStatus.NEW

    if not existing:
        db.add(listing)
    
    db.commit()
    db.refresh(listing)

    # ── Download photos asynchronously in background ──
    photo_urls = details.get("photo_urls", [])
    if photo_urls and download_photos:
        # Avoid re-downloading if already present
        try:
            downloaded = await download_listing_photos(listing.id, photo_urls)
            if downloaded:
                local_paths = downloaded
                listing.photos_local = photos_to_json(local_paths)
                db.commit()
        except Exception as e:
            print(f"[Services] Error downloading photos for listing {listing.id}: {e}")

    # ── Geocoding ──
    if (listing.location or listing.city) and listing.latitude is None:
        loc = listing.location or listing.city
        coords = get_coordinates(loc)
        if coords:
            listing.latitude, listing.longitude = coords
            db.commit()

    # ── Pre-calculate SNCF Distances ──
    if listing.city and listing.nearest_sncf_station is None:
        from app.models import ZoneRule
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
            listing.walk_time_sncf_2 = sncf_data.get('walk_time_sncf_2')
            listing.bike_time_sncf_2 = sncf_data.get('bike_time_sncf_2')
            listing.car_time_sncf_2 = sncf_data.get('car_time_sncf_2')
        else:
            listing.nearest_sncf_station = "NOT_FOUND"
        db.commit()

    # ── Géorisques Risk Report ──
    if listing.georisques_json is None:
        await update_listing_georisques(listing, db)

    # ── Ensure City MapPin exists ──
    if listing.city:
        ensure_city_map_pin(listing.city, db)

    return listing, (not existing)


async def update_listing_georisques(listing: Listing, db: Session):
    """
    Fetches and updates Géorisques data for a listing.
    """
    import re
    
    location = listing.location or ""
    city = listing.city or ""
    
    # Extract zipcode if present
    zip_match = re.search(r'\d{5}', location)
    zipcode = zip_match.group(0) if zip_match else None
    
    # Heuristic for full address: contains a number at start or is notably longer than city+zip
    location_norm = location.strip().lower()
    city_norm = city.strip().lower()
    
    is_address = False
    if location_norm:
        # Check for street number at start
        if re.match(r'^\d+', location_norm):
            is_address = True
        elif city_norm and len(location_norm) > (len(city_norm) + 7):
            is_address = True
            
    report_json = None
    if is_address:
        print(f"[Services] Fetching Géorisques for address: {location}")
        report_json = fetch_georisques_data(address=location)
    elif city:
        insee = get_insee_code(city, zipcode)
        if insee:
            print(f"[Services] Fetching Géorisques for INSEE: {insee} ({city})")
            report_json = fetch_georisques_data(insee_code=insee)
            
    if report_json:
        listing.georisques_json = json.dumps(report_json)
        db.commit()
        print(f"[Services] Géorisques report saved for listing {listing.id}")


# ─── Scrape and Diff (Search Queries) ─────────────────────────────────────────

async def scrape_and_diff(query: SearchQuery, db: Session, ready_search=None):
    """
    Runs the full scrape cycle for a search query:
    1. Scrapes listing results
    2. Marks disappeared listings
    3. Creates new listings with duplicate detection
    
    Args:
        query: The SearchQuery to run (URL + source/platform)
        db: DB session
        ready_search: Optional ReadySearch that triggered this job (used to store
                      platform/criteria origin on new listings for the auto_searches view)
    """
    scrapers = {
        Source.LEBONCOIN: LeboncoinScraper(),
        Source.SELOGER: SelogerScraper(),
        Source.LEFIGARO: LeFigaroScraper(),
        Source.LOGICIMMO: LogicimmoScraper(),
        Source.BIENICI: BieniciScraper(),
        Source.IADFRANCE: IadfranceScraper(),
        Source.NOTAIRES: NotairesScraper(),
        Source.VINCI: VinciScraper(),
        Source.IMMOBILIER_FRANCE: ImmobilierFranceScraper(),
        Source.ORPI: OrpiScraper(),
    }

    scraper = scrapers.get(query.source)
    if not scraper:
        print(f"[Services] Scraper introuvable pour: {query.source}")
        return

    print(f"[Services] Scraping de {query.url}")
    scraped_listings = await scraper.get_listings(query.url)
    scraped_ids = [str(l["external_id"]) for l in scraped_listings]

    # Find currently active listings for this source
    existing_active = db.query(Listing).filter(
        Listing.source == query.source,
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW])
    ).all()

    existing_ids = [l.external_id for l in existing_active]

    # 1. DISAPPEARED logic (DISABLED here because it's too aggressive with overlapping searches)
    # Disappearance is now handled by refresh_all_listings_status which checks URLs individually.
    disappeared_count = 0
    # for listing in existing_active:
    #     if listing.external_id not in scraped_ids:
    #         listing.status = ListingStatus.DISAPPEARED
    #         disappeared_count += 1

    # 2. Process new listings
    new_count = 0
    new_listing_objects: list[Listing] = []  # collected for notifications
    for item in scraped_listings:
        ext_id = str(item["external_id"])
        item_url = item.get("url", "")
        
        city_val = item.get("city")
        loc_val = item.get("location") or city_val
        city_to_check = loc_val or city_val
        
        if city_to_check:
            from app.geo import standardize_and_enrich_city
            std_city, _, _ = standardize_and_enrich_city(city_to_check)
            if std_city:
                city_val = std_city
                loc_val = std_city
                item["city"] = std_city
                item["location"] = std_city
                city_to_check = std_city

            from app.main import _is_city_in_allowed_departments
            if not _is_city_in_allowed_departments(city_to_check, db):
                continue
        
        # Check if listing already exists by external_id OR URL
        # We check globally, not just in existing_active, to avoid UNIQUE constraint violations
        existing = db.query(Listing).filter(
            (Listing.external_id == ext_id) | (Listing.url == item_url)
        ).first()

        if existing:
            # Case: Already exists (active, new, or disappeared)
            if existing.status == ListingStatus.DISAPPEARED:
                existing.status = ListingStatus.NEW
                existing.date_updated = datetime.now(timezone.utc)
            
            # Update fields
            existing.price = item.get("price")
            existing.scraped_at = datetime.now(timezone.utc)
            
            # If external_id was None (manual) or changed, update it
            if not existing.external_id or existing.external_id != ext_id:
                existing.external_id = ext_id
            
            # Refresh Géorisques even for existing listings (as requested)
            await update_listing_georisques(existing, db)
        else:
            # Check for photo_urls in item
            photo_urls = item.get("photo_urls", [])
            
            # Case: Brand new listing
            city_val = item.get("city")
            loc_val = item.get("location") or city_val
            
            new_listing = Listing(
                external_id=ext_id,
                title=item.get("title", "Sans titre"),
                url=item_url,
                original_url=item_url,
                price=item.get("price"),
                location=loc_val,
                city=city_val,
                area=item.get("area"),
                rooms=item.get("rooms"),
                source=query.source,
                status=ListingStatus.NEW,
                scraped_at=datetime.now(timezone.utc),
                is_duplicate=False,
                duplicate_of_id=None,
                # Store the origin ReadySearch for the auto_searches view
                source_ready_search_id=ready_search.id if ready_search else None,
                source_criteria=ready_search.criteria if ready_search else None,
                original_photo_urls=json.dumps(photo_urls) if photo_urls else None,
            )

            # Geocoding for new listing
            loc = new_listing.location or new_listing.city
            if loc:
                coords = get_coordinates(loc)
                if coords:
                    new_listing.latitude, new_listing.longitude = coords

            db.add(new_listing)
            try:
                db.commit() # Commit to get ID
                db.refresh(new_listing)
                
                # Download photos if available
                if photo_urls:
                    try:
                        downloaded = await download_listing_photos(new_listing.id, photo_urls)
                        if downloaded:
                            new_listing.photos_local = photos_to_json(downloaded)
                            db.commit()
                    except Exception as e:
                        print(f"[Services] Error downloading photos for NEW listing {new_listing.id}: {e}")

                await update_listing_georisques(new_listing, db)
                if new_listing.city:
                    ensure_city_map_pin(new_listing.city, db)
                new_listing_objects.append(new_listing)
                new_count += 1
            except Exception as e:
                db.rollback()
                print(f"[Services] Erreur lors de l'insertion de l'annonce {ext_id}: {e}")
                continue

    db.commit()

    # Update last_run timestamp
    query.last_run = datetime.now(timezone.utc)
    db.commit()

    print(
        f"[Services] Diff terminé: {len(scraped_ids)} annonces scrapées, "
        f"{new_count} nouvelles."
    )

    # ── Send push notifications for new listings ──
    if new_listing_objects:
        await send_new_listing_notifications(new_listing_objects, db)


async def refresh_listing_status(listing: Listing, db: Session, force_update: bool = False):
    """
    Checks if a listing is still online by visiting its URL.
    Updates status to DISAPPEARED if not found.
    Also ensures the presentation image is valid; if not, refreshes the listing.
    If force_update is True, always updates listing fields from scraper.
    """
    from app.main import _resolve_scraper
    source, scraper = _resolve_scraper(listing.url)
    
    print(f"[Services] Refreshing status for listing {listing.id} ({listing.url})")
    
    is_online = True
    details = {}
    try:
        if scraper:
            details = await scraper.get_listing_details(listing.url)
            # If scraper returns empty or a title indicating an error/removed page
            if not details or not details.get("external_id") or "Erreur" in details.get("title", ""):
                is_online = False
        else:
            # Fallback for manual or unknown sources
            details = await fetch_basic_metadata(listing.url)
            if not details or "Erreur" in details.get("title", ""):
                is_online = False
    except Exception as e:
        print(f"[Services] Error checking status for {listing.id}: {e}")
        # In case of network error, we don't assume it's disappeared
        return

    # Check if presentation photo (the first one) is valid on disk
    photo_ok = False
    photos = json_to_photos(listing.photos_local)
    if photos:
        first_photo_path = photos[0]
        if os.path.exists(first_photo_path) and os.path.getsize(first_photo_path) > 0:
            photo_ok = True

    if not is_online:
        if listing.status != ListingStatus.DISAPPEARED:
            print(f"[Services] Listing {listing.id} has DISAPPEARED")
            listing.status = ListingStatus.DISAPPEARED
            db.commit()
    else:
        # If it was disappeared but now it's back, OR if the photo is broken
        was_disappeared = (listing.status == ListingStatus.DISAPPEARED)
        
        if was_disappeared or not photo_ok or force_update:
            reason = "BACK ONLINE" if was_disappeared else ("PHOTO BROKEN/MISSING" if not photo_ok else "MANUAL REPAIR")
            print(f"[Services] Listing {listing.id} is {reason}, performing full refresh...")
            
            # Update fields from details
            for key, value in details.items():
                if hasattr(listing, key) and value is not None:
                    # Skip fields handled specially or problematic
                    if key in ("id", "external_id", "url", "source", "status", "scraped_at", "photo_urls"):
                        continue
                    setattr(listing, key, value)
            
            # Re-download photos
            photo_urls = details.get("photo_urls", [])
            if photo_urls:
                try:
                    downloaded = await download_listing_photos(listing.id, photo_urls)
                    if downloaded:
                        listing.photos_local = photos_to_json(downloaded)
                except Exception as e:
                    print(f"[Services] Error re-downloading photos for listing {listing.id}: {e}")
            
            if was_disappeared:
                print(f"[Services] Listing {listing.id} is BACK ONLINE")
                listing.status = ListingStatus.ACTIVE
            
            db.commit()
    
    listing.scraped_at = datetime.now(timezone.utc)
    db.commit()


async def refresh_all_listings_status(db: Session):
    """
    Iterates through all ACTIVE, NEW and DISAPPEARED listings 
    to refresh their online status.
    """
    listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, ListingStatus.DISAPPEARED])
    ).all()
    
    print(f"[Services] Starting global status refresh for {len(listings)} listings...")
    for l in listings:
        await refresh_listing_status(l, db)
    print("[Services] Global status refresh completed.")


# ─── Review Management ────────────────────────────────────────────────────────

def get_or_create_review(
    db: Session,
    listing_id: int,
    reviewer: str,
    pros: Optional[str] = None,
    cons: Optional[str] = None,
    rating: Optional[float] = None,
    visit_done: bool = False,
    notes: Optional[str] = None,
) -> Tuple[Review, bool]:
    """
    Creates or updates a review for a listing by a specific reviewer.
    Only one review per (listing_id, reviewer) pair.
    """
    existing = db.query(Review).filter(
        Review.listing_id == listing_id,
        Review.reviewer == reviewer.lower()
    ).first()

    if existing:
        # Update existing review
        if pros is not None:
            existing.pros = pros
        if cons is not None:
            existing.cons = cons
        if rating is not None:
            existing.rating = rating
        if visit_done is not None:
            existing.visit_done = visit_done
        if notes is not None:
            existing.notes = notes
        db.commit()
        db.refresh(existing)
        return existing, False

    # Create new review
    review = Review(
        listing_id=listing_id,
        reviewer=reviewer.lower(),
        pros=pros,
        cons=cons,
        rating=rating,
        visit_done=visit_done,
        notes=notes,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review, True


# ─── Ideal Property Profile ───────────────────────────────────────────────────

def _parse_keywords(raw_list: list) -> list:
    """
    Parse a list of raw pros/cons strings into deduplicated, counted, sorted items.
    Each raw string may contain multiple items separated by newlines or ' - '.
    Returns: [{"text": str, "count": int}, ...] sorted by count desc, then alpha asc.
    """
    from collections import Counter
    counts: Counter = Counter()
    for raw in raw_list:
        if not raw:
            continue
        for block in raw.split('\n'):
            for item in block.split(' - '):
                clean = item.strip().strip('-').strip()
                if clean:
                    counts[clean] += 1
    return [
        {"text": text, "count": count}
        for text, count in sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
    ]


def generate_ideal_profile(db: Session) -> dict:
    """
    Aggregates all well-rated reviews (≥ 7/10) to generate
    an "Ideal Property Profile" highlighting common positives
    and points to avoid.
    """
    # Get all reviews with a rating
    good_reviews = db.query(Review).filter(
        Review.rating >= 7.0,
        Review.pros != None,
    ).all()

    bad_reviews = db.query(Review).filter(
        Review.cons != None,
    ).all()

    # Collect pros and cons as raw strings
    raw_pros = [r.pros for r in good_reviews if r.pros]
    raw_cons = [r.cons for r in bad_reviews if r.cons]

    # Deduplicate, count occurrences, and sort (most frequent first, then alpha)
    all_pros = _parse_keywords(raw_pros)
    all_cons = _parse_keywords(raw_cons)

    # Get statistics from top-rated listings AND favorite listings
    top_listing_ids = list(set(r.listing_id for r in good_reviews))
    favorite_listings = db.query(Listing).filter(Listing.is_favorite == True).all()
    for fl in favorite_listings:
        if fl.id not in top_listing_ids:
            top_listing_ids.append(fl.id)

    top_listings = db.query(Listing).filter(Listing.id.in_(top_listing_ids)).all()

    # Compute averages
    prices = [l.price for l in top_listings if l.price]
    areas = [l.area for l in top_listings if l.area]
    ppsqm = [l.price_per_sqm for l in top_listings if l.price_per_sqm]
    rooms = [l.rooms for l in top_listings if l.rooms]

    avg_price = round(sum(prices) / len(prices), 0) if prices else None
    avg_area = round(sum(areas) / len(areas), 1) if areas else None
    avg_ppsqm = round(sum(ppsqm) / len(ppsqm), 0) if ppsqm else None
    avg_rooms = round(sum(rooms) / len(rooms), 1) if rooms else None

    # DPE distribution
    dpe_ratings = [l.dpe_rating for l in top_listings if l.dpe_rating]
    dpe_dist = {}
    for d in dpe_ratings:
        dpe_dist[d] = dpe_dist.get(d, 0) + 1

    return {
        "based_on": len(good_reviews),
        "avg_price": avg_price,
        "avg_area": avg_area,
        "avg_price_per_sqm": avg_ppsqm,
        "avg_rooms": avg_rooms,
        "dpe_distribution": dpe_dist,
        "common_pros": all_pros,
        "common_cons": all_cons,
        "top_listings": [
            {
                "id": l.id,
                "title": l.title,
                "price": l.price,
                "area": l.area,
                "rooms": l.rooms,
                "location": l.location,
                "dpe_rating": l.dpe_rating,
                "is_favorite": l.is_favorite,
                "source": l.source.value if l.source else None,
                "source_criteria": l.source_criteria,
                "status": l.status.value if l.status else None,
                "url": l.url,
            }
            for l in top_listings
        ],
    }

# ─── Duplicate Hunting ────────────────────────────────────────────────────────

def calculate_listing_similarity(l1: Listing, l2: Listing, hash_cache: dict = None) -> Tuple[float, list]:
    """
    Calculates a similarity score (0 to 100) and common points between two listings.
    """
    import difflib
    score = 0
    common = []
    
    # 1. City (Mandatory for high score)
    c1 = (l1.city or l1.location or "").strip().lower()
    c2 = (l2.city or l2.location or "").strip().lower()
    if c1 and c2 and c1 == c2:
        score += 30
        common.append("city")

    # 2. Price (±5%)
    if l1.price and l2.price:
        diff = abs(l1.price - l2.price)
        max_p = max(l1.price, l2.price)
        if max_p > 0 and (diff / max_p) <= 0.05:
            score += 20
            common.append("price")
        elif max_p > 0 and (diff / max_p) <= 0.10:
            score += 10 # Half points for 10% range

    # 3. Area (±5%)
    if l1.area and l2.area:
        diff = abs(l1.area - l2.area)
        max_a = max(l1.area, l2.area)
        if max_a > 0 and (diff / max_a) <= 0.05:
            score += 20
            common.append("area")
        elif max_a > 0 and (diff / max_a) <= 0.10:
            score += 10

    # 4. Land Area (±5%) - Only if both have it
    if l1.land_area and l2.land_area:
        diff = abs(l1.land_area - l2.land_area)
        max_la = max(l1.land_area, l2.land_area)
        if max_la > 0 and (diff / max_la) <= 0.05:
            score += 10
            common.append("land_area")
            
    # 5. Description Similarity
    if l1.description_text and l2.description_text:
        # Use difflib for a quick ratio
        ratio = difflib.SequenceMatcher(None, l1.description_text[:1000], l2.description_text[:1000]).ratio()
        if ratio > 0.8:
            score += 20
            common.append("description")
        elif ratio > 0.6:
            score += 10

    # 6. First Photo (Visual/Metadata hint via perceptual hashing)
    p1 = json_to_photos(l1.photos_local)
    p2 = json_to_photos(l2.photos_local)
    if p1 and p2:
        path1 = os.path.join(os.getcwd(), p1[0])
        path2 = os.path.join(os.getcwd(), p2[0])
        if os.path.exists(path1) and os.path.exists(path2):
            if hash_cache is not None:
                if path1 not in hash_cache:
                    hash_cache[path1] = (compute_image_dhash(path1), compute_image_ahash(path1))
                if path2 not in hash_cache:
                    hash_cache[path2] = (compute_image_dhash(path2), compute_image_ahash(path2))
                d1, a1 = hash_cache[path1]
                d2, a2 = hash_cache[path2]
                
                if d1 and d2 and a1 and a2:
                    def hamming_distance(h1, h2):
                        return sum(bin(int(c1, 16) ^ int(c2, 16)).count('1') for c1, c2 in zip(h1, h2))
                    
                    dist_d = hamming_distance(d1, d2)
                    dist_a = hamming_distance(a1, a2)
                    
                    sim_d = (64 - dist_d) / 64 * 100
                    sim_a = (64 - dist_a) / 64 * 100
                    img_sim = (sim_d + sim_a) / 2.0
                else:
                    img_sim = 0.0
            else:
                img_sim = calculate_images_similarity(path1, path2)

            if img_sim >= 90.0:
                score += 30
                common.append("photo")
            elif img_sim >= 75.0:
                score += 20
                common.append("photo")
            elif img_sim >= 60.0:
                score += 10

    return min(score, 100), common


def find_potential_duplicates(db: Session, limit_listings: int = 200) -> list:
    """
    Finds pairs of listings that might be duplicates.
    Excludes pairs already rejected or already marked as duplicates.
    """
    from app.models import RejectedDuplicate
    
    # Get active/new listings, sorted by date (most recent first)
    listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW]),
        Listing.is_duplicate == False
    ).order_by(Listing.date_added.desc()).limit(limit_listings).all()
    
    # Get rejected pairs
    rejected = db.query(RejectedDuplicate).all()
    rejected_pairs = set()
    for r in rejected:
        rejected_pairs.add(tuple(sorted((r.listing_a_id, r.listing_b_id))))
        
    potential_pairs = []
    hash_cache = {}
    
    for i in range(len(listings)):
        for j in range(i + 1, len(listings)):
            l1 = listings[i]
            l2 = listings[j]
            
            # Skip if same source (usually same platform doesn't have same listing twice with different IDs, 
            # but sometimes they do. However, the goal is often cross-platform duplicates).
            # Actually, the user might want to see them even on same source.
            
            # Skip if already in rejected
            if tuple(sorted((l1.id, l2.id))) in rejected_pairs:
                continue
                
            score, common = calculate_listing_similarity(l1, l2, hash_cache=hash_cache)
            
            if score >= 50: # Threshold for "potential" (ignores duplicates strictly below 50% for performance)
                potential_pairs.append({
                    "l1": l1,
                    "l2": l2,
                    "score": score,
                    "common": common
                })
                
    # Sort by score descending
    potential_pairs.sort(key=lambda x: x["score"], reverse=True)
    return potential_pairs
