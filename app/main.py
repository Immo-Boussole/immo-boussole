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
import hashlib
import os


from fastapi import FastAPI, Request, Depends, HTTPException, BackgroundTasks, Form, Response, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models, database
from app.database import engine, get_db, run_migrations
from app.models import Listing, ListingStatus, Review, Source, SearchQuery, ReadySearch
from app.services import (
    scrape_and_diff,
    create_listing_from_details,
    get_or_create_review,
    fetch_basic_metadata,
    generate_ideal_profile,
)
from app.media import json_to_photos
from app.config import settings
from app.translations import get_text

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

# Add session middleware for authentication
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

# Mount static files (local media storage)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
templates.env.globals["t"] = get_text


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


class ListingUpdateRequest(BaseModel):
    title: Optional[str] = None
    price: Optional[float] = None
    area: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    location: Optional[str] = None
    description_text: Optional[str] = None
    dpe_rating: Optional[str] = None
    ges_rating: Optional[str] = None
    land_tax: Optional[float] = None
    charges: Optional[float] = None
    agency_fee: Optional[float] = None
    heating_type: Optional[str] = None
    condition: Optional[str] = None
    parking_count: Optional[int] = None


class PhotoImportRequest(BaseModel):
    urls: list[str]


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
        allowed = ["jean-dupont", "marie-martin"]
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


class ReadySearchRequest(BaseModel):
    platform: str
    custom_platform_name: Optional[str] = None
    criteria: Optional[str] = None
    url: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in ["admin", "user"]:
            raise ValueError("Role must be 'admin' or 'user'")
        return v


# ─── Auth Logic ───────────────────────────────────────────────────────────────

def is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated") is True

def get_current_user_role(request: Request) -> Optional[str]:
    return request.session.get("role")

def login_required(request: Request, db: Session = Depends(get_db)):
    if not is_authenticated(request):
        # Check if any user exists
        user_count = db.query(models.User).count()
        if user_count == 0:
            if request.url.path.startswith("/api/"):
                raise HTTPException(status_code=401, detail="Setup required")
            raise HTTPException(status_code=307, detail="Redirect to setup-admin")
            
        # For API calls, return 401. For pages, redirect to login.
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail=get_text(request, "api.unauthenticated"))
        raise HTTPException(status_code=307, detail="Redirect to login")

def admin_required(request: Request, _auth = Depends(login_required)):
    if get_current_user_role(request) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

def user_required(request: Request, _auth = Depends(login_required)):
    if get_current_user_role(request) != "user":
        raise HTTPException(status_code=403, detail="User access required (Admins cannot perform this action)")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Custom handler for HTTPExceptions.
    Handles 307 redirects for auth flow and provides a safe fallback for others
    to avoid crashing if app.default_exception_handler is missing.
    """
    if exc.status_code == 307:
        if exc.detail == "Redirect to login":
            return RedirectResponse(url="/login")
        elif exc.detail == "Redirect to setup-admin":
            return RedirectResponse(url="/setup-admin")
    
    # Use the default FastAPI exception handler for everything else (404, 401, etc.)
    # This avoids the AttributeError: 'FastAPI' object has no attribute 'default_exception_handler'
    return await default_http_exception_handler(request, exc)


@app.get("/setup-admin")
def setup_admin_page(request: Request, db: Session = Depends(get_db)):
    if db.query(models.User).count() > 0:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("setup_admin.html", {"request": request})


@app.post("/setup-admin")
def setup_admin(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    if db.query(models.User).count() > 0:
        return RedirectResponse(url="/login")
        
    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    
    user = models.User(username=username, password_hash=pwd_hash, salt=salt, role="admin")
    db.add(user)
    db.commit()
    
    # Auto-login after creation
    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["role"] = "admin"
    return RedirectResponse(url="/", status_code=303)


@app.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if db.query(models.User).count() == 0:
        return RedirectResponse(url="/setup-admin")
    if is_authenticated(request):
        return RedirectResponse(url="/")
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(
    request: Request, 
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if user:
        pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), user.salt, 100000)
        if pwd_hash == user.password_hash:
            request.session["authenticated"] = True
            request.session["username"] = username
            request.session["role"] = user.role
            return RedirectResponse(url="/", status_code=303)
            
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": get_text(request, "api.invalid_credentials")
    })


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")


# ─── System: Health & Maintenance ─────────────────────────────────────────────

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Public health check endpoint for Docker/Orchestrators.
    Verifies database connectivity.
    """
    try:
        # Simple query to verify DB is alive and reachable
        db.execute(text("SELECT 1"))
        return {
            "status": "ok", 
            "timestamp": datetime.now().isoformat(),
            "version": "1.1.0"
        }
    except Exception as e:
        # If DB is down, return 500 so container becomes "unhealthy"
        raise HTTPException(status_code=500, detail=f"Database unreachable: {str(e)}")


# ─── Administration: User Management ──────────────────────────────────────────

@app.get("/admin/users")
def admin_users_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(admin_required)
):
    users = db.query(models.User).all()
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "users": users,
        "title": "Gestion des Utilisateurs — Immo-Boussole",
    })


@app.post("/api/admin/users")
def create_user(
    body: UserCreateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    # Check if username exists
    existing = db.query(models.User).filter(models.User.username == body.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', body.password.encode('utf-8'), salt, 100000)
    
    user = models.User(
        username=body.username, 
        password_hash=pwd_hash, 
        salt=salt, 
        role=body.role
    )
    db.add(user)
    db.commit()
    return {"status": "created", "username": user.username}


@app.delete("/api/admin/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    # Don't allow deleting yourself
    current_username = request.session.get("username")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.username == current_username:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    db.delete(user)
    db.commit()
    return {"status": "deleted"}


def get_local_commit_hash() -> str:
    """Attempt to safely read the local git commit hash."""
    try:
        git_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".git")
        head_file = os.path.join(git_dir, "HEAD")
        if os.path.exists(head_file):
            with open(head_file, "r") as f:
                head_content = f.read().strip()
                if head_content.startswith("ref: "):
                    ref_path = os.path.join(git_dir, head_content.split(" ")[1])
                    if os.path.exists(ref_path):
                        with open(ref_path, "r") as ref_f:
                            return ref_f.read().strip()
                else:
                    return head_content
    except Exception:
        pass
    return ""


# ─── HTML Pages ───────────────────────────────────────────────────────────────

@app.get("/lang/{lang}")
def set_language(request: Request, lang: str):
    if lang in ["fr", "en"]:
        request.session["lang"] = lang
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)


@app.get("/")
def read_root(request: Request, db: Session = Depends(get_db), _auth = Depends(login_required)):
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    queries = db.query(SearchQuery).all()

    # Attach local photos to each listing
    for listing in listings:
        listing._photos = json_to_photos(listing.photos_local)

    local_hash = get_local_commit_hash()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "listings": listings,
        "queries": queries,
        "local_hash": local_hash,
        "title": "Tableau de Bord — Immo-Boussole",
    })


@app.get("/listings/table")
def listings_table_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
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
    _auth = Depends(login_required)
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

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
def ideal_profile_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    profile = generate_ideal_profile(db)
    return templates.TemplateResponse("ideal_profile.html", {
        "request": request,
        "profile": profile,
        "title": "Fiche de Bien Idéal — Immo-Boussole",
    })


@app.get("/searches/ready")
def ready_searches_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    ready_searches = db.query(ReadySearch).all()
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).all()
    
    return templates.TemplateResponse("ready_searches.html", {
        "request": request,
        "ready_searches": ready_searches,
        "queries": queries,
        "listings": listings,
        "title": "Prêt à Rechercher — Immo-Boussole",
    })


# ─── API: Listings ────────────────────────────────────────────────────────────

@app.get("/api/listings")
def get_listings(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
    _auth = Depends(login_required)
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
def get_listing(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Get a single listing by ID."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    return listing


@app.post("/api/listings/{listing_id}/rescrape")
async def rescrape_listing(
    request: Request,
    listing_id: int, 
    db: Session = Depends(get_db), 
    _auth = Depends(user_required)
):
    """Manually trigger or re-trigger scraping for a specific listing."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

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
    scraping_success = True
    if scraper:
        try:
            details = await scraper.get_listing_details(url)
        except Exception as e:
            print(f"[API] Re-scrape error for {url}: {e}")
            scraping_success = False
    
    if not details or not details.get("title"):
        details = await fetch_basic_metadata(url)
        scraping_success = False

    # ── Update via service ──
    updated_listing, _ = await create_listing_from_details(db, details, source, url)
    
    return {
        "status": "updated",
        "listing_id": updated_listing.id,
        "title": updated_listing.title,
        "scraping_success": scraping_success
    }


@app.post("/api/listings/submit-url")
async def submit_listing_url(
    request: Request,
    body: SubmitUrlRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
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
            "message": get_text(request, "api.already_exists"),
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
            "message": get_text(request, "api.added_without_scraping"),
            "listing_id": listing.id,
            "title": listing.title
        }

    # ── Full Scrape Path ──────────────────────────────────────────────────
    details = {}
    scraping_success = True
    if scraper:
        try:
            details = await scraper.get_listing_details(url)
        except Exception as e:
            print(f"[API] Erreur scraping plein pour {url}: {e}")
            scraping_success = False

    # ── Fallback: basic metadata if full scrape failed ───────────────────
    if not details or not details.get("title"):
        fb_details = await fetch_basic_metadata(url)
        details.update(fb_details)
        scraping_success = False

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
        "scraping_success": scraping_success,
    }

    if listing.is_duplicate and listing.duplicate_of_id:
        original = db.query(Listing).filter(Listing.id == listing.duplicate_of_id).first()
        response["duplicate_warning"] = {
            "message": get_text(request, "api.duplicate_warning"),
            "original_listing_id": listing.duplicate_of_id,
            "original_title": original.title if original else None,
            "original_url": f"/listings/{listing.duplicate_of_id}",
        }

    return response


@app.delete("/api/listings/{listing_id}")
def delete_listing(
    request: Request,
    listing_id: int, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    """Delete a listing and its reviews."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    db.delete(listing)
    db.commit()
    return {"status": "deleted", "listing_id": listing_id}


@app.put("/api/listings/{listing_id}")
def update_listing(
    request: Request,
    listing_id: int,
    body: ListingUpdateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Update listing attributes."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(listing, key, value)
        
    db.commit()
    db.refresh(listing)
    return {"status": "updated", "listing_id": listing.id}


@app.post("/api/listings/{listing_id}/photos")
async def import_listing_photos(
    request: Request,
    listing_id: int,
    body: PhotoImportRequest,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Import and download photos for an existing listing from a list of URLs."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

    urls_to_download = [u.strip() for u in body.urls if u.strip().startswith("http")]
    if not urls_to_download:
        return {"status": "no_urls", "imported": 0}

    from app.media import download_listing_photos, json_to_photos, photos_to_json
    local_paths = await download_listing_photos(listing.id, urls_to_download)
    
    if local_paths:
        existing_photos = json_to_photos(listing.photos_local)
        # Avoid exact duplicates in the local paths list
        for path in local_paths:
            if path not in existing_photos:
                existing_photos.append(path)
        listing.photos_local = photos_to_json(existing_photos)
        db.commit()

    return {"status": "success", "imported": len(local_paths)}


@app.post("/api/listings/{listing_id}/photos/upload")
async def upload_listing_photos(
    request: Request,
    listing_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Upload photos directly for a listing via multipart form data."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

    if not files:
        return {"status": "no_files", "imported": 0}

    from app.media import save_uploaded_photos, json_to_photos, photos_to_json
    local_paths = await save_uploaded_photos(listing.id, files)

    if local_paths:
        existing_photos = json_to_photos(listing.photos_local)
        for path in local_paths:
            if path not in existing_photos:
                existing_photos.append(path)
        listing.photos_local = photos_to_json(existing_photos)
        db.commit()

    return {"status": "success", "imported": len(local_paths)}


# ─── API: Reviews ─────────────────────────────────────────────────────────────

@app.get("/api/listings/{listing_id}/reviews")
def get_reviews(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Get all reviews for a listing."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    reviews = db.query(Review).filter(Review.listing_id == listing_id).all()
    return reviews


@app.post("/api/listings/{listing_id}/reviews")
def create_or_update_review(
    request: Request,
    listing_id: int,
    body: ReviewRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Create or update a review for a listing. One review per (listing, reviewer)."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

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
    request: Request,
    review_id: int,
    body: ReviewRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Update a specific review by ID."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail=get_text(request, "api.review_not_found"))

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
def delete_review(request: Request, review_id: int, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Delete a review."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail=get_text(request, "api.review_not_found"))
    db.delete(review)
    db.commit()
    return {"status": "deleted"}


# ─── API: Ideal Profile ───────────────────────────────────────────────────────

@app.get("/api/profile/ideal")
def get_ideal_profile(db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Get the dynamically generated ideal property profile."""
    return generate_ideal_profile(db)


# ─── API: Search Queries ──────────────────────────────────────────────────────

@app.get("/api/queries")
def get_queries(db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Get all search queries."""
    return db.query(SearchQuery).all()


@app.post("/api/queries")
def create_query(request: Request, body: SearchQueryRequest, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Add a new search query to the scheduler."""
    try:
        source_enum = Source(body.source)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{get_text(request, 'api.unknown_source')} {body.source}")

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
async def run_query_now(request: Request, query_id: int, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Manually trigger scraping for a specific search query."""
    query = db.query(SearchQuery).filter(SearchQuery.id == query_id).first()
    if not query:
        raise HTTPException(status_code=404, detail=get_text(request, "api.search_not_found"))

    try:
        await scrape_and_diff(query, db)
        return {"status": "completed", "query": query.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── API: Ready Searches ──────────────────────────────────────────────────────

@app.post("/api/searches/ready")
def create_ready_search(body: ReadySearchRequest, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Add a new ready search."""
    platform_name = body.platform
    if body.platform == "manuel" and body.custom_platform_name:
        platform_name = f"{body.custom_platform_name} (ajout manuel)"
    
    # We no longer strictly enforce Source enum for platform since it can be custom
    search = ReadySearch(
        platform=platform_name,
        criteria=body.criteria,
        url=body.url,
    )
    db.add(search)
    db.commit()
    db.refresh(search)
    return search


@app.put("/api/searches/ready/{search_id}")
def update_ready_search(request: Request, search_id: int, body: ReadySearchRequest, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Update an existing ready search."""
    search = db.query(ReadySearch).filter(ReadySearch.id == search_id).first()
    if not search:
        raise HTTPException(status_code=404, detail=get_text(request, "api.search_not_found"))

    platform_name = body.platform
    if body.platform == "manuel" and body.custom_platform_name:
        platform_name = f"{body.custom_platform_name} (ajout manuel)"

    search.platform = platform_name
    search.criteria = body.criteria
    search.url = body.url

    db.commit()
    db.refresh(search)
    return search


@app.delete("/api/searches/ready/{search_id}")
def delete_ready_search(request: Request, search_id: int, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Remove a ready search."""
    search = db.query(ReadySearch).filter(ReadySearch.id == search_id).first()
    if not search:
        raise HTTPException(status_code=404, detail=get_text(request, "api.search_not_found"))
    
    db.delete(search)
    db.commit()
    return {"status": "deleted", "id": search_id}
