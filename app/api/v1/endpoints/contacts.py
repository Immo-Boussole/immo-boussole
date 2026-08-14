from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from typing import List, Optional, Dict, Any
import json
import logging
import difflib

from app.database import get_db
from app.models import Agency, Agent, GlobalSettings, VisitContact, Listing, Visit, ListingStatus
from app import schemas
from app import google_service
from app.media import json_to_photos
from app.services import extract_contact_info_from_text

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_listing_photo_thumbnail(listing: Listing) -> Optional[str]:
    """Helper to retrieve a photo URL or local path for thumbnail display."""
    if listing.photos_local:
        photos = json_to_photos(listing.photos_local)
        if photos:
            return photos[0]
    if listing.original_photo_urls:
        try:
            urls = json.loads(listing.original_photo_urls)
            if urls and isinstance(urls, list):
                return urls[0]
        except Exception:
            pass
    return None


def _format_listing_summary(l: Listing) -> schemas.AttachedListingSummary:
    return schemas.AttachedListingSummary(
        id=l.id,
        title=l.title or f"Bien #{l.id}",
        price=l.price,
        city=l.city or l.location,
        area=l.area,
        rooms=l.rooms,
        photo_thumbnail=_get_listing_photo_thumbnail(l),
        url=l.url,
        status=l.status.value if hasattr(l.status, 'value') else str(l.status)
    )


# --- Unified Contact Overview ---

@router.get("/contacts/overview", response_model=List[schemas.UnifiedContactItem])
def get_contacts_overview(
    q: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Returns a unified list of contacts:
    - All Agents (with their agency information and attached listings)
    - Standalone Agencies without agents (or agencies having listings directly attached)
    """
    agents = db.query(Agent).all()
    agencies = db.query(Agency).all()
    
    # Pre-fetch listings linked to agents or agencies
    listings_by_agent: Dict[int, List[Listing]] = {}
    listings_by_agency: Dict[int, List[Listing]] = {}
    
    linked_listings = db.query(Listing).filter(
        or_(Listing.main_agent_id.isnot(None), Listing.agency_id.isnot(None))
    ).order_by(Listing.date_added.desc()).all()
    
    for l in linked_listings:
        if l.main_agent_id:
            listings_by_agent.setdefault(l.main_agent_id, []).append(l)
        elif l.agency_id:
            listings_by_agency.setdefault(l.agency_id, []).append(l)

    unified_list: List[schemas.UnifiedContactItem] = []

    # 1. Add all agents
    for ag in agents:
        attached = [_format_listing_summary(l) for l in listings_by_agent.get(ag.id, [])]
        agency_name = (ag.agency.commercial_name or ag.agency.legal_name) if ag.agency else None
        
        unified_list.append(schemas.UnifiedContactItem(
            contact_type="agent",
            id=ag.id,
            name=f"{ag.first_name} {ag.last_name}".strip(),
            first_name=ag.first_name,
            last_name=ag.last_name,
            title=ag.title or "Agent Commercial",
            agency_id=ag.agency_id,
            agency_name=agency_name,
            phone_mobile=ag.phone_mobile,
            phone_landline=ag.phone_landline,
            phone=ag.phone_mobile or ag.phone_landline,
            email=ag.email,
            city=ag.agency.city if ag.agency else None,
            notes=ag.internal_notes,
            commission_rate=ag.commission_rate,
            communication_prefs=ag.communication_prefs,
            google_contact_resource_name=ag.google_contact_resource_name,
            attached_listings=attached
        ))

    # 2. Add standalone agencies (agencies with no agents or with directly linked listings)
    agencies_with_agents = {ag.agency_id for ag in agents if ag.agency_id is not None}
    for ac in agencies:
        has_direct_listings = bool(listings_by_agency.get(ac.id))
        is_standalone = (ac.id not in agencies_with_agents) or has_direct_listings
        if is_standalone:
            attached = [_format_listing_summary(l) for l in listings_by_agency.get(ac.id, [])]
            unified_list.append(schemas.UnifiedContactItem(
                contact_type="agency",
                id=ac.id,
                name=ac.commercial_name or ac.legal_name,
                first_name=None,
                last_name=None,
                title="Agence Immobilière",
                agency_id=ac.id,
                agency_name=ac.legal_name,
                phone_mobile=None,
                phone_landline=ac.phone,
                phone=ac.phone,
                email=ac.email,
                city=ac.city,
                notes=ac.reputation_notes,
                commission_rate=None,
                communication_prefs=None,
                google_contact_resource_name=ac.google_contact_resource_name,
                attached_listings=attached
            ))

    # Apply search filter if query provided
    if q:
        query_str = q.strip().lower()
        filtered = []
        for item in unified_list:
            match_name = query_str in item.name.lower()
            match_email = bool(item.email and query_str in item.email.lower())
            match_phone = bool(item.phone and query_str in item.phone.replace(" ", ""))
            match_agency = bool(item.agency_name and query_str in item.agency_name.lower())
            match_city = bool(item.city and query_str in item.city.lower())
            match_listings = any(
                query_str in (l.title or "").lower() or query_str in (l.city or "").lower()
                for l in item.attached_listings
            )
            if match_name or match_email or match_phone or match_agency or match_city or match_listings:
                filtered.append(item)
        return filtered

    return unified_list


# --- Listing Association & Disassociation Endpoints ---

@router.post("/contacts/link-listing")
def link_listing_to_contact(
    body: schemas.LinkListingRequest,
    db: Session = Depends(get_db)
):
    """
    Attaches a listing to an agent and/or agency.
    """
    listing = db.query(Listing).filter(Listing.id == body.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce non trouvée")

    if body.agent_id:
        agent = db.query(Agent).filter(Agent.id == body.agent_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent non trouvé")
        listing.main_agent_id = agent.id
        if agent.agency_id:
            listing.agency_id = agent.agency_id
        elif body.agency_id:
            listing.agency_id = body.agency_id
    elif body.agency_id:
        agency = db.query(Agency).filter(Agency.id == body.agency_id).first()
        if not agency:
            raise HTTPException(status_code=404, detail="Agence non trouvée")
        listing.agency_id = agency.id
    else:
        raise HTTPException(status_code=400, detail="Veuillez spécifier un agent ou une agence")

    db.commit()
    db.refresh(listing)
    return {
        "status": "success",
        "message": "Bien rattaché avec succès",
        "listing_id": listing.id,
        "main_agent_id": listing.main_agent_id,
        "agency_id": listing.agency_id
    }


@router.post("/contacts/unlink-listing")
def unlink_listing_from_contact(
    body: schemas.UnlinkListingRequest,
    db: Session = Depends(get_db)
):
    """
    Detaches a listing from its contact/agency.
    """
    listing = db.query(Listing).filter(Listing.id == body.listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce non trouvée")

    listing.main_agent_id = None
    listing.agency_id = None
    db.commit()
    return {"status": "success", "message": "Bien détaché avec succès", "listing_id": listing.id}


# --- Unassigned & Detected Contacts Endpoints ---

@router.get("/contacts/unassigned")
def list_unassigned_listings(
    page: int = Query(1, ge=1),
    limit: int = Query(15, ge=1, le=100),
    q: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Lists listings without any attached contact (main_agent_id IS NULL and agency_id IS NULL).
    Supports search and pagination.
    """
    query = db.query(Listing).filter(
        Listing.main_agent_id.is_(None),
        Listing.agency_id.is_(None),
        Listing.is_duplicate == False
    )

    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Listing.title.ilike(search),
                Listing.city.ilike(search),
                Listing.location.ilike(search),
                Listing.description_text.ilike(search)
            )
        )

    total = query.count()
    listings = query.order_by(Listing.date_added.desc()).offset((page - 1) * limit).limit(limit).all()

    items = [_format_listing_summary(l).model_dump() for l in listings]
    pages = (total + limit - 1) // limit if total > 0 else 1

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages
    }


@router.get("/contacts/detected")
def list_detected_contacts(
    page: int = Query(1, ge=1),
    limit: int = Query(15, ge=1, le=100),
    q: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Analyzes listings missing a contact and/or agency to detect potential contacts mentioned in the description.
    """
    query = db.query(Listing).filter(
        or_(
            Listing.main_agent_id.is_(None),
            Listing.agency_id.is_(None)
        ),
        Listing.description_text.isnot(None),
        Listing.is_duplicate == False
    ).order_by(Listing.date_added.desc())

    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Listing.title.ilike(search),
                Listing.city.ilike(search),
                Listing.location.ilike(search),
                Listing.description_text.ilike(search)
            )
        )

    all_candidates = query.all()
    detected_list = []

    for l in all_candidates:
        info = extract_contact_info_from_text(l.description_text or "")
        if info.get("has_detected"):
            detected_list.append({
                "listing": _format_listing_summary(l).model_dump(),
                "detected": info
            })

    total = len(detected_list)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    page_items = detected_list[start_idx:end_idx]
    pages = (total + limit - 1) // limit if total > 0 else 1

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages
    }


# --- Merge & Duplicate Detection Endpoints ---

@router.get("/contacts/merge-suggestions")
def get_merge_suggestions(db: Session = Depends(get_db)):
    """
    Computes potential duplicate contact suggestions based on name similarity and contact clues.
    """
    agents = db.query(Agent).all()
    agencies = db.query(Agency).all()
    suggestions = []

    def _similarity(s1: str, s2: str) -> float:
        if not s1 or not s2:
            return 0.0
        return difflib.SequenceMatcher(None, s1.lower().strip(), s2.lower().strip()).ratio()

    # 1. Compare Agents against Agents
    for i in range(len(agents)):
        for j in range(i + 1, len(agents)):
            a1 = agents[i]
            a2 = agents[j]
            name1 = f"{a1.first_name} {a1.last_name}"
            name2 = f"{a2.first_name} {a2.last_name}"
            name_score = _similarity(name1, name2)
            
            same_phone = bool(a1.phone_mobile and a2.phone_mobile and a1.phone_mobile.replace(" ", "") == a2.phone_mobile.replace(" ", ""))
            same_email = bool(a1.email and a2.email and a1.email.strip().lower() == a2.email.strip().lower())
            
            score = int(name_score * 100)
            reason = "Noms similaires"
            if same_phone or same_email:
                score = max(score, 95)
                reason = "Numéro de téléphone ou email identique"

            if score >= 65:
                suggestions.append({
                    "source": {
                        "type": "agent",
                        "id": a1.id,
                        "name": name1,
                        "email": a1.email,
                        "phone": a1.phone_mobile or a1.phone_landline,
                        "agency": a1.agency.commercial_name if a1.agency else None
                    },
                    "target": {
                        "type": "agent",
                        "id": a2.id,
                        "name": name2,
                        "email": a2.email,
                        "phone": a2.phone_mobile or a2.phone_landline,
                        "agency": a2.agency.commercial_name if a2.agency else None
                    },
                    "similarity_score": score,
                    "reason": reason
                })

    # 2. Compare Agencies against Agencies
    for i in range(len(agencies)):
        for j in range(i + 1, len(agencies)):
            ac1 = agencies[i]
            ac2 = agencies[j]
            name1 = ac1.commercial_name or ac1.legal_name
            name2 = ac2.commercial_name or ac2.legal_name
            score = int(_similarity(name1, name2) * 100)
            
            same_phone = bool(ac1.phone and ac2.phone and ac1.phone.replace(" ", "") == ac2.phone.replace(" ", ""))
            same_siret = bool(ac1.siret and ac2.siret and ac1.siret == ac2.siret)
            
            reason = "Raison sociale / enseigne similaire"
            if same_phone or same_siret:
                score = max(score, 95)
                reason = "SIRET ou téléphone identique"

            if score >= 65:
                suggestions.append({
                    "source": {
                        "type": "agency",
                        "id": ac1.id,
                        "name": name1,
                        "email": ac1.email,
                        "phone": ac1.phone,
                        "city": ac1.city
                    },
                    "target": {
                        "type": "agency",
                        "id": ac2.id,
                        "name": name2,
                        "email": ac2.email,
                        "phone": ac2.phone,
                        "city": ac2.city
                    },
                    "similarity_score": score,
                    "reason": reason
                })

    suggestions.sort(key=lambda s: s["similarity_score"], reverse=True)
    return suggestions


@router.post("/contacts/merge")
def merge_contacts(
    body: schemas.MergeContactsRequest,
    db: Session = Depends(get_db)
):
    """
    Merges a source contact into a target contact.
    Reassigns all listings and visits, copies over missing contact fields, and deletes the source contact.
    """
    if body.source_type == body.target_type and body.source_id == body.target_id:
        raise HTTPException(status_code=400, detail="Impossible de fusionner un contact avec lui-même.")

    if body.source_type == "agent" and body.target_type == "agent":
        source_agent = db.query(Agent).filter(Agent.id == body.source_id).first()
        target_agent = db.query(Agent).filter(Agent.id == body.target_id).first()
        if not source_agent or not target_agent:
            raise HTTPException(status_code=404, detail="Agent source ou cible non trouvé.")

        # 1. Reassign Listings
        listings = db.query(Listing).filter(Listing.main_agent_id == source_agent.id).all()
        for l in listings:
            l.main_agent_id = target_agent.id
            if target_agent.agency_id:
                l.agency_id = target_agent.agency_id

        # 2. Reassign VisitContacts
        vcs = db.query(VisitContact).filter(VisitContact.agent_id == source_agent.id).all()
        for vc in vcs:
            vc.agent_id = target_agent.id

        # 3. Fill missing fields on target
        if not target_agent.phone_mobile and source_agent.phone_mobile:
            target_agent.phone_mobile = source_agent.phone_mobile
        if not target_agent.phone_landline and source_agent.phone_landline:
            target_agent.phone_landline = source_agent.phone_landline
        if not target_agent.email and source_agent.email:
            target_agent.email = source_agent.email
        if not target_agent.agency_id and source_agent.agency_id:
            target_agent.agency_id = source_agent.agency_id
        if not target_agent.commission_rate and source_agent.commission_rate:
            target_agent.commission_rate = source_agent.commission_rate
        if source_agent.internal_notes:
            if target_agent.internal_notes:
                target_agent.internal_notes += f"\n[Fusion]: {source_agent.internal_notes}"
            else:
                target_agent.internal_notes = source_agent.internal_notes

        # 4. Clean up Google Contact if exists
        if source_agent.google_contact_resource_name:
            google_service.delete_google_contact(db, source_agent.google_contact_resource_name)

        # 5. Delete source agent
        db.delete(source_agent)
        db.commit()
        db.refresh(target_agent)

        # Sync target to Google Contacts
        google_service.sync_agent_to_google_contacts(db, target_agent)

        return {
            "status": "success",
            "message": f"Agents fusionnés avec succès dans '{target_agent.first_name} {target_agent.last_name}'.",
            "target_id": target_agent.id
        }

    elif body.source_type == "agency" and body.target_type == "agency":
        source_agency = db.query(Agency).filter(Agency.id == body.source_id).first()
        target_agency = db.query(Agency).filter(Agency.id == body.target_id).first()
        if not source_agency or not target_agency:
            raise HTTPException(status_code=404, detail="Agence source ou cible non trouvée.")

        # 1. Reassign Agents
        agents = db.query(Agent).filter(Agent.agency_id == source_agency.id).all()
        for a in agents:
            a.agency_id = target_agency.id

        # 2. Reassign Listings
        listings = db.query(Listing).filter(Listing.agency_id == source_agency.id).all()
        for l in listings:
            l.agency_id = target_agency.id

        # 3. Reassign VisitContacts
        vcs = db.query(VisitContact).filter(VisitContact.agency_id == source_agency.id).all()
        for vc in vcs:
            vc.agency_id = target_agency.id

        # 4. Fill missing fields
        if not target_agency.phone and source_agency.phone:
            target_agency.phone = source_agency.phone
        if not target_agency.email and source_agency.email:
            target_agency.email = source_agency.email
        if not target_agency.website and source_agency.website:
            target_agency.website = source_agency.website
        if not target_agency.city and source_agency.city:
            target_agency.city = source_agency.city
        if not target_agency.siret and source_agency.siret:
            target_agency.siret = source_agency.siret
        if not target_agency.carte_t_number and source_agency.carte_t_number:
            target_agency.carte_t_number = source_agency.carte_t_number
        if source_agency.reputation_notes:
            if target_agency.reputation_notes:
                target_agency.reputation_notes += f"\n[Fusion]: {source_agency.reputation_notes}"
            else:
                target_agency.reputation_notes = source_agency.reputation_notes

        # 5. Clean up Google Contact
        if source_agency.google_contact_resource_name:
            google_service.delete_google_contact(db, source_agency.google_contact_resource_name)

        db.delete(source_agency)
        db.commit()
        db.refresh(target_agency)

        google_service.sync_agency_to_google_contacts(db, target_agency)

        return {
            "status": "success",
            "message": f"Agences fusionnées avec succès dans '{target_agency.commercial_name or target_agency.legal_name}'.",
            "target_id": target_agency.id
        }

    else:
        raise HTTPException(
            status_code=400,
            detail="La fusion directe entre un Agent et une Agence n'est pas supportée. Veuillez rattacher l'agent à l'agence."
        )


# --- Agency CRUD Endpoints ---

@router.get("/agencies", response_model=List[schemas.AgencyResponse])
def list_agencies(
    q: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Agency)
    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Agency.legal_name.ilike(search),
                Agency.commercial_name.ilike(search),
                Agency.city.ilike(search)
            )
        )
    return query.order_by(Agency.legal_name).all()


@router.post("/agencies", response_model=schemas.AgencyResponse, status_code=status.HTTP_201_CREATED)
def create_agency(
    agency_in: schemas.AgencyCreate,
    db: Session = Depends(get_db)
):
    agency = Agency(**agency_in.model_dump())
    db.add(agency)
    db.commit()
    db.refresh(agency)

    # Sync to Google Contacts
    google_service.sync_agency_to_google_contacts(db, agency)
    return agency


@router.get("/agencies/{agency_id}", response_model=schemas.AgencyResponse)
def get_agency(
    agency_id: int,
    db: Session = Depends(get_db)
):
    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agence non trouvée")
    return agency


@router.put("/agencies/{agency_id}", response_model=schemas.AgencyResponse)
def update_agency(
    agency_id: int,
    agency_in: schemas.AgencyUpdateRequest,
    db: Session = Depends(get_db)
):
    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agence non trouvée")

    update_data = agency_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agency, field, value)

    db.commit()
    db.refresh(agency)

    # Sync to Google Contacts
    google_service.sync_agency_to_google_contacts(db, agency)
    return agency


@router.delete("/agencies/{agency_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agency(
    agency_id: int,
    db: Session = Depends(get_db)
):
    agency = db.query(Agency).filter(Agency.id == agency_id).first()
    if not agency:
        raise HTTPException(status_code=404, detail="Agence non trouvée")

    if agency.google_contact_resource_name:
        google_service.delete_google_contact(db, agency.google_contact_resource_name)

    db.delete(agency)
    db.commit()
    return None


# --- Agent CRUD Endpoints ---

@router.get("/agents", response_model=List[schemas.AgentResponse])
def list_agents(
    q: Optional[str] = None,
    agency_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Agent)
    if agency_id:
        query = query.filter(Agent.agency_id == agency_id)
    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Agent.first_name.ilike(search),
                Agent.last_name.ilike(search),
                Agent.email.ilike(search),
                Agent.title.ilike(search)
            )
        )
    agents = query.order_by(Agent.last_name, Agent.first_name).all()
    res = []
    for agent in agents:
        agent_dict = schemas.AgentResponse.model_validate(agent).model_dump()
        if agent.agency:
            agent_dict["agency_name"] = agent.agency.commercial_name or agent.agency.legal_name
        res.append(agent_dict)
    return res


@router.post("/agents", response_model=schemas.AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    agent_in: schemas.AgentCreate,
    db: Session = Depends(get_db)
):
    agent = Agent(**agent_in.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(agent)

    # Sync to Google Contacts
    google_service.sync_agent_to_google_contacts(db, agent)

    agent_dict = schemas.AgentResponse.model_validate(agent).model_dump()
    if agent.agency:
        agent_dict["agency_name"] = agent.agency.commercial_name or agent.agency.legal_name
    return agent_dict


@router.get("/agents/{agent_id}", response_model=schemas.AgentResponse)
def get_agent(
    agent_id: int,
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent non trouvé")
    agent_dict = schemas.AgentResponse.model_validate(agent).model_dump()
    if agent.agency:
        agent_dict["agency_name"] = agent.agency.commercial_name or agent.agency.legal_name
    return agent_dict


@router.put("/agents/{agent_id}", response_model=schemas.AgentResponse)
def update_agent(
    agent_id: int,
    agent_in: schemas.AgentUpdateRequest,
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent non trouvé")

    update_data = agent_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)

    db.commit()
    db.refresh(agent)

    # Sync to Google Contacts
    google_service.sync_agent_to_google_contacts(db, agent)

    agent_dict = schemas.AgentResponse.model_validate(agent).model_dump()
    if agent.agency:
        agent_dict["agency_name"] = agent.agency.commercial_name or agent.agency.legal_name
    return agent_dict


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent non trouvé")

    if agent.google_contact_resource_name:
        google_service.delete_google_contact(db, agent.google_contact_resource_name)

    db.delete(agent)
    db.commit()
    return None


# --- Global Search & Google Auth ---

@router.get("/contacts/search")
def search_all_contacts(
    q: str = Query("", min_length=1),
    db: Session = Depends(get_db)
):
    search = f"%{q.strip()}%"
    agents = db.query(Agent).filter(
        or_(
            Agent.first_name.ilike(search),
            Agent.last_name.ilike(search),
            Agent.email.ilike(search)
        )
    ).limit(10).all()

    agencies = db.query(Agency).filter(
        or_(
            Agency.legal_name.ilike(search),
            Agency.commercial_name.ilike(search)
        )
    ).limit(10).all()

    results = []
    for ag in agents:
        agency_name = (ag.agency.commercial_name or ag.agency.legal_name) if ag.agency else None
        results.append({
            "type": "agent",
            "id": ag.id,
            "name": f"{ag.first_name} {ag.last_name}".strip(),
            "title": ag.title,
            "email": ag.email,
            "phone": ag.phone_mobile or ag.phone_landline,
            "agency_name": agency_name
        })

    for ac in agencies:
        results.append({
            "type": "agency",
            "id": ac.id,
            "name": ac.commercial_name or ac.legal_name,
            "title": "Agence immobilière",
            "email": ac.email,
            "phone": ac.phone,
            "agency_name": ac.legal_name
        })

    return results


@router.get("/auth/google/status")
def google_auth_status(db: Session = Depends(get_db)):
    settings = db.query(GlobalSettings).first()
    connected = False
    if settings and settings.google_oauth_tokens_json:
        try:
            tok = json.loads(settings.google_oauth_tokens_json)
            connected = bool(tok.get("refresh_token") or tok.get("token"))
        except Exception:
            connected = False
    has_credentials = bool(settings and settings.google_oauth_credentials_json)
    return {
        "connected": connected,
        "pilot_email": google_service.get_pilot_email(db),
        "has_credentials": has_credentials
    }


@router.post("/auth/google/pilot-email")
def save_google_pilot_email(
    payload: Dict[str, str],
    db: Session = Depends(get_db)
):
    email = payload.get("email", "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="L'adresse e-mail est obligatoire.")
    
    settings = db.query(GlobalSettings).first()
    if not settings:
        settings = GlobalSettings()
        db.add(settings)
    
    settings.google_pilot_email = email
    db.commit()
    return {"status": "success", "message": "Adresse e-mail Google enregistrée avec succès."}


@router.post("/auth/google/credentials")
def save_google_credentials(
    credentials_input: Dict[str, Any],
    db: Session = Depends(get_db)
):
    settings = db.query(GlobalSettings).first()
    if not settings:
        settings = GlobalSettings()
        db.add(settings)

    if "client_id" in credentials_input and "client_secret" in credentials_input:
        credentials_json = {
            "web": {
                "client_id": credentials_input["client_id"].strip(),
                "client_secret": credentials_input["client_secret"].strip(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        }
    elif "web" in credentials_input or "installed" in credentials_input:
        credentials_json = credentials_input
    elif "credentials_json" in credentials_input:
        raw = credentials_input["credentials_json"]
        if isinstance(raw, str):
            credentials_json = json.loads(raw)
        else:
            credentials_json = raw
    else:
        credentials_json = credentials_input

    settings.google_oauth_credentials_json = json.dumps(credentials_json)
    db.commit()
    return {"status": "success", "message": "Identifiants Google OAuth configurés avec succès."}


@router.post("/auth/google/disconnect")
def google_auth_disconnect(db: Session = Depends(get_db)):
    settings = db.query(GlobalSettings).first()
    if settings:
        settings.google_oauth_tokens_json = None
        db.commit()
    return {"status": "success", "message": "Compte Google déconnecté."}


@router.post("/auth/google/test")
def google_auth_test(db: Session = Depends(get_db)):
    res = google_service.test_google_connection(db)
    return res


@router.get("/auth/google/login")
def google_auth_login(request: Request, db: Session = Depends(get_db)):
    settings = db.query(GlobalSettings).first()
    if not settings or not settings.google_oauth_credentials_json:
        raise HTTPException(
            status_code=400,
            detail="Les identifiants Google OAuth2 (Client ID & Secret) ne sont pas configurés."
        )

    try:
        from google_auth_oauthlib.flow import Flow
        client_config = json.loads(settings.google_oauth_credentials_json)
        redirect_uri = str(request.url_for("google_auth_callback"))
        flow = Flow.from_client_config(
            client_config,
            scopes=google_service.SCOPES,
            redirect_uri=redirect_uri
        )
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"
        )
        return {"authorization_url": authorization_url}
    except Exception as e:
        logger.error(f"Error initiating Google OAuth login: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auth/google/callback", name="google_auth_callback")
def google_auth_callback(code: str, request: Request, db: Session = Depends(get_db)):
    settings = db.query(GlobalSettings).first()
    if not settings or not settings.google_oauth_credentials_json:
        raise HTTPException(status_code=400, detail="Missing Google OAuth credentials.")

    try:
        from google_auth_oauthlib.flow import Flow
        client_config = json.loads(settings.google_oauth_credentials_json)
        redirect_uri = str(request.url_for("google_auth_callback"))
        flow = Flow.from_client_config(
            client_config,
            scopes=google_service.SCOPES,
            redirect_uri=redirect_uri
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials
        settings.google_oauth_tokens_json = credentials.to_json()
        db.commit()
        return RedirectResponse(url="/admin/maintenance?google=connected")
    except Exception as e:
        logger.error(f"Error handling Google OAuth callback: {e}")
        return RedirectResponse(url="/admin/maintenance?google=error")
