from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import SessionLocal
from app.models import Listing, ListingStatus, Source, Review
from typing import Optional, List
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-immo")

# Create an MCP server
mcp = FastMCP("Immo-Boussole", dependencies=["sqlalchemy", "pydantic"])

def tool_search_listings(
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    city: Optional[str] = None,
    min_area: Optional[float] = None,
    status: Optional[str] = "active",
    limit: int = 10
) -> str:
    db = SessionLocal()
    try:
        query = db.query(Listing)
        if status:
            query = query.filter(Listing.status == status)
        if min_price:
            query = query.filter(Listing.price >= min_price)
        if max_price:
            query = query.filter(Listing.price <= max_price)
        if city:
            query = query.filter(Listing.city.ilike(f"%{city}%"))
        if min_area:
            query = query.filter(Listing.area >= min_area)
        
        query = query.order_by(Listing.date_added.desc())
        listings = query.limit(limit).all()
        
        results = []
        for l in listings:
            results.append({
                "id": l.id,
                "title": l.title,
                "price": l.price,
                "city": l.city,
                "area": l.area,
                "rooms": l.rooms,
                "url": f"/listing/{l.id}"
            })
        
        if not results:
            return "Aucune annonce ne correspond à ces critères."
        return json.dumps(results, indent=2, ensure_ascii=False)
    finally:
        db.close()

def tool_get_listing_details(listing_id: int) -> str:
    db = SessionLocal()
    try:
        l = db.query(Listing).filter(Listing.id == listing_id).first()
        if not l:
            return f"Annonce {listing_id} introuvable."
        
        data = {
            "id": l.id,
            "title": l.title,
            "url_originale": l.url,
            "price": l.price,
            "city": l.city,
            "area": l.area,
            "rooms": l.rooms,
            "bedrooms": l.bedrooms,
            "description": l.description_text,
            "status": l.status,
            "source": l.source,
            "date_ajout": l.date_added.strftime("%Y-%m-%d") if l.date_added else None,
            "dpe": l.dpe_rating,
            "ges": l.ges_rating,
            "gare_proche": l.nearest_sncf_station,
            "temps_marche_gare": l.walk_time_sncf,
            "taxe_fonciere": l.land_tax,
            "charges_mensuelles": l.charges
        }
        
        reviews = db.query(Review).filter(Review.listing_id == l.id).all()
        if reviews:
            data["avis"] = [{
                "reviewer": r.reviewer,
                "note": r.rating,
                "points_positifs": r.pros,
                "points_negatifs": r.cons,
                "visite_faite": r.visit_done
            } for r in reviews]
            
        return json.dumps(data, indent=2, ensure_ascii=False)
    finally:
        db.close()

def tool_get_stats() -> str:
    db = SessionLocal()
    try:
        total = db.query(Listing).count()
        active = db.query(Listing).filter(Listing.status == ListingStatus.ACTIVE).count()
        new = db.query(Listing).filter(Listing.status == ListingStatus.NEW).count()
        
        avg_prices = db.query(
            Listing.city, 
            func.avg(Listing.price).label('avg_price')
        ).filter(Listing.status == ListingStatus.ACTIVE)\
         .group_by(Listing.city)\
         .order_by(func.count(Listing.id).desc())\
         .limit(5).all()
        
        stats = {
            "total_annonces": total,
            "annonces_actives": active,
            "nouvelles_annonces": new,
            "top_villes_prix_moyen": {city: round(price, 2) for city, price in avg_prices if city},
            "sources": {s.value: db.query(Listing).filter(Listing.source == s).count() for s in Source}
        }
        return json.dumps(stats, indent=2, ensure_ascii=False)
    finally:
        db.close()

@mcp.tool()
def search_listings(
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    city: Optional[str] = None,
    min_area: Optional[float] = None,
    status: Optional[str] = "active",
    limit: int = 10
) -> str:
    """
    Recherche des annonces immobilières dans la base de données Immo-Boussole.
    """
    return tool_search_listings(min_price, max_price, city, min_area, status, limit)

@mcp.tool()
def get_listing_details(listing_id: int) -> str:
    """
    Récupère les détails complets d'une annonce spécifique par son ID.
    """
    return tool_get_listing_details(listing_id)

@mcp.resource("immo://stats")
def get_stats() -> str:
    """
    Statistiques globales de la base de données immobilière.
    """
    return tool_get_stats()

if __name__ == "__main__":
    import uvicorn
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    args, _ = parser.parse_known_args()
    
    mcp.settings.port = args.port
    mcp.settings.host = args.host
    mcp.run(transport='sse')
