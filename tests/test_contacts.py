#!/usr/bin/env python3
"""
Unit test for Contact Manager (Agencies, Agents) and Google integration.
"""
import sys
import os
import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import Agency, Agent, Listing, Visit, VisitContact, Source, ListingStatus, GlobalSettings
from app import schemas
from app import google_service


def test_contacts_and_sync_flow():
    # Ensure migrations run
    run_migrations()
    db = SessionLocal()

    try:
        # 1. Create an Agency
        agency = Agency(
            legal_name="Immobilière des Alpes SARL",
            commercial_name="Alpes Immo Grenoble",
            address="15 Boulevard Gambetta",
            city="Grenoble",
            postal_code="38000",
            phone="0476000000",
            email="contact@alpes-immo.fr",
            siret="12345678900012",
            carte_t_number="CPI 3801 2020 000 012",
            guarantor="Garantie Immobilier SA",
            reputation_notes="Excellente agence réactive"
        )
        db.add(agency)
        db.commit()
        db.refresh(agency)
        agency_id = agency.id
        print(f"Created agency #{agency_id}: {agency.commercial_name}")
        assert agency.id is not None

        # 2. Create an Agent linked to Agency
        agent = Agent(
            first_name="Marc",
            last_name="Vidal",
            title="Négociateur Senior",
            phone_mobile="0612345678",
            phone_landline="0476000001",
            email="m.vidal@alpes-immo.fr",
            agency_id=agency_id,
            communication_prefs="SMS, Email",
            commission_rate=4.5,
            internal_notes="Très efficace sur les appartements T3"
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
        agent_id = agent.id
        print(f"Created agent #{agent_id}: {agent.first_name} {agent.last_name}")
        assert agent.agency_id == agency_id
        assert agent.agency.commercial_name == "Alpes Immo Grenoble"

        # 3. Create a Listing and link agent
        listing = Listing(
            title="Appartement 3 pièces Haussmannien",
            url=f"http://example.com/test-contact-listing-{datetime.datetime.now().timestamp()}",
            price=320000.0,
            city="Grenoble",
            area=82.0,
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            main_agent_id=agent_id,
            agency_id=agency_id
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)
        assert listing.main_agent_id == agent_id
        assert listing.agency_id == agency_id

        # 4. Create a Visit and link VisitContact
        scheduled_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)
        visit = Visit(
            listing_id=listing.id,
            visit_type="visite",
            step_family="visite",
            step="1ere_visite",
            scheduled_at=scheduled_time,
            status="programme",
            visitor="Jean Dupont",
            notes="Accès via digicode 1234"
        )
        db.add(visit)
        db.commit()
        db.refresh(visit)

        # Attach VisitContact
        vc = VisitContact(visit_id=visit.id, agent_id=agent_id, agency_id=agency_id)
        db.add(vc)
        db.commit()
        db.refresh(visit)

        assert len(visit.visit_contacts) == 1
        assert visit.visit_contacts[0].agent_id == agent_id

        # 5. Test Google Services (Graceful fallback when tokens not configured)
        creds = google_service.get_google_credentials(db)
        assert creds is None  # Should safely return None when not configured

        c_name = google_service.sync_agent_to_google_contacts(db, agent)
        assert c_name is None  # Gracefully returns None

        ev_id = google_service.sync_visit_to_google_calendar(db, visit)
        assert ev_id is None  # Gracefully returns None

        # 6. Cleanup
        db.delete(visit)
        db.delete(listing)
        db.delete(agent)
        db.delete(agency)
        db.commit()
        print("Cleaned up test data cleanly!")

    finally:
        db.close()


if __name__ == "__main__":
    test_contacts_and_sync_flow()
    print("ALL CONTACTS & GOOGLE TESTS PASSED!")
