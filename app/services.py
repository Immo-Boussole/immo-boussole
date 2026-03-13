"""
Business logic services: scraping, duplicate detection, listing creation.
"""
import json
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Listing, ListingStatus, SearchQuery, Source, Review
from app.scrapers import (
    LeboncoinScraper, SelogerScraper, LeFigaroScraper,
    LogicimmoScraper, BieniciScraper, IadfranceScraper,
    NotairesScraper, VinciScraper, ImmobilierFranceScraper
)
from app.media import download_listing_photos, photos_to_json
import httpx
from bs4 import BeautifulSoup


# ─── Duplicate Detection ──────────────────────────────────────────────────────

def check_duplicate(
    db: Session,
    price: Optional[float],
    area: Optional[float],
    city: Optional[str],
) -> Optional[Listing]:
    """
    Returns an existing listing if a near-match is found based on:
    - Price within ±5%
    - Area within ±5 m²
    - Same normalized city name (case-insensitive)

    Returns None if no duplicate exists.
    """
    if not price and not area and not city:
        return None

    query = db.query(Listing).filter(
        Listing.status != ListingStatus.DISAPPEARED
    )

    candidates = query.all()

    for listing in candidates:
        # Price match (±5%)
        price_match = True
        if price and listing.price and listing.price > 0:
            tolerance = listing.price * 0.05
            price_match = abs(listing.price - price) <= tolerance

        # Area match (±5 m²)
        area_match = True
        if area and listing.area and listing.area > 0:
            area_match = abs(listing.area - area) <= 5.0

        # City match (case-insensitive)
        city_match = True
        if city and listing.city:
            city_match = listing.city.lower().strip() == city.lower().strip()

        if price_match and area_match and city_match:
            return listing

    return None


# ─── Basic Metadata Extraction ────────────────────────────────────────────────

async def fetch_basic_metadata(url: str) -> dict:
    """
    Attempts to retrieve listing metadata (title, description, image) 
    using basic HTTP requests and OpenGraph meta tags.
    """
    details = {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            og_title = soup.find("meta", attrs={"property": "og:title"})
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            og_img = soup.find("meta", attrs={"property": "og:image"})
            page_title = soup.find("title")

            fb_title = (
                og_title.get("content") if og_title else
                page_title.text.strip() if page_title else
                f"Annonce ({url[:40]}…)"
            )
            details["title"] = fb_title
            if og_desc:
                details["description_text"] = og_desc.get("content", "")
            if og_img:
                details["photo_urls"] = [og_img.get("content")]
            print(f"[Services] Basic metadata OK: {fb_title!r}")
        else:
            details["title"] = f"Annonce ({url[:40]}…)"
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

    if existing:
        # Update scraped_at timestamp and return
        existing.scraped_at = datetime.utcnow()
        existing.status = ListingStatus.NEW
        db.commit()
        db.refresh(existing)
        return existing, False

    # Prepare photo URLs for download
    photo_urls = details.get("photo_urls", [])

    # Check for duplicates before inserting
    price = details.get("price")
    area = details.get("area")
    city = details.get("city")
    duplicate = check_duplicate(db, price, area, city)

    # Create new listing
    new_listing = Listing(
        external_id=external_id,
        title=details.get("title", "Annonce importée"),
        url=original_url,
        original_url=original_url,
        price=price,
        price_per_sqm=details.get("price_per_sqm"),
        location=details.get("location"),
        city=city,
        area=area,
        land_area=details.get("land_area"),
        rooms=details.get("rooms"),
        bedrooms=details.get("bedrooms"),
        bathroom_count=details.get("bathroom_count"),
        toilet_count=details.get("toilet_count"),
        floor=details.get("floor"),
        total_floors=details.get("total_floors"),
        building_year=details.get("building_year"),
        # Property characteristics
        property_type=details.get("property_type"),
        condition=details.get("condition"),
        heating_type=details.get("heating_type"),
        heating_mode=details.get("heating_mode"),
        kitchen_type=details.get("kitchen_type"),
        orientation=details.get("orientation"),
        view=details.get("view"),
        # Outdoor & amenities
        cellar=details.get("cellar"),
        parking_count=details.get("parking_count"),
        balcony=details.get("balcony"),
        balcony_area=details.get("balcony_area"),
        terrace=details.get("terrace"),
        terrace_area=details.get("terrace_area"),
        garden=details.get("garden"),
        garden_area=details.get("garden_area"),
        pool=details.get("pool"),
        elevator=details.get("elevator"),
        interphone=details.get("interphone"),
        guardian=details.get("guardian"),
        furnished=details.get("furnished"),
        # Energy
        dpe_rating=details.get("dpe_rating"),
        ges_rating=details.get("ges_rating"),
        dpe_value=details.get("dpe_value"),
        ges_value=details.get("ges_value"),
        # Costs
        land_tax=details.get("land_tax"),
        charges=details.get("charges"),
        agency_fee=details.get("agency_fee"),
        # Copropriété
        copropriete_lots=details.get("copropriete_lots"),
        procedure_syndic=details.get("procedure_syndic"),
        honoraires_a_charge=details.get("honoraires_a_charge"),
        # Media
        virtual_tour_url=details.get("virtual_tour_url"),
        description_text=details.get("description_text"),
        original_photo_urls=json.dumps(photo_urls) if photo_urls else None,
        source=source,
        status=ListingStatus.NEW,
        scraped_at=datetime.utcnow(),
        is_duplicate=(duplicate is not None),
        duplicate_of_id=duplicate.id if duplicate else None,
    )


    db.add(new_listing)
    db.commit()
    db.refresh(new_listing)

    # Download photos asynchronously in background
    if photo_urls and download_photos:
        local_paths = await download_listing_photos(new_listing.id, photo_urls)
        if local_paths:
            new_listing.photos_local = photos_to_json(local_paths)
            db.commit()

    return new_listing, True


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
            existing = db.query(Listing).filter(Listing.external_id == ext_id).first()
            if existing:
                existing.status = ListingStatus.NEW
                existing.price = item.get("price")
                existing.date_updated = datetime.utcnow()
            else:
                # Check for duplicates
                duplicate = check_duplicate(
                    db,
                    item.get("price"),
                    item.get("area"),
                    item.get("city"),
                )

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
                    scraped_at=datetime.utcnow(),
                    is_duplicate=(duplicate is not None),
                    duplicate_of_id=duplicate.id if duplicate else None,
                )
                db.add(new_listing)
                new_count += 1

    db.commit()

    # Update last_run timestamp
    query.last_run = datetime.utcnow()
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
