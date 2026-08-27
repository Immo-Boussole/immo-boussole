"""
FastAPI application main entry point.
Defines all routes: HTML pages + REST API.
"""
import json
import os
import re
import urllib.parse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import hashlib
import zipfile
import shutil
import tempfile
from fastapi.responses import StreamingResponse, FileResponse
import io


from fastapi import FastAPI, Request, Depends, HTTPException, BackgroundTasks, Form, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, field_validator
import time
from collections import defaultdict
import secrets
from sqlalchemy import text, func, or_
from sqlalchemy.orm import Session

from app import models, database, schemas, google_service
from app.database import engine, get_db, run_migrations
from app.models import Listing, ListingStatus, Review, Source, SearchQuery, ReadySearch, MapPin, UserListingView, ZoneRule, RejectedDuplicate, AIProfile, Visit, VisitContact, Agent, Agency, ListingAttachment, ListingLink

from app.services import (
    scrape_and_diff,
    create_listing_from_details,
    get_or_create_review,
    fetch_basic_metadata,
    generate_ideal_profile,
    find_potential_duplicates,
)
from app.geo import (
    fetch_sncf_times_for_city,
    find_nearby_stations,
    calculate_station_times,
    get_coordinates,
    get_postal_code,
    search_places_unified,
    calculate_multi_route,
    fetch_pois_around,
    POI_CATEGORIES
)
from app.media import json_to_photos, photos_to_json
from app.config import settings
from app.translations import get_text
from app.assistant import run_assistant_step
from app import db_maintenance

# Run migrations FIRST (adds missing columns to existing tables)
run_migrations()
# Then create any brand-new tables (e.g. reviews)
models.Base.metadata.create_all(bind=engine)

# Create static media directory and ensure app assets exist
os.makedirs("static/media", exist_ok=True)
os.makedirs("static/media/app", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Seed app icons into static/media/app if missing (handles Docker volume mount overlays)
if os.path.exists("static/app_icons") and not os.path.exists("static/media/app/icon-192.png"):
    import shutil
    try:
        shutil.copytree("static/app_icons", "static/media/app", dirs_exist_ok=True)
    except Exception as e:
        logger.warning(f"Could not seed static/media/app: {e}")


# Global scheduler instance
app_scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_scheduler
    # Startup: start background scheduler
    from app.scheduler import start_scheduler
    app_scheduler = start_scheduler()
    yield
    # Shutdown
    if app_scheduler and app_scheduler.running:
        app_scheduler.shutdown()


from starlette.middleware.gzip import GZipMiddleware

app = FastAPI(title="Immo-Boussole", lifespan=lifespan)

class SecureHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.endswith("/source-preview-html"):
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        else:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # High-performance Cache-Control for static files & local media photos
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=86400, stale-while-revalidate=604800"
            
        return response

app.add_middleware(SecureHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Allow Cross-Origin Requests from browser extensions and bookmarklets
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add session middleware for authentication
app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.SECRET_KEY, 
    https_only=settings.HTTPS_ONLY, 
    same_site="lax"
)

# Mount static files (local media storage)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")

@app.get("/manifest.json", include_in_schema=False)
async def manifest():
    return FileResponse("static/manifest.json")

@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")

templates = Jinja2Templates(directory="templates")
templates.env.globals["t"] = get_text

# Build a concise display version from APP_VERSION (which may be a full Docker tag)
_raw_version = settings.APP_VERSION
if ":" in _raw_version:
    # Docker image tag like "wikijm/immo-boussole:267266ff1192..."  →  "267266ff"
    _raw_version = _raw_version.split(":")[-1][:8]
templates.env.globals["app_version"] = _raw_version

def get_unread_count_global(request: Request) -> int:
    try:
        db = next(database.get_db())
        current_user = None
        if request and hasattr(request, "session") and request.session.get("authenticated") is True:
            username = request.session.get("username")
            if username:
                current_user = db.query(models.User).filter(models.User.username == username).first()
        from app.notifications import get_unread_notifications_count
        return get_unread_notifications_count(db, current_user)
    except Exception:
        return 0

templates.env.globals["get_unread_count"] = get_unread_count_global

from app.api.v1.router import api_router
from app.api.v1.endpoints import notifications as notifications_endpoint
app.include_router(api_router, prefix="/api/v1")
app.include_router(api_router, prefix="/api")
app.include_router(notifications_endpoint.router)


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
    city: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    address_precision: Optional[str] = None
    manual_address_override: Optional[bool] = None
    cadastral_parcel: Optional[str] = None
    description_text: Optional[str] = None
    dpe_rating: Optional[str] = None
    ges_rating: Optional[str] = None
    land_tax: Optional[float] = None
    charges: Optional[float] = None
    agency_fee: Optional[float] = None
    heating_type: Optional[str] = None
    heating_mode: Optional[str] = None
    building_year: Optional[int] = None
    condition: Optional[str] = None
    parking_count: Optional[int] = None


class PhotoImportRequest(BaseModel):
    urls: list[str]


class PhotoBatchDeleteRequest(BaseModel):
    indices: list[int]


class ReviewRequest(BaseModel):
    pros: Optional[str] = None
    cons: Optional[str] = None
    rating: Optional[float] = None
    visit_done: bool = False
    notes: Optional[str] = None

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


class KeywordCreateRequest(BaseModel):
    text: str
    keyword_type: str  # "pros" or "cons"
    
    @field_validator("keyword_type")
    @classmethod
    def validate_type(cls, v):
        if v not in ["pros", "cons"]:
            raise ValueError("Type must be 'pros' or 'cons'")
        return v


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    email: Optional[str] = None
    phone: Optional[str] = None
    sfr_identifier: Optional[str] = None
    sfr_password: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in ["admin", "user"]:
            raise ValueError("Role must be 'admin' or 'user'")
        return v


class UserPasswordUpdateRequest(BaseModel):
    password: str


class UserAdminUpdateRequest(BaseModel):
    role: str
    email: Optional[str] = None
    phone: Optional[str] = None
    sfr_identifier: Optional[str] = None
    sfr_password: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in ["admin", "user"]:
            raise ValueError("Role must be 'admin' or 'user'")
        return v


class ProfilePOI(BaseModel):
    name: str
    address: str
    lat: Optional[float] = None
    lon: Optional[float] = None


class ProfileUpdateRequest(BaseModel):
    work_address: Optional[str] = None
    pois: list[ProfilePOI] = []
    apprise_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    sfr_identifier: Optional[str] = None
    sfr_password: Optional[str] = None
    auto_read_after_days: Optional[int] = None


class StationChoice(BaseModel):
    name: str
    lat: float
    lon: float

class StationsUpdateRequest(BaseModel):
    station_1: StationChoice
    station_2: Optional[StationChoice] = None


class MapPinEntry(BaseModel):
    title: str
    address: str


class MapPinBulkRequest(BaseModel):
    pins: list[MapPinEntry]


class NearbyCityPin(BaseModel):
    nom_commune: str
    code_postal: str
    distance: float        # in km
    ref_commune: str       # Deduced reference city name (first result at distance ≈ 0)
    ref_cp: str            # Postal code of the reference city


class NearbyCityBulkRequest(BaseModel):
    cities: list[NearbyCityPin]
    include_stations: bool = False


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class TrainLineCreateRequest(BaseModel):
    departure_station: str
    arrival_station: str
    path: list[list[float]]
    color: str


class DuplicateDeclarationRequest(BaseModel):
    target_listing_id: Optional[int] = None
    original_url: Optional[str] = None


class GlobalSettingsRequest(BaseModel):
    resend_api_key: Optional[str] = None
    resend_sender_name: Optional[str] = None
    resend_sender_email: Optional[str] = None
    resend_subject: Optional[str] = None
    
    # DB Maintenance
    db_check_automate: Optional[bool] = None
    db_check_interval: Optional[str] = None
    db_repair_automate: Optional[bool] = None
    db_repair_interval: Optional[str] = None

    # Scraping Proxies (JSON)
    scraping_proxies_json: Optional[str] = None

    # Public Services Integrations (JSON)
    public_services_json: Optional[str] = None

    # Automated Nightly Maintenance & Storage Optimization
    auto_maintenance_enabled: Optional[bool] = None
    auto_maintenance_time: Optional[str] = None
    auto_maintenance_purge_rejected: Optional[bool] = None


class DuplicateMergeRequest(BaseModel):
    listing_a_id: int
    listing_b_id: int

class DuplicateRejectRequest(BaseModel):
    listing_a_id: int
    listing_b_id: int


class ZoneRuleRequest(BaseModel):
    zone_type: str   # "city" or "station"
    name: str
    rule: str = "forbidden"  # "forbidden" or "allowed"

    @field_validator("zone_type")
    @classmethod
    def validate_zone_type(cls, v):
        if v not in ["city", "station"]:
            raise ValueError("zone_type must be 'city' or 'station'")
        return v

    @field_validator("rule")
    @classmethod
    def validate_rule(cls, v):
        if v not in ["forbidden", "allowed"]:
            raise ValueError("rule must be 'forbidden' or 'allowed'")
        return v


class AIProfileCreate(BaseModel):
    name: str
    provider: str
    endpoint: str
    model_name: str
    api_key: Optional[str] = None


class AIProfileAssignAdmin(BaseModel):
    user_id: int
    name: str
    provider: str
    endpoint: str
    model_name: str
    api_key: Optional[str] = None


from pydantic import BaseModel, field_serializer

class AIProfileResponse(BaseModel):
    id: int
    user_id: int
    name: str
    provider: str
    endpoint: str
    model_name: str
    is_default: bool
    created_by_admin: bool
    api_key: Optional[str] = None

    class Config:
        from_attributes = True

    @field_serializer("api_key")
    def mask_api_key(self, api_key: Optional[str], _info):
        return "********" if api_key else None



# ─── Scraper Resolution Helper ────────────────────────────────────────────

def _resolve_scraper(url: str):
    """
    Determines the Source and Scraper instance for a given listing URL.
    Returns (Source, BaseScraper|None).
    """
    from app.scrapers import (
        LeboncoinScraper, SelogerScraper, LeFigaroScraper,
        LogicimmoScraper, BieniciScraper, IadfranceScraper,
        NotairesScraper, VinciScraper, ImmobilierFranceScraper,
        OrpiScraper, ProvimoScraper, HektorScraper
    )

    _SCRAPER_MAP = [
        ("leboncoin.fr",         Source.LEBONCOIN,         LeboncoinScraper),
        ("seloger.com",          Source.SELOGER,           SelogerScraper),
        ("lefigaro.fr",          Source.LEFIGARO,          LeFigaroScraper),
        ("logic-immo.com",       Source.LOGICIMMO,         LogicimmoScraper),
        ("bienici.com",          Source.BIENICI,           BieniciScraper),
        ("iadfrance.fr",         Source.IADFRANCE,         IadfranceScraper),
        ("immobilier.notaires.fr", Source.NOTAIRES,        NotairesScraper),
        ("vinci-immobilier.com", Source.VINCI,             VinciScraper),
        ("immobilier-france.fr", Source.IMMOBILIER_FRANCE, ImmobilierFranceScraper),
        ("orpi.com",             Source.ORPI,              OrpiScraper),
        ("provimo.fr",           Source.PROVIMO,           ProvimoScraper),
        ("immoreve.fr",          Source.HEKTOR,            HektorScraper),
        ("admin/crm",            Source.HEKTOR,            HektorScraper),
        ("hektor",               Source.HEKTOR,            HektorScraper),
        ("ma-boite-immo",        Source.HEKTOR,            HektorScraper),
    ]

    for domain, source, scraper_cls in _SCRAPER_MAP:
        if domain in url:
            return source, scraper_cls()
    return Source.MANUAL, None


# ─── Auth Logic ───────────────────────────────────────────────────────────────

failed_logins = defaultdict(list)

def check_rate_limit(request: Request) -> bool:
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    failed_logins[client_ip] = [t for t in failed_logins[client_ip] if now - t < 900]
    return len(failed_logins[client_ip]) < 5

def record_failed_login(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    failed_logins[client_ip].append(time.time())

def verify_csrf(request: Request, csrf_token: str = Form(...)):
    session_token = request.session.get("csrf_token")
    if not session_token or not secrets.compare_digest(session_token, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

def generate_csrf_token(request: Request) -> str:
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_hex(32)
    return request.session["csrf_token"]


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
    role = get_current_user_role(request)
    if role not in ["user", "admin"]:
        raise HTTPException(status_code=403, detail="Accès refusé")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Custom handler for HTTPExceptions.
    Handles 307 redirects for authentication flow and delegates others 
    to the default FastAPI exception handler.
    """
    if exc.status_code == 307:
        if exc.detail == "Redirect to login":
            req_path = request.url.path
            if request.url.query:
                req_path = f"{req_path}?{request.url.query}"
            import urllib.parse
            if req_path and req_path != "/" and not req_path.startswith("/login"):
                return RedirectResponse(url=f"/login?next={urllib.parse.quote(req_path, safe='')}")
            return RedirectResponse(url="/login")
        elif exc.detail == "Redirect to setup-admin":
            return RedirectResponse(url="/setup-admin")
    
    # Return 401 for API calls instead of redirecting if the exception came from login_required
    if exc.status_code == 401 and request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=401,
            content={"detail": exc.detail}
        )

    # Use the default FastAPI exception handler for everything else (404, 401 for pages, etc.)
    return await default_http_exception_handler(request, exc)


@app.get("/setup-admin")
def setup_admin_page(request: Request, db: Session = Depends(get_db)):
    if db.query(models.User).count() > 0:
        return RedirectResponse(url="/login")
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse(request=request, name="setup_admin.html", context={"csrf_token": csrf_token})


@app.post("/setup-admin", dependencies=[Depends(verify_csrf)])
def setup_admin(
    request: Request, 
    username: str = Form(...), 
    password: str = Form(...),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    sfr_identifier: Optional[str] = Form(None),
    sfr_password: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    if db.query(models.User).count() > 0:
        return RedirectResponse(url="/login")
        
    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 600000)
    
    user = models.User(
        username=username, 
        password_hash=pwd_hash, 
        salt=salt, 
        role="admin",
        email=email,
        phone=phone,
        sfr_identifier=sfr_identifier,
        sfr_password=sfr_password
    )
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
    next_url = request.query_params.get("next")
    if is_authenticated(request):
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return RedirectResponse(url=next_url)
        return RedirectResponse(url="/")
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse(
        request=request, 
        name="login.html", 
        context={"csrf_token": csrf_token, "next_url": next_url or ""}
    )


@app.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request, 
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    next_url = next or request.query_params.get("next")
    if not check_rate_limit(request):
        return templates.TemplateResponse(request=request, name="login.html", context={
            "error": "Trop de tentatives de connexion. Veuillez réessayer plus tard.",
            "csrf_token": generate_csrf_token(request),
            "next_url": next_url or ""
        }, status_code=429)

    user = db.query(models.User).filter(models.User.username == username).first()
    if user:
        pwd_hash_600k = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), user.salt, 600000)
        pwd_hash_100k = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), user.salt, 100000)
        
        if user.password_hash in (pwd_hash_600k, pwd_hash_100k):
            request.session["authenticated"] = True
            request.session["username"] = username
            request.session["role"] = user.role
            try:
                from datetime import datetime, timezone
                user.last_login_at = datetime.now(timezone.utc)
                db.commit()
            except Exception:
                pass
            target_url = "/"
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                target_url = next_url
            return RedirectResponse(url=target_url, status_code=303)
            
    record_failed_login(request)
    return templates.TemplateResponse(request=request, name="login.html", context={
        "error": get_text(request, "api.invalid_credentials"),
        "csrf_token": generate_csrf_token(request),
        "next_url": next_url or ""
    }, status_code=401)


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
            "version": settings.APP_VERSION
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
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    return templates.TemplateResponse(request=request, name="admin_users.html", context={
        "users": users,
        "queries": queries,
        "listings": listings,
        "title": f"{get_text(request, 'admin_users.title')} — {get_text(request, 'app.title')}",
    })


@app.get("/admin/maintenance")
def admin_maintenance_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(admin_required)
):
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    return templates.TemplateResponse(request=request, name="admin_maintenance.html", context={
        "queries": queries,
        "listings": listings,
        "title": f"{get_text(request, 'admin_maintenance.title')} — {get_text(request, 'app.title')}",
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
        role=body.role,
        email=body.email,
        phone=body.phone,
        sfr_identifier=body.sfr_identifier,
        sfr_password=body.sfr_password
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


@app.put("/api/admin/users/{user_id}/password")
def update_user_password(
    user_id: int,
    body: UserPasswordUpdateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', body.password.encode('utf-8'), salt, 100000)
    
    user.salt = salt
    user.password_hash = pwd_hash
    db.commit()
    
    return {"status": "updated", "username": user.username}


@app.put("/api/admin/users/{user_id}/profile")
def update_user_admin(
    user_id: int,
    body: UserAdminUpdateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.role = body.role
    if body.email is not None: user.email = body.email.strip() or None
    if body.phone is not None: user.phone = body.phone.strip() or None
    if body.sfr_identifier is not None: user.sfr_identifier = body.sfr_identifier.strip() or None
    if body.sfr_password is not None: user.sfr_password = body.sfr_password.strip() or None
    
    db.commit()
    return {"status": "updated", "username": user.username}


@app.get("/api/admin/settings")
def get_global_settings(
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    settings = db.query(models.GlobalSettings).first()
    if not settings:
        settings = models.GlobalSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@app.post("/api/admin/settings")
def update_global_settings(
    body: GlobalSettingsRequest,
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    settings = db.query(models.GlobalSettings).first()
    if not settings:
        settings = models.GlobalSettings()
        db.add(settings)
    
    if body.resend_api_key is not None: settings.resend_api_key = body.resend_api_key.strip() or None
    if body.resend_sender_name is not None: settings.resend_sender_name = body.resend_sender_name.strip() or "Immo-Boussole"
    if body.resend_sender_email is not None: settings.resend_sender_email = body.resend_sender_email.strip() or None
    if body.resend_subject is not None: settings.resend_subject = body.resend_subject.strip() or None
    
    if body.db_check_automate is not None: settings.db_check_automate = body.db_check_automate
    if body.db_check_interval is not None: settings.db_check_interval = body.db_check_interval
    if body.db_repair_automate is not None: settings.db_repair_automate = body.db_repair_automate
    if body.db_repair_interval is not None: settings.db_repair_interval = body.db_repair_interval
    
    if body.scraping_proxies_json is not None:
        settings.scraping_proxies_json = body.scraping_proxies_json.strip() or None
        try:
            from app.proxy_router import proxy_router
            proxy_router.reload_chains(settings.scraping_proxies_json)
        except Exception as e:
            print(f"[Main] Erreur reload_chains proxy_router: {e}")

    if body.public_services_json is not None:
        settings.public_services_json = body.public_services_json.strip() or "{}"

    if body.auto_maintenance_enabled is not None: settings.auto_maintenance_enabled = body.auto_maintenance_enabled
    if body.auto_maintenance_time is not None: settings.auto_maintenance_time = body.auto_maintenance_time.strip() or "03:30"
    if body.auto_maintenance_purge_rejected is not None: settings.auto_maintenance_purge_rejected = body.auto_maintenance_purge_rejected

    db.commit()

    # Sync scheduler jobs
    if app_scheduler:
        from app.scheduler import sync_db_maintenance_jobs
        sync_db_maintenance_jobs(app_scheduler)

    return {"status": "updated"}


@app.get("/api/admin/maintenance/storage-stats")
def get_admin_storage_and_db_stats(
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    """
    Returns live storage metrics for static/media, database file size, and maintenance history.
    """
    from app.media import get_storage_metrics
    from app.db_maintenance import get_db_stats

    storage = get_storage_metrics(db)
    database_stats = get_db_stats()
    settings = db.query(models.GlobalSettings).first()

    history = {}
    if settings and settings.last_maintenance_metrics_json:
        try:
            history = json.loads(settings.last_maintenance_metrics_json)
        except Exception:
            history = {}

    return {
        "storage": storage,
        "database": database_stats,
        "last_storage_cleanup": settings.last_storage_cleanup if settings else None,
        "last_db_optimization": settings.last_db_optimization if settings else None,
        "auto_maintenance_enabled": settings.auto_maintenance_enabled if settings and settings.auto_maintenance_enabled is not None else True,
        "auto_maintenance_time": settings.auto_maintenance_time if settings else "03:30",
        "auto_maintenance_purge_rejected": settings.auto_maintenance_purge_rejected if settings and settings.auto_maintenance_purge_rejected is not None else False,
        "history": history,
    }


class StorageCleanupRequest(BaseModel):
    purge_orphaned: bool = True
    purge_rejected: bool = False


@app.post("/api/admin/maintenance/storage-cleanup")
def run_admin_storage_cleanup(
    body: Optional[StorageCleanupRequest] = None,
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    """
    Purges orphaned listing media directories and/or local photos of rejected listings.
    """
    from app.media import purge_orphaned_and_rejected_media
    purge_orphaned = body.purge_orphaned if body is not None else True
    purge_rejected = body.purge_rejected if body is not None else False
    res = purge_orphaned_and_rejected_media(db, purge_orphaned=purge_orphaned, purge_rejected=purge_rejected)

    # Update GlobalSettings timestamp
    settings = db.query(models.GlobalSettings).first()
    if settings:
        now_iso = datetime.now(timezone.utc).isoformat()
        settings.last_storage_cleanup = now_iso
        try:
            metrics = json.loads(settings.last_maintenance_metrics_json or "{}")
        except Exception:
            metrics = {}
        metrics["last_storage_cleanup"] = now_iso
        metrics["storage_cleanup_result"] = res
        settings.last_maintenance_metrics_json = json.dumps(metrics)
        db.commit()

    return res


@app.post("/api/admin/maintenance/db-optimize")
def run_admin_db_optimize(
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    """
    Executes SQLite VACUUM, ANALYZE, PRAGMA optimize, and WAL Checkpoint.
    """
    from app.db_maintenance import optimize_sqlite_database
    res = optimize_sqlite_database()

    # Update GlobalSettings timestamp
    settings = db.query(models.GlobalSettings).first()
    if settings:
        now_iso = datetime.now(timezone.utc).isoformat()
        settings.last_db_optimization = now_iso
        try:
            metrics = json.loads(settings.last_maintenance_metrics_json or "{}")
        except Exception:
            metrics = {}
        metrics["last_db_optimization"] = now_iso
        metrics["db_optimize_result"] = res
        settings.last_maintenance_metrics_json = json.dumps(metrics)
        db.commit()

    return res


@app.post("/api/admin/settings/test-email")
async def test_email_configuration(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    from app.email_service import send_email
    
    current_username = request.session.get("username")
    current_user = db.query(models.User).filter(models.User.username == current_username).first()
    
    if not current_user or not current_user.email:
        raise HTTPException(status_code=400, detail="Votre profil n'a pas d'adresse e-mail configurée pour recevoir le test.")
    
    html = f"<p>Ceci est un test de configuration Resend pour <strong>Immo-Boussole</strong>.</p><p>Si vous recevez cet email, tout est bien configuré !</p>"
    res = send_email(db, current_user.email, html, subject="Test Configuration Resend — Immo-Boussole")
    
    if res:
        return {"status": "success", "message": f"Email de test envoyé à {current_user.email}"}
    else:
        raise HTTPException(status_code=500, detail="Échec de l'envoi de l'email. Vérifiez vos paramètres et la console.")


# ─── Administration: Backup & Restore ──────────────────────────────────────────

@app.get("/api/admin/env-config")
def get_env_config(_auth = Depends(admin_required)):
    from app.config import settings
    # Read environment specifically since some might not be in settings
    import os
    return {
        "APP_DOMAIN": getattr(settings, "APP_DOMAIN", os.environ.get("APP_DOMAIN", "")),
        "APP_URL": getattr(settings, "APP_URL", os.environ.get("APP_URL", "")),
        "APP_ENV": getattr(settings, "APP_ENV", os.environ.get("APP_ENV", "")),
        "APP_VERSION": getattr(settings, "APP_VERSION", os.environ.get("APP_VERSION", "")),
        "COMPOSE_PROJECT_NAME": os.environ.get("COMPOSE_PROJECT_NAME", ""),
        "SCRAPING_INTERVAL_HOURS": getattr(settings, "SCRAPING_INTERVAL_HOURS", ""),
        "APPRISE_URL": getattr(settings, "APPRISE_URL", "")
    }


@app.get("/api/admin/backup")
def download_backup(
    request: Request,
    background_tasks: BackgroundTasks,
    include_env: bool = True,
    include_media: bool = True,
    include_users: bool = True,
    include_listings: bool = True,
    include_settings: bool = True,
    _auth = Depends(admin_required)
):
    """
    Generates a ZIP backup of the database, media, and configuration with granular control.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"immo_boussole_backup_{timestamp}.zip"
    
    tmp_path = os.path.join(tempfile.gettempdir(), filename)
    
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. Database
            # Try to get path from settings, fallback to BASE_DIR
            from app.config import settings
            if settings.DATABASE_URL.startswith("sqlite:///"):
                db_path = settings.DATABASE_URL.replace("sqlite:///", "")
                if not os.path.isabs(db_path):
                    # Remove leading './' if present
                    if db_path.startswith("./"):
                        db_path = db_path[2:]
                    db_path = os.path.join(BASE_DIR, db_path)
            else:
                db_path = os.path.join(BASE_DIR, "immo_boussole.db")

            if os.path.exists(db_path):
                import sqlite3
                tmp_db = os.path.join(tempfile.gettempdir(), f"tmp_db_{timestamp}.sqlite")
                shutil.copy2(db_path, tmp_db)
                
                try:
                    conn = sqlite3.connect(tmp_db)
                    conn.execute("PRAGMA foreign_keys = OFF")
                    if not include_users:
                        conn.execute("DELETE FROM users")
                        conn.execute("DELETE FROM user_listing_views")
                    if not include_listings:
                        conn.execute("DELETE FROM listings")
                        conn.execute("DELETE FROM reviews")
                        conn.execute("DELETE FROM rejected_duplicates")
                        conn.execute("DELETE FROM user_listing_views")
                    if not include_settings:
                        conn.execute("DELETE FROM global_settings")
                        conn.execute("DELETE FROM zone_rules")
                        conn.execute("DELETE FROM search_queries")
                        conn.execute("DELETE FROM ready_searches")
                        conn.execute("DELETE FROM review_keywords")
                        conn.execute("DELETE FROM map_pins")
                        conn.execute("DELETE FROM train_lines")
                    conn.commit()
                    conn.execute("VACUUM")
                    conn.close()
                    
                    zipf.write(tmp_db, arcname="immo_boussole.db")
                finally:
                    if os.path.exists(tmp_db):
                        os.remove(tmp_db)
            
            # 2. Media
            media_root = os.path.join(BASE_DIR, "static", "media")
            if include_media and os.path.exists(media_root):
                for root, dirs, files in os.walk(media_root):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Arcname must be relative so it unzips into static/media
                        arcname = os.path.relpath(file_path, BASE_DIR)
                        zipf.write(file_path, arcname=arcname)
            
            # 3. Environment (config)
            env_path = os.path.join(BASE_DIR, ".env")
            if include_env and os.path.exists(env_path):
                zipf.write(env_path, arcname=".env")

        # Do not use add_task in background parameter if it returns None, pass the callable instead
        background_tasks.add_task(os.remove, tmp_path)
        return FileResponse(
            path=tmp_path,
            filename=filename,
            media_type="application/zip"
        )
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")


@app.post("/api/admin/restore")
async def restore_backup(
    file: UploadFile = File(...),
    restore_env: bool = Form(True),
    restore_media: bool = Form(True),
    restore_users: bool = Form(True),
    restore_listings: bool = Form(True),
    restore_settings: bool = Form(True),
    _auth = Depends(admin_required)
):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .zip file.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_zip_path = tmp.name

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(tmp_zip_path, 'r') as zipf:
                # Prevent Zip Slip / Path Traversal attacks during extraction
                abs_tmp_dir = os.path.abspath(tmp_dir)
                for member in zipf.infolist():
                    target_path = os.path.abspath(os.path.join(tmp_dir, member.filename))
                    if not target_path.startswith(abs_tmp_dir + os.sep) and target_path != abs_tmp_dir:
                        raise HTTPException(status_code=400, detail="Zip file contains unsafe file path (path traversal attempt).")
                zipf.extractall(tmp_dir)
            
            BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            # Resolve db path
            from app.config import settings
            if settings.DATABASE_URL.startswith("sqlite:///"):
                db_path = settings.DATABASE_URL.replace("sqlite:///", "")
                if not os.path.isabs(db_path):
                    if db_path.startswith("./"):
                        db_path = db_path[2:]
                    db_path = os.path.join(BASE_DIR, db_path)
            else:
                db_path = os.path.join(BASE_DIR, "immo_boussole.db")

            db_in_backup = os.path.join(tmp_dir, "immo_boussole.db")
            
            # 1. Database logic
            if os.path.exists(db_in_backup) and (restore_users or restore_listings or restore_settings):
                engine.dispose()
                import sqlite3
                conn = sqlite3.connect(db_path)
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.execute(f"ATTACH DATABASE '{db_in_backup}' AS backup_db")
                
                tables_to_restore = []
                if restore_users:
                    tables_to_restore.extend(["users"])
                if restore_listings:
                    tables_to_restore.extend(["listings", "reviews", "rejected_duplicates"])
                if restore_users or restore_listings:
                    # If we restore one or the other, we might as well sync views 
                    # (it will just delete them if missing in backup)
                    tables_to_restore.extend(["user_listing_views"])
                if restore_settings:
                    tables_to_restore.extend(["global_settings", "zone_rules", "search_queries", "ready_searches", "review_keywords", "map_pins", "train_lines"])

                for table in set(tables_to_restore):
                    try:
                        conn.execute(f"DELETE FROM main.{table}")
                        conn.execute(f"INSERT INTO main.{table} SELECT * FROM backup_db.{table}")
                    except Exception as e:
                        print(f"Error restoring table {table}: {e}")
                        pass
                
                conn.commit()
                conn.close()

            # 2. Media
            if restore_media:
                backup_media = os.path.join(tmp_dir, "static", "media")
                target_media = os.path.join(BASE_DIR, "static", "media")
                if os.path.exists(backup_media):
                    if os.path.exists(target_media):
                        shutil.rmtree(target_media)
                    shutil.copytree(backup_media, target_media)
            
            # 3. Env
            if restore_env:
                backup_env = os.path.join(tmp_dir, ".env")
                target_env = os.path.join(BASE_DIR, ".env")
                if os.path.exists(backup_env):
                    if not os.path.exists(target_env):
                        shutil.copy2(backup_env, target_env)
                    else:
                        # Granular restore: merge but protect critical environment keys
                        protected_keys = {
                            "APP_DOMAIN", "APP_URL", "APP_ENV", "APP_VERSION",
                            "COMPOSE_PROJECT_NAME", "DATABASE_URL", "BROWSERLESS_URL",
                            "BROWSERLESS_TOKEN", "APP_PASSWORD", "SECRET_KEY",
                            "DEBUG", "HTTPS_ONLY"
                        }
                        target_lines = []
                        target_keys = {}
                        with open(target_env, "r", encoding="utf-8") as f:
                            for idx, line in enumerate(f):
                                target_lines.append(line)
                                stripped = line.strip()
                                if stripped and not stripped.startswith("#") and "=" in stripped:
                                    k, _ = stripped.split("=", 1)
                                    target_keys[k.strip()] = idx
                        
                        with open(backup_env, "r", encoding="utf-8") as f:
                            for line in f:
                                stripped = line.strip()
                                if stripped and not stripped.startswith("#") and "=" in stripped:
                                    k, v = stripped.split("=", 1)
                                    k = k.strip()
                                    if k not in protected_keys:
                                        if k in target_keys:
                                            target_lines[target_keys[k]] = line
                                        else:
                                            target_lines.append(line)
                        
                        with open(target_env, "w", encoding="utf-8") as f:
                            f.writelines(target_lines)

        return {"status": "success", "message": "System restored successfully. Please restart the application for all changes to take effect."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")
    finally:
        if os.path.exists(tmp_zip_path):
            os.remove(tmp_zip_path)


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


def _get_viewed_listing_ids(request: Request, db: Session) -> set[int]:
    username = request.session.get("username")
    if not username:
        return set()
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        return set()
    views = db.query(UserListingView.listing_id).filter(UserListingView.user_id == user.id).all()
    return {v[0] for v in views}


def _enrich_listings(listings: list[Listing], viewed_ids: set[int]):
    for listing in listings:
        if not hasattr(listing, "_photos"):
            listing._photos = json_to_photos(listing.photos_local)
        
        # Dynamic status for the UI: Only override if it's currently NEW or ACTIVE
        if listing.status in [ListingStatus.NEW, ListingStatus.ACTIVE]:
            if listing.id in viewed_ids:
                listing.user_status = "active"
            else:
                listing.user_status = "nouvelle"
        else:
            listing.user_status = getattr(listing.status, 'value', listing.status)

        # Compute dynamic contact status
        has_contact = (listing.contact_made == True)
        if hasattr(listing, "visits") and listing.visits:
            if any(v.visit_type in ["contact_agence", "relance_agence"] for v in listing.visits):
                has_contact = True
        listing.has_contact_or_visit = has_contact


@app.get("/")
def read_root(request: Request, db: Session = Depends(get_db), _auth = Depends(login_required)):
    # Original mixed list for sidebar
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    
    # Split for Dashboard view
    imported_listings = db.query(Listing).filter(Listing.status == ListingStatus.ACTIVE).order_by(Listing.date_added.desc()).limit(100).all()
    rejected_listings = db.query(Listing).filter(Listing.status == ListingStatus.REJECTED).order_by(Listing.date_added.desc()).limit(100).all()
    
    queries = db.query(SearchQuery).all()
    viewed_ids = _get_viewed_listing_ids(request, db)

    _enrich_listings(all_listings + imported_listings + rejected_listings, viewed_ids)

    local_hash = get_local_commit_hash()

    return templates.TemplateResponse(request=request, name="index.html", context={
        "imported_listings": imported_listings,
        "rejected_listings": rejected_listings,
        "listings": all_listings,
        "queries": queries,
        "local_hash": local_hash,
        "app_version": settings.APP_VERSION,
        "title": "Tableau de Bord — Immo-Boussole",
    })


@app.get("/a-voir")
def a_voir_page(request: Request, db: Session = Depends(get_db), _auth = Depends(login_required)):
    # Original mixed list for sidebar
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    queries = db.query(SearchQuery).all()
    viewed_ids = _get_viewed_listing_ids(request, db)

    # The "A voir" view should show imported listings (e.g. status ACTIVE or NEW)
    # that the current user has not yet viewed.
    unseen_query = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.NEW, ListingStatus.ACTIVE])
    )
    if viewed_ids:
        unseen_query = unseen_query.filter(Listing.id.notin_(viewed_ids))
        
    unseen_listings = unseen_query.order_by(Listing.date_added.desc()).all()

    _enrich_listings(all_listings + unseen_listings, viewed_ids)
    local_hash = get_local_commit_hash()

    return templates.TemplateResponse(request=request, name="index.html", context={
        "imported_listings": [], 
        "rejected_listings": [], 
        "listings": all_listings, 
        "display_listings": unseen_listings,
        "queries": queries,
        "local_hash": local_hash,
        "app_version": settings.APP_VERSION,
        "title": "À voir — Immo-Boussole",
        "is_a_voir": True
    })


@app.get("/a-visiter")
def a_visiter_page(request: Request, db: Session = Depends(get_db), _auth = Depends(login_required)):
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    queries = db.query(SearchQuery).all()
    viewed_ids = _get_viewed_listing_ids(request, db)

    refused_ids = [r[0] for r in db.query(Visit.listing_id).filter(Visit.visit_type == "reponse_negative").all()]

    candidates = db.query(Listing).filter(
        Listing.status != ListingStatus.REJECTED
    ).all()
    
    _enrich_listings(candidates, viewed_ids)
    
    display_listings = []
    for l in candidates:
        if l.id in refused_ids:
            continue
        if l.contact_made or l.has_contact_or_visit:
            display_listings.append(l)

    display_listings.sort(key=lambda x: x.date_added or datetime.min, reverse=True)

    _enrich_listings(all_listings, viewed_ids)
    local_hash = get_local_commit_hash()

    return templates.TemplateResponse(request=request, name="index.html", context={
        "imported_listings": [], 
        "rejected_listings": [], 
        "listings": all_listings, 
        "display_listings": display_listings,
        "queries": queries,
        "local_hash": local_hash,
        "app_version": settings.APP_VERSION,
        "title": "À visiter — Immo-Boussole",
        "is_a_visiter": True
    })


@app.get("/visites")
def visites_page(request: Request, db: Session = Depends(get_db), _auth = Depends(login_required)):
    all_listings = db.query(Listing).filter(Listing.status != ListingStatus.REJECTED).order_by(Listing.date_added.desc()).all()
    queries = db.query(SearchQuery).all()
    users = db.query(models.User).order_by(models.User.username.asc()).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(all_listings, viewed_ids)

    # Targeted listings: to_visit == True or listings having visits, excluding those with any "reponse_negative"
    refused_ids = [r[0] for r in db.query(Visit.listing_id).filter(Visit.visit_type == "reponse_negative").all()]
    target_listings_query = db.query(Listing).filter(Listing.to_visit == True, Listing.status != ListingStatus.REJECTED)
    if refused_ids:
        target_listings_query = target_listings_query.filter(~Listing.id.in_(refused_ids))
    target_listings = target_listings_query.order_by(Listing.date_added.desc()).all()
    _enrich_listings(target_listings, viewed_ids)

    # All visits ordered by date
    visits = db.query(Visit).order_by(Visit.scheduled_at.asc()).all()

    visits_with_listings = []
    for v in visits:
        l = db.query(Listing).filter(Listing.id == v.listing_id).first()
        if l:
            if hasattr(l, 'photos_local') and l.photos_local:
                l._photos = json_to_photos(l.photos_local)
            visits_with_listings.append({
                "visit": v,
                "listing": l
            })

    all_agents = db.query(Agent).order_by(Agent.last_name.asc(), Agent.first_name.asc()).all()
    all_agencies = db.query(Agency).order_by(Agency.commercial_name.asc(), Agency.legal_name.asc()).all()
    local_hash = get_local_commit_hash()

    # Split counters: Rendez-vous (total visit activities) vs Biens visités (unique listings with non-cancelled visit steps)
    rdv_cnt = sum(1 for item in visits_with_listings if (item["visit"].step_family or "visite") == "visite")
    biens_visites_ids = {
        item["visit"].listing_id
        for item in visits_with_listings
        if (item["visit"].step_family or "visite") == "visite" and item["visit"].step != "visite_annulee"
    }
    biens_visites_cnt = len(biens_visites_ids)

    return templates.TemplateResponse(request=request, name="visites.html", context={
        "listings": all_listings,
        "target_listings": target_listings,
        "visits_with_listings": visits_with_listings,
        "rdv_cnt": rdv_cnt,
        "biens_visites_cnt": biens_visites_cnt,
        "queries": queries,
        "users": users,
        "all_agents": all_agents,
        "all_agencies": all_agencies,
        "local_hash": local_hash,
        "app_version": settings.APP_VERSION,
        "title": f"{get_text(request, 'visites.page_title')} — {get_text(request, 'app.title')}",
    })


@app.get("/contacts")
def contacts_page(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    queries = db.query(SearchQuery).all()
    users = db.query(models.User).all()
    local_hash = get_local_commit_hash()

    return templates.TemplateResponse(request=request, name="contacts.html", context={
        "listings": all_listings,
        "queries": queries,
        "users": users,
        "local_hash": local_hash,
        "app_version": settings.APP_VERSION,
        "title": f"{get_text(request, 'contacts.page_title')} — {get_text(request, 'app.title')}",
    })




@app.get("/tableau")
@app.get("/listings/table")
def listings_table_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    imported_listings = db.query(Listing).filter(Listing.status == ListingStatus.ACTIVE).order_by(Listing.date_added.desc()).all()
    rejected_listings = db.query(Listing).filter(Listing.status == ListingStatus.REJECTED).order_by(Listing.date_added.desc()).all()
    
    # For sidebar stats
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    queries = db.query(SearchQuery).all()
    viewed_ids = _get_viewed_listing_ids(request, db)

    _enrich_listings(imported_listings + rejected_listings + all_listings, viewed_ids)

    return templates.TemplateResponse(request=request, name="listings_table.html", context={
        "imported_listings": imported_listings,
        "rejected_listings": rejected_listings,
        "listings": all_listings,
        "queries": queries,
        "title": f"{get_text(request, 'table.title')} — {get_text(request, 'app.title')}",
    })


@app.get("/listings/repair")
def listings_repair_page(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """User-facing repair view — non-destructive repairs only."""
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)

    return templates.TemplateResponse(request=request, name="listings_repair.html", context={
        "queries": queries,
        "listings": listings,
        "title": f"{get_text(request, 'repairs.title')} — {get_text(request, 'app.title')}",
    })


@app.get("/listing/{listing_id}")
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
        
    # Lazy geocoding backfill
    if listing.city and listing.nearest_sncf_station is None:
        forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
            ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
        ).all()}
        sncf_data = fetch_sncf_times_for_city(listing.city, forbidden_stations)
        if sncf_data is not None:
            listing.nearest_sncf_station = sncf_data.get('nearest_sncf_station')
            listing.walk_time_sncf = sncf_data.get('walk_time_sncf')
            listing.bike_time_sncf = sncf_data.get('bike_time_sncf')
            listing.car_time_sncf = sncf_data.get('car_time_sncf')
            
            listing.second_sncf_station = sncf_data.get('second_sncf_station')
            listing.walk_time_sncf_2 = sncf_data.get('walk_time_sncf_2')
            listing.bike_time_sncf_2 = sncf_data.get('bike_time_sncf_2')
            listing.car_time_sncf_2 = sncf_data.get('car_time_sncf_2')
            db.commit()
            
    # Mark it as 'None' instead of NULL if we already tried so we don't try again
    if listing.city and listing.nearest_sncf_station is None:
        listing.nearest_sncf_station = "NOT_FOUND" 
        db.commit()

    main_photos = json_to_photos(listing.photos_local)
    attachments = db.query(ListingAttachment).filter(ListingAttachment.listing_id == listing_id).order_by(ListingAttachment.created_at.desc()).all()
    links = db.query(ListingLink).filter(ListingLink.listing_id == listing_id).order_by(ListingLink.created_at.asc()).all()
    reviews = db.query(Review).filter(Review.listing_id == listing_id).all()

    # Build a dict of reviews by reviewer for easy template access
    reviews_by_reviewer = {r.reviewer: r for r in reviews}

    # If there is a duplicate of another listing, load it
    duplicate_original = None
    if listing.duplicate_of_id:
        duplicate_original = db.query(Listing).filter(
            Listing.id == listing.duplicate_of_id
        ).first()
    
    # Load all duplicates of this listing (bidirectional visibility)
    if listing.duplicate_of_id:
        duplicate_children = db.query(Listing).filter(
            Listing.duplicate_of_id == listing.duplicate_of_id,
            Listing.id != listing.id
        ).all()
    else:
        duplicate_children = db.query(Listing).filter(
            Listing.duplicate_of_id == listing.id
        ).all()

    # Aggregate photos: main listing photos first, followed by photos from duplicate listings
    photos = [
        {
            "url": p,
            "is_duplicate": False,
            "listing_id": listing.id,
            "badge_text": None,
            "portal_name": listing.source.value if hasattr(listing.source, 'value') else str(listing.source) if listing.source else None,
        }
        for p in main_photos
    ]
    duplicate_photos_count = 0
    duplicate_listings = []
    if duplicate_original:
        duplicate_listings.append(duplicate_original)
    if duplicate_children:
        duplicate_listings.extend(duplicate_children)

    for dup in duplicate_listings:
        dup_photos = json_to_photos(dup.photos_local)
        for dp in dup_photos:
            photos.append({
                "url": dp,
                "is_duplicate": True,
                "listing_id": dup.id,
                "badge_text": f"Annonce {dup.id}",
                "portal_name": dup.source.value if hasattr(dup.source, 'value') else str(dup.source) if dup.source else None,
            })
            duplicate_photos_count += 1

    # Sidebars context
    queries = db.query(SearchQuery).all()
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)

    _enrich_listings([listing] + all_listings, viewed_ids)

    # Record user view
    username = request.session.get("username")
    if username:
        user = db.query(models.User).filter(models.User.username == username).first()
        if user:
            # Check if already viewed
            existing_view = db.query(UserListingView).filter(
                UserListingView.user_id == user.id,
                UserListingView.listing_id == listing_id
            ).first()
            if not existing_view:
                new_view = UserListingView(user_id=user.id, listing_id=listing_id)
                db.add(new_view)
                db.commit()

    # ─── Zone Rule Detection ──────────────────────────────────────────────────
    from app.geo import is_city_in_forbidden_set
    all_zone_rules = db.query(ZoneRule).all()
    city_rules = {r.name.strip().lower(): r.rule for r in all_zone_rules if r.zone_type == "city"}
    station_rules = {r.name.strip().lower(): r.rule for r in all_zone_rules if r.zone_type == "station"}
    forbidden_cities = {r.name.strip().lower() for r in all_zone_rules if r.zone_type == "city" and r.rule == "forbidden"}

    listing_city_lower = (listing.city or "").strip().lower()
    listing_location_lower = (listing.location or "").strip().lower()
    
    city_rule = city_rules.get(listing_city_lower)
    if not city_rule:
        for name, rule in city_rules.items():
            if name and name in listing_location_lower:
                city_rule = rule
                break
    if not city_rule and (
        (listing.city and is_city_in_forbidden_set(listing.city, forbidden_cities)) or
        (listing.location and is_city_in_forbidden_set(listing.location, forbidden_cities))
    ):
        city_rule = "forbidden"

    station1_rule = station_rules.get((listing.nearest_sncf_station or "").strip().lower())
    station2_rule = station_rules.get((listing.second_sncf_station or "").strip().lower())

    # Auto-reject listing if located in a forbidden zone (unless marked as to_visit)
    if (city_rule == "forbidden" or station1_rule == "forbidden" or station2_rule == "forbidden") and listing.status != ListingStatus.REJECTED and not listing.to_visit:
        listing.status = ListingStatus.REJECTED
        db.commit()
        db.refresh(listing)

    users = db.query(models.User).order_by(models.User.username.asc()).all()

    # Contact & Agency associations
    main_agent = db.query(Agent).filter(Agent.id == listing.main_agent_id).first() if listing.main_agent_id else None
    agency = db.query(Agency).filter(Agency.id == listing.agency_id).first() if listing.agency_id else (main_agent.agency if main_agent and main_agent.agency else None)

    # Regex detection for unassigned contact info in text
    from app.services import extract_contact_info_from_text
    detected_contact = extract_contact_info_from_text(f"{listing.title or ''}\n{listing.description_text or ''}")

    # All agents and agencies for dropdown selection
    all_agents = db.query(Agent).order_by(Agent.last_name.asc(), Agent.first_name.asc()).all()
    all_agencies = db.query(Agency).order_by(Agency.commercial_name.asc(), Agency.legal_name.asc()).all()

    global_settings = db.query(models.GlobalSettings).first()
    public_services = {}
    if global_settings and global_settings.public_services_json:
        try:
            public_services = json.loads(global_settings.public_services_json)
        except Exception:
            public_services = {}

    from app.services import is_search_page_title, is_valid_listing_url
    is_aggregate_search = is_search_page_title(listing.title) or (bool(listing.url) and not is_valid_listing_url(listing.url)[0])

    return templates.TemplateResponse(request=request, name="listing_detail.html", context={
        "listing": listing,
        "photos": photos,
        "main_photos_count": len(main_photos),
        "duplicate_photos_count": duplicate_photos_count,
        "attachments": attachments,
        "links": links,
        "reviews": reviews,
        "reviews_by_reviewer": reviews_by_reviewer,
        "duplicate_original": duplicate_original,
        "duplicate_children": duplicate_children,
        "queries": queries,
        "listings": all_listings,
        "users": users,
        "georisques": json.loads(listing.georisques_json) if listing.georisques_json else None,
        "title": f"{listing.title} — Immo-Boussole",
        "city_rule": city_rule,
        "station1_rule": station1_rule,
        "station2_rule": station2_rule,
        "main_agent": main_agent,
        "agency": agency,
        "detected_contact": detected_contact,
        "all_agents": all_agents,
        "all_agencies": all_agencies,
        "public_services": public_services,
        "is_aggregate_search": is_aggregate_search,
    })


@app.get("/profile/ideal")
def ideal_profile_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    profile = generate_ideal_profile(db)
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    # Extract standard users (role == "user")
    std_users = db.query(models.User).filter(models.User.role == "user").all()
    std_usernames = [u.username.lower() for u in std_users]
    
    coup_de_coeur_listings = []
    if std_usernames:
        # Fetch reviews from standard users with a rating >= 7.0
        reviews = db.query(models.Review).filter(
            models.Review.rating >= 7.0,
            models.Review.reviewer.in_(std_usernames)
        ).all()
        
        # Group reviews by listing ID
        from collections import defaultdict
        listing_votes = defaultdict(list)
        for r in reviews:
            listing_votes[r.listing_id].append(r.reviewer)
            
        if listing_votes:
            # Query all listings that received a vote
            voted_listings = db.query(models.Listing).filter(
                models.Listing.id.in_(list(listing_votes.keys()))
            ).all()
            _enrich_listings(voted_listings, viewed_ids)
            
            num_std_users = len(std_users)
            for l in voted_listings:
                votes = listing_votes[l.id]
                # is_general is true if 100% of standard users voted for this listing
                is_general = all(uname in votes for uname in std_usernames)
                coup_de_coeur_listings.append({
                    "listing": l,
                    "votes": votes,
                    "is_general": is_general
                })
                
    return templates.TemplateResponse(request=request, name="ideal_profile.html", context={
        "profile": profile,
        "queries": queries,
        "listings": listings,
        "std_users": std_users,
        "coup_de_coeur_listings": coup_de_coeur_listings,
        "title": f"{get_text(request, 'ideal_profile.title')} — {get_text(request, 'app.title')}",
    })


@app.get("/searches/ready")
def ready_searches_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    ready_searches = db.query(ReadySearch).all()
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    return templates.TemplateResponse(request=request, name="ready_searches.html", context={
        "ready_searches": ready_searches,
        "queries": queries,
        "listings": listings,
        "title": f"{get_text(request, 'ready_searches.title')} — {get_text(request, 'app.title')}",
    })


@app.get("/searches/auto")
def auto_searches_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    from app.services import normalize_listing_url, enrich_auto_search_duplicates

    # Fetch NEW listings that come from a ReadySearch (automatic results)
    new_listings_raw = db.query(Listing).filter(
        Listing.status == ListingStatus.NEW,
        Listing.is_duplicate == False,
        Listing.source_ready_search_id.isnot(None)
    ).order_by(Listing.date_added.desc()).all()

    # Build set of normalized URLs already in the DB with status != NEW
    existing_db_urls = set()
    for row in db.query(Listing.url, Listing.original_url).filter(Listing.status != ListingStatus.NEW).all():
        if row.url:
            norm_u = normalize_listing_url(row.url)
            if norm_u:
                existing_db_urls.add(norm_u)
        if row.original_url:
            norm_ou = normalize_listing_url(row.original_url)
            if norm_ou:
                existing_db_urls.add(norm_ou)

    # Filter out listings whose URL is already in DB or duplicated in this batch
    new_listings = []
    seen_new_urls = set()
    for l in new_listings_raw:
        norm_u = normalize_listing_url(l.url)
        norm_orig = normalize_listing_url(l.original_url) if l.original_url else ""

        if norm_u in existing_db_urls or (norm_orig and norm_orig in existing_db_urls):
            continue
        if norm_u in seen_new_urls or (norm_orig and norm_orig in seen_new_urls):
            continue

        if norm_u:
            seen_new_urls.add(norm_u)
        if norm_orig:
            seen_new_urls.add(norm_orig)

        new_listings.append(l)

    queries = db.query(SearchQuery).all()
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(new_listings + all_listings, viewed_ids)

    # Enrich new listings with potential duplicates (> 50%)
    enrich_auto_search_duplicates(new_listings, db)

    # Calculate counts for quick filter pills
    count_total = len(new_listings)
    count_duplicates = sum(1 for l in new_listings if getattr(l, "_duplicate", None) is not None)
    count_unique = count_total - count_duplicates

    # Build a lookup map of ReadySearch by ID for fast access
    ready_search_map = {rs.id: rs for rs in db.query(ReadySearch).all()}

    # Get the latest sync time from active queries
    latest_query = db.query(SearchQuery).filter(SearchQuery.active == 1).order_by(SearchQuery.last_run.desc()).first()
    last_sync = latest_query.last_run if latest_query else None

    # Platform branding & formatting metadata
    platform_meta = {
        "leboncoin": {"label": "LeBonCoin", "icon": "fa-solid fa-tag", "color": "#f56b2a"},
        "seloger": {"label": "SeLoger", "icon": "fa-solid fa-house-chimney", "color": "#e01a4f"},
        "lefigaro": {"label": "Le Figaro", "icon": "fa-solid fa-newspaper", "color": "#1a73e8"},
        "logicimmo": {"label": "Logic-Immo", "icon": "fa-solid fa-house-laptop", "color": "#8e24aa"},
        "bienici": {"label": "Bien'Ici", "icon": "fa-solid fa-map-pin", "color": "#fbc02d"},
        "iadfrance": {"label": "IAD France", "icon": "fa-solid fa-city", "color": "#00897b"},
        "notaires": {"label": "Notaires", "icon": "fa-solid fa-scale-balanced", "color": "#546e7a"},
        "vinci": {"label": "Vinci", "icon": "fa-solid fa-building", "color": "#0d47a1"},
        "orpi": {"label": "Orpi", "icon": "fa-solid fa-house-user", "color": "#d32f2f"},
        "provimo": {"label": "Provimo", "icon": "fa-solid fa-key", "color": "#388e3c"},
        "hektor": {"label": "Hektor", "icon": "fa-solid fa-handshake", "color": "#7b1fa2"},
    }

    # Fetch all ready searches
    all_ready_searches = db.query(ReadySearch).order_by(ReadySearch.platform.asc(), ReadySearch.criteria.asc()).all()

    for listing in new_listings:
        listing._photos = json_to_photos(listing.photos_local)

        # Resolve platform and criteria — first 2 columns in auto_searches view
        if listing.source_ready_search_id and listing.source_ready_search_id in ready_search_map:
            rs = ready_search_map[listing.source_ready_search_id]
            listing._platform = rs.platform.upper()
            listing._platform_key = rs.platform.lower()
            listing._criteria = rs.criteria or "-"
        else:
            # Fallback for listings created before this feature, or via other paths
            listing._platform = listing.source.value.upper() if listing.source else "-"
            listing._platform_key = listing.source.value.lower() if listing.source else "manuel"
            listing._criteria = listing.source_criteria or "-"

    # Collect all known platforms from ready searches + new listings
    known_platforms = set(rs.platform.lower() for rs in all_ready_searches if rs.platform)
    for l in new_listings:
        if getattr(l, "_platform_key", None):
            known_platforms.add(l._platform_key)

    sources_stats = []
    for p_key in sorted(known_platforms):
        meta = platform_meta.get(p_key, {
            "label": p_key.capitalize(),
            "icon": "fa-solid fa-globe",
            "color": "var(--accent)"
        })
        p_listings = [
            l for l in new_listings 
            if getattr(l, "_platform_key", "") == p_key
        ]
        p_count = len(p_listings)

        # Determine latest offer date
        last_offer = None
        dates_in_new = [l.date_added for l in p_listings if l.date_added]
        if dates_in_new:
            last_offer = max(dates_in_new)
        else:
            # Fallback to latest listing in DB for this source / platform
            p_rs_ids = [rs.id for rs in all_ready_searches if rs.platform.lower() == p_key]
            conds = [Listing.source == p_key]
            if p_rs_ids:
                conds.append(Listing.source_ready_search_id.in_(p_rs_ids))
            db_row = db.query(Listing.date_added).filter(or_(*conds)).order_by(Listing.date_added.desc()).first()
            if db_row and db_row[0]:
                last_offer = db_row[0]

        sources_stats.append({
            "key": p_key,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "count": p_count,
            "last_offer": last_offer,
            "has_new": p_count > 0,
        })

    # Sort sources: sources with new listings first, then by latest offer date descending
    sources_stats.sort(key=lambda x: (x["count"] > 0, x["count"], x["last_offer"] or datetime.min), reverse=True)

    # Prepare ready searches for selector dropdown
    ready_searches_stats = []
    for rs in all_ready_searches:
        rs_count = sum(1 for l in new_listings if l.source_ready_search_id == rs.id)
        ready_searches_stats.append({
            "id": rs.id,
            "platform": rs.platform.lower(),
            "platform_label": platform_meta.get(rs.platform.lower(), {}).get("label", rs.platform.capitalize()),
            "criteria": rs.criteria or get_text(request, "auto_searches.no_criteria", "Critères non spécifiés"),
            "url": rs.url,
            "count": rs_count
        })

    # Group listings by date_added.date()
    from itertools import groupby
    grouped = []
    for k, g in groupby(new_listings, key=lambda x: x.date_added.date() if x.date_added else None):
        grouped.append((k, list(g)))

    return templates.TemplateResponse(request=request, name="auto_searches.html", context={
        "grouped_listings": grouped,
        "count_total": count_total,
        "count_duplicates": count_duplicates,
        "count_unique": count_unique,
        "sources_stats": sources_stats,
        "ready_searches_stats": ready_searches_stats,
        "queries": queries,
        "listings": all_listings,
        "scraping_schedule": get_text(request, "auto_searches.auto_refresh_value"),
        "last_sync": last_sync,
        "title": f"{get_text(request, 'auto_searches.title')} — {get_text(request, 'app.title')}",
    })


@app.get("/profile")
def profile_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    # Parse POIs
    pois = []
    if user.poi_json:
        try:
            pois = json.loads(user.poi_json)
        except:
            pois = []

    return templates.TemplateResponse(request=request, name="profile.html", context={
        "user": user,
        "pois": pois,
        "queries": queries,
        "listings": listings,
        "title": f"{get_text(request, 'profile.title')} — {get_text(request, 'app.title')}",
    })



def _group_zones(items):
    """Groups similar names together (e.g. 'Paris' and 'Paris 15')."""
    if not items: return []
    # Sort by name and length
    sorted_items = sorted(items, key=lambda x: x[0].lower())
    groups = []
    for name, count in sorted_items:
        found = False
        name_lower = name.lower().strip()
        for g in groups:
            leader_lower = g['name'].lower().strip()
            # Simple prefix check: if one starts with the other and prefix >= 4 chars
            shorter = leader_lower if len(leader_lower) < len(name_lower) else name_lower
            longer = name_lower if len(leader_lower) < len(name_lower) else leader_lower
            if len(shorter) >= 4 and longer.startswith(shorter):
                if name not in g['variants']: g['variants'].append(name)
                g['count'] += count
                if len(name) < len(g['name']): g['name'] = name
                found = True
                break
        if not found:
            groups.append({"name": name, "count": count, "variants": [name]})
    return groups


@app.get("/zones")
def zones_page(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Zone management page — forbidden/allowed cities and SNCF stations."""
    zone_rules = db.query(ZoneRule).order_by(ZoneRule.created_at.desc()).all()
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)

    # Calculate zones to qualify
    city_counts_raw = db.query(Listing.city, func.count(Listing.id)).filter(Listing.city != None).group_by(Listing.city).all()
    
    # Combined stations logic
    station_counts_dict = {}
    nearest_stations = db.query(Listing.nearest_sncf_station, func.count(Listing.id)).filter(Listing.nearest_sncf_station != None).group_by(Listing.nearest_sncf_station).all()
    second_stations = db.query(Listing.second_sncf_station, func.count(Listing.id)).filter(Listing.second_sncf_station != None).group_by(Listing.second_sncf_station).all()
    
    for name, count in nearest_stations:
        station_counts_dict[name] = station_counts_dict.get(name, 0) + count
    for name, count in second_stations:
        station_counts_dict[name] = station_counts_dict.get(name, 0) + count

    existing_city_rules = {r.name.lower().strip() for r in zone_rules if r.zone_type == 'city'}
    existing_station_rules = {r.name.lower().strip() for r in zone_rules if r.zone_type == 'station'}

    to_qualify_cities_raw = [(c, cnt) for c, cnt in city_counts_raw if c.lower().strip() not in existing_city_rules]
    to_qualify_stations_raw = [(s, cnt) for s, cnt in station_counts_dict.items() if s.lower().strip() not in existing_station_rules]

    grouped_cities = _group_zones(to_qualify_cities_raw)
    for g in grouped_cities: g['type'] = 'city'
    
    grouped_stations = _group_zones(to_qualify_stations_raw)
    for g in grouped_stations: g['type'] = 'station'

    to_qualify = grouped_cities + grouped_stations
    # Sort by total count descending
    to_qualify.sort(key=lambda x: x["count"], reverse=True)

    return templates.TemplateResponse(request=request, name="zones.html", context={
        "zone_rules": zone_rules,
        "queries": queries,
        "listings": listings,
        "to_qualify": to_qualify,
        "title": f"{get_text(request, 'zones.page_title')} — {get_text(request, 'app.title')}",
    })


@app.get("/duplicates/hunt")
def duplicate_hunt_page(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """View potential duplicate listings for manual review."""
    potential_pairs = find_potential_duplicates(db)
    queries = db.query(SearchQuery).all()
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    
    viewed_ids = _get_viewed_listing_ids(request, db)
    
    # Collect all listings to enrich (sidebar + pairs)
    to_enrich = list(all_listings)
    for pair in potential_pairs:
        to_enrich.append(pair["l1"])
        to_enrich.append(pair["l2"])
    
    _enrich_listings(to_enrich, viewed_ids)

    return templates.TemplateResponse(request=request, name="duplicate_hunt.html", context={
        "potential_pairs": potential_pairs,
        "queries": queries,
        "listings": all_listings,
        "title": f"{get_text(request, 'duplicates.title')} — {get_text(request, 'app.title')}",
    })

# ─── API: Allowed Departments ─────────────────────────────────────────────────

@app.get("/api/departments")
def get_allowed_departments(db: Session = Depends(get_db), _auth = Depends(login_required)):
    settings = db.query(models.GlobalSettings).first()
    if not settings or not settings.allowed_departments:
        return []
    try:
        import json
        return json.loads(settings.allowed_departments)
    except:
        return []

class DepartmentsRequest(BaseModel):
    departments: list[str]

@app.post("/api/departments")
def update_allowed_departments(
    body: DepartmentsRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    settings = db.query(models.GlobalSettings).first()
    if not settings:
        settings = models.GlobalSettings()
        db.add(settings)
    import json
    settings.allowed_departments = json.dumps(body.departments)
    db.commit()
    return {"status": "success", "departments": body.departments}

def _is_city_in_allowed_departments(city: str, db: Session) -> bool:
    """
    Checks if a city belongs to one of the allowed departments.
    Returns True if allowed or if no restrictions are set.
    """
    if not city:
        return False
        
    import re
    match = re.search(r'\((\d{5})\)', city)
    if not match:
        return False
        
    zipcode = match.group(1)
    if zipcode.startswith('97') and len(zipcode) >= 3:
        dept = zipcode[:3]
    else:
        dept = zipcode[:2]

    settings = db.query(models.GlobalSettings).first()
    if not settings or not settings.allowed_departments:
        return True
        
    try:
        import json
        allowed = json.loads(settings.allowed_departments)
        if not allowed:
            return True
    except:
        return True
        
    return dept in allowed

# ─── API: Zone Rules ──────────────────────────────────────────────────────────

@app.get("/api/zones")
def get_zone_rules(
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Returns all zone rules (forbidden/allowed cities and stations)."""
    rules = db.query(ZoneRule).order_by(ZoneRule.zone_type, ZoneRule.name).all()
    return [
        {
            "id": r.id,
            "zone_type": r.zone_type,
            "name": r.name,
            "rule": r.rule,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rules
    ]


@app.post("/api/zones")
def create_zone_rule(
    request: Request,
    body: ZoneRuleRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Creates a new zone rule. All authenticated users can manage zones."""
    username = request.session.get("username", "unknown")

    # Normalize name to avoid duplicates with different casing
    normalized_name = body.name.strip()

    # Check for duplicate
    existing = db.query(ZoneRule).filter(
        ZoneRule.zone_type == body.zone_type,
        ZoneRule.name.ilike(normalized_name),
        ZoneRule.rule == body.rule,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Cette zone existe déjà : {normalized_name}")

    rule = ZoneRule(
        zone_type=body.zone_type,
        name=normalized_name,
        rule=body.rule,
        created_by=username,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    # If the new rule is 'forbidden', retroactively reject all matching active/new listings (excluding to_visit)
    if body.rule == "forbidden":
        from app.geo import is_city_in_forbidden_set
        active_listings = db.query(Listing).filter(
            Listing.status != ListingStatus.REJECTED,
            Listing.to_visit.isnot(True)
        ).all()
        rejected_count = 0
        if body.zone_type == "city":
            forbidden_set = {normalized_name.lower()}
            for l in active_listings:
                if (l.city and is_city_in_forbidden_set(l.city, forbidden_set)) or \
                   (l.location and is_city_in_forbidden_set(l.location, forbidden_set)):
                    l.status = ListingStatus.REJECTED
                    rejected_count += 1
        elif body.zone_type == "station":
            norm_station = normalized_name.lower()
            for l in active_listings:
                s1 = (l.nearest_sncf_station or "").strip().lower()
                s2 = (l.second_sncf_station or "").strip().lower()
                if norm_station in s1 or norm_station in s2 or s1 == norm_station or s2 == norm_station:
                    l.status = ListingStatus.REJECTED
                    rejected_count += 1
        if rejected_count > 0:
            db.commit()
            print(f"[ZoneRule] {rejected_count} listing(s) retroactively marked as REJECTED for forbidden zone: {normalized_name}")

    return {
        "id": rule.id,
        "zone_type": rule.zone_type,
        "name": rule.name,
        "rule": rule.rule,
        "created_by": rule.created_by,
    }


@app.delete("/api/zones/{zone_id}")
def delete_zone_rule(
    zone_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Deletes a zone rule. All authenticated users can delete zones."""
    rule = db.query(ZoneRule).filter(ZoneRule.id == zone_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    db.delete(rule)
    db.commit()
    return {"status": "deleted", "id": zone_id}


@app.post("/api/zones/purge-listings")
def purge_zone_listings(
    payload: dict,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Deletes all listings associated with a given city or station."""
    zone_type = payload.get("type")
    name = (payload.get("name") or "").strip()
    if not name or zone_type not in ("city", "station"):
        raise HTTPException(status_code=400, detail="Nom et type de zone valides requis")

    import os, shutil
    
    if zone_type == "city":
        target_listings = db.query(Listing).filter(Listing.city.ilike(name)).all()
    else:
        target_listings = db.query(Listing).filter(
            (Listing.nearest_sncf_station.ilike(name)) | (Listing.second_sncf_station.ilike(name))
        ).all()

    count = len(target_listings)
    for listing in target_listings:
        listing_id = listing.id
        db.query(Listing).filter(Listing.duplicate_of_id == listing_id).update(
            {"duplicate_of_id": None, "is_duplicate": False}
        )
        db.query(UserListingView).filter(UserListingView.listing_id == listing_id).delete()
        db.delete(listing)
        
        media_dir = os.path.join("static", "media", str(listing_id))
        if os.path.exists(media_dir):
            try:
                shutil.rmtree(media_dir)
            except Exception as e:
                print(f"[PurgeZone] Could not remove media dir {media_dir}: {e}")

    db.commit()
    return {"status": "deleted", "deleted_count": count, "name": name}



@app.get("/carte")
def map_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    return templates.TemplateResponse(request=request, name="carte.html", context={
        "queries": queries,
        "listings": listings,
        "title": f"{get_text(request, 'nav.map')} — {get_text(request, 'app.title')}",
    })


@app.get("/distance-temps")
def distance_temps_page(
    request: Request,
    listing_id: Optional[int] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    name: Optional[str] = None,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.NEW, ListingStatus.ACTIVE])
    ).order_by(Listing.date_added.desc()).limit(300).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    # User Reference Points
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    
    user_points = []
    if user:
        if user.work_address and user.work_lat and user.work_lon:
            user_points.append({
                "id": "work",
                "name": get_text(request, "map.work", "Mon travail"),
                "address": user.work_address,
                "lat": user.work_lat,
                "lon": user.work_lon,
                "icon": "fa-briefcase",
                "is_work": True
            })
        if user.poi_json:
            try:
                pois = json.loads(user.poi_json)
                for idx, poi in enumerate(pois):
                    poi_id = poi.get("id") or f"poi_{idx}"
                    user_points.append({
                        "id": str(poi_id),
                        "name": poi.get("name", get_text(request, "pois.title", "Point d'intérêt")),
                        "address": poi.get("address", ""),
                        "lat": poi.get("lat"),
                        "lon": poi.get("lon"),
                        "icon": poi.get("icon", "fa-location-dot"),
                        "is_work": False
                    })
            except Exception as e:
                print(f"[DistanceTemps] Error loading poi_json: {e}")

    # Shared Map Pins
    map_pins = db.query(MapPin).filter(MapPin.lat.isnot(None), MapPin.lon.isnot(None)).all()

    selected_listing = None
    if listing_id:
        selected_listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if selected_listing:
            _enrich_listings([selected_listing], viewed_ids)

    return templates.TemplateResponse(request=request, name="distance_temps.html", context={
        "title": f"{get_text(request, 'distance_temps.title')} — {get_text(request, 'app.title')}",
        "queries": queries,
        "listings": listings,
        "user_points": user_points,
        "map_pins": map_pins,
        "selected_listing": selected_listing,
        "init_lat": lat,
        "init_lon": lon,
        "init_name": name,
    })


@app.get("/points-interet")
def points_interet_page(
    request: Request,
    listing_id: Optional[int] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    name: Optional[str] = None,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    queries = db.query(SearchQuery).all()
    listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.NEW, ListingStatus.ACTIVE])
    ).order_by(Listing.date_added.desc()).limit(300).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    # User Reference Points
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    
    user_points = []
    if user:
        if user.work_address and user.work_lat and user.work_lon:
            user_points.append({
                "id": "work",
                "name": get_text(request, "map.work", "Mon travail"),
                "address": user.work_address,
                "lat": user.work_lat,
                "lon": user.work_lon,
                "icon": "fa-briefcase",
                "is_work": True
            })
        if user.poi_json:
            try:
                pois = json.loads(user.poi_json)
                for idx, poi in enumerate(pois):
                    poi_id = poi.get("id") or f"poi_{idx}"
                    user_points.append({
                        "id": str(poi_id),
                        "name": poi.get("name", get_text(request, "pois.title", "Point d'intérêt")),
                        "address": poi.get("address", ""),
                        "lat": poi.get("lat"),
                        "lon": poi.get("lon"),
                        "icon": poi.get("icon", "fa-location-dot"),
                        "is_work": False
                    })
            except Exception as e:
                print(f"[PointsInteret] Error loading poi_json: {e}")

    # Shared Map Pins
    map_pins = db.query(MapPin).filter(MapPin.lat.isnot(None), MapPin.lon.isnot(None)).all()

    selected_listing = None
    if listing_id:
        selected_listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if selected_listing:
            _enrich_listings([selected_listing], viewed_ids)

    return templates.TemplateResponse(request=request, name="points_interet.html", context={
        "title": f"{get_text(request, 'pois.title')} — {get_text(request, 'app.title')}",
        "queries": queries,
        "listings": listings,
        "user_points": user_points,
        "map_pins": map_pins,
        "selected_listing": selected_listing,
        "init_lat": lat,
        "init_lon": lon,
        "init_name": name,
        "categories_meta": POI_CATEGORIES
    })



@app.get("/chat")
def chat_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    queries = db.query(SearchQuery).all()
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(all_listings, viewed_ids)
    
    return templates.TemplateResponse(request=request, name="chat.html", context={
        "queries": queries,
        "listings": all_listings,
        "title": f"{get_text(request, 'chat.title')} — {get_text(request, 'app.title')}",
    })


# ─── API: AI Profiles ─────────────────────────────────────────────────────────

@app.get("/api/ai/profiles", response_model=list[AIProfileResponse])
def get_ai_profiles(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    profiles = db.query(AIProfile).filter(AIProfile.user_id == user.id).order_by(AIProfile.created_at.asc()).all()
    return profiles


@app.post("/api/ai/profiles", response_model=AIProfileResponse)
def create_ai_profile(
    request: Request,
    body: AIProfileCreate,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    
    # If this is their first profile, make it default
    is_first = db.query(AIProfile).filter(AIProfile.user_id == user.id).count() == 0
    
    profile = AIProfile(
        user_id=user.id,
        name=body.name.strip(),
        provider=body.provider,
        endpoint=body.endpoint.strip(),
        model_name=body.model_name.strip(),
        api_key=body.api_key.strip() if body.api_key else None,
        is_default=is_first,
        created_by_admin=False
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.delete("/api/ai/profiles/{profile_id}")
def delete_ai_profile(
    request: Request,
    profile_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    
    profile = db.query(AIProfile).filter(AIProfile.id == profile_id, AIProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    was_default = profile.is_default
    db.delete(profile)
    db.commit()
    
    # If we deleted the default profile, set another one as default if any exist
    if was_default:
        next_profile = db.query(AIProfile).filter(AIProfile.user_id == user.id).first()
        if next_profile:
            next_profile.is_default = True
            db.commit()
            
    return {"status": "deleted"}


@app.put("/api/ai/profiles/{profile_id}/default")
def set_default_ai_profile(
    request: Request,
    profile_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    
    profile = db.query(AIProfile).filter(AIProfile.id == profile_id, AIProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    # Unset default for all other profiles of this user
    db.query(AIProfile).filter(AIProfile.user_id == user.id).update({"is_default": False})
    
    profile.is_default = True
    db.commit()
    return {"status": "success"}


@app.post("/api/ai/profiles/{profile_id}/quota")
async def check_ai_profile_quota(
    request: Request,
    profile_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    import httpx
    
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    
    profile = db.query(AIProfile).filter(AIProfile.id == profile_id, AIProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if profile.provider in ["chatgpt", "openai-compatible"]:
                # Try to list models (lightweight endpoint)
                headers = {"Authorization": f"Bearer {profile.api_key}"} if profile.api_key else {}
                endpoint = profile.endpoint.rstrip("/")
                if not endpoint.endswith("/v1"):
                    endpoint = f"{endpoint}/v1"
                resp = await client.get(f"{endpoint}/models", headers=headers)
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Connexion réussie et clé valide."}
                elif resp.status_code == 401:
                    return {"status": "error", "message": "Clé API invalide ou non autorisée."}
                elif resp.status_code == 429:
                    return {"status": "error", "message": "Quota dépassé (Too Many Requests)."}
                else:
                    return {"status": "warning", "message": f"Statut inattendu: {resp.status_code}"}
                    
            elif profile.provider == "claude":
                # Anthropic API test
                headers = {
                    "x-api-key": profile.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                # Create a minimal message
                data = {
                    "model": profile.model_name or "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Hello"}]
                }
                endpoint = profile.endpoint or "https://api.anthropic.com/v1/messages"
                resp = await client.post(endpoint, headers=headers, json=data)
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Connexion réussie et clé valide."}
                elif resp.status_code in [401, 403]:
                    return {"status": "error", "message": "Clé API invalide ou refusée."}
                elif resp.status_code == 429:
                    return {"status": "error", "message": "Quota dépassé / Plus de crédits."}
                else:
                    return {"status": "warning", "message": f"Erreur {resp.status_code}."}
                    
            elif profile.provider == "mistral":
                headers = {"Authorization": f"Bearer {profile.api_key}"}
                endpoint = profile.endpoint or "https://api.mistral.ai/v1/models"
                resp = await client.get(endpoint, headers=headers)
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Connexion réussie et clé valide."}
                elif resp.status_code == 401:
                    return {"status": "error", "message": "Clé API invalide."}
                elif resp.status_code == 429:
                    return {"status": "error", "message": "Quota dépassé."}
                else:
                    return {"status": "warning", "message": f"Statut: {resp.status_code}"}
                    
            elif profile.provider == "google":
                # Google Gemini test
                # Endpoint is typically: https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_API_KEY
                endpoint = profile.endpoint or "https://generativelanguage.googleapis.com/v1beta/models"
                url = f"{endpoint}?key={profile.api_key}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Connexion réussie et clé valide."}
                elif resp.status_code in [400, 403]:
                    return {"status": "error", "message": "Clé API invalide ou accès refusé."}
                elif resp.status_code == 429:
                    return {"status": "error", "message": "Quota dépassé."}
                else:
                    return {"status": "warning", "message": f"Statut: {resp.status_code}"}
            else:
                return {"status": "warning", "message": "Test non supporté pour ce fournisseur."}
    except Exception as e:
        return {"status": "error", "message": f"Erreur réseau: {str(e)}"}


@app.post("/api/admin/ai/profiles", response_model=AIProfileResponse)
def create_ai_profile_admin(
    body: AIProfileAssignAdmin,
    db: Session = Depends(get_db),
    _auth = Depends(admin_required)
):
    user = db.query(models.User).filter(models.User.id == body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur cible non trouvé")
        
    profile = AIProfile(
        user_id=user.id,
        name=body.name.strip(),
        provider=body.provider,
        endpoint=body.endpoint.strip(),
        model_name=body.model_name.strip(),
        api_key=body.api_key.strip() if body.api_key else None,
        is_default=False, # Do not overwrite user's default!
        created_by_admin=True
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.post("/api/chat")

async def chat_api(
    request: Request,
    body: ChatRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """
    Endpoint de discussion avec l'assistant IA.
    """
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    user_id = user.id if user else None

    content, new_history = await run_assistant_step(body.message, body.history, user_id=user_id, db=db)
    # Filter out system prompt and internal messages for the frontend if necessary
    # or just return everything
    return {"content": content, "history": new_history}


# ─── API: Listings ────────────────────────────────────────────────────────────

@app.post("/api/listings/refresh-tags")
def refresh_tags(background_tasks: BackgroundTasks, _auth = Depends(login_required)):
    """Triggers the full refresh job (Scraping + Individual status checks) in the background."""
    from app.scheduler import full_refresh_job
    background_tasks.add_task(full_refresh_job)
    return {"status": "success", "message": "Le rafraîchissement complet des tags et statuts a été lancé en arrière-plan."}


# ─── Administration: Database Maintenance ──────────────────────────────────────

@app.get("/api/admin/db/problems")
def get_db_problems(db: Session = Depends(get_db), _auth = Depends(admin_required)):
    problems = db_maintenance.identify_problems(db)
    settings = db.query(models.GlobalSettings).first()
    if not settings:
        settings = models.GlobalSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    import json
    try:
        checks = json.loads(settings.last_checks_json or "{}")
    except Exception:
        checks = {}
        
    try:
        repairs = json.loads(settings.last_repairs_json or "{}")
    except Exception:
        repairs = {}
        
    return {
        "problems": {k: v["count"] for k, v in problems.items()},
        "last_global_check": settings.last_global_check,
        "last_checks": checks,
        "last_repairs": repairs
    }

@app.post("/api/admin/db/check")
def check_db_problems(db: Session = Depends(get_db), _auth = Depends(admin_required)):
    problems = db_maintenance.identify_problems(db)
    settings = db.query(models.GlobalSettings).first()
    if not settings:
        settings = models.GlobalSettings()
        db.add(settings)
    
    import json
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).isoformat()
    settings.last_global_check = now_str
    
    try:
        checks = json.loads(settings.last_checks_json or "{}")
    except Exception:
        checks = {}
    
    for key in problems.keys():
        checks[key] = now_str
        
    settings.last_checks_json = json.dumps(checks)
    db.commit()
    db.refresh(settings)
    
    try:
        repairs = json.loads(settings.last_repairs_json or "{}")
    except Exception:
        repairs = {}

    return {
        "problems": {k: v["count"] for k, v in problems.items()},
        "last_global_check": settings.last_global_check,
        "last_checks": checks,
        "last_repairs": repairs
    }

@app.post("/api/admin/db/repair")
async def repair_db_problems(
    problem_type: str, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), 
    _auth = Depends(admin_required)
):
    status = db_maintenance.get_repair_status()
    if status["is_running"]:
        raise HTTPException(status_code=400, detail="Une réparation est déjà en cours.")
    
    background_tasks.add_task(db_maintenance.repair_listings_batch_task, problem_type)
    return {"status": "started", "problem_type": problem_type}

@app.post("/api/admin/db/repair-all")
async def repair_all_db_problems(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db), 
    _auth = Depends(admin_required)
):
    status = db_maintenance.get_repair_status()
    if status["is_running"]:
        raise HTTPException(status_code=400, detail="Une réparation est déjà en cours.")
    
    background_tasks.add_task(db_maintenance.repair_all_sequential_task)
    return {"status": "started"}

@app.get("/api/admin/db/repair/status")
def get_db_repair_status(_auth = Depends(admin_required)):
    return db_maintenance.get_repair_status()


# ─── Listings: Repair API (all authenticated users) ────────────────────────────

@app.get("/api/db/problems")
def get_db_problems_user(
    request: Request,
    hide_rejected: bool = True,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Returns problem counts + listing details for the user-facing repair view."""
    problems = db_maintenance.identify_problems_with_details(db, hide_rejected=hide_rejected)
    settings = db.query(models.GlobalSettings).first()
    if not settings:
        settings = models.GlobalSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)

    import json
    try:
        checks = json.loads(settings.last_checks_json or "{}")
    except Exception:
        checks = {}

    try:
        repairs = json.loads(settings.last_repairs_json or "{}")
    except Exception:
        repairs = {}

    is_admin = (request.session.get("role") == "admin")
    # Filter problem types based on role
    visible_types = (
        list(problems.keys())
        if is_admin
        else db_maintenance.SAFE_PROBLEM_TYPES
    )
    filtered = {k: v for k, v in problems.items() if k in visible_types}

    return {
        "problems": {k: {"count": v["count"], "listings": v["listings"]} for k, v in filtered.items()},
        "last_global_check": settings.last_global_check,
        "last_checks": checks,
        "last_repairs": repairs,
        "is_admin": is_admin,
    }


@app.post("/api/db/check")
def check_db_problems_user(
    hide_rejected: bool = True,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Runs a full check and updates timestamps — accessible to all users."""
    problems = db_maintenance.identify_problems(db, hide_rejected=hide_rejected)
    settings = db.query(models.GlobalSettings).first()
    if not settings:
        settings = models.GlobalSettings()
        db.add(settings)

    import json
    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).isoformat()
    settings.last_global_check = now_str

    try:
        checks = json.loads(settings.last_checks_json or "{}")
    except Exception:
        checks = {}

    for key in problems.keys():
        checks[key] = now_str

    settings.last_checks_json = json.dumps(checks)
    db.commit()
    db.refresh(settings)

    try:
        repairs = json.loads(settings.last_repairs_json or "{}")
    except Exception:
        repairs = {}

    return {
        "problems": {k: v["count"] for k, v in problems.items()},
        "last_global_check": settings.last_global_check,
        "last_checks": checks,
        "last_repairs": repairs,
    }


@app.post("/api/db/repair")
async def repair_db_problems_user(
    request: Request,
    problem_type: str,
    background_tasks: BackgroundTasks,
    hide_rejected: bool = True,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Launches a non-destructive repair. Dangerous types are blocked unless admin."""
    is_admin = (request.session.get("role") == "admin")
    if problem_type in db_maintenance.DANGEROUS_PROBLEM_TYPES and not is_admin:
        raise HTTPException(status_code=403, detail="Cette action est réservée aux administrateurs.")

    all_safe = db_maintenance.SAFE_PROBLEM_TYPES + db_maintenance.DANGEROUS_PROBLEM_TYPES
    if problem_type not in all_safe:
        raise HTTPException(status_code=400, detail="Type de problème inconnu.")

    status = db_maintenance.get_repair_status()
    if status["is_running"]:
        raise HTTPException(status_code=400, detail="Une réparation est déjà en cours.")

    background_tasks.add_task(db_maintenance.repair_listings_batch_task, problem_type, False, hide_rejected)
    return {"status": "started", "problem_type": problem_type}


class RepairBatchPayload(BaseModel):
    problem_types: list[str]
    hide_rejected: bool = True


@app.post("/api/db/repair-batch")
async def repair_db_problems_batch(
    request: Request,
    payload: RepairBatchPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Launches batch repair for a list of problem types. Dangerous types are blocked unless admin."""
    is_admin = (request.session.get("role") == "admin")
    all_safe = db_maintenance.SAFE_PROBLEM_TYPES + db_maintenance.DANGEROUS_PROBLEM_TYPES

    for p_type in payload.problem_types:
        if p_type in db_maintenance.DANGEROUS_PROBLEM_TYPES and not is_admin:
            raise HTTPException(status_code=403, detail=f"L'action '{p_type}' est réservée aux administrateurs.")
        if p_type not in all_safe:
            raise HTTPException(status_code=400, detail=f"Type de problème inconnu : '{p_type}'.")

    status = db_maintenance.get_repair_status()
    if status["is_running"]:
        raise HTTPException(status_code=400, detail="Une réparation est déjà en cours.")

    background_tasks.add_task(db_maintenance.repair_selected_sequential_task, payload.problem_types, payload.hide_rejected)
    return {"status": "started", "problem_types": payload.problem_types}


@app.get("/api/db/repair/status")
def get_db_repair_status_user(_auth = Depends(login_required)):
    return db_maintenance.get_repair_status()


# ─── Missing Location Notification & Manual Repair ───────────────────────────

@app.get("/api/maintenance/missing-location-notification")
def get_missing_location_notification(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Returns missing location stats, delta since last connection, snooze status and GitHub issue URL."""
    username = request.session.get("username")
    current_user = db.query(models.User).filter(models.User.username == username).first() if username else None
    summary = db_maintenance.get_missing_location_summary(db, current_user=current_user)
    return summary


class SnoozeMissingLocationRequest(BaseModel):
    duration: str = "24h"  # "session", "1h", "24h", "3d", "7d"


@app.post("/api/maintenance/snooze-missing-location")
def snooze_missing_location_notification(
    body: SnoozeMissingLocationRequest,
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Snoozes the missing location overlay notification for the specified duration and updates last seen count."""
    from datetime import datetime, timezone, timedelta
    username = request.session.get("username")
    current_user = db.query(models.User).filter(models.User.username == username).first() if username else None

    # Calculate current count to store as baseline
    summary = db_maintenance.get_missing_location_summary(db, current_user=current_user)
    current_count = summary["count"]

    dur = body.duration.lower()
    now_utc = datetime.now(timezone.utc)
    if dur == "1h":
        snooze_until = now_utc + timedelta(hours=1)
    elif dur == "24h":
        snooze_until = now_utc + timedelta(hours=24)
    elif dur == "3d":
        snooze_until = now_utc + timedelta(days=3)
    elif dur == "7d":
        snooze_until = now_utc + timedelta(days=7)
    elif dur == "session":
        snooze_until = now_utc + timedelta(hours=12)
    else:
        snooze_until = now_utc + timedelta(hours=24)

    if current_user:
        current_user.missing_loc_snooze_until = snooze_until
        current_user.last_seen_missing_loc_count = current_count
        db.commit()

    return {
        "success": True,
        "snooze_until": snooze_until.isoformat(),
        "last_seen_count": current_count
    }


class SetListingLocationRequest(BaseModel):
    location: str
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@app.post("/api/listings/{listing_id}/set-location")
def set_listing_location_endpoint(
    listing_id: int,
    body: SetListingLocationRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """
    Sets or updates the location for a listing, runs standardization, geocoding,
    recalculates SNCF routing, and triggers automatic rejection rules (departments and forbidden zones).
    """
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable.")

    loc_input = body.location.strip()
    if not loc_input:
        raise HTTPException(status_code=400, detail="Veuillez fournir une localisation valide.")

    from app.geo import standardize_and_enrich_city, get_coordinates
    from app.services import fetch_sncf_times_for_city
    from app.models import ZoneRule, ListingStatus
    from app.geo import is_city_in_forbidden_set

    std_city, std_postal_code, _ = standardize_and_enrich_city(loc_input)
    final_city = std_city or loc_input

    listing.city = final_city
    listing.location = final_city
    if body.postal_code:
        listing.postal_code = body.postal_code.strip()
    elif std_postal_code:
        listing.postal_code = std_postal_code

    listing.address_precision = "city"
    listing.manual_address_override = True

    # Geocoding
    if body.latitude is not None and body.longitude is not None:
        listing.latitude = body.latitude
        listing.longitude = body.longitude
    else:
        coords = get_coordinates(final_city)
        if coords:
            listing.latitude, listing.longitude = coords

    # SNCF Station routing calculation
    try:
        forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
            ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
        ).all()}
        sncf_data = fetch_sncf_times_for_city(final_city, forbidden_stations)
        if sncf_data is not None:
            listing.nearest_sncf_station = sncf_data.get('nearest_sncf_station')
            listing.walk_time_sncf = sncf_data.get('walk_time_sncf')
            listing.bike_time_sncf = sncf_data.get('bike_time_sncf')
            listing.car_time_sncf = sncf_data.get('car_time_sncf')
            listing.second_sncf_station = sncf_data.get('second_sncf_station')
            listing.walk_time_sncf_2 = sncf_data.get('walk_time_sncf_2')
            listing.bike_time_sncf_2 = sncf_data.get('bike_time_sncf_2')
            listing.car_time_sncf_2 = sncf_data.get('car_time_sncf_2')
    except Exception as e:
        print(f"[set-location] Error calculating SNCF station for listing #{listing_id}: {e}")

    # Check automatic rejection rules (Allowed departments & Forbidden zones)
    was_rejected = False
    rejection_reason = None
    if not listing.to_visit:
        if not _is_city_in_allowed_departments(final_city, db):
            listing.status = ListingStatus.REJECTED
            was_rejected = True
            rejection_reason = "department_forbidden"
        else:
            forbidden_cities = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
                ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
            ).all()}
            forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
                ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
            ).all()}

            if is_city_in_forbidden_set(final_city, forbidden_cities):
                listing.status = ListingStatus.REJECTED
                was_rejected = True
                rejection_reason = "city_forbidden"
            elif forbidden_stations:
                s1 = (listing.nearest_sncf_station or "").strip().lower()
                s2 = (listing.second_sncf_station or "").strip().lower()
                if any(fs in s1 or fs == s1 for fs in forbidden_stations) or any(fs in s2 or fs == s2 for fs in forbidden_stations):
                    listing.status = ListingStatus.REJECTED
                    was_rejected = True
                    rejection_reason = "station_forbidden"

    # Price per sqm
    listing.update_price_per_sqm()

    db.commit()
    db.refresh(listing)

    return {
        "success": True,
        "listing": {
            "id": listing.id,
            "title": listing.title,
            "city": listing.city,
            "location": listing.location,
            "postal_code": listing.postal_code,
            "latitude": listing.latitude,
            "longitude": listing.longitude,
            "status": listing.status.value if hasattr(listing.status, 'value') else str(listing.status),
            "is_rejected": was_rejected,
            "rejection_reason": rejection_reason
        }
    }


# ─── Scrapers: Statistical Analytics & Parser Health ───────────────────────────

@app.get("/api/scrapers/analytics")
def get_scrapers_analytics_endpoint(
    force_refresh: bool = False,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Returns statistical analysis, completeness matrix, and defects for all scrapers/parsers."""
    from app.scraper_analytics import get_scraper_analytics
    return get_scraper_analytics(db=db, force_refresh=force_refresh)


@app.post("/api/scrapers/reparse-listing/{listing_id}")
async def reparse_single_listing_endpoint(
    listing_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Re-parses and re-fetches data for a single listing to fix parsed defects."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable.")

    from app.services import refresh_listing_status, repair_listing_photos, repair_listing_title
    from app.scraper_analytics import clear_scraper_analytics_cache

    await repair_listing_title(listing, db)
    await repair_listing_photos(listing, db)
    try:
        await refresh_listing_status(listing, db)
    except Exception as e:
        print(f"[reparse] Error refreshing listing #{listing_id}: {e}")

    clear_scraper_analytics_cache()
    return {"status": "success", "listing_id": listing_id}




@app.get("/api/listings")
def get_listings(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    visit_status: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    _auth = Depends(login_required)
):
    """Get all listings with optional filters and search."""
    query = db.query(Listing)
    if status:
        query = query.filter(Listing.status == status)
    if visit_status:
        if visit_status == "none":
            query = query.filter((Listing.last_visit_status == None) | (Listing.last_visit_status == ""))
        else:
            query = query.filter(Listing.last_visit_status == visit_status)
    if source:
        query = query.filter(Listing.source == source)
    if q:
        search_q = f"%{q}%"
        # Base text search filters
        filter_expr = (
            (Listing.title.ilike(search_q)) | 
            (Listing.city.ilike(search_q)) | 
            (Listing.location.ilike(search_q))
        )
        
        # Optional ID search if q is numeric or #number
        try:
            val = q.lstrip('#')
            if val.isdigit():
                filter_expr = filter_expr | (Listing.id == int(val))
        except:
            pass
            
        query = query.filter(filter_expr)
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
            "last_visit_status": l.last_visit_status,
            "is_duplicate": l.is_duplicate,
            "photos": json_to_photos(l.photos_local),
            "date_added": l.date_added.isoformat() if l.date_added else None,
            "scraped_at": l.scraped_at.isoformat() if l.scraped_at else None,
            "latitude": l.latitude,
            "longitude": l.longitude,
        }
        for l in listings
    ]


def sync_listing_cluster(db: Session, listing_id: int):
    """
    Propagates shared data (status, interactions, reviews) 
    across all listings in a duplicate cluster.
    """
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        return
    
    # Identify the root of the cluster
    root_id = listing.duplicate_of_id or listing.id
    
    # Get all listings in the cluster (star-topology: all point to root)
    cluster = db.query(Listing).filter(
        (Listing.id == root_id) | (Listing.duplicate_of_id == root_id)
    ).all()
    
    if len(cluster) <= 1:
        return

    # Sync status and interaction flags from 'listing' to others
    for other in cluster:
        if other.id == listing.id:
            continue
        other.status = listing.status
        other.is_favorite = listing.is_favorite
        other.is_liked = listing.is_liked
        other.is_disliked = listing.is_disliked
    
    # Sync Reviews
    source_reviews = db.query(Review).filter(Review.listing_id == listing.id).all()
    for review in source_reviews:
        for other in cluster:
            if other.id == listing.id:
                continue
            get_or_create_review(
                db=db,
                listing_id=other.id,
                reviewer=review.reviewer,
                pros=review.pros,
                cons=review.cons,
                rating=review.rating,
                visit_done=review.visit_done,
                notes=review.notes
            )
    
    db.commit()


@app.post("/api/listings/{listing_id}/duplicate")
def declare_duplicate(
    listing_id: int,
    body: DuplicateDeclarationRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce introuvable")

    if body.target_listing_id:
        target = db.query(Listing).filter(Listing.id == body.target_listing_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Annonce cible introuvable")
        
        # Star-topology: always point to the ultimate original (root)
        root_id = target.duplicate_of_id or target.id
        listing.is_duplicate = True
        listing.duplicate_of_id = root_id
        db.commit() # Save the link first
        
        # Initial sync: push data from the cluster to the newly declared duplicate
        sync_listing_cluster(db, root_id)
    elif body.original_url:
        listing.is_duplicate = True
        listing.original_url = body.original_url
        db.commit()
    else:
        raise HTTPException(status_code=400, detail="Veuillez fournir une annonce cible ou une URL")

    return {"status": "success"}


@app.post("/api/duplicates/merge")
def merge_duplicate(
    body: DuplicateMergeRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Merges listing A as a duplicate of listing B."""
    l_a = db.query(Listing).filter(Listing.id == body.listing_a_id).first()
    l_b = db.query(Listing).filter(Listing.id == body.listing_b_id).first()
    
    if not l_a or not l_b:
        raise HTTPException(status_code=404, detail="Listing not found")
        
    # Star-topology: always point to the ultimate original (root)
    root_id = l_b.duplicate_of_id or l_b.id
    l_a.is_duplicate = True
    l_a.duplicate_of_id = root_id
    if l_a.status == ListingStatus.NEW:
        l_a.status = ListingStatus.ACTIVE
    db.commit()
    
    # Sync data across the cluster
    sync_listing_cluster(db, root_id)
    return {"status": "success"}


@app.post("/api/duplicates/reject")
def reject_duplicate(
    body: DuplicateRejectRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Marks a pair of listings as NOT duplicates."""
    # Check if already exists
    existing = db.query(RejectedDuplicate).filter(
        (RejectedDuplicate.listing_a_id == min(body.listing_a_id, body.listing_b_id)) &
        (RejectedDuplicate.listing_b_id == max(body.listing_a_id, body.listing_b_id))
    ).first()
    
    if not existing:
        rej = RejectedDuplicate(
            listing_a_id=min(body.listing_a_id, body.listing_b_id),
            listing_b_id=max(body.listing_a_id, body.listing_b_id)
        )
        db.add(rej)
        db.commit()

    try:
        from app.notifications import refresh_standard_user_tasks_notifications
        refresh_standard_user_tasks_notifications(db)
    except Exception:
        pass
        
    return {"status": "success"}


@app.get("/api/map-data")
def get_map_data(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Returns listings, user POIs, and shared map pins for the map."""
    listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.NEW, ListingStatus.ACTIVE]),
        Listing.latitude.isnot(None),
        Listing.longitude.isnot(None)
    ).all()

    # Enrichment
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)

    # 2. User Data
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first() if username else None

    pois = []
    if user and user.poi_json:
        try:
            pois = json.loads(user.poi_json)
        except:
            pois = []

    # 3. Shared Map Pins (from all users)
    all_pins = db.query(MapPin).filter(
        MapPin.lat.isnot(None),
        MapPin.lon.isnot(None)
    ).all()

    # Cities to qualify
    from app.geo import is_city_in_forbidden_set
    zone_rules = db.query(ZoneRule).all()
    existing_city_rules = {r.name.lower().strip() for r in zone_rules if r.zone_type == 'city'}

    active_cities_raw = db.query(Listing.city).filter(
        Listing.status.in_([ListingStatus.NEW, ListingStatus.ACTIVE]),
        Listing.city != None,
        Listing.city != ""
    ).distinct().all()

    active_locations_raw = db.query(Listing.location).filter(
        Listing.status.in_([ListingStatus.NEW, ListingStatus.ACTIVE]),
        (Listing.city == None) | (Listing.city == ""),
        Listing.location != None,
        Listing.location != ""
    ).distinct().all()

    to_qualify_cities = []
    seen_cities = set()

    for c in active_cities_raw:
        city_name = (c[0] or "").strip()
        if city_name and city_name.lower() not in seen_cities:
            seen_cities.add(city_name.lower())
            if not is_city_in_forbidden_set(city_name, existing_city_rules) and city_name.lower() not in existing_city_rules:
                to_qualify_cities.append(city_name)

    for loc in active_locations_raw:
        loc_str = (loc[0] or "").strip()
        if loc_str and loc_str.lower() not in seen_cities:
            seen_cities.add(loc_str.lower())
            if not is_city_in_forbidden_set(loc_str, existing_city_rules) and loc_str.lower() not in existing_city_rules:
                to_qualify_cities.append(loc_str)

    return {
        "listings": [
            {
                "id": l.id,
                "title": l.title,
                "price": l.price,
                "location": l.location or l.city,
                "lat": l.latitude,
                "lon": l.longitude,
                "url": f"/listings/{l.id}",
                "status": l.user_status,
                "last_visit_status": l.last_visit_status,
                "photos": json_to_photos(l.photos_local)
            }
            for l in listings
        ],
        "user": {
            "work": {
                "address": user.work_address,
                "lat": user.work_lat,
                "lon": user.work_lon
            } if user and user.work_address and user.work_lat else None,
            "pois": pois
        },
        "pins": [
            {
                "id": p.id,
                "title": p.title,
                "address": p.address,
                "lat": p.lat,
                "lon": p.lon,
                "created_by": p.created_by,
                "nearby_distance_km": p.nearby_distance_km,
                "nearby_ref_commune": p.nearby_ref_commune,
                "nearby_ref_cp": p.nearby_ref_cp,
                "pin_type": p.pin_type,
            }
            for p in all_pins
        ],
        "current_user": username,
        "zone_rules": [
            {
                "id": r.id,
                "zone_type": r.zone_type,
                "name": r.name,
                "rule": r.rule,
            }
            for r in zone_rules
        ],
        "to_qualify_cities": to_qualify_cities,
    }


# ─── API: Geo Distance & Autocomplete ─────────────────────────────────────────

@app.get("/api/geo/autocomplete")
def api_geo_autocomplete(
    q: str,
    limit: int = 8,
    _auth = Depends(login_required)
):
    """Unified autocomplete search for addresses, cities, and SNCF stations."""
    results = search_places_unified(q, limit=limit)
    return {"results": results}


@app.post("/api/geo/route-calc")
def api_geo_route_calc(
    body: schemas.RouteCalcRequest,
    _auth = Depends(login_required)
):
    """Calculates route distance and durations for car, bike, walking."""
    data = calculate_multi_route(
        start_lat=body.start_lat,
        start_lon=body.start_lon,
        end_lat=body.end_lat,
        end_lon=body.end_lon,
        start_name=body.start_name or "Point A",
        end_name=body.end_name or "Point B"
    )
    return data


@app.get("/api/geo/pois")
def api_geo_pois(
    lat: float,
    lon: float,
    radius: int = 5000,
    categories: Optional[str] = None,
    limit: int = 25,
    _auth = Depends(login_required)
):
    """Fetches Points of Interest around coordinates within radius (meters)."""
    cat_list = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    data = fetch_pois_around(
        lat=lat,
        lon=lon,
        radius_meters=radius,
        categories=cat_list,
        limit_per_category=limit
    )
    return data


@app.get("/api/geo/reference-points")
def api_get_reference_points(
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    points = []
    if user.work_address and user.work_lat and user.work_lon:
        points.append({
            "id": "work",
            "name": "Mon travail",
            "address": user.work_address,
            "lat": user.work_lat,
            "lon": user.work_lon,
            "icon": "fa-briefcase",
            "is_work": True
        })
    if user.poi_json:
        try:
            pois = json.loads(user.poi_json)
            for idx, poi in enumerate(pois):
                points.append({
                    "id": str(poi.get("id") or f"poi_{idx}"),
                    "name": poi.get("name", "Point d'intérêt"),
                    "address": poi.get("address", ""),
                    "lat": poi.get("lat"),
                    "lon": poi.get("lon"),
                    "icon": poi.get("icon", "fa-location-dot"),
                    "is_work": False
                })
        except:
            pass
            
    return {"points": points}


@app.post("/api/geo/reference-points")
def api_add_reference_point(
    request: Request,
    body: schemas.ReferencePointRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    pois = []
    if user.poi_json:
        try:
            pois = json.loads(user.poi_json)
        except:
            pois = []
            
    import uuid
    new_poi = {
        "id": f"poi_{uuid.uuid4().hex[:8]}",
        "name": body.name.strip(),
        "address": body.address.strip(),
        "lat": body.lat,
        "lon": body.lon,
        "icon": body.icon or "fa-location-dot",
        "category": body.category or "custom"
    }
    pois.append(new_poi)
    user.poi_json = json.dumps(pois, ensure_ascii=False)
    db.commit()
    return {"status": "ok", "point": new_poi}


@app.delete("/api/geo/reference-points/{point_id}")
def api_delete_reference_point(
    request: Request,
    point_id: str,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if point_id == "work":
        user.work_address = None
        user.work_lat = None
        user.work_lon = None
        db.commit()
        return {"status": "deleted", "id": "work"}
        
    if user.poi_json:
        try:
            pois = json.loads(user.poi_json)
            pois = [p for p in pois if str(p.get("id")) != point_id]
            user.poi_json = json.dumps(pois, ensure_ascii=False)
            db.commit()
        except:
            pass
            
    return {"status": "deleted", "id": point_id}


@app.post("/api/map-pins")
def create_map_pins(
    request: Request,
    body: MapPinBulkRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Bulk-create map pins from title;address pairs. Geocodes each address."""
    username = request.session.get("username")
    created = []
    errors = []

    for entry in body.pins:
        coords = get_coordinates(entry.address)
        if coords:
            lat, lon = coords
            pin = MapPin(
                title=entry.title.strip(),
                address=entry.address.strip(),
                lat=lat,
                lon=lon,
                created_by=username
            )
            db.add(pin)
            created.append({"title": entry.title, "address": entry.address})
        else:
            errors.append({"title": entry.title, "address": entry.address, "error": "geocode_failed"})

    db.commit()
    return {"status": "ok", "created": len(created), "errors": errors}


@app.get("/api/nearby-cities")
async def get_nearby_cities(
    query: str,
    rayon: int = 5,
    _auth = Depends(login_required)
):
    """
    Proxy endpoint to villes-voisines.fr API.
    Supports both postal code (5 digits) and city names.
    Returns a dict with 'cities' (list) and 'reference' (dict).
    """
    import httpx as _httpx
    import re

    query = query.strip()
    cp = ""
    ref_name = query

    # Check if query is a postal code
    if re.fullmatch(r"\d{5}", query):
        cp = query
    else:
        # Try to resolve city name to postal code
        resolved_cp = get_postal_code(query)
        if not resolved_cp:
            raise HTTPException(status_code=404, detail=f"Impossible de trouver le code postal pour '{query}'")
        cp = resolved_cp

    # Clamp rayon to sensible bounds
    rayon = max(1, min(rayon, 200))

    url = f"https://www.villes-voisines.fr/getcp.php?cp={cp}&rayon={rayon}"
    try:
        async with _httpx.AsyncClient() as client:
            res = await client.get(url, timeout=10.0, headers={"User-Agent": "ImmoBoussole/1.0"})
        res.raise_for_status()
        raw = res.json()
        
        if isinstance(raw, dict):
            cities = list(raw.values())
        else:
            cities = raw

        cities.sort(key=lambda c: float(c.get("distance", 0)) if c.get("distance") is not None else 0)
        
        # Determine reference info
        # If the first city has distance 0, use its name as ref_name if query was a CP
        if cities and float(cities[0].get("distance", 0)) == 0:
            if re.fullmatch(r"\d{5}", query):
                ref_name = cities[0].get("nom_commune", query)
            ref_cp = cities[0].get("code_postal", cp)
        else:
            ref_cp = cp

        return {
            "cities": cities,
            "reference": {
                "name": ref_name,
                "cp": ref_cp
            }
        }
    except _httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Erreur API villes-voisines: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Impossible de contacter l'API villes-voisines: {str(e)}")


@app.post("/api/map-pins/nearby")
def create_nearby_city_pins(
    request: Request,
    body: NearbyCityBulkRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """
    Geocodes and persists selected nearby cities as MapPins.
    Stores reference city metadata so the map tooltip can display
    \"À X km de [Ville] (CP)\".
    """
    username = request.session.get("username")
    created = []
    errors = []

    for city in body.cities:
        query_str = f"{city.nom_commune} {city.code_postal}, France"
        coords = get_coordinates(query_str)
        if coords:
            lat, lon = coords
            pin = MapPin(
                title=f"{city.nom_commune.title()} ({city.code_postal})",
                address=query_str,
                lat=lat,
                lon=lon,
                created_by=username,
                nearby_distance_km=round(city.distance, 2),
                nearby_ref_commune=city.ref_commune,
                nearby_ref_cp=city.ref_cp,
                pin_type="city"
            )
            db.add(pin)
            created.append({"title": pin.title, "address": pin.address})

            # Import nearby stations if requested
            if body.include_stations:
                stations = find_nearby_stations(lat, lon, radius=20000)
                for s in stations:
                    # Check if station already exists for this city/user to avoid massive duplicates?
                    # For simplicity, we just add them.
                    # Or maybe only add if it's not already a pin at the exact same lat/lon?
                    s_pin = MapPin(
                        title=f"Gare de {s['name']}",
                        address=f"Gare SNCF, {city.nom_commune}",
                        lat=s["lat"],
                        lon=s["lon"],
                        created_by=username,
                        pin_type="station",
                        # Link it to the city
                        nearby_ref_commune=city.nom_commune,
                        nearby_ref_cp=city.code_postal
                    )
                    db.add(s_pin)
                    created.append({"title": s_pin.title, "address": s_pin.address})
        else:
            errors.append({
                "title": f"{city.nom_commune} ({city.code_postal})",
                "address": query_str,
                "error": "geocode_failed"
            })

    db.commit()
    return {"status": "ok", "created": len(created), "errors": errors}


@app.delete("/api/map-pins/{pin_id}")
def delete_map_pin(
    pin_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Delete a map pin. Only the creator or admins can delete."""
    pin = db.query(MapPin).filter(MapPin.id == pin_id).first()
    if not pin:
        raise HTTPException(status_code=404, detail="Pin not found")
    
    username = request.session.get("username")
    role = request.session.get("role")
    if pin.created_by != username and role != "admin":
        raise HTTPException(status_code=403, detail="Cannot delete another user's pin")
    
    db.delete(pin)
    db.commit()
    return {"status": "deleted"}


@app.get("/api/geo/address-autocomplete")
def address_autocomplete(
    request: Request,
    q: str = "",
    limit: int = 6,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Returns BAN address autocomplete suggestions."""
    from app.geo import search_ban_addresses
    results = search_ban_addresses(q, limit=limit)
    return {"query": q, "results": results}


@app.get("/api/geo/cadastre-lookup")
def cadastre_lookup(
    request: Request,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    insee: Optional[str] = None,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Returns cadastral parcel info and official DVF link via APICarto / BAN."""
    from app.geo import fetch_cadastral_parcel
    result = fetch_cadastral_parcel(address=address, lat=lat, lon=lon, insee_code=insee)
    if not result:
        return {"status": "not_found", "parcel": None, "dvf_url": None}
    return {"status": "ok", "parcel": result}


@app.get("/api/city-info")
async def get_city_info(
    city: str,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """
    Returns geographic info for a given city name:
    - total_area_km2: administrative area in km² (from Nominatim extratags)
    - stations: list of SNCF stations with walk/bike/car times (minutes)
    Results are cached in GEO_CACHE.
    Also returns matching dynamic listings and any existing ZoneRule.
    """
    import httpx as _httpx
    import re
    from sqlalchemy import or_
    from app.geo import (
        GEO_CACHE, find_nearby_stations, calculate_station_times, haversine_km,
        standardize_and_enrich_city, parse_city_input, clean_arrondissement,
        is_city_in_forbidden_set
    )

    std_city, std_zip, _ = standardize_and_enrich_city(city)
    city_key = std_city if std_city else city.strip()
    plain_name = re.sub(r'\s*\(\d{5}\)$', '', city_key).strip()
    cache_key = f"city_info:{city_key.lower()}"

    if cache_key in GEO_CACHE:
        geo_data = GEO_CACHE[cache_key]
    else:
        headers = {"User-Agent": "ImmoBoussole/1.0"}
        area_km2 = None
        lat = None
        lon = None

        try:
            async with _httpx.AsyncClient() as client:
                # 1a. First try: structured search for administrative boundary (has area data)
                boundary_params = {
                    "city": plain_name,
                    "country": "France",
                    "featuretype": "city",
                    "format": "json",
                    "limit": 1,
                    "extratags": 1,
                    "addressdetails": 0,
                }
                if std_zip:
                    boundary_params["postalcode"] = std_zip

                res_boundary = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params=boundary_params,
                    headers=headers,
                    timeout=10.0,
                )
                if res_boundary.status_code == 200:
                    boundary_data = res_boundary.json()
                    if boundary_data:
                        place = boundary_data[0]
                        lat = float(place["lat"])
                        lon = float(place["lon"])
                        extratags = place.get("extratags") or {}
                        area_m2 = extratags.get("area")
                        if area_m2:
                            try:
                                area_km2 = round(float(area_m2) / 1_000_000, 1)
                            except Exception:
                                area_km2 = None

                # 1b. Fallback: generic search (if boundary search found nothing)
                if lat is None:
                    res_generic = await client.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={
                            "q": f"{plain_name} {std_zip}".strip() if std_zip else plain_name,
                            "format": "json",
                            "limit": 1,
                            "extratags": 1,
                            "addressdetails": 0,
                            "countrycodes": "fr",
                        },
                        headers=headers,
                        timeout=10.0,
                    )
                    if res_generic.status_code == 200:
                        generic_data = res_generic.json()
                        if generic_data:
                            place = generic_data[0]
                            lat = float(place["lat"])
                            lon = float(place["lon"])
                            if area_km2 is None:
                                extratags = place.get("extratags") or {}
                                area_m2 = extratags.get("area")
                                if area_m2:
                                    try:
                                        area_km2 = round(float(area_m2) / 1_000_000, 1)
                                    except Exception:
                                        area_km2 = None

                # 1c. Second fallback: geo.api.gouv.fr (for French communes)
                if lat is None:
                    geo_api_url = f"https://geo.api.gouv.fr/communes?nom={plain_name}&boost=population&fields=nom,code,codesPostaux,centre,surface&format=json"
                    res_geo = await client.get(geo_api_url, timeout=5.0)
                    if res_geo.status_code == 200:
                        geo_communes = res_geo.json()
                        if geo_communes:
                            best = geo_communes[0]
                            if std_zip and "codesPostaux" in best:
                                for c in geo_communes:
                                    if std_zip in c.get("codesPostaux", []):
                                        best = c
                                        break
                            if "centre" in best and "coordinates" in best["centre"]:
                                lon = float(best["centre"]["coordinates"][0])
                                lat = float(best["centre"]["coordinates"][1])
                            if "surface" in best and best["surface"]:
                                # surface in hectares -> convert to km2 (/100)
                                area_km2 = round(float(best["surface"]) / 100.0, 1)

            if lat is None or lon is None:
                raise HTTPException(status_code=404, detail=f"Ville '{city_key}' introuvable")

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erreur géocodage : {e}")

        # 2. Find nearby SNCF stations (up to 5) and calculate travel times
        stations_raw = find_nearby_stations(lat, lon, radius=20000)

        forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
            ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
        ).all()}
        stations_raw = [s for s in stations_raw if s["name"].lower().strip() not in forbidden_stations]

        # Sort by haversine distance (proper great-circle) and take top 5
        for s in stations_raw:
            s["_dist_km"] = haversine_km(lat, lon, s["lat"], s["lon"])
        stations_raw.sort(key=lambda s: s["_dist_km"])
        stations_raw = stations_raw[:5]

        stations_out = []
        for s in stations_raw:
            times = calculate_station_times(lat, lon, s["lat"], s["lon"])
            stations_out.append({
                "name": s["name"],
                "distance_km": round(s["_dist_km"], 1),
                "walk": times.get("walk"),
                "bike": times.get("bike"),
                "car": times.get("car"),
            })

        geo_data = {
            "city": city_key,
            "area_km2": area_km2,
            "stations": stations_out,
        }
        GEO_CACHE[cache_key] = geo_data

    # Query matching listings dynamically (NOT cached, to reflect up-to-date data)
    search_terms = {city.strip(), city_key, plain_name}
    filters = []
    for term in search_terms:
        if term:
            filters.append(Listing.city.ilike(f"%{term}%"))
            filters.append(Listing.location.ilike(f"%{term}%"))

    listings = db.query(Listing).filter(or_(*filters)).order_by(Listing.date_added.desc()).all() if filters else []

    # Query active zone rule for this city (matching variations cleanly)
    all_city_rules = db.query(ZoneRule).filter(ZoneRule.zone_type == "city").all()
    zone_rule = None
    target_names = {t.lower() for t in search_terms if t}
    for r in all_city_rules:
        r_name_clean = r.name.strip().lower()
        if (
            r_name_clean in target_names
            or is_city_in_forbidden_set(r.name, target_names)
            or is_city_in_forbidden_set(city_key, {r_name_clean})
            or is_city_in_forbidden_set(plain_name, {r_name_clean})
        ):
            zone_rule = r
            break

    zone_rule_info = None
    if zone_rule:
        zone_rule_info = {
            "id": zone_rule.id,
            "rule": zone_rule.rule,
        }

    return {
        **geo_data,
        "zone_rule": zone_rule_info,
        "listings": [
            {
                "id": l.id,
                "title": l.title,
                "price": l.price,
                "area": l.area,
                "rooms": l.rooms,
                "status": l.status.value if hasattr(l.status, 'value') else l.status,
                "url": f"/listings/{l.id}",
                "photos": json_to_photos(l.photos_local)
            }
            for l in listings
        ]
    }



@app.post("/api/profile")
async def update_profile(
    request: Request,
    body: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update Work Address
    if body.work_address != user.work_address:
        user.work_address = body.work_address
        if body.work_address:
            coords = get_coordinates(body.work_address)
            if coords:
                user.work_lat, user.work_lon = coords
            else:
                user.work_lat, user.work_lon = None, None
        else:
            user.work_lat, user.work_lon = None, None

    # Update POIs
    new_pois = []
    for poi in body.pois:
        if not poi.lat or not poi.lon:
            coords = get_coordinates(poi.address)
            if coords:
                poi.lat, poi.lon = coords
        new_pois.append(poi.model_dump())
    
    user.poi_json = json.dumps(new_pois)

    # Update Apprise notification URL
    if body.apprise_url is not None:
        user.apprise_url = body.apprise_url.strip() or None

    # Update Contact & SFR fields
    if body.email is not None: user.email = body.email.strip() or None
    if body.phone is not None: user.phone = body.phone.strip() or None
    if body.sfr_identifier is not None: user.sfr_identifier = body.sfr_identifier.strip() or None
    if body.sfr_password is not None: user.sfr_password = body.sfr_password.strip() or None
    if body.auto_read_after_days is not None and body.auto_read_after_days in (2, 7, 30, 60):
        user.auto_read_after_days = body.auto_read_after_days

    db.commit()
    
    return {"status": "updated"}


class NotificationTestRequest(BaseModel):
    apprise_url: str


@app.post("/api/notifications/test")
async def test_notification(
    body: NotificationTestRequest,
    request: Request,
    _auth = Depends(login_required)
):
    """
    Sends a test push notification to the provided Apprise URL.
    Used from the Mon Profil page to validate the configuration.
    """
    from app.notifications import send_test_notification

    url = body.apprise_url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL Apprise vide")

    success = await send_test_notification(url)
    if not success:
        raise HTTPException(
            status_code=502,
            detail="La notification n'a pas pu être envoyée. Vérifiez votre URL Apprise."
        )
    return {"status": "sent"}


@app.get("/api/listings/{listing_id}")
def get_listing(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Get a single listing by ID."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    return listing


@app.get("/api/listings/{listing_id}/nearby-stations")
async def get_nearby_stations(listing_id: int, db: Session = Depends(get_db), _auth = Depends(login_required)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing or not (listing.location or listing.city):
        return []
    
    # Geocode the location
    loc = listing.location or listing.city
    coords = get_coordinates(loc)
    if not coords:
        return []
    
    stations = find_nearby_stations(coords[0], coords[1])
    return stations


@app.post("/api/listings/{listing_id}/stations")
async def update_listing_stations(
    listing_id: int, 
    body: StationsUpdateRequest, 
    db: Session = Depends(get_db), 
    _auth = Depends(user_required)
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing or not (listing.location or listing.city):
        raise HTTPException(status_code=404, detail="Annonce ou localisation introuvable")

    coords = get_coordinates(listing.location or listing.city)
    if not coords:
        raise HTTPException(status_code=400, detail="Impossible de géolocaliser le bien")

    # Update Station 1
    listing.nearest_sncf_station = body.station_1.name
    t1 = calculate_station_times(coords[0], coords[1], body.station_1.lat, body.station_1.lon)
    listing.walk_time_sncf = t1.get('walk')
    listing.bike_time_sncf = t1.get('bike')
    listing.car_time_sncf = t1.get('car')

    # Update Station 2
    if body.station_2:
        listing.second_sncf_station = body.station_2.name
        t2 = calculate_station_times(coords[0], coords[1], body.station_2.lat, body.station_2.lon)
        listing.walk_time_sncf_2 = t2.get('walk')
        listing.bike_time_sncf_2 = t2.get('bike')
        listing.car_time_sncf_2 = t2.get('car')
    else:
        listing.second_sncf_station = None
        listing.walk_time_sncf_2 = None
        listing.bike_time_sncf_2 = None
        listing.car_time_sncf_2 = None

    db.commit()
    return {"status": "updated"}


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
    source, scraper = _resolve_scraper(url)

    from app.services import (
        is_search_page_title,
        is_valid_listing_url,
        fetch_basic_metadata,
        is_error_or_generic_title,
        has_valid_local_photos,
        is_missing_or_corrupt_photos,
        repair_listing_photos,
        repair_listing_title,
        create_listing_from_details
    )

    # ── Scrape ──
    details = {}
    scraping_success = True
    if scraper:
        try:
            details = await scraper.get_listing_details(url)
            if details and is_search_page_title(details.get("title", "")):
                listing.status = ListingStatus.REJECTED
                listing.scraped_at = datetime.now(timezone.utc)
                db.commit()
                return {
                    "status": "updated",
                    "listing_id": listing.id,
                    "title": listing.title,
                    "scraping_success": True,
                    "forbidden_zone_warning": {
                        "message": "Cette annonce a été rejetée car elle a été identifiée comme une page de recherche."
                    }
                }
            if not details or is_error_or_generic_title(details.get("title")):
                scraping_success = False
        except Exception as e:
            print(f"[API] Re-scrape error for {url}: {e}")
            scraping_success = False
    
    if details.get("is_disappeared"):
        listing.status = ListingStatus.DISAPPEARED
        listing.scraped_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "status": "updated",
            "listing_id": listing.id,
            "title": listing.title,
            "scraping_success": True,
            "message": "L'annonce est indiquée comme n'étant plus en ligne."
        }

    if not details or not details.get("title") or is_error_or_generic_title(details.get("title")):
        fb_details = await fetch_basic_metadata(url)
        if fb_details.get("is_invalid_search_page"):
            listing.status = ListingStatus.REJECTED
            listing.scraped_at = datetime.now(timezone.utc)
            db.commit()
            return {
                "status": "updated",
                "listing_id": listing.id,
                "title": listing.title,
                "scraping_success": False,
                "forbidden_zone_warning": {
                    "message": "Cette annonce a été rejetée car elle a été identifiée comme une page de recherche."
                }
            }
        if fb_details and not is_error_or_generic_title(fb_details.get("title")):
            details = fb_details
            scraping_success = True
        else:
            scraping_success = False
            # Merge any extracted photos from fallback
            if fb_details and fb_details.get("photo_urls") and not details.get("photo_urls"):
                details["photo_urls"] = fb_details["photo_urls"]

    # ── Update via service ──
    updated_listing, _ = await create_listing_from_details(db, details, source, url)

    # Ensure title is repaired if error or generic title
    title_repaired = False
    if is_error_or_generic_title(updated_listing.title):
        title_repaired, _ = await repair_listing_title(updated_listing, db)

    # Ensure photos are repaired if missing
    if is_missing_or_corrupt_photos(updated_listing):
        try:
            await repair_listing_photos(updated_listing, db)
        except Exception as e:
            print(f"[API] Error in repair_listing_photos for {updated_listing.id}: {e}")

    photos = json_to_photos(updated_listing.photos_local)
    photos_count = len(photos)
    if scraping_success or title_repaired:
        if title_repaired:
            msg = f"Titre et informations réparés avec succès : {updated_listing.title}"
        else:
            msg = "Annonce actualisée avec succès."
        scraping_success = True
    elif photos_count > 0:
        msg = f"Photos disponibles ({photos_count}). Données existantes préservées (le site source a restreint l'accès direct)."
    else:
        msg = "Données existantes préservées (le site source a renvoyé une erreur ou est temporairement inaccessible)."

    rescrape_response = {
        "status": "updated",
        "listing_id": updated_listing.id,
        "title": updated_listing.title,
        "scraping_success": scraping_success,
        "photos_count": photos_count,
        "message": msg
    }

    # ── Forbidden Zone Warning ──
    from app.geo import is_city_in_forbidden_set
    forbidden_cities_rescrape = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
        ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
    ).all()}
    forbidden_stations_rescrape = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
        ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
    ).all()}
    
    city_to_check = updated_listing.city or updated_listing.location
    in_forbidden_city = city_to_check and is_city_in_forbidden_set(city_to_check, forbidden_cities_rescrape)
    s1 = (updated_listing.nearest_sncf_station or "").strip().lower()
    s2 = (updated_listing.second_sncf_station or "").strip().lower()
    in_forbidden_station = bool(forbidden_stations_rescrape and (
        any(fs in s1 or fs == s1 for fs in forbidden_stations_rescrape) or
        any(fs in s2 or fs == s2 for fs in forbidden_stations_rescrape)
    ))

    if (in_forbidden_city or in_forbidden_station) and not updated_listing.to_visit:
        updated_listing.status = ListingStatus.REJECTED
        db.commit()
        rescrape_response["forbidden_zone_warning"] = {
            "message": f"⛔ Cette annonce a été rejetée car elle est en zone interdite.",
            "city": updated_listing.city or updated_listing.location,
        }

    return rescrape_response


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

    from app.services import is_valid_listing_url, is_search_page_title, fetch_basic_metadata

    # ── URL Structure Validation ──
    is_valid, err_msg = is_valid_listing_url(url)
    if not is_valid:
        return {
            "status": "invalid_url",
            "message": f"⛔ {err_msg}",
            "listing_id": None,
            "title": None
        }

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
    source, scraper = _resolve_scraper(url)

    if body.skip_scraping:
        # ── Fast path: fetch only basic metadata ───────────────────────────
        details = await fetch_basic_metadata(url)
        if details.get("is_invalid_search_page"):
            return {
                "status": "invalid_url",
                "message": "⛔ L'URL ou le titre de l'annonce indique une page de recherche plutôt qu'une annonce unique.",
                "listing_id": None,
                "title": None
            }
        
        city_to_check = details.get("city") or details.get("location")
        if city_to_check:
            from app.geo import standardize_and_enrich_city
            std_city, _, _ = standardize_and_enrich_city(city_to_check)
            if std_city:
                details["city"] = std_city
                details["location"] = std_city
                city_to_check = std_city

        if city_to_check and not _is_city_in_allowed_departments(city_to_check, db):
            return {
                "status": "rejected_department",
                "message": f"⛔ Cette annonce est hors des départements autorisés : {city_to_check}",
                "listing_id": None,
                "title": details.get("title")
            }
            
        # Create listing (includes duplicate check) without photo download
        listing, is_new = await create_listing_from_details(
            db, details, source, url, download_photos=False, status=ListingStatus.ACTIVE
        )
        
        # ── Fast path: Forbidden Zone Check ──
        from app.geo import is_city_in_forbidden_set
        forbidden_cities_fast = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
            ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
        ).all()}
        
        city_to_check = listing.city or listing.location
        in_forbidden_city = city_to_check and is_city_in_forbidden_set(city_to_check, forbidden_cities_fast)
            
        if in_forbidden_city and not listing.to_visit:
            listing.status = ListingStatus.REJECTED
            db.commit()

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
            if details and is_search_page_title(details.get("title", "")):
                return {
                    "status": "invalid_url",
                    "message": "⛔ L'URL ou le titre de l'annonce indique une page de recherche plutôt qu'une annonce unique.",
                    "listing_id": None,
                    "title": None
                }
        except Exception as e:
            print(f"[API] Erreur scraping plein pour {url}: {e}")
            scraping_success = False

    if details.get("is_disappeared"):
        listing, is_new = await create_listing_from_details(db, details, source, url, status=ListingStatus.DISAPPEARED)
        return {
            "status": "created" if is_new else "updated",
            "listing_id": listing.id,
            "title": listing.title,
            "scraping_success": True
        }

    # ── Fallback: basic metadata if full scrape failed ───────────────────
    if not details or not details.get("title"):
        fb_details = await fetch_basic_metadata(url)
        if fb_details.get("is_invalid_search_page"):
            return {
                "status": "invalid_url",
                "message": "⛔ L'URL ou le titre de l'annonce indique une page de recherche plutôt qu'une annonce unique.",
                "listing_id": None,
                "title": None
            }
        details.update(fb_details)
        scraping_success = False

    city_to_check = details.get("city") or details.get("location")
    if city_to_check:
        from app.geo import standardize_and_enrich_city
        std_city, _, _ = standardize_and_enrich_city(city_to_check)
        if std_city:
            details["city"] = std_city
            details["location"] = std_city
            city_to_check = std_city

    if city_to_check and not _is_city_in_allowed_departments(city_to_check, db):
        return {
            "status": "rejected_department",
            "message": f"⛔ Cette annonce est hors des départements autorisés : {city_to_check}",
            "listing_id": None,
            "title": details.get("title")
        }

    # Create listing (includes duplicate check + photo download)
    listing, is_new = await create_listing_from_details(db, details, source, url, status=ListingStatus.ACTIVE)

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

    # ── Forbidden Zone Warning ──
    from app.geo import is_city_in_forbidden_set
    forbidden_cities = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
        ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
    ).all()}
    forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
        ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
    ).all()}
    
    city_to_check = listing.city or listing.location
    in_forbidden_city = city_to_check and is_city_in_forbidden_set(city_to_check, forbidden_cities)
    s1 = (listing.nearest_sncf_station or "").strip().lower()
    s2 = (listing.second_sncf_station or "").strip().lower()
    in_forbidden_station = bool(forbidden_stations and (
        any(fs in s1 or fs == s1 for fs in forbidden_stations) or
        any(fs in s2 or fs == s2 for fs in forbidden_stations)
    ))

    if (in_forbidden_city or in_forbidden_station) and not listing.to_visit:
        listing.status = ListingStatus.REJECTED
        db.commit()
        response["forbidden_zone_warning"] = {
            "message": f"⛔ Cette annonce a été rejetée car elle est en zone interdite.",
            "city": listing.city or listing.location,
        }

    return response


# ─── API: Keywords ────────────────────────────────────────────────────────────

@app.get("/api/keywords")
def get_keywords(db: Session = Depends(get_db), _auth = Depends(login_required)):
    """Get all review keywords."""
    keywords = db.query(models.ReviewKeyword).all()
    # Initial seed if empty
    if not keywords:
        default_keywords = [
            ("Aucun travaux à prévoir", "pros"), ("Grands volumes", "pros"), ("Piscine", "pros"),
            ("Climatisation", "pros"), ("Jardin sécurisable", "pros"), ("Lumineux", "pros"),
            ("Calme", "pros"), ("Bon état général", "pros"), ("Proche commodités", "pros"),
            ("Travaux à prévoir", "cons"), ("Jardin non sécurisé", "cons"), ("Pas de clim", "cons"),
            ("Bruyant", "cons"), ("Mauvaise isolation", "cons"), ("Vis-à-vis", "cons"), ("Éloigné des commodités", "cons")
        ]
        for text, type_ in default_keywords:
            kw = models.ReviewKeyword(text=text, keyword_type=type_)
            db.add(kw)
        db.commit()
        keywords = db.query(models.ReviewKeyword).all()
        
    return {
        "pros": [{"id": k.id, "text": k.text} for k in keywords if k.keyword_type == "pros"],
        "cons": [{"id": k.id, "text": k.text} for k in keywords if k.keyword_type == "cons"]
    }


@app.post("/api/listings/{listing_id}/split-or-purge")
async def split_or_purge_listing_endpoint(
    listing_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """
    Splits an aggregate search listing into individual listings or purges it cleanly.
    """
    from app.services import split_or_purge_aggregate_listing
    res = await split_or_purge_aggregate_listing(db, listing_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@app.post("/api/keywords")
def add_keyword(
    body: KeywordCreateRequest, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    """Add a new review keyword to the global pool."""
    kw = db.query(models.ReviewKeyword).filter(models.ReviewKeyword.text.ilike(body.text.strip())).first()
    if kw:
        # If it already exists, just return it
        return {"status": "exists", "id": kw.id, "text": kw.text, "keyword_type": kw.keyword_type}
        
    new_kw = models.ReviewKeyword(text=body.text.strip(), keyword_type=body.keyword_type)
    db.add(new_kw)
    db.commit()
    db.refresh(new_kw)
    return {"status": "created", "id": new_kw.id, "text": new_kw.text, "keyword_type": new_kw.keyword_type}


@app.delete("/api/keywords/{keyword_id}")
def delete_keyword(
    keyword_id: int, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    """Delete a review keyword from the global pool."""
    kw = db.query(models.ReviewKeyword).filter(models.ReviewKeyword.id == keyword_id).first()
    if not kw:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    db.delete(kw)
    db.commit()
    return {"status": "deleted", "id": keyword_id}


@app.delete("/api/listings/{listing_id}")
def delete_listing(
    request: Request,
    listing_id: int, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    """Delete a listing, its reviews, and its media files."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

    try:
        # Clear duplicate_of_id references pointing to this listing
        db.query(Listing).filter(Listing.duplicate_of_id == listing_id).update(
            {"duplicate_of_id": None, "is_duplicate": False}
        )

        # Delete user views
        db.query(UserListingView).filter(UserListingView.listing_id == listing_id).delete()

        db.delete(listing)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Delete] Error deleting listing {listing_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression : {e}")

    # Clean up media files on disk (best effort, don't fail if files are missing)
    import shutil, os
    media_dir = os.path.join("static", "media", str(listing_id))
    if os.path.isdir(media_dir):
        try:
            shutil.rmtree(media_dir)
        except Exception as e:
            print(f"[Delete] Warning: could not remove media dir {media_dir}: {e}")

    return {"status": "deleted", "listing_id": listing_id}


@app.delete("/api/listings/{listing_id}/photos/{photo_index}")
def delete_listing_photo(
    request: Request,
    listing_id: int,
    photo_index: int,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Delete a specific photo by its index."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
        
    photos = json_to_photos(listing.photos_local)
    if photo_index < 0 or photo_index >= len(photos):
        raise HTTPException(status_code=404, detail="Photo index out of range")
        
    photo_path = photos.pop(photo_index)
    
    # Try to delete the physical file
    try:
        full_path = os.path.join(os.getcwd(), photo_path.strip('/'))
        if os.path.exists(full_path):
            os.remove(full_path)
    except Exception as e:
        print(f"Failed to delete photo file {photo_path}: {e}")
        
    listing.photos_local = photos_to_json(photos)
    db.commit()
    
    return {"status": "deleted", "photo_index": photo_index}


@app.delete("/api/listings/{listing_id}/photos")
@app.post("/api/listings/{listing_id}/photos/bulk-delete")
def delete_listing_photos_batch(
    request: Request,
    listing_id: int,
    body: PhotoBatchDeleteRequest,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Delete multiple photos by their indices."""
    if not body.indices:
        raise HTTPException(status_code=400, detail="No photo indices provided")

    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    photos = json_to_photos(listing.photos_local)
    
    # Sort indices in descending order so popping from list does not disrupt lower indices
    unique_indices = sorted(set(body.indices), reverse=True)
    deleted_paths = []

    for idx in unique_indices:
        if 0 <= idx < len(photos):
            photo_path = photos.pop(idx)
            deleted_paths.append(photo_path)
            try:
                full_path = os.path.join(os.getcwd(), photo_path.strip('/'))
                if os.path.exists(full_path):
                    os.remove(full_path)
            except Exception as e:
                print(f"Failed to delete photo file {photo_path}: {e}")

    if not deleted_paths:
        raise HTTPException(status_code=404, detail="No matching photos found for provided indices")

    listing.photos_local = photos_to_json(photos)
    db.commit()

    return {
        "status": "deleted",
        "deleted_count": len(deleted_paths),
        "remaining_count": len(photos),
        "listing_id": listing_id
    }


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
    
    # Handle address update specifically
    if "address" in update_data:
        addr = update_data.pop("address")
        from app.services import update_listing_address
        update_listing_address(
            db=db,
            listing=listing,
            address=addr,
            city=update_data.pop("city", None),
            postal_code=update_data.pop("postal_code", None),
            precision=update_data.pop("address_precision", None),
            lat=update_data.pop("latitude", None),
            lon=update_data.pop("longitude", None)
        )
        update_data.pop("manual_address_override", None)
        update_data.pop("location", None)
    
    # Standardize city and location if either is being updated
    if ("city" in update_data and update_data["city"]) or ("location" in update_data and update_data["location"]):
        from app.geo import standardize_and_enrich_city
        src_val = update_data.get("city") or update_data.get("location") or listing.city or listing.location
        if src_val:
            std_city, _, _ = standardize_and_enrich_city(src_val)
            if std_city:
                update_data["city"] = std_city
                update_data["location"] = std_city
    
    # If location or city is changed without address, we need to re-geocode
    re_geocode = False
    if "location" in update_data and update_data["location"] != listing.location:
        re_geocode = True
    if "city" in update_data and update_data["city"] != listing.city:
        re_geocode = True

    for key, value in update_data.items():
        setattr(listing, key, value)
    
    listing.update_price_per_sqm()
    
    if re_geocode:
        loc = listing.location or listing.city
        if loc:
            from app.geo import get_coordinates, fetch_sncf_times_for_city
            coords = get_coordinates(loc)
            if coords:
                listing.latitude, listing.longitude = coords
                # Clear SNCF data so it gets re-fetched on next detail page load
                listing.nearest_sncf_station = None
                listing.walk_time_sncf = None
                listing.bike_time_sncf = None
                listing.car_time_sncf = None
                listing.second_sncf_station = None
                listing.walk_time_sncf_2 = None
                listing.bike_time_sncf_2 = None
                listing.car_time_sncf_2 = None
            else:
                listing.latitude, listing.longitude = None, None
        
    db.commit()
    db.refresh(listing)
    sync_listing_cluster(db, listing_id)
    return {"status": "updated", "listing_id": listing.id}


@app.post("/api/listings/{listing_id}/import")
def import_listing(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    listing.status = ListingStatus.ACTIVE
    db.commit()
    sync_listing_cluster(db, listing_id)
    return {"status": "imported", "listing_id": listing.id}


@app.post("/api/listings/{listing_id}/reject")
def reject_listing(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    listing.status = ListingStatus.REJECTED
    db.commit()
    sync_listing_cluster(db, listing_id)
    return {"status": "rejected", "listing_id": listing.id}


@app.patch("/api/listings/{listing_id}/favorite")
def toggle_favorite(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    
    listing.is_favorite = not listing.is_favorite
    if listing.is_favorite:
        listing.is_liked = True
        listing.is_disliked = False
    db.commit()
    sync_listing_cluster(db, listing_id)
    return {"status": "updated", "is_favorite": listing.is_favorite, "is_liked": listing.is_liked, "is_disliked": listing.is_disliked}


@app.patch("/api/listings/{listing_id}/like")
def toggle_like(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    
    listing.is_liked = not listing.is_liked
    if listing.is_liked:
        listing.is_disliked = False
    else:
        # If no longer liked, it cannot be a favorite
        listing.is_favorite = False
        
    db.commit()
    sync_listing_cluster(db, listing_id)
    return {"status": "updated", "is_favorite": listing.is_favorite, "is_liked": listing.is_liked, "is_disliked": listing.is_disliked}


@app.patch("/api/listings/{listing_id}/dislike")
def toggle_dislike(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    
    listing.is_disliked = not listing.is_disliked
    if listing.is_disliked:
        listing.is_liked = False
        listing.is_favorite = False
        
    db.commit()
    sync_listing_cluster(db, listing_id)
    return {"status": "updated", "is_favorite": listing.is_favorite, "is_liked": listing.is_liked, "is_disliked": listing.is_disliked}


@app.patch("/api/listings/{listing_id}/to-visit")
def toggle_to_visit(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    
    listing.to_visit = not listing.to_visit
    db.commit()
    return {"status": "updated", "to_visit": listing.to_visit, "listing_id": listing.id}


@app.patch("/api/listings/{listing_id}/contact-made")
def toggle_contact_made(request: Request, listing_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    
    listing.contact_made = not listing.contact_made
    db.commit()
    return {"status": "updated", "contact_made": listing.contact_made, "listing_id": listing.id}


VALID_VISIT_STATUSES = {
    "retour_agence",
    "visite_programmee",
    "deja_visitee",
    "sans_suite_acheteur",
    "sans_suite_visiteur",
    "sans_suite_vendeur",
    "a_relancer"
}


def _derive_visit_status_from_visit(visit: Visit) -> Optional[str]:
    """Helper to derive the listing visit status from a Visit entity."""
    if not visit:
        return None
    if visit.step_family == "cloture" or visit.visit_type == "reponse_negative" or visit.step in ("offre_refusee", "bien_vendu", "abandon"):
        if visit.step == "abandon":
            return "sans_suite_visiteur"
        return "sans_suite_acheteur"
    if visit.step_family == "contact" or visit.visit_type in ("contact_agence", "relance_agence", "contact_proprio"):
        if visit.step == "relance_sans_reponse" or visit.visit_type == "relance_agence":
            return "a_relancer"
        return "retour_agence"
    if visit.step_family == "reflexion" or visit.step in ("en_reflexion_sans_offre", "en_reflexion"):
        return "deja_visitee"
    if visit.step_family == "visite" or visit.visit_type in ("visite", "contre_visite"):
        if visit.status == "effectuee":
            return "deja_visitee"
        return "visite_programmee"
    return None


@app.patch("/api/listings/{listing_id}/visit-status")
def update_listing_visit_status(
    request: Request,
    listing_id: int,
    body: schemas.ListingVisitStatusUpdate,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    
    status_val = body.last_visit_status
    if status_val is not None and status_val != "" and status_val not in VALID_VISIT_STATUSES:
        raise HTTPException(status_code=400, detail="Statut de visite invalide")
    
    listing.last_visit_status = status_val if status_val else None
    
    # Adjust to_visit flag if relevant
    if status_val in {"visite_programmee", "retour_agence", "deja_visitee", "a_relancer"}:
        listing.to_visit = True
    elif status_val in {"sans_suite_acheteur", "sans_suite_visiteur", "sans_suite_vendeur"}:
        listing.to_visit = False

    db.commit()
    return {"status": "updated", "last_visit_status": listing.last_visit_status, "listing_id": listing.id}


@app.post("/api/visites", response_model=schemas.VisitResponse)
def create_visit(request: Request, body: schemas.VisitCreateRequest, db: Session = Depends(get_db), _auth = Depends(user_required)):
    listing = db.query(Listing).filter(Listing.id == body.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    
    step_family = body.step_family or "visite"
    step = body.step or "1ere_visite"
    visit_type = body.visit_type or "visite"
    
    if step_family == "cloture" or step in ("offre_refusee", "bien_vendu", "abandon"):
        visit_type = "reponse_negative"
        listing.to_visit = False
    elif step_family == "contact":
        if step == "relance_sans_reponse":
            visit_type = "relance_agence"
        else:
            visit_type = "contact_agence"
        listing.to_visit = True
    elif step_family == "reflexion" or step in ("en_reflexion_sans_offre", "en_reflexion"):
        visit_type = "visite"
        listing.to_visit = True
    elif step == "contre_visite":
        visit_type = "contre_visite"
        listing.to_visit = True
    else:
        listing.to_visit = True

    visitor_name = body.visitor or request.session.get("username") or "Utilisateur"

    visit = Visit(
        listing_id=body.listing_id,
        visit_type=visit_type,
        step_family=step_family,
        step=step,
        scheduled_at=body.scheduled_at,
        status=body.status or "programme",
        visitor=visitor_name,
        notes=body.notes
    )
    db.add(visit)
    
    derived = _derive_visit_status_from_visit(visit)
    if derived:
        listing.last_visit_status = derived

    db.commit()
    db.refresh(visit)

    # Attach contacts if specified
    if body.agent_ids:
        for aid in body.agent_ids:
            db.add(VisitContact(visit_id=visit.id, agent_id=aid))
        if listing and (body.update_listing_contact or (not listing.main_agent_id and not listing.agency_id)):
            listing.main_agent_id = body.agent_ids[0]
            ag = db.query(Agent).filter(Agent.id == body.agent_ids[0]).first()
            if ag and ag.agency_id:
                listing.agency_id = ag.agency_id
    if body.agency_ids:
        for agid in body.agency_ids:
            db.add(VisitContact(visit_id=visit.id, agency_id=agid))
        if listing and not body.agent_ids and (body.update_listing_contact or (not listing.main_agent_id and not listing.agency_id)):
            listing.agency_id = body.agency_ids[0]
    
    # Update listing address if specified during visit creation
    if body.listing_address and listing:
        from app.services import update_listing_address
        update_listing_address(
            db=db,
            listing=listing,
            address=body.listing_address,
            city=body.listing_city,
            postal_code=body.listing_postal_code,
            precision=body.listing_address_precision
        )

    if body.agent_ids or body.agency_ids or body.listing_address:
        db.commit()
        db.refresh(visit)

    # Sync to Google Calendar
    google_service.sync_visit_to_google_calendar(db, visit)
    return visit


@app.get("/api/visites")
def list_visites(
    request: Request,
    status: Optional[str] = None,
    visit_type: Optional[str] = None,
    step_family: Optional[str] = None,
    step: Optional[str] = None,
    listing_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    query = db.query(Visit)
    if status:
        query = query.filter(Visit.status == status)
    if visit_type:
        query = query.filter(Visit.visit_type == visit_type)
    if step_family:
        query = query.filter(Visit.step_family == step_family)
    if step:
        query = query.filter(Visit.step == step)
    if listing_id:
        query = query.filter(Visit.listing_id == listing_id)
    
    visits = query.order_by(Visit.scheduled_at.asc()).all()
    results = []
    for v in visits:
        l = db.query(Listing).filter(Listing.id == v.listing_id).first()
        contacts_list = []
        if v.visit_contacts:
            for vc in v.visit_contacts:
                c_item = {"agent_id": vc.agent_id, "agency_id": vc.agency_id}
                if vc.agent:
                    c_item["agent_name"] = f"{vc.agent.first_name} {vc.agent.last_name}"
                if vc.agency:
                    c_item["agency_name"] = vc.agency.commercial_name or vc.agency.legal_name
                contacts_list.append(c_item)

        results.append({
            "id": v.id,
            "listing_id": v.listing_id,
            "listing_title": l.title if l else "Non disponible",
            "listing_price": l.price if l else None,
            "listing_city": l.city or l.location if l else None,
            "listing_address": l.address if l else None,
            "listing_postal_code": l.postal_code if l else None,
            "listing_address_precision": l.address_precision if l else "city",
            "listing_url": l.url if l else None,
            "visit_type": v.visit_type,
            "step_family": v.step_family or "visite",
            "step": v.step or "1ere_visite",
            "scheduled_at": v.scheduled_at.isoformat() if v.scheduled_at else None,
            "status": v.status,
            "visitor": v.visitor,
            "notes": v.notes,
            "google_event_id": v.google_event_id,
            "contacts": contacts_list,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        })
    return results


@app.put("/api/visites/{visit_id}", response_model=schemas.VisitResponse)
def update_visit(request: Request, visit_id: int, body: schemas.VisitUpdateRequest, db: Session = Depends(get_db), _auth = Depends(user_required)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visite non trouvée")
    
    if body.step_family is not None:
        visit.step_family = body.step_family
    if body.step is not None:
        visit.step = body.step
    if body.visit_type is not None:
        visit.visit_type = body.visit_type

    listing = db.query(Listing).filter(Listing.id == visit.listing_id).first()
    if listing:
        if (visit.step_family == "cloture") or (visit.step in ("offre_refusee", "bien_vendu", "abandon")) or (visit.visit_type == "reponse_negative"):
            listing.to_visit = False
        else:
            listing.to_visit = True
        derived = _derive_visit_status_from_visit(visit)
        if derived:
            listing.last_visit_status = derived

    if body.scheduled_at is not None:
        visit.scheduled_at = body.scheduled_at
    if body.status is not None:
        visit.status = body.status
    if body.visitor is not None:
        visit.visitor = body.visitor
    if body.notes is not None:
        visit.notes = body.notes

    if body.agent_ids is not None or body.agency_ids is not None:
        # Clear existing contacts
        db.query(VisitContact).filter(VisitContact.visit_id == visit.id).delete()
        if body.agent_ids:
            for aid in body.agent_ids:
                db.add(VisitContact(visit_id=visit.id, agent_id=aid))
            if listing and (body.update_listing_contact or (not listing.main_agent_id and not listing.agency_id)):
                listing.main_agent_id = body.agent_ids[0]
                ag = db.query(Agent).filter(Agent.id == body.agent_ids[0]).first()
                if ag and ag.agency_id:
                    listing.agency_id = ag.agency_id
        if body.agency_ids:
            for agid in body.agency_ids:
                db.add(VisitContact(visit_id=visit.id, agency_id=agid))
            if listing and not body.agent_ids and (body.update_listing_contact or (not listing.main_agent_id and not listing.agency_id)):
                listing.agency_id = body.agency_ids[0]

    # Update listing address if provided in visit update
    if body.listing_address is not None and listing:
        from app.services import update_listing_address
        update_listing_address(
            db=db,
            listing=listing,
            address=body.listing_address,
            city=body.listing_city,
            postal_code=body.listing_postal_code,
            precision=body.listing_address_precision
        )

    db.commit()
    db.refresh(visit)

    # Sync update to Google Calendar
    google_service.sync_visit_to_google_calendar(db, visit)
    return visit


@app.delete("/api/visites/{visit_id}")
def delete_visit(request: Request, visit_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visite non trouvée")
    
    if visit.google_event_id:
        google_service.delete_google_calendar_event(db, visit.google_event_id)

    db.delete(visit)
    db.commit()
    return {"status": "deleted", "visit_id": visit_id}


@app.patch("/api/visites/{visit_id}/status")
def change_visit_status(request: Request, visit_id: int, status: str = Form(...), db: Session = Depends(get_db), _auth = Depends(user_required)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visite non trouvée")
    
    visit.status = status
    db.commit()

    # Sync status change to Google Calendar
    google_service.sync_visit_to_google_calendar(db, visit)
    return {"status": "updated", "visit_id": visit.id, "new_status": visit.status}




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


# ─── API: Listing Attachments ──────────────────────────────────────────────────

@app.get("/api/listings/{listing_id}/attachments", response_model=list[schemas.ListingAttachmentResponse])
def get_listing_attachments(
    request: Request,
    listing_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Retrieve all attachments for a specific listing."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    
    attachments = db.query(ListingAttachment).filter(
        ListingAttachment.listing_id == listing_id
    ).order_by(ListingAttachment.created_at.desc()).all()
    return attachments


@app.post("/api/listings/{listing_id}/attachments", response_model=list[schemas.ListingAttachmentResponse])
async def upload_listing_attachments(
    request: Request,
    listing_id: int,
    files: list[UploadFile] = File(...),
    title: Optional[str] = Form(None),
    file_type: Optional[str] = Form("autre"),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Upload one or more attachments for a listing."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    from app.media import save_listing_attachment_file
    current_username = request.session.get("username")

    created_attachments = []
    for i, file in enumerate(files):
        custom_title = title
        if len(files) > 1 and title:
            custom_title = f"{title} ({i+1})"
        
        saved_filename, orig_name, web_path, file_size, mime_type = await save_listing_attachment_file(listing_id, file)
        
        if not custom_title:
            custom_title = os.path.splitext(orig_name)[0].replace("_", " ").replace("-", " ")

        att = ListingAttachment(
            listing_id=listing_id,
            filename=saved_filename,
            original_filename=orig_name,
            file_path=web_path,
            file_type=file_type or "autre",
            title=custom_title,
            description=description,
            file_size=file_size,
            mime_type=mime_type,
            created_by=current_username
        )
        db.add(att)
        created_attachments.append(att)

    db.commit()
    for att in created_attachments:
        db.refresh(att)

    return created_attachments


@app.put("/api/listings/{listing_id}/attachments/{attachment_id}", response_model=schemas.ListingAttachmentResponse)
def update_listing_attachment(
    request: Request,
    listing_id: int,
    attachment_id: int,
    body: schemas.ListingAttachmentUpdateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Update metadata (title, category, description) of a listing attachment."""
    att = db.query(ListingAttachment).filter(
        ListingAttachment.id == attachment_id,
        ListingAttachment.listing_id == listing_id
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="Pièce jointe introuvable")

    if body.title is not None:
        att.title = body.title.strip() if body.title.strip() else att.original_filename
    if body.file_type is not None:
        att.file_type = body.file_type.strip().lower()
    if body.description is not None:
        att.description = body.description.strip()

    db.commit()
    db.refresh(att)
    return att


@app.delete("/api/listings/{listing_id}/attachments/{attachment_id}")
def delete_listing_attachment(
    request: Request,
    listing_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Delete a listing attachment and its physical file on disk."""
    att = db.query(ListingAttachment).filter(
        ListingAttachment.id == attachment_id,
        ListingAttachment.listing_id == listing_id
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="Pièce jointe introuvable")

    from app.media import delete_attachment_file
    delete_attachment_file(att.file_path)

    db.delete(att)
    db.commit()
    return {"status": "deleted", "attachment_id": attachment_id, "listing_id": listing_id}


@app.post("/api/listings/{listing_id}/attachments/bulk-delete")
def bulk_delete_listing_attachments(
    request: Request,
    listing_id: int,
    body: schemas.BulkDeleteAttachmentsRequest,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Delete multiple listing attachments and their physical files on disk."""
    if not body.attachment_ids:
        raise HTTPException(status_code=400, detail="Aucun identifiant de pièce jointe fourni")

    atts = db.query(ListingAttachment).filter(
        ListingAttachment.id.in_(body.attachment_ids),
        ListingAttachment.listing_id == listing_id
    ).all()

    if not atts:
        raise HTTPException(status_code=404, detail="Aucune pièce jointe trouvée")

    from app.media import delete_attachment_file
    deleted_ids = []
    for att in atts:
        delete_attachment_file(att.file_path)
        db.delete(att)
        deleted_ids.append(att.id)

    db.commit()
    return {"status": "deleted", "deleted_ids": deleted_ids, "count": len(deleted_ids), "listing_id": listing_id}


@app.get("/api/listings/{listing_id}/attachments/{attachment_id}/download")
def download_listing_attachment(
    request: Request,
    listing_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Download an attachment with its original filename and proper headers."""
    att = db.query(ListingAttachment).filter(
        ListingAttachment.id == attachment_id,
        ListingAttachment.listing_id == listing_id
    ).first()
    if not att:
        raise HTTPException(status_code=404, detail="Pièce jointe introuvable")

    file_path = att.file_path.strip().lstrip("/\\")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier physique introuvable sur le serveur")

    return FileResponse(
        path=file_path,
        filename=att.original_filename or os.path.basename(file_path),
        media_type=att.mime_type or "application/octet-stream"
    )


# ─── API: Useful Links (Liens utiles) ─────────────────────────────────────────

def _deduce_link_metadata(raw_url: str, custom_title: Optional[str] = None, custom_category: Optional[str] = None):
    """Clean URL and deduce a user-friendly title and category from hostname if not provided."""
    clean_url = raw_url.strip()
    if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
        clean_url = "https://" + clean_url

    parsed = urllib.parse.urlparse(clean_url)
    hostname = (parsed.hostname or "").lower()

    # Deduce title
    if custom_title and custom_title.strip():
        title = custom_title.strip()
    else:
        if "haven-score" in hostname:
            title = "Haven Score"
        elif "clairbien" in hostname:
            title = "Rapport Clairbien"
        elif "terva" in hostname:
            title = "Analyse Terva"
        elif "valeurici" in hostname:
            title = "ValeurIci (Estimation)"
        elif "georisques" in hostname:
            title = "Géorisques"
        elif "cadastre.gouv" in hostname:
            title = "Cadastre"
        elif "explore.data.gouv" in hostname or "data.gouv" in hostname:
            title = "Data.gouv.fr (DVF)"
        elif "meilleursagents" in hostname:
            title = "Meilleurs Agents"
        elif "castorus" in hostname:
            title = "Castorus"
        elif "wikipedia" in hostname:
            title = "Wikipédia"
        elif "leboncoin" in hostname:
            title = "LeBonCoin"
        elif "seloger" in hostname:
            title = "SeLoger"
        elif "bienici" in hostname:
            title = "Bien'ici"
        elif "figaro" in hostname:
            title = "Figaro Immobilier"
        elif "notaires" in hostname:
            title = "Notaires de France"
        elif hostname:
            parts = hostname.split(".")
            if len(parts) >= 2 and parts[-2] not in ["gouv", "co", "asso", "org", "net", "com"]:
                title = parts[-2].capitalize()
            else:
                title = hostname
        else:
            title = "Lien externe"

    # Deduce category
    category = custom_category or "rapport"
    if category == "rapport":
        if any(k in hostname for k in ["haven-score", "clairbien", "terva", "georisques"]):
            category = "rapport"
        elif any(k in hostname for k in ["data.gouv", "dvf", "meilleursagents", "castorus", "valeurici"]):
            category = "marche"
        elif any(k in hostname for k in ["cadastre", "urbanisme", "plu"]):
            category = "cadastre"
        elif any(k in hostname for k in ["wikipedia", "ville-", "mairie-", "commune", "sncf"]):
            category = "ville"

    return clean_url, title, category


@app.get("/api/listings/{listing_id}/links", response_model=list[schemas.ListingLinkResponse])
def get_listing_links(
    request: Request,
    listing_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """Retrieve all useful links for a listing."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))
    return db.query(ListingLink).filter(ListingLink.listing_id == listing_id).order_by(ListingLink.created_at.asc()).all()


@app.post("/api/listings/{listing_id}/links", response_model=list[schemas.ListingLinkResponse])
def create_listing_links(
    request: Request,
    listing_id: int,
    body: schemas.ListingLinkCreateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Create one or more useful links for a listing (supports pasting multiple URLs)."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

    username = request.session.get("username")
    raw_input = (body.url or "").strip()
    if not raw_input:
        raise HTTPException(status_code=400, detail="URL requise")

    # Split on whitespace/newlines to support bulk pasting multiple URLs
    tokens = [t.strip() for t in re.split(r'[\r\n\s]+', raw_input) if t.strip()]
    if not tokens:
        tokens = [raw_input]

    created = []
    is_multi = len(tokens) > 1

    for tok in tokens:
        # Ignore non-url-like tokens if multi
        if is_multi and not ("." in tok or "http" in tok):
            continue
        
        # If user gave a single custom title and single URL, use that title; otherwise deduce per URL
        custom_t = body.title if (not is_multi and body.title) else None
        clean_url, title, cat = _deduce_link_metadata(tok, custom_title=custom_t, custom_category=body.category)
        
        link = ListingLink(
            listing_id=listing_id,
            url=clean_url,
            title=title,
            category=cat,
            description=body.description.strip() if (body.description and not is_multi) else None,
            created_by=username
        )
        db.add(link)
        created.append(link)

    db.commit()
    for l in created:
        db.refresh(l)

    return created


@app.put("/api/listings/{listing_id}/links/{link_id}", response_model=schemas.ListingLinkResponse)
def update_listing_link(
    request: Request,
    listing_id: int,
    link_id: int,
    body: schemas.ListingLinkUpdateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Update metadata for an existing useful link."""
    link = db.query(ListingLink).filter(
        ListingLink.id == link_id,
        ListingLink.listing_id == listing_id
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Lien introuvable")

    if body.url is not None and body.url.strip():
        clean_url, title, cat = _deduce_link_metadata(body.url, custom_title=body.title, custom_category=body.category)
        link.url = clean_url
        if body.title is not None:
            link.title = body.title.strip() if body.title.strip() else title
        if body.category is not None:
            link.category = body.category
    else:
        if body.title is not None:
            link.title = body.title.strip() or link.title
        if body.category is not None:
            link.category = body.category

    if body.description is not None:
        link.description = body.description.strip() if body.description.strip() else None

    db.commit()
    db.refresh(link)
    return link


@app.delete("/api/listings/{listing_id}/links/{link_id}")
def delete_listing_link(
    request: Request,
    listing_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(user_required)
):
    """Delete a useful link from a listing."""
    link = db.query(ListingLink).filter(
        ListingLink.id == link_id,
        ListingLink.listing_id == listing_id
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Lien introuvable")

    db.delete(link)
    db.commit()
    return {"status": "deleted", "link_id": link_id, "listing_id": listing_id}


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
    _auth = Depends(user_required)
):
    """Create or update a review for a listing. One review per (listing, reviewer).
    The reviewer is always the currently logged-in user — cannot post on behalf of another."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail=get_text(request, "api.listing_not_found"))

    # Force reviewer = current user's username (prevents impersonation)
    reviewer = request.session.get("username")
    if not reviewer:
        raise HTTPException(status_code=401, detail="Not authenticated")

    review, is_new = get_or_create_review(
        db=db,
        listing_id=listing_id,
        reviewer=reviewer.lower(),
        pros=body.pros,
        cons=body.cons,
        rating=body.rating,
        visit_done=body.visit_done,
        notes=body.notes,
    )
    sync_listing_cluster(db, listing_id)

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
    _auth = Depends(user_required)
):
    """Update a specific review by ID. A user can only update their own review."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail=get_text(request, "api.review_not_found"))

    # Verify ownership
    current_username = request.session.get("username", "").lower()
    if review.reviewer != current_username:
        raise HTTPException(status_code=403, detail="You can only edit your own reviews")

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
    sync_listing_cluster(db, review.listing_id)
    return {"status": "updated", "review_id": review.id}


@app.delete("/api/reviews/{review_id}")
def delete_review(request: Request, review_id: int, db: Session = Depends(get_db), _auth = Depends(user_required)):
    """Delete a review. A user can only delete their own review."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail=get_text(request, "api.review_not_found"))

    # Verify ownership
    current_username = request.session.get("username", "").lower()
    if review.reviewer != current_username:
        raise HTTPException(status_code=403, detail="You can only delete your own reviews")

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


# ─── API: Force Scraping ───────────────────────────────────────────────────────

@app.post("/api/searches/force")
def force_scraping(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    """
    Manually triggers a full scraping cycle immediately,
    running it in a background thread so the response returns instantly.
    """
    from app.scheduler import scraping_job
    background_tasks.add_task(scraping_job)
    return {"status": "started", "message": "Scraping forcé lancé en arrière-plan."}
@app.get("/api/geo/stations/search")
def api_search_stations(
    q: str,
    _auth = Depends(login_required)
):
    from app.geo import search_stations
    return search_stations(q)


@app.get("/api/geo/cities/search")
def api_search_cities(
    q: str,
    _auth = Depends(login_required)
):
    from app.geo import search_cities
    return search_cities(q)


@app.get("/api/geo/train-path")
def api_get_train_path(
    lat1: float, lon1: float, lat2: float, lon2: float,
    _auth = Depends(login_required)
):
    from app.geo import get_railway_path
    return get_railway_path(lat1, lon1, lat2, lon2)


@app.post("/api/geo/train-lines")
def create_train_line(
    request: Request,
    body: TrainLineCreateRequest,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    username = request.session.get("username")
    line = models.TrainLine(
        departure_station=body.departure_station,
        arrival_station=body.arrival_station,
        path_json=json.dumps(body.path),
        color=body.color,
        created_by=username
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


@app.get("/api/geo/train-lines")
def list_train_lines(
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    return db.query(models.TrainLine).all()


@app.delete("/api/geo/train-lines/{line_id}")
def delete_train_line(
    line_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(login_required)
):
    line = db.query(models.TrainLine).filter(models.TrainLine.id == line_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Train line not found")
    db.delete(line)
    db.commit()
    return {"status": "deleted"}
