from sqlalchemy import Column, Integer, String, Float, DateTime, Enum
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

class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, unique=True, index=True, nullable=False) # ID of the ad on the website
    title = Column(String, index=True)
    url = Column(String, unique=True, nullable=False)
    price = Column(Float, nullable=True)
    location = Column(String, nullable=True)
    area = Column(Float, nullable=True) # Square meters
    source = Column(Enum(Source), nullable=False)
    status = Column(Enum(ListingStatus), default=ListingStatus.NEW, nullable=False)
    
    date_added = Column(DateTime(timezone=True), server_default=func.now())
    date_updated = Column(DateTime(timezone=True), onupdate=func.now())

class SearchQuery(Base):
    __tablename__ = "search_queries"
    
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    source = Column(Enum(Source), nullable=False)
    name = Column(String, nullable=True) # e.g. "Maisons Paris < 500k"
    active = Column(Integer, default=1)
