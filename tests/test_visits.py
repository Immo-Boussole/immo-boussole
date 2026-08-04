#!/usr/bin/env python3
"""
Unit test for visit management database models, REST API endpoints, and FastMCP tools.
"""
import sys
import os
import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import Listing, Visit, Source, ListingStatus
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

    try:
        # 1. Create a dummy listing
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

        # 6. Test MCP tool: schedule counter-visit
        sch_res2 = tool_schedule_visit(
            listing_id=listing_id,
            scheduled_at="2026-08-25T16:00:00",
            visit_type="contre_visite",
            visitor="Jean & Marie",
            notes="Contre-visite avec l'artisan"
        )
        print("Schedule counter-visit res:", sch_res2)

        # 7. Check stats tool includes visits
        stats_json = tool_get_stats()
        print("Stats res:", stats_json)
        assert "annonces_a_visiter" in stats_json
        assert "total_visites" in stats_json

        # 8. Clean up test data
        tool_delete_visit(visit_id)
        v2_db = db.query(Visit).filter(Visit.listing_id == listing_id).all()
        for v in v2_db:
            db.delete(v)
        db.delete(test_listing)
        db.commit()
        print("Cleaned up test data successfully!")
        print("ALL VISIT TESTS PASSED!")

    finally:
        db.close()

if __name__ == "__main__":
    test_visits_flow()
