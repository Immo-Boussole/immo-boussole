from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Enum, Text, ForeignKey, Boolean, LargeBinary
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import relationship
# pyrefly: ignore [missing-import]
from sqlalchemy.sql import func
import enum
import json
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(LargeBinary, nullable=False)
    salt = Column(LargeBinary, nullable=False)
    role = Column(String(20), nullable=False, default="user") # "admin" or "user"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # API
    api_key_hash = Column(String, nullable=True)
    can_create_api_key = Column(Boolean, nullable=False, default=False)
    api_key_last_used = Column(DateTime(timezone=True), nullable=True)

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
    auto_read_after_days = Column(Integer, default=30, nullable=False)

    # Missing location notifications & session tracking
    last_seen_missing_loc_count = Column(Integer, default=0, nullable=False)
    missing_loc_snooze_until = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


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
    PROVIMO = "provimo"
    HEKTOR = "hektor"
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
    address = Column(String, nullable=True)        # Exact street address (e.g., "14 Rue Victor Hugo")
    postal_code = Column(String(10), nullable=True)# Postal code (e.g., "69002")
    address_precision = Column(String(20), default="city") # "exact", "street", "city", "unknown"
    manual_address_override = Column(Boolean, default=False) # True if address was set manually by user
    cadastral_parcel = Column(String(50), nullable=True)     # Parcelle cadastrale (ex: "33063000AB0123" ou "AB 123")
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
    to_visit = Column(Boolean, default=False)
    contact_made = Column(Boolean, default=False)
    last_visit_status = Column(String(50), nullable=True)  # retour_agence, visite_programmee, deja_visitee, contre_visite, sans_suite_acheteur, sans_suite_visiteur, a_relancer
    repair_tags = Column(Text, nullable=True)              # JSON list of active error type keys (e.g. ["missing_location", "empty_description"])
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

    # Solar and exposure data
    orientation = Column(String, nullable=True)
    solar_json = Column(Text, nullable=True)

    # Risk data
    georisques_json = Column(Text, nullable=True)

    # Source tracking (which ReadySearch generated this listing)
    source_ready_search_id = Column(Integer, ForeignKey("ready_searches.id"), nullable=True)
    source_criteria        = Column(String, nullable=True)  # Copy of ReadySearch.criteria for persistence

    # Relationships
    reviews = relationship("Review", back_populates="listing", cascade="all, delete-orphan")
    visits = relationship("Visit", back_populates="listing", cascade="all, delete-orphan", order_by="Visit.scheduled_at")
    attachments = relationship("ListingAttachment", back_populates="listing", cascade="all, delete-orphan", order_by="ListingAttachment.created_at.desc()")
    links = relationship("ListingLink", back_populates="listing", cascade="all, delete-orphan", order_by="ListingLink.created_at.asc()")
    visit_media = relationship("VisitMedia", back_populates="listing", cascade="all, delete-orphan", order_by="VisitMedia.created_at.desc()")
    questions = relationship("VisitQuestion", back_populates="listing", cascade="all, delete-orphan", foreign_keys="VisitQuestion.listing_id", order_by="VisitQuestion.order_index.asc()")
    inclusions = relationship("VisitInclusion", back_populates="listing", cascade="all, delete-orphan", order_by="VisitInclusion.created_at.desc()")
    main_agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    agency_id = Column(Integer, ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True)
    main_agent = relationship("Agent", foreign_keys=[main_agent_id])
    agency = relationship("Agency", foreign_keys=[agency_id])

    def update_price_per_sqm(self):
        """
        Calculates and updates price_per_sqm based on price and area.
        Returns the updated price_per_sqm value.
        """
        if self.price is not None and self.area is not None:
            try:
                p = float(self.price)
                a = float(self.area)
                if p > 0 and a > 0:
                    self.price_per_sqm = round(p / a, 2)
                else:
                    self.price_per_sqm = None
            except (ValueError, TypeError):
                self.price_per_sqm = None
        else:
            self.price_per_sqm = None
        return self.price_per_sqm


class Agency(Base):
    __tablename__ = "agencies"

    id = Column(Integer, primary_key=True, index=True)
    legal_name = Column(String, nullable=False)        # Raison sociale
    commercial_name = Column(String, nullable=True)     # Nom commercial
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    siret = Column(String, nullable=True)
    legal_status = Column(String, nullable=True)       # SARL, SAS, etc.
    carte_t_number = Column(String, nullable=True)     # Numéro carte pro T
    guarantor = Column(String, nullable=True)          # Garant financier
    geographic_zone = Column(String, nullable=True)    # Zone géographique couverte
    reputation_notes = Column(Text, nullable=True)     # Notes internes (réputation, etc.)
    google_contact_resource_name = Column(String, nullable=True)  # ID Google Contact sync

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    agents = relationship("Agent", back_populates="agency", cascade="all, delete-orphan")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    title = Column(String, nullable=True)               # Fonction / rôle
    phone_mobile = Column(String, nullable=True)
    phone_landline = Column(String, nullable=True)
    email = Column(String, nullable=True)
    agency_id = Column(Integer, ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True)
    communication_prefs = Column(String, nullable=True) # SMS, Email, Téléphone
    commission_rate = Column(Float, nullable=True)      # Taux de commission (%)
    internal_notes = Column(Text, nullable=True)
    google_contact_resource_name = Column(String, nullable=True)  # ID Google Contact sync

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    agency = relationship("Agency", back_populates="agents")


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


class Visit(Base):
    __tablename__ = "visits"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    visit_type = Column(String(50), nullable=False, default="visite")  # visite, contre_visite, proposition_offre, contre_proposition_offre
    step_family = Column(String(50), nullable=True)                     # Step family
    step = Column(String(50), nullable=True)                            # Detailed step name
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, default="programme")   # "programme", "effectuee", "annulee"
    visitor = Column(String(100), nullable=True)                        # Visitor name/username
    notes = Column(Text, nullable=True)                                 # Free notes/comments/contact
    google_event_id = Column(String, nullable=True)                    # ID Google Calendar sync
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    access_token = Column(String(64), unique=True, index=True, nullable=True) # Unique short link token for /v/{token}
    meeting_address = Column(String, nullable=True)                     # Specific meeting point / address
    instructions = Column(Text, nullable=True)                         # Instructions / briefing for participants
    participants_json = Column(Text, nullable=True)                     # JSON list of participant emails / usernames / roles

    # Relationships
    listing = relationship("Listing", back_populates="visits")
    visit_contacts = relationship("VisitContact", back_populates="visit", cascade="all, delete-orphan")
    questions = relationship("VisitQuestion", back_populates="visit", cascade="all, delete-orphan", foreign_keys="VisitQuestion.visit_id", order_by="VisitQuestion.order_index.asc()")
    media = relationship("VisitMedia", back_populates="visit", cascade="all, delete-orphan", order_by="VisitMedia.created_at.desc()")
    inclusions = relationship("VisitInclusion", back_populates="visit")

    @property
    def contacts(self):
        result = []
        if self.visit_contacts:
            for vc in self.visit_contacts:
                agent_name = f"{vc.agent.first_name} {vc.agent.last_name}".strip() if vc.agent else None
                agency_name = (vc.agency.commercial_name or vc.agency.legal_name) if vc.agency else None
                result.append({
                    "agent_id": vc.agent_id,
                    "agent_name": agent_name,
                    "agency_id": vc.agency_id,
                    "agency_name": agency_name,
                })
        return result


class VisitContact(Base):
    __tablename__ = "visit_contacts"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True)
    agency_id = Column(Integer, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=True)

    # Relationships
    visit = relationship("Visit", back_populates="visit_contacts")
    agent = relationship("Agent")
    agency = relationship("Agency")


class GlobalQuestion(Base):
    """
    Platform-wide master question catalog.
    Shared across all properties and visits.
    Automatically enriched when users formulate new questions.
    """
    __tablename__ = "global_questions"

    id = Column(Integer, primary_key=True, index=True)
    question_text = Column(Text, nullable=False, index=True)
    themes_json = Column(Text, nullable=True)  # JSON list of theme tags, e.g. ["Piscine", "Extérieur", "Jardin"]
    category = Column(String(100), nullable=True) # e.g. "Inspection technique", "Copropriété", "Financier"
    advice_notes = Column(Text, nullable=True) # Advice on why to ask and what to verify
    language = Column(String(10), default="fr", nullable=False, index=True) # e.g. "fr", "en"
    usage_count = Column(Integer, default=0, nullable=False)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class VisitQuestion(Base):
    """
    Stores interactive FAQ & inspection questions for a property and its visits/contre-visites.
    Supports multi-thematic classification (e.g. ['Piscine', 'Extérieur', 'Jardin']),
    status lifecycle ('en_attente', 'satisfaisante', 'relance_necessaire', 'resolu', 'non_applicable'),
    and answer note-taking with author attribution, language, and multi-visit continuity.
    """
    __tablename__ = "visit_questions"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=True, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id", ondelete="CASCADE"), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="en_attente") # en_attente, satisfaisante, relance_necessaire, resolu, non_applicable
    themes_json = Column(Text, nullable=True) # JSON list of theme tags, e.g. ["Piscine", "Extérieur", "Jardin"]
    language = Column(String(10), default="fr", nullable=False, index=True) # e.g. "fr", "en"
    created_by = Column(String(100), nullable=True)
    assigned_to = Column(String(100), nullable=True)
    answer_text = Column(Text, nullable=True)
    answered_by = Column(String(100), nullable=True)
    answered_at = Column(DateTime(timezone=True), nullable=True)
    respondent_type = Column(String(50), nullable=True) # agent, proprietaire_via_agent, proprietaire_direct
    order_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    visit = relationship("Visit", back_populates="questions", foreign_keys=[visit_id])
    listing = relationship("Listing", back_populates="questions", foreign_keys=[listing_id])
    media = relationship(
        "VisitMedia",
        secondary="visit_question_media",
        back_populates="questions",
        order_by="VisitMedia.created_at.desc()"
    )

    @property
    def assigned_list(self) -> list:
        if not self.assigned_to:
            return []
        try:
            val = json.loads(self.assigned_to)
            if isinstance(val, list):
                return [str(x).strip() for x in val if str(x).strip()]
            return [str(val).strip()]
        except Exception:
            return [x.strip() for x in self.assigned_to.split(",") if x.strip()]

    @property
    def respondent_label(self) -> str:
        mapping = {
            "agent": "Agent immobilier",
            "proprietaire_via_agent": "Propriétaire via agent",
            "proprietaire_direct": "Propriétaire direct"
        }
        return mapping.get(self.respondent_type, "")


class VisitQuestionMedia(Base):
    """
    Association table linking visit questions with visit media (photos, audio recordings, videos, docs).
    """
    __tablename__ = "visit_question_media"

    question_id = Column(Integer, ForeignKey("visit_questions.id", ondelete="CASCADE"), primary_key=True)
    media_id = Column(Integer, ForeignKey("visit_media.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class VisitInclusion(Base):
    """
    Stores furniture, physical goods, equipment, and recurring service contracts
    negotiated or included with the property sale.
    """
    __tablename__ = "visit_inclusions"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id", ondelete="SET NULL"), nullable=True, index=True)
    item_type = Column(String(50), nullable=False, default="objet") # "objet", "service"
    room = Column(String(100), nullable=True) # Salon, Chambre 1, Cuisine, Extérieur, etc.
    title = Column(String(255), nullable=False) # Lit, Table, Télésurveillance, Entretien PAC
    variation_notes = Column(Text, nullable=True) # Avec matelas, sans matelas, modèle 65"
    condition = Column(String(50), nullable=True) # Neuf, Très bon état, Bon état, À réparer
    estimated_value = Column(Float, nullable=True) # Estimated value (tax-deductible for notary fees)
    provider_name = Column(String(255), nullable=True) # Verisure, Somfy, Dalkia
    equipment_included = Column(Text, nullable=True) # Centrale + 4 détecteurs + 2 caméras
    contract_start_date = Column(Date, nullable=True)
    contract_end_date = Column(Date, nullable=True)
    initial_cost = Column(Float, nullable=True) # Initial setup / equipment cost
    monthly_cost = Column(Float, nullable=True) # Monthly fee
    annual_cost = Column(Float, nullable=True) # Annual fee
    transfer_status = Column(String(50), nullable=True) # reprise_contrat, resiliation_vendeur, a_etudier
    negotiation_status = Column(String(50), nullable=False, default="inclus_prix_negocie") # inclus_prix_negocie, en_discussion, exclu_vendeur, option_payante
    photo_url = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    listing = relationship("Listing", back_populates="inclusions")
    visit = relationship("Visit", back_populates="inclusions")


class VisitMedia(Base):
    """
    Stores contributions added during or before a visit (photos taken on site,
    videos, audio recordings, PDF diagnostics/plans, external URLs) with bidirectional linkage
    to both the visit event and the main property listing.
    """
    __tablename__ = "visit_media"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id", ondelete="CASCADE"), nullable=False, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True)
    media_type = Column(String(50), nullable=False, default="photo") # photo, video, audio, document, link
    file_path = Column(String(500), nullable=True)
    url = Column(Text, nullable=True)
    title = Column(String(255), nullable=True)
    category_tag = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    visit = relationship("Visit", back_populates="media")
    listing = relationship("Listing", back_populates="visit_media")
    questions = relationship(
        "VisitQuestion",
        secondary="visit_question_media",
        back_populates="media"
    )




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

    # Google Sync Settings
    google_oauth_credentials_json = Column(Text, nullable=True) # Client ID & Secret JSON
    google_oauth_tokens_json = Column(Text, nullable=True)      # OAuth Tokens (Access/Refresh Token)
    google_pilot_email = Column(String, nullable=True, default="GOOGLE_ACCOUNT_EMAIL@gmail.com")

    # Scraping Proxies Settings (JSON string)
    scraping_proxies_json = Column(Text, nullable=True)

    # Public Data Services Integrations (JSON string, e.g. {"dvf": true, "cadastre": true, "georisques": false})
    public_services_json = Column(Text, nullable=True, default="{}")

    # Automated Nightly Maintenance & Storage Optimization Settings
    auto_maintenance_enabled = Column(Boolean, default=True)
    auto_maintenance_time = Column(String, default="03:30")
    auto_maintenance_purge_rejected = Column(Boolean, default=False)
    last_storage_cleanup = Column(String, nullable=True)
    last_db_optimization = Column(String, nullable=True)
    last_maintenance_metrics_json = Column(Text, nullable=True, default="{}")

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


class ListingAttachment(Base):
    """
    Stores file attachments and documents linked to a listing
    (e.g., diagnostics, plans, PV d'AG, devis, copropriété, etc.).
    """
    __tablename__ = "listing_attachments"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=False, default="autre")  # diagnostic, plan, pv_ag, devis, copropriete, compromis, autre
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    file_size = Column(Integer, nullable=True)  # size in bytes
    mime_type = Column(String(100), nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    listing = relationship("Listing", back_populates="attachments")


class ListingLink(Base):
    """
    Stores external and useful links related to a listing
    (e.g., Haven Score, Clairbien report, Terva, city/neighborhood guides, etc.).
    """
    __tablename__ = "listing_links"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    url = Column(Text, nullable=False)
    category = Column(String(50), nullable=True, default="rapport")  # rapport, ville, marche, cadastre, autre
    description = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    listing = relationship("Listing", back_populates="links")


class Notification(Base):
    """
    Stores in-app notifications targeting specific users, roles/groups, or AI profiles.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    target_role = Column(String(20), nullable=True, index=True)  # "admin", "user", or None for all
    target_profile_id = Column(Integer, ForeignKey("ai_profiles.id", ondelete="CASCADE"), nullable=True, index=True)

    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    category = Column(String(30), nullable=False, default="systeme")  # "annonce", "visite", "systeme"
    link_url = Column(String(500), nullable=True)

    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)


class SolarCache(Base):
    """
    Persistent cache for geo-based solar irradiance, sunshine duration, and PV potential.
    Keyed by rounded coordinates (lat/lon) to avoid redundant external API calls.
    """
    __tablename__ = "solar_cache"

    id = Column(Integer, primary_key=True, index=True)
    geo_key = Column(String, unique=True, index=True, nullable=False)
    sunshine_hours = Column(Integer, nullable=True)
    solar_irradiation = Column(Float, nullable=True)
    pv_yield_per_kwc = Column(Float, nullable=True)
    data_json = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())



