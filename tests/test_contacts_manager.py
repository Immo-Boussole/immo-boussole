#!/usr/bin/env python3
"""
Unit and integration tests for the enriched Contact Manager:
- Regex and heuristic contact extraction from descriptions
- Unified contact overview
- Listing linking and unlinking
- Contact merge and transfer of attached listings & visits
- Unassigned & detected listings endpoints
"""
import sys
import os
import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import Agency, Agent, Listing, Visit, VisitContact, Source, ListingStatus
from app.services import extract_contact_info_from_text
from app.api.v1.endpoints.contacts import (
    get_contacts_overview,
    link_listing_to_contact,
    unlink_listing_from_contact,
    list_unassigned_listings,
    list_detected_contacts,
    get_merge_suggestions,
    merge_contacts
)
from app import schemas


def test_contact_extraction_from_description():
    # 1. Text with agent name, agency and mobile phone
    desc1 = "Magnifique appartement T3 lumineux. Contactez Marc Dupont au 06 12 34 56 78 de chez iad France pour organiser une visite."
    info1 = extract_contact_info_from_text(desc1)
    assert info1["has_detected"] is True
    assert "06 12 34 56 78" in info1["phones"]
    assert info1["first_name"] == "Marc"
    assert info1["last_name"] == "DUPONT"
    assert info1["agency_name"] == "iad France"

    # 2. Text with email and phone
    desc2 = "Maison de village à rénover. Pour plus d'informations: contact@immo-alpes.fr ou au 04.76.11.22.33. Agence Immobilière Centrale."
    info2 = extract_contact_info_from_text(desc2)
    assert info2["has_detected"] is True
    assert "04 76 11 22 33" in info2["phones"]
    assert "contact@immo-alpes.fr" in info2["emails"]
    assert info2["agency_name"] is not None

    # 3. Empty text
    info3 = extract_contact_info_from_text("")
    assert info3["has_detected"] is False


def test_contacts_manager_full_flow():
    run_migrations()
    db = SessionLocal()

    try:
        # 1. Setup Agency & Agent
        agency = Agency(
            legal_name="Agence du Centre SAS",
            commercial_name="Centre Immo Lyon",
            city="Lyon",
            phone="0478000000",
            email="contact@centre-immo.fr"
        )
        db.add(agency)
        db.commit()
        db.refresh(agency)

        agent1 = Agent(
            first_name="Jean",
            last_name="Dupont",
            title="Négociateur",
            phone_mobile="0611223344",
            email="j.dupont@centre-immo.fr",
            agency_id=agency.id
        )
        agent2 = Agent(
            first_name="Jean",
            last_name="Dupond",  # Similar name for merge test
            title="Agent Commercial",
            phone_mobile="0611223344",  # Same phone
            email="j.dupond@gmail.com"
        )
        db.add_all([agent1, agent2])
        db.commit()
        db.refresh(agent1)
        db.refresh(agent2)

        # 2. Create Listings (one unassigned with detected contact, one normal)
        listing1 = Listing(
            title="Appartement T2 Proche Gare",
            url=f"http://example.com/test-cm-1-{datetime.datetime.now().timestamp()}",
            price=185000.0,
            city="Lyon",
            area=45.0,
            rooms=2,
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            description_text="Superbe T2 rénové. Contactez Jean Dupont au 06 11 22 33 44 pour visiter."
        )
        listing2 = Listing(
            title="Maison avec Jardin",
            url=f"http://example.com/test-cm-2-{datetime.datetime.now().timestamp()}",
            price=390000.0,
            city="Lyon",
            area=110.0,
            rooms=5,
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            main_agent_id=agent2.id
        )
        db.add_all([listing1, listing2])
        db.commit()
        db.refresh(listing1)
        db.refresh(listing2)

        # 3. Test link listing
        link_res = link_listing_to_contact(
            schemas.LinkListingRequest(listing_id=listing1.id, agent_id=agent1.id),
            db=db
        )
        assert link_res["status"] == "success"
        db.refresh(listing1)
        assert listing1.main_agent_id == agent1.id
        assert listing1.agency_id == agency.id

        # 4. Test contacts overview
        overview = get_contacts_overview(db=db)
        assert len(overview) >= 2
        # Check alphabetical sorting
        names = [(item.last_name or item.name or "").lower() for item in overview]
        assert names == sorted(names)
        agent1_item = next((item for item in overview if item.id == agent1.id and item.contact_type == "agent"), None)
        assert agent1_item is not None
        assert len(agent1_item.attached_listings) == 1
        assert agent1_item.attached_listings[0].id == listing1.id
        assert agent1_item.attached_listings[0].agent_name == "Jean Dupont"
        assert agent1_item.attached_listings[0].agency_name == "Centre Immo Lyon"

        # 5. Test unlink listing
        unlink_res = unlink_listing_from_contact(
            schemas.UnlinkListingRequest(listing_id=listing1.id),
            db=db
        )
        assert unlink_res["status"] == "success"
        db.refresh(listing1)
        assert listing1.main_agent_id is None

        # 6. Test unassigned listings endpoint
        unassigned_res = list_unassigned_listings(page=1, limit=10, db=db)
        assert unassigned_res["total"] >= 1
        assert any(item["id"] == listing1.id for item in unassigned_res["items"])

        # 7. Test detected contacts endpoint
        detected_res = list_detected_contacts(page=1, limit=10, db=db)
        assert detected_res["total"] >= 1
        detected_item = next((item for item in detected_res["items"] if item["listing"]["id"] == listing1.id), None)
        assert detected_item is not None
        assert detected_item["detected"]["has_detected"] is True
        # listing2 has agent2 attached and no agency -> detected endpoint returns listing2 with main_agent_id and agent_name
        detected_item_2 = next((item for item in detected_res["items"] if item["listing"]["id"] == listing2.id), None)
        if detected_item_2:
            assert detected_item_2["listing"]["main_agent_id"] == agent2.id
            assert detected_item_2["listing"]["agent_name"] == "Jean Dupond"

        # 8. Test merge suggestions
        suggestions = get_merge_suggestions(db=db)
        assert len(suggestions) >= 1
        # Similar name or same phone between agent1 and agent2
        assert any(s["similarity_score"] >= 65 for s in suggestions)

        # 9. Test merge contacts (agent2 -> agent1)
        # Agent2 has listing2 attached
        merge_res = merge_contacts(
            schemas.MergeContactsRequest(
                source_type="agent",
                source_id=agent2.id,
                target_type="agent",
                target_id=agent1.id
            ),
            db=db
        )
        assert merge_res["status"] == "success"
        db.refresh(listing2)
        # Verify listing2 has been transferred to agent1
        assert listing2.main_agent_id == agent1.id
        # Verify agent2 is deleted
        deleted_agent2 = db.query(Agent).filter(Agent.id == agent2.id).first()
        assert deleted_agent2 is None

        # Cleanup
        db.query(Listing).filter(Listing.id.in_([listing1.id, listing2.id])).delete(synchronize_session=False)
        db.delete(agent1)
        db.delete(agency)
        db.commit()

    finally:
        db.close()


def test_link_listing_with_agency_assignment():
    run_migrations()
    db = SessionLocal()

    try:
        # Create 2 agencies
        agency1 = Agency(legal_name="Agence Alpha", commercial_name="Alpha Immo", city="Grenoble")
        agency2 = Agency(legal_name="Agence Beta", commercial_name="Beta Immo", city="Grenoble")
        db.add_all([agency1, agency2])
        db.commit()
        db.refresh(agency1)
        db.refresh(agency2)

        # Create an agent without agency
        agent = Agent(first_name="Claire", last_name="Morel", email="claire@test.fr")
        db.add(agent)
        db.commit()
        db.refresh(agent)
        assert agent.agency_id is None

        # Create a listing
        listing = Listing(
            title="Appartement T3 Centre",
            url=f"http://example.com/test-assign-{datetime.datetime.now().timestamp()}",
            price=200000.0,
            city="Grenoble",
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)

        # 1. Link agent and assign agency1
        res1 = link_listing_to_contact(
            schemas.LinkListingRequest(listing_id=listing.id, agent_id=agent.id, agency_id=agency1.id),
            db=db
        )
        assert res1["status"] == "success"
        db.refresh(agent)
        db.refresh(listing)
        assert agent.agency_id == agency1.id
        assert listing.main_agent_id == agent.id
        assert listing.agency_id == agency1.id

        # 2. Reassign to agency2 without page reload / in one step
        res2 = link_listing_to_contact(
            schemas.LinkListingRequest(listing_id=listing.id, agent_id=agent.id, agency_id=agency2.id),
            db=db
        )
        assert res2["status"] == "success"
        db.refresh(agent)
        db.refresh(listing)
        assert agent.agency_id == agency2.id
        assert listing.main_agent_id == agent.id
        assert listing.agency_id == agency2.id

        # 3. Detach agency by setting agency_id = 0
        res3 = link_listing_to_contact(
            schemas.LinkListingRequest(listing_id=listing.id, agent_id=agent.id, agency_id=0),
            db=db
        )
        assert res3["status"] == "success"
        db.refresh(agent)
        db.refresh(listing)
        assert agent.agency_id is None
        assert listing.main_agent_id == agent.id
        assert listing.agency_id is None

        # 4. Cleanup
        db.query(Listing).filter(Listing.id == listing.id).delete(synchronize_session=False)
        db.delete(agent)
        db.delete(agency1)
        db.delete(agency2)
        db.commit()

    finally:
        db.close()


if __name__ == "__main__":
    print("Running test_contact_extraction_from_description()...")
    test_contact_extraction_from_description()
    print("Running test_contacts_manager_full_flow()...")
    test_contacts_manager_full_flow()
    print("Running test_link_listing_with_agency_assignment()...")
    test_link_listing_with_agency_assignment()
    print("ALL CONTACT MANAGER TESTS PASSED SUCCESSFULLY!")
