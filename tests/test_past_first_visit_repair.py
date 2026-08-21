import sys
import os
import unittest
import datetime
from datetime import timezone
import asyncio
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, run_migrations
from app.models import Listing, Visit, Source, ListingStatus
from app.db_maintenance import (
    identify_problems,
    identify_problems_with_details,
    repair_listings_batch_task,
    PAST_FIRST_VISIT_NOT_DONE,
    SAFE_PROBLEM_TYPES
)


class TestPastFirstVisitRepair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        # Create test listing
        self.listing = Listing(
            title="Appartement Test Visite Passée",
            url=f"http://example.com/test-past-visit-{uuid.uuid4().hex[:8]}",
            price=240000.0,
            city="Grenoble (38000)",
            location="Grenoble (38000)",
            area=60.0,
            source=Source.MANUAL,
            status=ListingStatus.ACTIVE,
            to_visit=True,
            last_visit_status="visite_programmee"
        )
        self.db.add(self.listing)
        self.db.commit()
        self.db.refresh(self.listing)

    def tearDown(self):
        # Cleanup test visits and listing
        self.db.query(Visit).filter(Visit.listing_id == self.listing.id).delete()
        self.db.delete(self.listing)
        self.db.commit()

    def test_past_first_visit_in_safe_problem_types(self):
        self.assertIn(PAST_FIRST_VISIT_NOT_DONE, SAFE_PROBLEM_TYPES)

    def test_past_first_visit_identification_and_repair(self):
        # 1. Add a visit with step '1ere_visite', scheduled yesterday, status 'programme'
        yesterday = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=1)
        past_visit = Visit(
            listing_id=self.listing.id,
            visit_type="visite",
            step_family="visite",
            step="1ere_visite",
            scheduled_at=yesterday,
            status="programme",
            visitor="Jean Dupont",
            notes="Visite du bien hier"
        )
        self.db.add(past_visit)
        self.db.commit()
        self.db.refresh(past_visit)

        # 2. Identify problems
        problems = identify_problems(self.db)
        self.assertIn(PAST_FIRST_VISIT_NOT_DONE, problems)
        self.assertGreaterEqual(problems[PAST_FIRST_VISIT_NOT_DONE]["count"], 1)
        self.assertIn(self.listing.id, problems[PAST_FIRST_VISIT_NOT_DONE]["ids"])

        # 3. Details format check
        details = identify_problems_with_details(self.db)
        self.assertIn(PAST_FIRST_VISIT_NOT_DONE, details)
        listing_details = [l for l in details[PAST_FIRST_VISIT_NOT_DONE]["listings"] if l["id"] == self.listing.id]
        self.assertEqual(len(listing_details), 1)
        self.assertEqual(listing_details[0]["title"], "Appartement Test Visite Passée")

        # 4. Run repair task
        asyncio.run(repair_listings_batch_task(PAST_FIRST_VISIT_NOT_DONE))

        # 5. Verify visit is now 'effectuee'
        self.db.refresh(past_visit)
        self.assertEqual(past_visit.status, "effectuee")

        # 6. Verify listing last_visit_status is updated to 'deja_visitee'
        self.db.refresh(self.listing)
        self.assertEqual(self.listing.last_visit_status, "deja_visitee")

        # 7. Verify problems after repair for this listing are 0
        problems_after = identify_problems(self.db)
        self.assertNotIn(self.listing.id, problems_after[PAST_FIRST_VISIT_NOT_DONE]["ids"])

    def test_future_visit_not_flagged(self):
        # Future visit with step 1ere_visite should NOT be identified as problem
        future_date = datetime.datetime.now(timezone.utc) + datetime.timedelta(days=2)
        future_visit = Visit(
            listing_id=self.listing.id,
            visit_type="visite",
            step_family="visite",
            step="1ere_visite",
            scheduled_at=future_date,
            status="programme"
        )
        self.db.add(future_visit)
        self.db.commit()

        problems = identify_problems(self.db)
        self.assertNotIn(self.listing.id, problems[PAST_FIRST_VISIT_NOT_DONE]["ids"])

    def test_already_done_past_visit_not_flagged(self):
        # Past visit already marked 'effectuee' should NOT be identified as problem
        past_date = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=3)
        done_visit = Visit(
            listing_id=self.listing.id,
            visit_type="visite",
            step_family="visite",
            step="1ere_visite",
            scheduled_at=past_date,
            status="effectuee"
        )
        self.db.add(done_visit)
        self.db.commit()

        problems = identify_problems(self.db)
        self.assertNotIn(self.listing.id, problems[PAST_FIRST_VISIT_NOT_DONE]["ids"])


if __name__ == "__main__":
    unittest.main()
