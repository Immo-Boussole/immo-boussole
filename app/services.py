"""
Business logic services: scraping, duplicate detection, listing creation.
"""
import json
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Listing, ListingStatus, SearchQuery, Source, Review
from app.scrapers import (
    LeboncoinScraper, SelogerScraper, LeFigaroScraper,
    LogicimmoScraper, BieniciScraper, IadfranceScraper,
    NotairesScraper, VinciScraper, ImmobilierFranceScraper
)
from app.media import download_listing_photos, photos_to_json
from app.geo import fetch_sncf_times_for_city, get_coordinates
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

async def create_listing_from_details(
    db: Session,
    details: dict,
    source: Source,
    original_url: str,
    download_photos: bool = True,
) -> Tuple[Listing, bool]:
    """
    Creates or updates a listing from scraped details.
    Also checks for duplicates and downloads photos asynchronously.

    Returns:
        (listing, is_new): the created/found listing and whether it's newly created
    """
    external_id = details.get("external_id", f"manual_{hash(original_url)}")

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
            setattr(listing, key, value)
    
    if details.get("photo_urls"):
        listing.original_photo_urls = json.dumps(details.get("photo_urls"))

    # Store source and update timestamp
    listing.source = source
    listing.scraped_at = datetime.now(timezone.utc)
    listing.status = ListingStatus.NEW

    if not existing:
        db.add(listing)
    
    db.commit()
    db.refresh(listing)

    # ── Download photos asynchronously in background ──
    photo_urls = details.get("photo_urls", [])
    if photo_urls and download_photos:
        # Avoid re-downloading if already present (unless it's a re-scrape with different photos?)
            if local_paths:
                listing.photos_local = photos_to_json(local_paths)
                db.commit()

    # ── Geocoding ──
    if (listing.location or listing.city) and listing.latitude is None:
        loc = listing.location or listing.city
        coords = get_coordinates(loc)
        if coords:
            listing.latitude, listing.longitude = coords
            db.commit()

    # ── Pre-calculate SNCF Distances ──
    if listing.city and listing.nearest_sncf_station is None:
        sncf_data = fetch_sncf_times_for_city(listing.city)
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

    return listing, (not existing)


# ─── Scrape and Diff (Search Queries) ─────────────────────────────────────────

async def scrape_and_diff(query: SearchQuery, db: Session):
    """
    Runs the full scrape cycle for a search query:
    1. Scrapes listing results
    2. Marks disappeared listings
    3. Creates new listings with duplicate detection
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

    # 1. Mark disappeared listings
    disappeared_count = 0
    for listing in existing_active:
        if listing.external_id not in scraped_ids:
            listing.status = ListingStatus.DISAPPEARED
            disappeared_count += 1

    # 2. Process new listings
    new_count = 0
    for item in scraped_listings:
        ext_id = str(item["external_id"])
        if ext_id not in existing_ids:
            # Case 1: Brand new or was previously disappeared
            existing = db.query(Listing).filter(Listing.external_id == ext_id).first()
            if existing:
                existing.status = ListingStatus.NEW
                existing.price = item.get("price")
                existing.date_updated = datetime.now(timezone.utc)
                existing.scraped_at = datetime.now(timezone.utc)
            else:
                new_listing = Listing(
                    external_id=ext_id,
                    title=item.get("title", "Sans titre"),
                    url=item.get("url", ""),
                    original_url=item.get("url", ""),
                    price=item.get("price"),
                    location=item.get("location"),
                    city=item.get("city"),
                    area=item.get("area"),
                    rooms=item.get("rooms"),
                    source=query.source,
                    status=ListingStatus.NEW,
                    scraped_at=datetime.now(timezone.utc),
                    is_duplicate=False,
                    duplicate_of_id=None,
                )

                # Geocoding for new listing
                loc = new_listing.location or new_listing.city
                if loc:
                    coords = get_coordinates(loc)
                    if coords:
                        new_listing.latitude, new_listing.longitude = coords

                db.add(new_listing)
                new_count += 1
        else:
            # Case 2: Already active/new and still online
            # Find the object in our local list to update it
            existing = next((l for l in existing_active if l.external_id == ext_id), None)
            if existing:
                # Transition NEW -> ACTIVE
                if existing.status == ListingStatus.NEW:
                    existing.status = ListingStatus.ACTIVE
                # Always update the timestamp and price
                existing.scraped_at = datetime.now(timezone.utc)
                if item.get("price"):
                    existing.price = item.get("price")

    db.commit()

    # Update last_run timestamp
    query.last_run = datetime.now(timezone.utc)
    db.commit()

    print(
        f"[Services] Diff terminé: {len(scraped_ids)} annonces scrapées, "
        f"{new_count} nouvelles, {disappeared_count} disparues."
    )


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

    # Collect pros and cons
    all_pros = [r.pros for r in good_reviews if r.pros]
    all_cons = [r.cons for r in bad_reviews if r.cons]

    # Get statistics from top-rated listings
    top_listing_ids = list(set(r.listing_id for r in good_reviews))
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
                "location": l.location,
                "dpe_rating": l.dpe_rating,
            }
            for l in top_listings
        ],
    }
