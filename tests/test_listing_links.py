import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app, _deduce_link_metadata
from app.models import Listing, ListingLink, ListingStatus, Source, User
from app.schemas import ListingLinkCreateRequest, ListingLinkUpdateRequest

# In-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_deduce_link_metadata():
    # Test Haven Score
    url, title, cat = _deduce_link_metadata("https://app.haven-score.fr/l/u056s8ccmm")
    assert url == "https://app.haven-score.fr/l/u056s8ccmm"
    assert title == "Haven Score"
    assert cat == "rapport"

    # Test Clairbien
    url, title, cat = _deduce_link_metadata("https://clairbien.fr/report?q=Rue+des+Plantees")
    assert title == "Rapport Clairbien"
    assert cat == "rapport"

    # Test Terva
    url, title, cat = _deduce_link_metadata("https://terva.fr/analyses/cmt89c0jl0009my0pw8uox5pc")
    assert title == "Analyse Terva"
    assert cat == "rapport"

    # Test Data.gouv
    url, title, cat = _deduce_link_metadata("https://explore.data.gouv.fr/fr/immobilier?lat=45.44&lng=4.77")
    assert title == "Data.gouv.fr"
    assert cat == "marche"

    # Test Custom Title & Category preserved
    url, title, cat = _deduce_link_metadata("https://example.com/custom", custom_title="Mon Rapport Personnalisé", custom_category="autre")
    assert title == "Mon Rapport Personnalisé"
    assert cat == "autre"


def test_listing_link_db_model_and_cascade(db_session):
    # Create listing
    listing = Listing(
        title="Superbe Villa",
        url="https://leboncoin.fr/ad/12345",
        source=Source.MANUAL,
        status=ListingStatus.ACTIVE,
        price=450000,
        area=140
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)

    # Add links
    link1 = ListingLink(
        listing_id=listing.id,
        url="https://app.haven-score.fr/l/u056s8ccmm",
        title="Haven Score",
        category="rapport"
    )
    link2 = ListingLink(
        listing_id=listing.id,
        url="https://terva.fr/analyses/cmt89c0jl0009my0pw8uox5pc",
        title="Analyse Terva",
        category="rapport"
    )
    db_session.add_all([link1, link2])
    db_session.commit()

    # Query links
    assert len(listing.links) == 2
    assert listing.links[0].title == "Haven Score"
    assert listing.links[1].title == "Analyse Terva"

    # Delete listing -> cascade should delete links
    db_session.delete(listing)
    db_session.commit()

    remaining_links = db_session.query(ListingLink).filter(ListingLink.listing_id == listing.id).all()
    assert len(remaining_links) == 0


def test_multi_url_batch_create(db_session):
    listing = Listing(
        title="Maison avec piscine",
        url="https://leboncoin.fr/ad/999",
        source=Source.MANUAL,
        status=ListingStatus.ACTIVE
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)

    # Simulate multi-url text block as provided in the user prompt
    multi_url_text = (
        "https://app.haven-score.fr/l/u056s8ccmm "
        "https://clairbien.fr/report?q=Rue+des+Plantees "
        "https://terva.fr/analyses/cmt89c0jl0009my0pw8uox5pc"
    )

    req = ListingLinkCreateRequest(
        url=multi_url_text,
        category="rapport"
    )

    tokens = [t.strip() for t in multi_url_text.split() if t.strip()]
    assert len(tokens) == 3

    for tok in tokens:
        clean_url, title, cat = _deduce_link_metadata(tok, custom_category=req.category)
        link = ListingLink(
            listing_id=listing.id,
            url=clean_url,
            title=title,
            category=cat
        )
        db_session.add(link)
    db_session.commit()

    links = db_session.query(ListingLink).filter(ListingLink.listing_id == listing.id).all()
    assert len(links) == 3
    titles = [l.title for l in links]
    assert "Haven Score" in titles
    assert "Rapport Clairbien" in titles
    assert "Analyse Terva" in titles


def test_listing_link_update_and_delete(db_session):
    listing = Listing(
        title="Maison Lyon",
        url="https://leboncoin.fr/ad/777",
        source=Source.MANUAL,
        status=ListingStatus.ACTIVE
    )
    db_session.add(listing)
    db_session.commit()

    link = ListingLink(
        listing_id=listing.id,
        url="https://app.haven-score.fr/l/u056s8ccmm",
        title="Haven Score",
        category="rapport"
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    # Update link
    link.title = "Haven Score - Mis à jour"
    link.description = "Score environnemental 8.5/10"
    link.category = "rapport"
    db_session.commit()
    db_session.refresh(link)

    assert link.title == "Haven Score - Mis à jour"
    assert link.description == "Score environnemental 8.5/10"

    # Delete link
    db_session.delete(link)
    db_session.commit()

    assert db_session.query(ListingLink).filter(ListingLink.id == link.id).first() is None


def test_mcp_listing_details_with_links(db_session, monkeypatch):
    import app.mcp_server as mcp_server
    monkeypatch.setattr(mcp_server, "SessionLocal", lambda: db_session)

    listing = Listing(
        title="Villa contemporaine Saint-Clair",
        url="https://leboncoin.fr/ad/3180645396",
        source=Source.MANUAL,
        status=ListingStatus.ACTIVE,
        price=419000,
        area=143
    )
    db_session.add(listing)
    db_session.commit()

    link1 = ListingLink(
        listing_id=listing.id,
        url="https://app.haven-score.fr/l/u056s8ccmm",
        title="Haven Score",
        category="rapport"
    )
    link2 = ListingLink(
        listing_id=listing.id,
        url="https://terva.fr/analyses/cmt89c0jl0009my0pw8uox5pc",
        title="Analyse Terva",
        category="rapport"
    )
    db_session.add_all([link1, link2])
    db_session.commit()

    details_json = mcp_server.tool_get_listing_details(listing.id)
    import json
    data = json.loads(details_json)

    assert "liens_utiles" in data
    assert len(data["liens_utiles"]) == 2
    assert data["liens_utiles"][0]["titre"] == "Haven Score"
    assert data["liens_utiles"][1]["titre"] == "Analyse Terva"

