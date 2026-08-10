from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import json
import logging

from app.database import get_db
from app.models import Agency, Agent, GlobalSettings, VisitContact
from app import schemas
from app import google_service

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Agency Endpoints ---

@router.get("/agencies", response_model=List[schemas.AgencyResponse])
def list_agencies(
    q: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Agency)
    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            (Agency.legal_name.ilike(search)) |
            (Agency.commercial_name.ilike(search)) |
            (Agency.city.ilike(search))
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


# --- Agent Endpoints ---

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
            (Agent.first_name.ilike(search)) |
            (Agent.last_name.ilike(search)) |
            (Agent.email.ilike(search)) |
            (Agent.title.ilike(search))
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
        (Agent.first_name.ilike(search)) |
        (Agent.last_name.ilike(search)) |
        (Agent.email.ilike(search))
    ).limit(10).all()

    agencies = db.query(Agency).filter(
        (Agency.legal_name.ilike(search)) |
        (Agency.commercial_name.ilike(search))
    ).limit(10).all()

    results = []
    for ag in agents:
        agency_name = (ag.agency.commercial_name or ag.agency.legal_name) if ag.agency else None
        results.append({
            "type": "agent",
            "id": ag.id,
            "name": f"{ag.first_name} {ag.last_name}",
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
        "pilot_email": google_service.PILOT_EMAIL,
        "has_credentials": has_credentials
    }


@router.post("/auth/google/credentials")
def save_google_credentials(
    credentials_json: Dict[str, Any],
    db: Session = Depends(get_db)
):
    settings = db.query(GlobalSettings).first()
    if not settings:
        settings = GlobalSettings()
        db.add(settings)
    settings.google_oauth_credentials_json = json.dumps(credentials_json)
    db.commit()
    return {"status": "success", "message": "Identifiants Google OAuth configurés."}


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
        return RedirectResponse(url="/profile?google=connected")
    except Exception as e:
        logger.error(f"Error handling Google OAuth callback: {e}")
        return RedirectResponse(url="/profile?google=error")
