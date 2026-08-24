#!/usr/bin/env python3
"""
Unit test for visit management database models, REST API endpoints, and FastMCP tools.
"""
import sys
import os
import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from fastapi.testclient import TestClient
from app.main import app, user_required, login_required
from app.models import Listing, Visit, VisitContact, Agent, Agency, Source, ListingStatus
from app import schemas
from app.mcp_server import (
    tool_toggle_listing_to_visit,
    tool_schedule_visit,
    tool_list_visits,
    tool_update_visit,
    tool_delete_visit,
    tool_get_stats
)

def test_visits_flow():
    # Ensure migrations run
    run_migrations()
    db = SessionLocal()
    app.dependency_overrides[user_required] = lambda: {"username": "admin", "role": "admin"}
    app.dependency_overrides[login_required] = lambda: {"username": "admin", "role": "admin"}
    client = TestClient(app)

    try:
        # 1. Create a dummy listing and dummy agent / agency
        test_agency = Agency(legal_name="Agence Test Visite", commercial_name="Agence Visite", city="Grenoble")
        db.add(test_agency)
        db.commit()
        db.refresh(test_agency)

        test_agent = Agent(first_name="Sophie", last_name="Martin", email="sophie.martin@test.fr", agency_id=test_agency.id)
        db.add(test_agent)
        db.commit()
        db.refresh(test_agent)

        test_listing = Listing(
            title="Appartement Test Visite",
            url=f"http://example.com/test-visit-{datetime.datetime.now().timestamp()}",
            price=250000.0,
            city="Grenoble",
            area=65.0,
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            to_visit=False
        )
        db.add(test_listing)
        db.commit()
        db.refresh(test_listing)
        listing_id = test_listing.id
        print(f"Created test listing #{listing_id}")

        # 2. Test MCP tool: toggle_listing_to_visit
        res = tool_toggle_listing_to_visit(listing_id)
        print("Toggle to visit res:", res)
        db.refresh(test_listing)
        assert test_listing.to_visit == True, "Listing should be marked to_visit=True"

        # 3. Test MCP tool: schedule_visit
        sch_at = "2026-08-20T14:00:00"
        sch_res = tool_schedule_visit(
            listing_id=listing_id,
            scheduled_at=sch_at,
            visit_type="visite",
            visitor="Jean Dupont",
            notes="Clés à récupérer à l'agence"
        )
        print("Schedule visit res:", sch_res)
        assert "success" in sch_res

        # 4. Test MCP tool: list_visits
        visits_json = tool_list_visits(listing_id=listing_id)
        print("List visits res:", visits_json)
        assert f'"listing_id": {listing_id}' in visits_json

        # Parse visit_id from DB
        v_db = db.query(Visit).filter(Visit.listing_id == listing_id).first()
        assert v_db is not None
        visit_id = v_db.id

        # 5. Test MCP tool: update_visit
        up_res = tool_update_visit(visit_id=visit_id, status="effectuee", notes="Visite excellente, à revoir en contre-visite")
        print("Update visit res:", up_res)
        db.refresh(v_db)
        assert v_db.status == "effectuee"

        # 6. Test REST API: Create Visit with contact and update_listing_contact
        resp = client.post("/api/visites", json={
            "listing_id": listing_id,
            "step_family": "contact",
            "step": "appel_direct",
            "status": "effectuee",
            "scheduled_at": "2026-08-21T10:00:00",
            "visitor": "Jean Dupont",
            "notes": "1er contact téléphonique avec Sophie Martin",
            "agent_ids": [test_agent.id],
            "update_listing_contact": True
        })
        assert resp.status_code == 200, f"API create visit failed: {resp.text}"
        v_data = resp.json()
        assert v_data["step_family"] == "contact"
        assert v_data["step"] == "appel_direct"
        assert len(v_data["contacts"]) == 1
        assert v_data["contacts"][0]["agent_id"] == test_agent.id

        db.refresh(test_listing)
        assert test_listing.main_agent_id == test_agent.id, "Listing main_agent_id should have been updated"
        assert test_listing.agency_id == test_agency.id, "Listing agency_id should have been synced from agent"

        # 7. Test REST API: Update Visit with agency and update_listing_contact
        v2_id = v_data["id"]
        resp_up = client.put(f"/api/visites/{v2_id}", json={
            "agency_ids": [test_agency.id],
            "agent_ids": [],
            "update_listing_contact": True
        })
        assert resp_up.status_code == 200, f"API update visit failed: {resp_up.text}"
        v2_updated = resp_up.json()
        assert len(v2_updated["contacts"]) == 1
        assert v2_updated["contacts"][0]["agency_id"] == test_agency.id

        db.refresh(test_listing)
        assert test_listing.agency_id == test_agency.id

        # 8. Check stats tool and GET /visites route split counters
        stats_json = tool_get_stats()
        print("Stats res:", stats_json)
        assert "annonces_a_visiter" in stats_json
        assert "total_visites" in stats_json

        # Test GET /visites page counter split
        visites_html_resp = client.get("/visites", headers={"Accept-Language": "fr"})
        assert visites_html_resp.status_code == 200
        assert "Rendez-vous" in visites_html_resp.text
        assert "Biens visités" in visites_html_resp.text
        assert 'id="statBiensVisitesCnt"' in visites_html_resp.text

        # 9. Clean up test data
        tool_delete_visit(visit_id)
        tool_delete_visit(v2_id)
        db.delete(test_listing)
        db.delete(test_agent)
        db.delete(test_agency)
        db.commit()
        print("Cleaned up test data successfully!")
        print("ALL VISIT & CONTACT TESTS PASSED!")

    finally:
        db.close()

if __name__ == "__main__":
    test_visits_flow()
