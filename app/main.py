"""
FastAPI application main entry point.
Defines all routes: HTML pages + REST API.
"""
import json
import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app import models, database
from app.database import engine, get_db, run_migrations
from app.models import Listing, ListingStatus, Review, Source, SearchQuery
from app.services import (
    scrape_and_diff,
    create_listing_from_details,
    check_duplicate,
    get_or_create_review,
    fetch_basic_metadata,
    generate_ideal_profile,
)
from app.media import json_to_photos

# Run migrations FIRST (adds missing columns to existing tables)
run_migrations()
# Then create any brand-new tables (e.g. reviews)
models.Base.metadata.create_all(bind=engine)

# Create static media directory
os.makedirs("static/media", exist_ok=True)
os.makedirs("templates", exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: start background scheduler
    from app.scheduler import start_scheduler
    scheduler = start_scheduler()
    yield
    # Shutdown
    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(title="Immo-Boussole", lifespan=lifespan)

# Mount static files (local media storage)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class SubmitUrlRequest(BaseModel):
    url: str
    skip_scraping: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if not v.startswith("http"):
            raise ValueError("URL must start with http:// or https://")
        return v.strip()


class ReviewRequest(BaseModel):
    reviewer: str
    pros: Optional[str] = None
    cons: Optional[str] = None
    rating: Optional[float] = None
    visit_done: bool = False
    notes: Optional[str] = None

    @field_validator("reviewer")
    @classmethod
    def validate_reviewer(cls, v):
        allowed = ["jean-marc", "marceline"]
        if v.lower() not in allowed:
            raise ValueError(f"reviewer must be one of: {allowed}")
        return v.lower()

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v):
        if v is not None and not (0 <= v <= 10):
            raise ValueError("rating must be between 0 and 10")
        return v


class SearchQueryRequest(BaseModel):
    url: str
    source: str
    name: Optional[str] = None


# ─── HTML Pages ───────────────────────────────────────────────────────────────

@app.get("/")
def read_root(request: Request, db: Session = Depends(get_db)):
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    queries = db.query(SearchQuery).all()

    # Attach local photos to each listing
    for listing in listings:
        listing._photos = json_to_photos(listing.photos_local)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "listings": listings,
        "queries": queries,
        "title": "Tableau de Bord — Immo-Boussole",
    })


@app.get("/listings/table")
def listings_table_page(request: Request, db: Session = Depends(get_db)):
    listings = db.query(Listing).order_by(Listing.date_added.desc()).all()
    queries = db.query(SearchQuery).all()

    for listing in listings:
        listing._photos = json_to_photos(listing.photos_local)

    return templates.TemplateResponse("listings_table.html", {
        "request": request,
        "listings": listings,
        "queries": queries,
        "title": "Tableau des Annonces — Immo-Boussole",
    })


@app.get("/listings/{listing_id}")
def listing_detail_page(
    request: Request,
    listing_id: int,
    db: Session = Depends(get_db),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable")

    photos = json_to_photos(listing.photos_local)
    reviews = db.query(Review).filter(Review.listing_id == listing_id).all()

    # Build a dict of reviews by reviewer for easy template access
    reviews_by_reviewer = {r.reviewer: r for r in reviews}

    # If there is a duplicate of another listing, load it
    duplicate_original = None
    if listing.duplicate_of_id:
        duplicate_original = db.query(Listing).filter(
            Listing.id == listing.duplicate_of_id
        ).first()

    return templates.TemplateResponse("listing_detail.html", {
        "request": request,
        "listing": listing,
        "photos": photos,
        "reviews": reviews,
        "reviews_by_reviewer": reviews_by_reviewer,
        "duplicate_original": duplicate_original,
        "title": f"{listing.title} — Immo-Boussole",
    })


@app.get("/profile/ideal")
def ideal_profile_page(request: Request, db: Session = Depends(get_db)):
    profile = generate_ideal_profile(db)
    return templates.TemplateResponse("ideal_profile.html", {
        "request": request,
        "profile": profile,
        "title": "Fiche de Bien Idéal — Immo-Boussole",
    })


# ─── API: Listings ────────────────────────────────────────────────────────────

@app.get("/api/listings")
def get_listings(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
):
    """Get all listings with optional filters."""
    query = db.query(Listing)
    if status:
        query = query.filter(Listing.status == status)
    if source:
        query = query.filter(Listing.source == source)
    listings = query.order_by(Listing.date_added.desc()).limit(limit).all()

    return [
        {
            "id": l.id,
            "title": l.title,
            "url": l.url,
            "price": l.price,
            "price_per_sqm": l.price_per_sqm,
            "location": l.location,
            "city": l.city,
            "area": l.area,
            "rooms": l.rooms,
            "dpe_rating": l.dpe_rating,
            "ges_rating": l.ges_rating,
            "land_tax": l.land_tax,
            "charges": l.charges,
            "source": l.source,
            "status": l.status,
            "is_duplicate": l.is_duplicate,
            "photos": json_to_photos(l.photos_local),
            "date_added": l.date_added.isoformat() if l.date_added else None,
            "scraped_at": l.scraped_at.isoformat() if l.scraped_at else None,
        }
        for l in listings
    ]


@app.get("/api/listings/{listing_id}")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    """Get a single listing by ID."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable")
    return listing


@app.post("/api/listings/{listing_id}/rescrape")
async def rescrape_listing(listing_id: int, db: Session = Depends(get_db)):
    """Manually trigger or re-trigger scraping for a specific listing."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable")

    url = listing.url
    # ── Determine source ──
    from app.scrapers import (
        LeboncoinScraper, SelogerScraper, LeFigaroScraper,
        LogicimmoScraper, BieniciScraper, IadfranceScraper,
        NotairesScraper, VinciScraper, ImmobilierFranceScraper
    )
    
    scraper = None
    if "leboncoin.fr" in url: source, scraper = Source.LEBONCOIN, LeboncoinScraper()
    elif "seloger.com" in url: source, scraper = Source.SELOGER, SelogerScraper()
    elif "lefigaro.fr" in url: source, scraper = Source.LEFIGARO, LeFigaroScraper()
    elif "logic-immo.com" in url: source, scraper = Source.LOGICIMMO, LogicimmoScraper()
    elif "bienici.com" in url: source, scraper = Source.BIENICI, BieniciScraper()
    elif "iadfrance.fr" in url: source, scraper = Source.IADFRANCE, IadfranceScraper()
    elif "immobilier.notaires.fr" in url: source, scraper = Source.NOTAIRES, NotairesScraper()
    elif "vinci-immobilier.com" in url: source, scraper = Source.VINCI, VinciScraper()
    elif "immobilier-france.fr" in url: source, scraper = Source.IMMOBILIER_FRANCE, ImmobilierFranceScraper()
    else: source, scraper = Source.MANUAL, None

    # ── Scrape ──
    details = {}
    if scraper:
        try:
            details = await scraper.get_listing_details(url)
        except Exception as e:
            print(f"[API] Re-scrape error for {url}: {e}")
    
    if not details or not details.get("title"):
        details = await fetch_basic_metadata(url)

    # ── Update via service ──
    updated_listing, _ = await create_listing_from_details(db, details, source, url)
    
    return {
        "status": "updated",
        "listing_id": updated_listing.id,
        "title": updated_listing.title
    }


@app.post("/api/listings/submit-url")
async def submit_listing_url(
    body: SubmitUrlRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Submit a listing URL for scraping and import.
    Automatically detects source (LeBonCoin/SeLoger/Manual),
    scrapes full details, checks for duplicates, downloads photos.
    """
    url = body.url

    # Check if URL is already in DB
    existing = db.query(Listing).filter(Listing.url == url).first()
    if existing:
        return {
            "status": "already_exists",
            "message": "Cette annonce est déjà dans la base.",
            "listing_id": existing.id,
            "is_duplicate": existing.is_duplicate,
        }

    # Determine source and scraper
    from app.scrapers import (
        LeboncoinScraper, SelogerScraper, LeFigaroScraper,
        LogicimmoScraper, BieniciScraper, IadfranceScraper,
        NotairesScraper, VinciScraper, ImmobilierFranceScraper
    )

    if "leboncoin.fr" in url:
        source = Source.LEBONCOIN
        scraper = LeboncoinScraper()
    elif "seloger.com" in url:
        source = Source.SELOGER
        scraper = SelogerScraper()
    elif "lefigaro.fr" in url:
        source = Source.LEFIGARO
        scraper = LeFigaroScraper()
    elif "logic-immo.com" in url:
        source = Source.LOGICIMMO
        scraper = LogicimmoScraper()
    elif "bienici.com" in url:
        source = Source.BIENICI
        scraper = BieniciScraper()
    elif "iadfrance.fr" in url:
        source = Source.IADFRANCE
        scraper = IadfranceScraper()
    elif "immobilier.notaires.fr" in url:
        source = Source.NOTAIRES
        scraper = NotairesScraper()
    elif "vinci-immobilier.com" in url:
        source = Source.VINCI
        scraper = VinciScraper()
    elif "immobilier-france.fr" in url:
        source = Source.IMMOBILIER_FRANCE
        scraper = ImmobilierFranceScraper()
    else:
        source = Source.MANUAL
        scraper = None

    if body.skip_scraping:
        # ── Fast path: fetch only basic metadata ───────────────────────────
        details = await fetch_basic_metadata(url)
        # Create listing (includes duplicate check) without photo download
        listing, is_new = await create_listing_from_details(
            db, details, source, url, download_photos=False
        )
        print(f"[API] Listing #{listing.id} ajouté via 'sans scraping' (metadatas OK).")
        return {
            "status": "created" if is_new else "already_exists",
            "message": "Annonce ajoutée avec informations de base (sans plein scraping).",
            "listing_id": listing.id,
            "title": listing.title
        }

    # ── Full Scrape Path ──────────────────────────────────────────────────
    details = {}
    if scraper:
        try:
            details = await scraper.get_listing_details(url)
        except Exception as e:
            print(f"[API] Erreur scraping plein pour {url}: {e}")

    # ── Fallback: basic metadata if full scrape failed ───────────────────
    if not details or not details.get("title"):
        fb_details = await fetch_basic_metadata(url)
        details.update(fb_details)

    # Create listing (includes duplicate check + photo download)
    listing, is_new = await create_listing_from_details(db, details, source, url)

    response = {
        "status": "created" if is_new else "updated",
        "listing_id": listing.id,
        "title": listing.title,
        "price": listing.price,
        "area": listing.area,
        "dpe_rating": listing.dpe_rating,
        "is_duplicate": listing.is_duplicate,
    }

    if listing.is_duplicate and listing.duplicate_of_id:
        original = db.query(Listing).filter(Listing.id == listing.duplicate_of_id).first()
        response["duplicate_warning"] = {
            "message": "⚠️ Un bien similaire (même prix, surface et ville) existe déjà !",
            "original_listing_id": listing.duplicate_of_id,
            "original_title": original.title if original else None,
            "original_url": f"/listings/{listing.duplicate_of_id}",
        }

    return response


@app.delete("/api/listings/{listing_id}")
def delete_listing(listing_id: int, db: Session = Depends(get_db)):
    """Delete a listing and its reviews."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable")
    db.delete(listing)
    db.commit()
    return {"status": "deleted", "listing_id": listing_id}


# ─── API: Reviews ─────────────────────────────────────────────────────────────

@app.get("/api/listings/{listing_id}/reviews")
def get_reviews(listing_id: int, db: Session = Depends(get_db)):
    """Get all reviews for a listing."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable")
    reviews = db.query(Review).filter(Review.listing_id == listing_id).all()
    return reviews


@app.post("/api/listings/{listing_id}/reviews")
def create_or_update_review(
    listing_id: int,
    body: ReviewRequest,
    db: Session = Depends(get_db),
):
    """Create or update a review for a listing. One review per (listing, reviewer)."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable")

    review, is_new = get_or_create_review(
        db=db,
        listing_id=listing_id,
        reviewer=body.reviewer,
        pros=body.pros,
        cons=body.cons,
        rating=body.rating,
        visit_done=body.visit_done,
        notes=body.notes,
    )

    return {
        "status": "created" if is_new else "updated",
        "review_id": review.id,
        "reviewer": review.reviewer,
        "rating": review.rating,
    }


@app.put("/api/reviews/{review_id}")
def update_review(
    review_id: int,
    body: ReviewRequest,
    db: Session = Depends(get_db),
):
    """Update a specific review by ID."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Avis introuvable")

    if body.pros is not None:
        review.pros = body.pros
    if body.cons is not None:
        review.cons = body.cons
    if body.rating is not None:
        review.rating = body.rating
    if body.visit_done is not None:
        review.visit_done = body.visit_done
    if body.notes is not None:
        review.notes = body.notes

    db.commit()
    db.refresh(review)
    return {"status": "updated", "review_id": review.id}


@app.delete("/api/reviews/{review_id}")
def delete_review(review_id: int, db: Session = Depends(get_db)):
    """Delete a review."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Avis introuvable")
    db.delete(review)
    db.commit()
    return {"status": "deleted"}


# ─── API: Ideal Profile ───────────────────────────────────────────────────────

@app.get("/api/profile/ideal")
def get_ideal_profile(db: Session = Depends(get_db)):
    """Get the dynamically generated ideal property profile."""
    return generate_ideal_profile(db)


# ─── API: Search Queries ──────────────────────────────────────────────────────

@app.get("/api/queries")
def get_queries(db: Session = Depends(get_db)):
    """Get all search queries."""
    return db.query(SearchQuery).all()


@app.post("/api/queries")
def create_query(body: SearchQueryRequest, db: Session = Depends(get_db)):
    """Add a new search query to the scheduler."""
    try:
        source_enum = Source(body.source)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Source inconnue: {body.source}")

    query = SearchQuery(
        url=body.url,
        source=source_enum,
        name=body.name or body.url[:50],
        active=1,
    )
    db.add(query)
    db.commit()
    db.refresh(query)
    return {"status": "created", "query_id": query.id}


@app.post("/api/queries/{query_id}/run")
async def run_query_now(query_id: int, db: Session = Depends(get_db)):
    """Manually trigger scraping for a specific search query."""
    query = db.query(SearchQuery).filter(SearchQuery.id == query_id).first()
    if not query:
        raise HTTPException(status_code=404, detail="Recherche introuvable")

    try:
        await scrape_and_diff(query, db)
        return {"status": "completed", "query": query.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
