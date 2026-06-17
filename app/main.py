"""
FastAPI application main entry point.
Defines all routes: HTML pages + REST API.
"""
import json
import os
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
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app import models, database
from app.database import engine, get_db, run_migrations
from app.models import Listing, ListingStatus, Review, Source, SearchQuery, ReadySearch, MapPin, UserListingView, ZoneRule, RejectedDuplicate, AIProfile
from app.services import (
    scrape_and_diff,
    create_listing_from_details,
    get_or_create_review,
    fetch_basic_metadata,
    generate_ideal_profile,
    find_potential_duplicates,
)
from app.geo import fetch_sncf_times_for_city, find_nearby_stations, calculate_station_times, get_coordinates, get_postal_code
from app.media import json_to_photos, photos_to_json
from app.config import settings
from app.translations import get_text
from app.assistant import run_assistant_step
from app import db_maintenance

# Run migrations FIRST (adds missing columns to existing tables)
run_migrations()
# Then create any brand-new tables (e.g. reviews)
models.Base.metadata.create_all(bind=engine)

# Create static media directory
os.makedirs("static/media", exist_ok=True)
os.makedirs("templates", exist_ok=True)


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


app = FastAPI(title="Immo-Boussole", lifespan=lifespan)

class SecureHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecureHeadersMiddleware)

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

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        import re
        if not re.match(r'^\d{5}$', v.strip()):
            raise ValueError("Le nom doit être un code postal complet (5 chiffres)")
        return v.strip()

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
        OrpiScraper
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
    if is_authenticated(request):
        return RedirectResponse(url="/")
    csrf_token = generate_csrf_token(request)
    return templates.TemplateResponse(request=request, name="login.html", context={"csrf_token": csrf_token})


@app.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request, 
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    if not check_rate_limit(request):
        return templates.TemplateResponse(request=request, name="login.html", context={
            "error": "Trop de tentatives de connexion. Veuillez réessayer plus tard.",
            "csrf_token": generate_csrf_token(request)
        }, status_code=429)

    user = db.query(models.User).filter(models.User.username == username).first()
    if user:
        pwd_hash_600k = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), user.salt, 600000)
        pwd_hash_100k = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), user.salt, 100000)
        
        if user.password_hash in (pwd_hash_600k, pwd_hash_100k):
            request.session["authenticated"] = True
            request.session["username"] = username
            request.session["role"] = user.role
            return RedirectResponse(url="/", status_code=303)
            
    record_failed_login(request)
    return templates.TemplateResponse(request=request, name="login.html", context={
        "error": get_text(request, "api.invalid_credentials"),
        "csrf_token": generate_csrf_token(request)
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
        "title": "Gestion des Utilisateurs — Immo-Boussole",
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
        "title": "Administration — Immo-Boussole",
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
    
    db.commit()

    # Sync scheduler jobs
    if app_scheduler:
        from app.scheduler import sync_db_maintenance_jobs
        sync_db_maintenance_jobs(app_scheduler)

    return {"status": "updated"}


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
                    shutil.copy2(backup_env, target_env)

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
            listing.user_status = listing.status.value


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
        
    # Lazy geocoding backfill
    if listing.city and listing.nearest_sncf_station is None:
        from app.models import ZoneRule
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
    all_zone_rules = db.query(ZoneRule).all()
    city_rules = {r.name.strip().lower(): r.rule for r in all_zone_rules if r.zone_type == "city"}
    station_rules = {r.name.strip().lower(): r.rule for r in all_zone_rules if r.zone_type == "station"}

    listing_city_lower = (listing.city or "").strip().lower()
    listing_location_lower = (listing.location or "").strip().lower()
    
    city_rule = city_rules.get(listing_city_lower)
    if not city_rule:
        for name, rule in city_rules.items():
            if name and name in listing_location_lower:
                city_rule = rule
                break

    station1_rule = station_rules.get((listing.nearest_sncf_station or "").strip().lower())
    station2_rule = station_rules.get((listing.second_sncf_station or "").strip().lower())

    return templates.TemplateResponse(request=request, name="listing_detail.html", context={
        "listing": listing,
        "photos": photos,
        "reviews": reviews,
        "reviews_by_reviewer": reviews_by_reviewer,
        "duplicate_original": duplicate_original,
        "duplicate_children": duplicate_children,
        "queries": queries,
        "listings": all_listings,
        "georisques": json.loads(listing.georisques_json) if listing.georisques_json else None,
        "title": f"{listing.title} — Immo-Boussole",
        "city_rule": city_rule,
        "station1_rule": station1_rule,
        "station2_rule": station2_rule,
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
    listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(listings, viewed_ids)
    
    return templates.TemplateResponse(request=request, name="ready_searches.html", context={
        "ready_searches": ready_searches,
        "queries": queries,
        "listings": listings,
        "title": "Prêt à Rechercher — Immo-Boussole",
    })


@app.get("/searches/auto")
def auto_searches_page(
    request: Request, 
    db: Session = Depends(get_db), 
    _auth = Depends(login_required)
):
    # Fetch NEW listings that come from a ReadySearch (automatic results)
    new_listings = db.query(Listing).filter(
        Listing.status == ListingStatus.NEW,
        Listing.source_ready_search_id.isnot(None)
    ).order_by(Listing.date_added.desc()).all()
    queries = db.query(SearchQuery).all()
    all_listings = db.query(Listing).order_by(Listing.date_added.desc()).limit(100).all()
    viewed_ids = _get_viewed_listing_ids(request, db)
    _enrich_listings(new_listings + all_listings, viewed_ids)

    # Build a lookup map of ReadySearch by ID for fast access
    ready_search_map = {rs.id: rs for rs in db.query(ReadySearch).all()}

    # Get the latest sync time from active queries
    latest_query = db.query(SearchQuery).filter(SearchQuery.active == 1).order_by(SearchQuery.last_run.desc()).first()
    last_sync = latest_query.last_run if latest_query else None

    for listing in new_listings:
        listing._photos = json_to_photos(listing.photos_local)

        # Resolve platform and criteria — first 2 columns in auto_searches view
        if listing.source_ready_search_id and listing.source_ready_search_id in ready_search_map:
            rs = ready_search_map[listing.source_ready_search_id]
            listing._platform = rs.platform.upper()
            listing._criteria = rs.criteria or "-"
        else:
            # Fallback for listings created before this feature, or via other paths
            listing._platform = listing.source.value.upper() if listing.source else "-"
            listing._criteria = listing.source_criteria or "-"

    # Group listings by date_added.date()
    from itertools import groupby
    grouped = []
    for k, g in groupby(new_listings, key=lambda x: x.date_added.date() if x.date_added else None):
        grouped.append((k, list(g)))

    return templates.TemplateResponse(request=request, name="auto_searches.html", context={
        "grouped_listings": grouped,
        "queries": queries,
        "listings": all_listings,
        "scraping_schedule": get_text(request, "auto_searches.auto_refresh_value"),
        "last_sync": last_sync,
        "title": "Recherches Automatiques",
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
        "title": "Mon Profil — Immo-Boussole",
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
        "title": "Gestion des Zones — Immo-Boussole",
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
        "title": "Chasse aux duplicats — Immo-Boussole",
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
        
    if not city:
        return True
        
    import re
    match = re.search(r'\((\d{5})\)', city)
    if not match:
        return True
        
    zipcode = match.group(1)
    if zipcode.startswith('97') and len(zipcode) >= 3:
        dept = zipcode[:3]
    else:
        dept = zipcode[:2]
        
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
        "title": "Carte des Biens — Immo-Boussole",
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
        "title": "Assistant IA — Immo-Boussole",
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


@app.get("/api/listings")
def get_listings(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    _auth = Depends(login_required)
):
    """Get all listings with optional filters and search."""
    query = db.query(Listing)
    if status:
        query = query.filter(Listing.status == status)
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
    user = db.query(models.User).filter(models.User.username == username).first()
    
    pois = []
    if user.poi_json:
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
    zone_rules = db.query(ZoneRule).all()
    existing_city_rules = {r.name.lower().strip() for r in zone_rules if r.zone_type == 'city'}
    
    active_cities_raw = db.query(Listing.city).filter(
        Listing.status.in_([ListingStatus.NEW, ListingStatus.ACTIVE]),
        Listing.city != None,
        Listing.city != ""
    ).distinct().all()
    
    to_qualify_cities = []
    for c in active_cities_raw:
        city_name = c[0].strip()
        if city_name.lower().strip() not in existing_city_rules:
            to_qualify_cities.append(city_name)

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
                "photos": json_to_photos(l.photos_local)
            }
            for l in listings
        ],
        "user": {
            "work": {
                "address": user.work_address,
                "lat": user.work_lat,
                "lon": user.work_lon
            } if user.work_address and user.work_lat else None,
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
    from app.geo import GEO_CACHE, find_nearby_stations, calculate_station_times, haversine_km

    from app.geo import standardize_and_enrich_city
    std_city, _, _ = standardize_and_enrich_city(city)
    city_key = std_city if std_city else city.strip()
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
                res_boundary = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "city": city_key,
                        "country": "France",
                        "featuretype": "city",
                        "format": "json",
                        "limit": 1,
                        "extratags": 1,
                        "addressdetails": 0,
                    },
                    headers=headers,
                    timeout=10.0,
                )
                res_boundary.raise_for_status()
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
                            "q": city_key,
                            "format": "json",
                            "limit": 1,
                            "extratags": 1,
                            "addressdetails": 0,
                            "countrycodes": "fr",
                        },
                        headers=headers,
                        timeout=10.0,
                    )
                    res_generic.raise_for_status()
                    generic_data = res_generic.json()
                    if generic_data:
                        place = generic_data[0]
                        lat = float(place["lat"])
                        lon = float(place["lon"])
                        # Try area from fallback too
                        if area_km2 is None:
                            extratags = place.get("extratags") or {}
                            area_m2 = extratags.get("area")
                            if area_m2:
                                try:
                                    area_km2 = round(float(area_m2) / 1_000_000, 1)
                                except Exception:
                                    area_km2 = None

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
    listings = db.query(Listing).filter(
        (Listing.city.ilike(city_key)) | (Listing.location.ilike(f"%{city_key}%"))
    ).order_by(Listing.date_added.desc()).all()

    # Query active zone rule for this city (NOT cached)
    zone_rule = db.query(ZoneRule).filter(
        ZoneRule.zone_type == "city",
        ZoneRule.name.ilike(city_key)
    ).first()

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

    # ── Scrape ──
    details = {}
    scraping_success = True
    if scraper:
        try:
            details = await scraper.get_listing_details(url)
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
            "scraping_success": True
        }

    if not details or not details.get("title"):
        details = await fetch_basic_metadata(url)
        scraping_success = False

    # ── Update via service ──
    updated_listing, _ = await create_listing_from_details(db, details, source, url)

    rescrape_response = {
        "status": "updated",
        "listing_id": updated_listing.id,
        "title": updated_listing.title,
        "scraping_success": scraping_success
    }

    # ── Forbidden Zone Warning ──
    from app.geo import is_city_in_forbidden_set
    forbidden_cities_rescrape = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
        ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
    ).all()}
    
    city_to_check = updated_listing.city or updated_listing.location
    in_forbidden_city = city_to_check and is_city_in_forbidden_set(city_to_check, forbidden_cities_rescrape)

    if in_forbidden_city:
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
        
        city_to_check = details.get("city") or details.get("location")
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
            
        if in_forbidden_city:
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
        details.update(fb_details)
        scraping_success = False

    city_to_check = details.get("city") or details.get("location")
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
    
    city_to_check = listing.city or listing.location
    in_forbidden_city = city_to_check and is_city_in_forbidden_set(city_to_check, forbidden_cities)

    if in_forbidden_city:
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
    
    # Standardize city and location if either is being updated
    if ("city" in update_data and update_data["city"]) or ("location" in update_data and update_data["location"]):
        from app.geo import standardize_and_enrich_city
        src_val = update_data.get("city") or update_data.get("location") or listing.city or listing.location
        if src_val:
            std_city, _, _ = standardize_and_enrich_city(src_val)
            if std_city:
                update_data["city"] = std_city
                update_data["location"] = std_city
    
    # If location or city is changed, we need to re-geocode
    re_geocode = False
    if "location" in update_data and update_data["location"] != listing.location:
        re_geocode = True
    if "city" in update_data and update_data["city"] != listing.city:
        re_geocode = True

    for key, value in update_data.items():
        setattr(listing, key, value)
    
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
