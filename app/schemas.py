from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime

class SubmitUrlRequest(BaseModel):
    url: str
    skip_scraping: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if not v.startswith("http"):
            raise ValueError("URL must start with http:// or https://")
        return v.strip()


class ExternalListingSubmitRequest(BaseModel):
    url: str
    external_id: Optional[str] = None
    title: Optional[str] = None
    price: Optional[float] = None
    area: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    location: Optional[str] = None
    cadastral_parcel: Optional[str] = None
    description: Optional[str] = None
    photos: Optional[List[str]] = None
    source: Optional[str] = None
    property_type: Optional[str] = None
    dpe_rating: Optional[str] = None
    ges_rating: Optional[str] = None
    floorplans: Optional[List[str]] = None
    land_area: Optional[float] = None
    bathroom_count: Optional[int] = None
    land_tax: Optional[float] = None
    charges: Optional[float] = None
    heating_type: Optional[str] = None
    heating_mode: Optional[str] = None
    building_year: Optional[int] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        if not v.startswith("http"):
            raise ValueError("URL must start with http:// or https://")
        return v.strip()


class ExternalListingBatchRequest(BaseModel):
    listings: List[ExternalListingSubmitRequest]
    tag: Optional[str] = None
    search_query_id: Optional[int] = None


class ExternalListingBatchItemResult(BaseModel):
    url: str
    status: str  # "created", "already_exists", "error"
    listing_id: Optional[int] = None
    title: Optional[str] = None
    error: Optional[str] = None


class ExternalListingBatchResponse(BaseModel):
    status: str
    message: str
    total_received: int
    created_count: int
    already_exists_count: int
    error_count: int
    results: List[ExternalListingBatchItemResult]


class ExternalListingCheckRequest(BaseModel):
    urls: List[str] = []
    external_ids: List[str] = []


class ExternalListingCheckResponse(BaseModel):
    existing_urls: List[str]
    existing_external_ids: List[str]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    api_key: str
    token_type: str = "bearer"
    username: str
    role: str
    message: str = "Authentication successful"




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
    is_favorite: Optional[bool] = None
    contact_made: Optional[bool] = None
    last_visit_status: Optional[str] = None


class ListingVisitStatusUpdate(BaseModel):
    last_visit_status: Optional[str] = None  # None or one of: retour_agence, visite_programmee, deja_visitee, sans_suite_acheteur, sans_suite_visiteur, a_relancer


class PhotoImportRequest(BaseModel):
    urls: List[str]


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
    pois: List[ProfilePOI] = []
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
    pins: List[MapPinEntry]


class NearbyCityPin(BaseModel):
    nom_commune: str
    code_postal: str
    distance: float        # in km
    ref_commune: str       # Deduced reference city name (first result at distance ≈ 0)
    ref_cp: str            # Postal code of the reference city


class NearbyCityBulkRequest(BaseModel):
    cities: List[NearbyCityPin]
    include_stations: bool = False


class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []

class ApiKeyResponse(BaseModel):
    api_key: str
    message: str

class UserApiMgmtResponse(BaseModel):
    id: int
    username: str
    role: str
    can_create_api_key: bool
    has_api_key: bool
    api_key_last_used: Optional[datetime] = None

    class Config:
        from_attributes = True

class ActionResponse(BaseModel):
    status: str
    message: str
    data: Optional[dict] = None

class ListingResponse(BaseModel):
    id: int
    external_id: Optional[str] = None
    title: Optional[str] = None
    url: str
    price: Optional[float] = None
    price_per_sqm: Optional[float] = None
    location: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    address_precision: Optional[str] = "city"
    manual_address_override: bool = False
    area: Optional[float] = None
    land_area: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    property_type: Optional[str] = None
    condition: Optional[str] = None
    dpe_rating: Optional[str] = None
    ges_rating: Optional[str] = None
    source: str
    status: str
    is_favorite: bool
    to_visit: bool = False
    contact_made: bool = False
    last_visit_status: Optional[str] = None
    is_duplicate: bool
    date_added: Optional[datetime] = None
    date_updated: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class AgencyCreate(BaseModel):
    legal_name: str
    commercial_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    siret: Optional[str] = None
    legal_status: Optional[str] = None
    carte_t_number: Optional[str] = None
    guarantor: Optional[str] = None
    geographic_zone: Optional[str] = None
    reputation_notes: Optional[str] = None

class AgencyUpdateRequest(BaseModel):
    legal_name: Optional[str] = None
    commercial_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    siret: Optional[str] = None
    legal_status: Optional[str] = None
    carte_t_number: Optional[str] = None
    guarantor: Optional[str] = None
    geographic_zone: Optional[str] = None
    reputation_notes: Optional[str] = None

class AgencyResponse(BaseModel):
    id: int
    legal_name: str
    commercial_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    siret: Optional[str] = None
    legal_status: Optional[str] = None
    carte_t_number: Optional[str] = None
    guarantor: Optional[str] = None
    geographic_zone: Optional[str] = None
    reputation_notes: Optional[str] = None
    google_contact_resource_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class AgentCreate(BaseModel):
    first_name: str
    last_name: str
    title: Optional[str] = None
    phone_mobile: Optional[str] = None
    phone_landline: Optional[str] = None
    email: Optional[str] = None
    agency_id: Optional[int] = None
    communication_prefs: Optional[str] = None
    commission_rate: Optional[float] = None
    internal_notes: Optional[str] = None

class AgentUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    phone_mobile: Optional[str] = None
    phone_landline: Optional[str] = None
    email: Optional[str] = None
    agency_id: Optional[int] = None
    communication_prefs: Optional[str] = None
    commission_rate: Optional[float] = None
    internal_notes: Optional[str] = None

class AgentResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    title: Optional[str] = None
    phone_mobile: Optional[str] = None
    phone_landline: Optional[str] = None
    email: Optional[str] = None
    agency_id: Optional[int] = None
    agency_name: Optional[str] = None
    communication_prefs: Optional[str] = None
    commission_rate: Optional[float] = None
    internal_notes: Optional[str] = None
    google_contact_resource_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class VisitCreateRequest(BaseModel):
    listing_id: int
    visit_type: str = "visite"  # "visite", "contre_visite", "proposition_offre", "contre_proposition_offre"
    step_family: Optional[str] = None
    step: Optional[str] = None
    scheduled_at: datetime
    status: str = "programme"   # "programme", "effectuee", "annulee"
    visitor: Optional[str] = None
    notes: Optional[str] = None
    agent_ids: List[int] = []
    agency_ids: List[int] = []
    update_listing_contact: Optional[bool] = None
    listing_address: Optional[str] = None
    listing_city: Optional[str] = None
    listing_postal_code: Optional[str] = None
    listing_address_precision: Optional[str] = None

class VisitUpdateRequest(BaseModel):
    visit_type: Optional[str] = None
    step_family: Optional[str] = None
    step: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None
    visitor: Optional[str] = None
    notes: Optional[str] = None
    agent_ids: Optional[List[int]] = None
    agency_ids: Optional[List[int]] = None
    update_listing_contact: Optional[bool] = None
    listing_address: Optional[str] = None
    listing_city: Optional[str] = None
    listing_postal_code: Optional[str] = None
    listing_address_precision: Optional[str] = None

class VisitContactSchema(BaseModel):
    agent_id: Optional[int] = None
    agent_name: Optional[str] = None
    agency_id: Optional[int] = None
    agency_name: Optional[str] = None

class VisitResponse(BaseModel):
    id: int
    listing_id: int
    visit_type: str
    step_family: Optional[str] = None
    step: Optional[str] = None
    scheduled_at: datetime
    status: str
    visitor: Optional[str] = None
    notes: Optional[str] = None
    google_event_id: Optional[str] = None
    contacts: List[VisitContactSchema] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AttachedListingSummary(BaseModel):
    id: int
    title: Optional[str] = None
    price: Optional[float] = None
    city: Optional[str] = None
    address: Optional[str] = None
    address_precision: Optional[str] = "city"
    area: Optional[float] = None
    rooms: Optional[int] = None
    photo_thumbnail: Optional[str] = None
    url: Optional[str] = None
    status: Optional[str] = None
    main_agent_id: Optional[int] = None
    agency_id: Optional[int] = None
    agent_name: Optional[str] = None
    agency_name: Optional[str] = None
    to_visit: bool = False
    last_visit_status: Optional[str] = None


class UnifiedContactItem(BaseModel):
    contact_type: str  # "agent" or "agency"
    id: int
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    agency_id: Optional[int] = None
    agency_name: Optional[str] = None
    phone_mobile: Optional[str] = None
    phone_landline: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None
    commission_rate: Optional[float] = None
    communication_prefs: Optional[str] = None
    google_contact_resource_name: Optional[str] = None
    attached_listings: List[AttachedListingSummary] = []


class LinkListingRequest(BaseModel):
    listing_id: int
    agent_id: Optional[int] = None
    agency_id: Optional[int] = None


class UnlinkListingRequest(BaseModel):
    listing_id: int


class MergeContactsRequest(BaseModel):
    source_type: str  # "agent" or "agency"
    source_id: int
    target_type: str  # "agent" or "agency"
    target_id: int


class AffiliatedAgentSummary(BaseModel):
    id: int
    name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class AgencyOverviewItem(BaseModel):
    id: int
    legal_name: str
    commercial_name: Optional[str] = None
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    siret: Optional[str] = None
    legal_status: Optional[str] = None
    carte_t_number: Optional[str] = None
    guarantor: Optional[str] = None
    geographic_zone: Optional[str] = None
    reputation_notes: Optional[str] = None
    google_contact_resource_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    affiliated_agents: List[AffiliatedAgentSummary] = []
    attached_listings: List[AttachedListingSummary] = []


class RouteCalcRequest(BaseModel):
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    start_name: Optional[str] = "Point A"
    end_name: Optional[str] = "Point B"


class ReferencePointRequest(BaseModel):
    name: str
    address: str
    lat: float
    lon: float
    icon: Optional[str] = "fa-location-dot"
    category: Optional[str] = "custom"


class ListingAttachmentResponse(BaseModel):
    id: int
    listing_id: int
    filename: str
    original_filename: str
    file_path: str
    file_type: str
    title: Optional[str] = None
    description: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ListingAttachmentUpdateRequest(BaseModel):
    title: Optional[str] = None
    file_type: Optional[str] = None
    description: Optional[str] = None


class BulkDeleteAttachmentsRequest(BaseModel):
    attachment_ids: list[int]


class ListingLinkCreateRequest(BaseModel):
    url: str
    title: Optional[str] = None
    category: Optional[str] = "rapport"
    description: Optional[str] = None


class ListingLinkUpdateRequest(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None


class ListingLinkResponse(BaseModel):
    id: int
    listing_id: int
    title: Optional[str] = None
    url: str
    category: Optional[str] = None
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True





