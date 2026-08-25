try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("Immo-Boussole", dependencies=["sqlalchemy", "pydantic"])
except ImportError:
    FastMCP = None
    mcp = None

from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import SessionLocal
from app.models import Listing, ListingStatus, Source, Review, Visit, ListingLink
from typing import Optional, List
from datetime import datetime
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-immo")


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
                "cadastral_parcel": getattr(l, "cadastral_parcel", None),
                "to_visit": getattr(l, "to_visit", False),
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
        
        dvf_url = None
        if l.latitude and l.longitude:
            dvf_url = f"https://explore.data.gouv.fr/fr/immobilier?lat={l.latitude}&lng={l.longitude}&zoom=18"

        data = {
            "id": l.id,
            "title": l.title,
            "url_originale": l.url,
            "price": l.price,
            "address": l.address,
            "postal_code": l.postal_code,
            "city": l.city,
            "cadastral_parcel": getattr(l, "cadastral_parcel", None),
            "dvf_url": dvf_url,
            "area": l.area,
            "rooms": l.rooms,
            "bedrooms": l.bedrooms,
            "description": l.description_text,
            "status": l.status,
            "source": l.source,
            "to_visit": getattr(l, "to_visit", False),
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
            
        visits = db.query(Visit).filter(Visit.listing_id == l.id).order_by(Visit.scheduled_at.asc()).all()
        if visits:
            data["visites_programmees"] = [{
                "id": v.id,
                "type": v.visit_type,
                "scheduled_at": v.scheduled_at.isoformat() if v.scheduled_at else None,
                "status": v.status,
                "visitor": v.visitor,
                "notes": v.notes
            } for v in visits]

        links = db.query(ListingLink).filter(ListingLink.listing_id == l.id).order_by(ListingLink.created_at.asc()).all()
        if links:
            data["liens_utiles"] = [{
                "id": link.id,
                "titre": link.title,
                "url": link.url,
                "categorie": link.category,
                "description": link.description
            } for link in links]

        return json.dumps(data, indent=2, ensure_ascii=False)
    finally:
        db.close()

def tool_get_stats() -> str:
    db = SessionLocal()
    try:
        total = db.query(Listing).count()
        active = db.query(Listing).filter(Listing.status == ListingStatus.ACTIVE).count()
        new = db.query(Listing).filter(Listing.status == ListingStatus.NEW).count()
        refused_ids = [r[0] for r in db.query(Visit.listing_id).filter(Visit.visit_type == "reponse_negative").all()]
        to_visit_query = db.query(Listing).filter(Listing.to_visit == True)
        if refused_ids:
            to_visit_query = to_visit_query.filter(~Listing.id.in_(refused_ids))
        to_visit_count = to_visit_query.count()
        total_visits = db.query(Visit).count()
        
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
            "annonces_a_visiter": to_visit_count,
            "total_visites": total_visits,
            "top_villes_prix_moyen": {city: round(price, 2) for city, price in avg_prices if city},
            "sources": {s.value: db.query(Listing).filter(Listing.source == s).count() for s in Source}
        }
        return json.dumps(stats, indent=2, ensure_ascii=False)
    finally:
        db.close()

def tool_toggle_listing_to_visit(listing_id: int) -> str:
    db = SessionLocal()
    try:
        l = db.query(Listing).filter(Listing.id == listing_id).first()
        if not l:
            return f"Annonce {listing_id} introuvable."
        l.to_visit = not l.to_visit
        db.commit()
        state_str = "marqué comme à visiter" if l.to_visit else "retiré des biens à visiter"
        return f"Succès: Bien #{l.id} ({l.title}) {state_str}."
    finally:
        db.close()

def tool_list_visits(status: Optional[str] = None, visit_type: Optional[str] = None, listing_id: Optional[int] = None) -> str:
    db = SessionLocal()
    try:
        query = db.query(Visit)
        if status:
            query = query.filter(Visit.status == status)
        if visit_type:
            query = query.filter(Visit.visit_type == visit_type)
        if listing_id:
            query = query.filter(Visit.listing_id == listing_id)
        
        visits = query.order_by(Visit.scheduled_at.asc()).all()
        results = []
        for v in visits:
            l = db.query(Listing).filter(Listing.id == v.listing_id).first()
            results.append({
                "id": v.id,
                "listing_id": v.listing_id,
                "listing_title": l.title if l else "Inconnu",
                "listing_city": l.city or l.location if l else None,
                "listing_price": l.price if l else None,
                "visit_type": v.visit_type,
                "scheduled_at": v.scheduled_at.isoformat() if v.scheduled_at else None,
                "status": v.status,
                "visitor": v.visitor,
                "notes": v.notes
            })
        return json.dumps(results, indent=2, ensure_ascii=False)
    finally:
        db.close()

def tool_schedule_visit(listing_id: int, scheduled_at: str, visit_type: str = "visite", visitor: Optional[str] = None, notes: Optional[str] = None, status: str = "programme") -> str:
    db = SessionLocal()
    try:
        l = db.query(Listing).filter(Listing.id == listing_id).first()
        if not l:
            return f"Annonce {listing_id} introuvable."
        
        try:
            dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            return "Format de date invalide. Utilisez le format ISO (ex: 2026-08-15T14:30:00)."

        if visit_type == "reponse_negative":
            l.to_visit = False
        else:
            l.to_visit = True

        v = Visit(
            listing_id=listing_id,
            visit_type=visit_type,
            scheduled_at=dt,
            status=status,
            visitor=visitor or "Agent MCP",
            notes=notes
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        return json.dumps({
            "status": "success",
            "message": f"Visite ({v.visit_type}) programmée pour le bien #{l.id} à {v.scheduled_at.isoformat()}",
            "visit_id": v.id
        }, indent=2, ensure_ascii=False)
    finally:
        db.close()

def tool_update_visit(visit_id: int, scheduled_at: Optional[str] = None, status: Optional[str] = None, notes: Optional[str] = None, visitor: Optional[str] = None, visit_type: Optional[str] = None) -> str:
    db = SessionLocal()
    try:
        v = db.query(Visit).filter(Visit.id == visit_id).first()
        if not v:
            return f"Visite #{visit_id} introuvable."
        
        if scheduled_at:
            try:
                v.scheduled_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            except ValueError:
                return "Format de date invalide. Utilisez le format ISO (ex: 2026-08-15T14:30:00)."
        if status:
            v.status = status
        if notes is not None:
            v.notes = notes
        if visitor:
            v.visitor = visitor
        if visit_type:
            v.visit_type = visit_type
            l = db.query(Listing).filter(Listing.id == v.listing_id).first()
            if l:
                if visit_type == "reponse_negative":
                    l.to_visit = False
                else:
                    l.to_visit = True
        
        db.commit()
        return f"Visite #{v.id} mise à jour avec succès (Statut: {v.status})."
    finally:
        db.close()

def tool_delete_visit(visit_id: int) -> str:
    db = SessionLocal()
    try:
        v = db.query(Visit).filter(Visit.id == visit_id).first()
        if not v:
            return f"Visite #{visit_id} introuvable."
        db.delete(v)
        db.commit()
        return f"Visite #{visit_id} supprimée avec succès."
    finally:
        db.close()

if mcp is not None:
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
        Récupère les détails complets d'une annonce spécifique par son ID (incluant le statut à visiter et l'historique des visites).
        """
        return tool_get_listing_details(listing_id)

    @mcp.tool()
    def toggle_listing_to_visit(listing_id: int) -> str:
        """
        Active ou désactive l'indicateur 'à visiter' pour une annonce immobilière.
        """
        return tool_toggle_listing_to_visit(listing_id)

    @mcp.tool()
    def list_visits(status: Optional[str] = None, visit_type: Optional[str] = None, listing_id: Optional[int] = None) -> str:
        """
        Liste toutes les visites et contre-visites (programmées, effectuées ou annulées).
        """
        return tool_list_visits(status, visit_type, listing_id)

    @mcp.tool()
    def schedule_visit(listing_id: int, scheduled_at: str, visit_type: str = "visite", visitor: Optional[str] = None, notes: Optional[str] = None, status: str = "programme") -> str:
        """
        Planifie une nouvelle visite ou contre-visite pour une annonce.
        scheduled_at doit être au format ISO (ex: '2026-08-15T14:30:00').
        visit_type: 'visite' ou 'contre_visite'.
        status: 'programme', 'effectuee' ou 'annulee'.
        """
        return tool_schedule_visit(listing_id, scheduled_at, visit_type, visitor, notes, status)

    @mcp.tool()
    def update_visit(visit_id: int, scheduled_at: Optional[str] = None, status: Optional[str] = None, notes: Optional[str] = None, visitor: Optional[str] = None, visit_type: Optional[str] = None) -> str:
        """
        Met à jour une visite existante (changer la date, le statut comme 'effectuee', ajouter des notes, etc.).
        """
        return tool_update_visit(visit_id, scheduled_at, status, notes, visitor, visit_type)

    @mcp.tool()
    def delete_visit(visit_id: int) -> str:
        """
        Supprime une visite enregistrée.
        """
        return tool_delete_visit(visit_id)

    @mcp.resource("immo://stats")
    def get_stats() -> str:
        """
        Statistiques globales de la base de données immobilière (incluant annonces à visiter et nombre de visites).
        """
        return tool_get_stats()



if __name__ == "__main__":
    import uvicorn
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--transport", default="sse", choices=["sse", "stdio"])
    args, _ = parser.parse_known_args()
    
    if args.transport == "stdio":
        mcp.run(transport='stdio')
    else:
        mcp.settings.port = args.port
        mcp.settings.host = args.host
        mcp.run(transport='sse')
