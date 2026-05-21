# pyrefly: ignore [missing-import]
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, Text, ForeignKey, Boolean, LargeBinary
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import relationship
# pyrefly: ignore [missing-import]
from sqlalchemy.sql import func
import enum
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(LargeBinary, nullable=False)
    salt = Column(LargeBinary, nullable=False)
    role = Column(String(20), nullable=False, default="user") # "admin" or "user"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Contact & Identifiers
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    sfr_identifier = Column(String, nullable=True)
    sfr_password = Column(String, nullable=True)

    # User Addresses & POIs
    work_address = Column(String, nullable=True)
    work_lat = Column(Float, nullable=True)
    work_lon = Column(Float, nullable=True)
    poi_json = Column(Text, nullable=True)  # JSON-encoded list of dicts: [{"name": "...", "address": "...", "lat": ..., "lon": ...}]

    # Notifications
    apprise_url = Column(String, nullable=True)  # Apprise-compatible URL (tgram://, discord://, ntfy://, mailto://, etc.)


class ListingStatus(str, enum.Enum):
    NEW = "nouvelle"
    ACTIVE = "active"
    DISAPPEARED = "disparue"
    REJECTED = "rejetee"


class Source(str, enum.Enum):
    LEBONCOIN = "leboncoin"
    SELOGER = "seloger"
    LEFIGARO = "lefigaro"
    LOGICIMMO = "logicimmo"
    BIENICI = "bienici"
    IADFRANCE = "iadfrance"
    NOTAIRES = "notaires"
    VINCI = "vinci"
    IMMOBILIER_FRANCE = "immobilier_france"
    ORPI = "orpi"
    MANUAL = "manuel"


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, unique=True, index=True, nullable=True)  # ID on the website (nullable for manual)
    title = Column(String, index=True)
    url = Column(String, unique=True, nullable=False)
    original_url = Column(String, nullable=True)  # Canonical source URL (for duplicate detection)

    # Pricing
    price = Column(Float, nullable=True)
    price_per_sqm = Column(Float, nullable=True)  # Prix au m²

    # Location & physical
    location = Column(String, nullable=True)
    city = Column(String, nullable=True)           # Normalized city for duplicate detection
    area = Column(Float, nullable=True)            # Surface habitable en m²
    land_area = Column(Float, nullable=True)       # Surface terrain en m²
    rooms = Column(Integer, nullable=True)           # Nombre de pièces
    bedrooms = Column(Integer, nullable=True)
    bathroom_count = Column(Integer, nullable=True)  # Nombre de salles de bain
    toilet_count = Column(Integer, nullable=True)    # Nombre de WC séparés
    floor = Column(Integer, nullable=True)
    total_floors = Column(Integer, nullable=True)
    building_year = Column(Integer, nullable=True)

    # Property characteristics
    property_type = Column(String, nullable=True)    # maison, appartement, terrain, etc.
    condition = Column(String, nullable=True)         # bon état, à rénover, neuf, etc.
    heating_type = Column(String, nullable=True)      # gaz, électrique, PAC, fioul, etc.
    heating_mode = Column(String, nullable=True)      # individuel, collectif
    kitchen_type = Column(String, nullable=True)      # américaine, séparée, équipée, etc.
    orientation = Column(String, nullable=True)       # Sud, Nord-Ouest, etc.
    view = Column(String, nullable=True)              # dégagée, mer, jardin, etc.

    # Outdoor & amenities (stored as 0/1)
    cellar = Column(Boolean, nullable=True)           # Cave
    parking_count = Column(Integer, nullable=True)    # Places de parking/garage
    balcony = Column(Boolean, nullable=True)          # Balcon
    balcony_area = Column(Float, nullable=True)       # Surface balcon m²
    terrace = Column(Boolean, nullable=True)          # Terrasse
    terrace_area = Column(Float, nullable=True)       # Surface terrasse m²
    garden = Column(Boolean, nullable=True)           # Jardin
    garden_area = Column(Float, nullable=True)        # Surface jardin m²
    pool = Column(Boolean, nullable=True)             # Piscine
    elevator = Column(Boolean, nullable=True)         # Ascenseur
    interphone = Column(Boolean, nullable=True)       # Interphone/digicode
    guardian = Column(Boolean, nullable=True)         # Gardien
    furnished = Column(Boolean, nullable=True)        # Meublé

    # Energy ratings
    dpe_rating = Column(String(1), nullable=True)    # A, B, C, D, E, F, G
    ges_rating = Column(String(1), nullable=True)    # A, B, C, D, E, F, G
    dpe_value = Column(Float, nullable=True)          # kWh/m²/an
    ges_value = Column(Float, nullable=True)          # kgCO₂/m²/an

    # Costs
    land_tax = Column(Float, nullable=True)           # Taxe foncière annuelle
    charges = Column(Float, nullable=True)            # Charges copropriété mensuelles
    agency_fee = Column(Float, nullable=True)

    # Copropriété
    copropriete_lots = Column(Integer, nullable=True) # Nombre de lots
    procedure_syndic = Column(Boolean, nullable=True) # Procédure syndicale en cours
    honoraires_a_charge = Column(String, nullable=True)  # Acquéreur ou vendeur

    # Media supplémentaires
    virtual_tour_url = Column(String, nullable=True)  # URL visite virtuelle 3D

    # Description
    description_text = Column(Text, nullable=True)

    # Media (stored as JSON strings)
    photos_local = Column(Text, nullable=True)      # JSON list of local file paths
    original_photo_urls = Column(Text, nullable=True)  # JSON list of original URLs

    # Metadata
    source = Column(Enum(Source), nullable=False, default=Source.MANUAL)
    status = Column(Enum(ListingStatus), default=ListingStatus.NEW, nullable=False)
    is_favorite = Column(Boolean, default=False)
    is_liked = Column(Boolean, default=False)
    is_disliked = Column(Boolean, default=False)
    scraped_at = Column(DateTime(timezone=True), nullable=True)  # When this data was retrieved
    date_added = Column(DateTime(timezone=True), server_default=func.now())
    date_updated = Column(DateTime(timezone=True), onupdate=func.now())

    # Duplicate detection
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_id = Column(Integer, ForeignKey("listings.id", ondelete="SET NULL"), nullable=True)

    # SNCF Station routing
    nearest_sncf_station = Column(String, nullable=True)
    walk_time_sncf = Column(Integer, nullable=True) # in minutes
    bike_time_sncf = Column(Integer, nullable=True) # in minutes
    car_time_sncf = Column(Integer, nullable=True)  # in minutes

    # Second SNCF Station routing
    second_sncf_station = Column(String, nullable=True)
    walk_time_sncf_2 = Column(Integer, nullable=True) # in minutes
    bike_time_sncf_2 = Column(Integer, nullable=True) # in minutes
    car_time_sncf_2 = Column(Integer, nullable=True)  # in minutes

    # Geolocation coordinates
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Risk data
    georisques_json = Column(Text, nullable=True)

    # Source tracking (which ReadySearch generated this listing)
    source_ready_search_id = Column(Integer, ForeignKey("ready_searches.id"), nullable=True)
    source_criteria        = Column(String, nullable=True)  # Copy of ReadySearch.criteria for persistence

    # Relationships
    reviews = relationship("Review", back_populates="listing", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    reviewer = Column(String(50), nullable=False)  # "jean-dupont" ou "marie-martin"
    pros = Column(Text, nullable=True)             # Points positifs
    cons = Column(Text, nullable=True)             # Points négatifs
    rating = Column(Float, nullable=True)          # Note globale 0-10
    visit_done = Column(Boolean, default=False)    # Visite réalisée ?
    notes = Column(Text, nullable=True)            # Notes libres supplémentaires
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    listing = relationship("Listing", back_populates="reviews")


class UserListingView(Base):
    __tablename__ = "user_listing_views"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    viewed_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", backref="views")
    listing = relationship("Listing", backref="user_views")


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    source = Column(Enum(Source), nullable=False)
    name = Column(String, nullable=True)  # e.g. "Maisons Paris < 500k"
    active = Column(Integer, default=1)
    last_run = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ReadySearch(Base):
    __tablename__ = "ready_searches"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, nullable=False)
    criteria = Column(String, nullable=True)
    url = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ReviewKeyword(Base):
    __tablename__ = "review_keywords"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(String, nullable=False, unique=True, index=True)
    keyword_type = Column(String, nullable=False) # 'pros' or 'cons'
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MapPin(Base):
    __tablename__ = "map_pins"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    address = Column(String, nullable=False)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    created_by = Column(String(50), nullable=False)  # username of creator
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Nearby city metadata (set when pin was imported via "villes voisines")
    nearby_distance_km = Column(Float, nullable=True)   # Distance from the search origin in km
    nearby_ref_commune = Column(String, nullable=True)  # Name of the reference city searched
    nearby_ref_cp      = Column(String, nullable=True)  # Postal code of the reference city

    pin_type = Column(String(20), nullable=False, default="city") # "city" or "station"


class TrainLine(Base):
    __tablename__ = "train_lines"

    id = Column(Integer, primary_key=True, index=True)
    departure_station = Column(String, nullable=False)
    arrival_station = Column(String, nullable=False)
    path_json = Column(Text, nullable=False) # JSON list of [lat, lon]
    color = Column(String(20), nullable=False)
    created_by = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class GlobalSettings(Base):
    __tablename__ = "global_settings"

    id = Column(Integer, primary_key=True, index=True)
    resend_api_key = Column(String, nullable=True)
    resend_sender_name = Column(String, nullable=True, default="Immo-Boussole")
    resend_sender_email = Column(String, nullable=True)
    resend_subject = Column(String, nullable=True)
    
    # DB Maintenance Settings
    db_check_automate = Column(Boolean, default=False)
    db_check_interval = Column(String, default="24h")
    db_repair_automate = Column(Boolean, default=False)
    db_repair_interval = Column(String, default="24h")

    # DB Maintenance History
    last_global_check = Column(String, nullable=True)
    last_checks_json = Column(String, nullable=True, default="{}")
    last_repairs_json = Column(String, nullable=True, default="{}")

    allowed_departments = Column(Text, nullable=True) # JSON list of ["38", "73"]

    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ZoneRule(Base):
    """
    Stores forbidden/allowed zone rules for cities and SNCF stations.
    zone_type: "city" or "station"
    rule: "forbidden" or "allowed"
    """
    __tablename__ = "zone_rules"

    id = Column(Integer, primary_key=True, index=True)
    zone_type = Column(String(20), nullable=False)   # "city" or "station"
    name = Column(String, nullable=False, index=True) # City or station name
    rule = Column(String(10), nullable=False)          # "forbidden" or "allowed"
    created_by = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
class RejectedDuplicate(Base):
    """
    Stores pairs of listings that the user has explicitly rejected as duplicates.
    """
    __tablename__ = "rejected_duplicates"

    id = Column(Integer, primary_key=True, index=True)
    listing_a_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    listing_b_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    rejected_at = Column(DateTime(timezone=True), server_default=func.now())


class AIProfile(Base):
    """
    Stores API profiles for the AI Assistant.
    """
    __tablename__ = "ai_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False)  # claude, chatgpt, mistral, google, openai-compatible
    endpoint = Column(String, nullable=False)
    model_name = Column(String, nullable=False)
    api_key = Column(String, nullable=True)
    is_default = Column(Boolean, default=False)
    created_by_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", backref="ai_profiles")

