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
    is_favorite: Optional[bool] = None
    contact_made: Optional[bool] = None


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
    is_duplicate: bool
    date_added: Optional[datetime] = None
    date_updated: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class VisitCreateRequest(BaseModel):
    listing_id: int
    visit_type: str = "visite"  # "visite" or "contre_visite"
    scheduled_at: datetime
    status: str = "programme"   # "programme", "effectuee", "annulee"
    visitor: Optional[str] = None
    notes: Optional[str] = None


class VisitUpdateRequest(BaseModel):
    visit_type: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None
    visitor: Optional[str] = None
    notes: Optional[str] = None


class VisitResponse(BaseModel):
    id: int
    listing_id: int
    visit_type: str
    scheduled_at: datetime
    status: str
    visitor: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

