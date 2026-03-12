from sqlalchemy import Column, Integer, String, Float, DateTime, Enum, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class ListingStatus(str, enum.Enum):
    NEW = "nouvelle"
    ACTIVE = "active"
    DISAPPEARED = "disparue"


class Source(str, enum.Enum):
    LEBONCOIN = "leboncoin"
    SELOGER = "seloger"
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
    rooms = Column(Integer, nullable=True)         # Nombre de pièces
    bedrooms = Column(Integer, nullable=True)
    floor = Column(Integer, nullable=True)
    total_floors = Column(Integer, nullable=True)
    building_year = Column(Integer, nullable=True)

    # Energy ratings
    dpe_rating = Column(String(1), nullable=True)  # A, B, C, D, E, F, G
    ges_rating = Column(String(1), nullable=True)  # A, B, C, D, E, F, G

    # Costs
    land_tax = Column(Float, nullable=True)        # Taxe foncière annuelle
    charges = Column(Float, nullable=True)         # Charges mensuelles de copropriété
    agency_fee = Column(Float, nullable=True)

    # Description
    description_text = Column(Text, nullable=True)

    # Media (stored as JSON strings)
    photos_local = Column(Text, nullable=True)      # JSON list of local file paths
    original_photo_urls = Column(Text, nullable=True)  # JSON list of original URLs

    # Metadata
    source = Column(Enum(Source), nullable=False, default=Source.MANUAL)
    status = Column(Enum(ListingStatus), default=ListingStatus.NEW, nullable=False)
    scraped_at = Column(DateTime(timezone=True), nullable=True)  # When this data was retrieved
    date_added = Column(DateTime(timezone=True), server_default=func.now())
    date_updated = Column(DateTime(timezone=True), onupdate=func.now())

    # Duplicate detection
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_id = Column(Integer, ForeignKey("listings.id"), nullable=True)

    # Relationships
    reviews = relationship("Review", back_populates="listing", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    reviewer = Column(String(50), nullable=False)  # "jean-marc" ou "marceline"
    pros = Column(Text, nullable=True)             # Points positifs
    cons = Column(Text, nullable=True)             # Points négatifs
    rating = Column(Float, nullable=True)          # Note globale 0-10
    visit_done = Column(Boolean, default=False)    # Visite réalisée ?
    notes = Column(Text, nullable=True)            # Notes libres supplémentaires
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    listing = relationship("Listing", back_populates="reviews")


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    source = Column(Enum(Source), nullable=False)
    name = Column(String, nullable=True)  # e.g. "Maisons Paris < 500k"
    active = Column(Integer, default=1)
    last_run = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
