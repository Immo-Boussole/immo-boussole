import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from app.models import GlobalSettings, Agent, Agency, Visit, Listing, VisitContact

logger = logging.getLogger(__name__)

# Scopes needed for Google Calendar and People API (Contacts)
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts"
]

PILOT_EMAIL = "GOOGLE_ACCOUNT_EMAIL@gmail.com"


def get_google_credentials(db: Session):
    """
    Retrieves and refreshes Google OAuth2 Credentials object from GlobalSettings.
    Returns None if credentials or tokens are missing/invalid.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        logger.warning("google-auth dependencies not installed.")
        return None

    settings = db.query(GlobalSettings).first()
    if not settings or not settings.google_oauth_tokens_json:
        return None

    try:
        token_data = json.loads(settings.google_oauth_tokens_json)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save updated token
            settings.google_oauth_tokens_json = creds.to_json()
            db.commit()
        return creds if creds.valid else None
    except Exception as e:
        logger.error(f"Error restoring Google credentials: {e}")
        return None


def get_google_calendar_service(db: Session):
    """Returns Google Calendar API service instance or None."""
    creds = get_google_credentials(db)
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Error building Google Calendar service: {e}")
        return None


def get_google_people_service(db: Session):
    """Returns Google People API (Contacts) service instance or None."""
    creds = get_google_credentials(db)
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("people", "v1", credentials=creds)
    except Exception as e:
        logger.error(f"Error building Google People service: {e}")
        return None


# --- Google Contacts Sync Functions ---

def sync_agent_to_google_contacts(db: Session, agent: Agent) -> Optional[str]:
    """
    Creates or updates an Agent in Google Contacts.
    Returns the Google contact resourceName.
    """
    service = get_google_people_service(db)
    if not service:
        logger.info("Google Contacts sync skipped (service unavailable).")
        return None

    try:
        # Build contact payload
        names = [{"givenName": agent.first_name, "familyName": agent.last_name}]
        phone_numbers = []
        if agent.phone_mobile:
            phone_numbers.append({"value": agent.phone_mobile, "type": "mobile"})
        if agent.phone_landline:
            phone_numbers.append({"value": agent.phone_landline, "type": "work"})

        email_addresses = []
        if agent.email:
            email_addresses.append({"value": agent.email, "type": "work"})

        organizations = []
        if agent.agency:
            org = {"name": agent.agency.commercial_name or agent.agency.legal_name}
            if agent.title:
                org["title"] = agent.title
            organizations.append(org)

        biographies = []
        notes = []
        if agent.internal_notes:
            notes.append(f"Notes: {agent.internal_notes}")
        if agent.commission_rate:
            notes.append(f"Commission: {agent.commission_rate}%")
        if notes:
            biographies.append({"value": "\n".join(notes)})

        body = {
            "names": names,
            "phoneNumbers": phone_numbers,
            "emailAddresses": email_addresses,
            "organizations": organizations,
            "biographies": biographies,
        }

        if agent.google_contact_resource_name:
            # Get existing person to get current etag
            try:
                existing = service.people().get(
                    resourceName=agent.google_contact_resource_name,
                    personFields="names,phoneNumbers,emailAddresses,organizations,biographies"
                ).execute()
                body["etag"] = existing.get("etag")
                updated = service.people().updateContact(
                    resourceName=agent.google_contact_resource_name,
                    updatePersonFields="names,phoneNumbers,emailAddresses,organizations,biographies",
                    body=body
                ).execute()
                return updated.get("resourceName")
            except Exception as ex:
                logger.warning(f"Failed to update contact {agent.google_contact_resource_name}, creating new: {ex}")
                agent.google_contact_resource_name = None

        # Create new contact
        created = service.people().createContact(body=body).execute()
        res_name = created.get("resourceName")
        agent.google_contact_resource_name = res_name
        db.commit()
        return res_name
    except Exception as e:
        logger.error(f"Error syncing agent {agent.id} to Google Contacts: {e}")
        return None


def sync_agency_to_google_contacts(db: Session, agency: Agency) -> Optional[str]:
    """
    Creates or updates an Agency in Google Contacts.
    """
    service = get_google_people_service(db)
    if not service:
        return None

    try:
        names = [{"givenName": agency.commercial_name or agency.legal_name, "familyName": "(Agence Immo)"}]
        phone_numbers = []
        if agency.phone:
            phone_numbers.append({"value": agency.phone, "type": "work"})
        email_addresses = []
        if agency.email:
            email_addresses.append({"value": agency.email, "type": "work"})
        organizations = [{"name": agency.legal_name}]

        biographies = []
        notes = []
        if agency.siret:
            notes.append(f"SIRET: {agency.siret}")
        if agency.carte_t_number:
            notes.append(f"Carte T: {agency.carte_t_number}")
        if agency.reputation_notes:
            notes.append(f"Réputation: {agency.reputation_notes}")
        if notes:
            biographies.append({"value": "\n".join(notes)})

        body = {
            "names": names,
            "phoneNumbers": phone_numbers,
            "emailAddresses": email_addresses,
            "organizations": organizations,
            "biographies": biographies,
        }

        if agency.google_contact_resource_name:
            try:
                existing = service.people().get(
                    resourceName=agency.google_contact_resource_name,
                    personFields="names,phoneNumbers,emailAddresses,organizations,biographies"
                ).execute()
                body["etag"] = existing.get("etag")
                updated = service.people().updateContact(
                    resourceName=agency.google_contact_resource_name,
                    updatePersonFields="names,phoneNumbers,emailAddresses,organizations,biographies",
                    body=body
                ).execute()
                return updated.get("resourceName")
            except Exception:
                agency.google_contact_resource_name = None

        created = service.people().createContact(body=body).execute()
        res_name = created.get("resourceName")
        agency.google_contact_resource_name = res_name
        db.commit()
        return res_name
    except Exception as e:
        logger.error(f"Error syncing agency {agency.id} to Google Contacts: {e}")
        return None


def delete_google_contact(db: Session, resource_name: str) -> bool:
    """Deletes a contact from Google Contacts by resourceName."""
    if not resource_name:
        return False
    service = get_google_people_service(db)
    if not service:
        return False
    try:
        service.people().deleteContact(resourceName=resource_name).execute()
        return True
    except Exception as e:
        logger.error(f"Error deleting Google Contact {resource_name}: {e}")
        return False


# --- Google Calendar Sync Functions ---

def sync_visit_to_google_calendar(db: Session, visit: Visit) -> Optional[str]:
    """
    Creates or updates a Visit/Offer event in Google Calendar.
    Sends automatic invitations to participants.
    Returns the Google Calendar event ID.
    """
    service = get_google_calendar_service(db)
    if not service:
        logger.info("Google Calendar sync skipped (service unavailable).")
        return None

    try:
        listing = db.query(Listing).filter(Listing.id == visit.listing_id).first()
        listing_title = listing.title if listing else f"Annonce #{visit.listing_id}"
        listing_address = listing.location if (listing and listing.location) else ""

        type_labels = {
            "visite": "Visite",
            "contre_visite": "Contre-visite",
            "proposition_offre": "Proposition d'offre",
            "contre_proposition_offre": "Contre-proposition d'offre"
        }
        event_type_label = type_labels.get(visit.visit_type, visit.visit_type.capitalize())
        summary = f"{event_type_label} - {listing_title}"

        start_time = visit.scheduled_at
        end_time = start_time + timedelta(hours=1)

        desc_lines = [
            f"Type: {event_type_label}",
            f"Statut: {visit.status}",
            f"Visiteur: {visit.visitor or 'Non spécifié'}"
        ]
        if listing:
            desc_lines.append(f"Bien: {listing.title}")
            desc_lines.append(f"Prix: {listing.price} €" if listing.price else "")
            desc_lines.append(f"Lien: {listing.url}")

        if visit.notes:
            desc_lines.append(f"\nNotes:\n{visit.notes}")

        attendees = []
        if visit.visit_contacts:
            desc_lines.append("\nContacts associés:")
            for vc in visit.visit_contacts:
                if vc.agent:
                    agent_str = f"- Agent: {vc.agent.first_name} {vc.agent.last_name}"
                    if vc.agent.phone_mobile:
                        agent_str += f" ({vc.agent.phone_mobile})"
                    desc_lines.append(agent_str)
                    if vc.agent.email:
                        attendees.append({"email": vc.agent.email, "displayName": f"{vc.agent.first_name} {vc.agent.last_name}"})
                elif vc.agency:
                    agency_str = f"- Agence: {vc.agency.commercial_name or vc.agency.legal_name}"
                    if vc.agency.phone:
                        agency_str += f" ({vc.agency.phone})"
                    desc_lines.append(agency_str)
                    if vc.agency.email:
                        attendees.append({"email": vc.agency.email, "displayName": vc.agency.legal_name})

        event_body = {
            "summary": summary,
            "location": listing_address,
            "description": "\n".join(desc_lines),
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Europe/Paris",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Europe/Paris",
            },
            "attendees": attendees,
        }

        if visit.google_event_id:
            try:
                updated_event = service.events().patch(
                    calendarId="primary",
                    eventId=visit.google_event_id,
                    body=event_body,
                    sendUpdates="all"
                ).execute()
                return updated_event.get("id")
            except Exception as ex:
                logger.warning(f"Event {visit.google_event_id} update failed, re-creating: {ex}")
                visit.google_event_id = None

        created_event = service.events().insert(
            calendarId="primary",
            body=event_body,
            sendUpdates="all"
        ).execute()

        event_id = created_event.get("id")
        visit.google_event_id = event_id
        db.commit()
        return event_id

    except Exception as e:
        logger.error(f"Error syncing visit {visit.id} to Google Calendar: {e}")
        return None


def delete_google_calendar_event(db: Session, google_event_id: str) -> bool:
    """Deletes an event from Google Calendar by ID."""
    if not google_event_id:
        return False
    service = get_google_calendar_service(db)
    if not service:
        return False
    try:
        service.events().delete(
            calendarId="primary",
            eventId=google_event_id,
            sendUpdates="all"
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Error deleting Google Calendar event {google_event_id}: {e}")
        return False


def test_google_connection(db: Session) -> Dict[str, Any]:
    """
    Tests live connection to Google Calendar & Contacts APIs using current credentials & tokens.
    Returns status details.
    """
    creds = get_google_credentials(db)
    if not creds:
        return {
            "success": False,
            "message": "Aucun jeton OAuth valide disponible. Veuillez autoriser l'accès avec Google."
        }

    calendar_ok = False
    contacts_ok = False
    details = []

    # Test Calendar
    try:
        service_cal = get_google_calendar_service(db)
        if service_cal:
            service_cal.calendarList().get(calendarId="primary").execute()
            calendar_ok = True
            details.append("Google Calendar API : OK")
    except Exception as e:
        details.append(f"Google Calendar API : Erreur ({str(e)})")

    # Test Contacts (People API)
    try:
        service_ppl = get_google_people_service(db)
        if service_ppl:
            service_ppl.people().get(resourceName="people/me", personFields="names,emailAddresses").execute()
            contacts_ok = True
            details.append("Google Contacts API (People API) : OK")
    except Exception as e:
        details.append(f"Google Contacts API : Erreur ({str(e)})")

    success = calendar_ok and contacts_ok
    return {
        "success": success,
        "calendar_ok": calendar_ok,
        "contacts_ok": contacts_ok,
        "message": " — ".join(details) if details else ("Connexion OK" if success else "Échec de connexion")
    }

