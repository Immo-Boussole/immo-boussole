import json
import unittest
from app.database import SessionLocal, run_migrations
from app.models import Listing, ListingStatus
from app.db_maintenance import identify_problems, identify_problems_with_details, MISSING_LOCATION, EMPTY_DESCRIPTION

class TestRepairTags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run_migrations()
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_repair_tags_persistence(self):
        # Create a listing with missing location and empty description
        listing = Listing(
            title="Test Listing Repair Tags",
            url="https://example.com/test-repair-tags-1",
            status=ListingStatus.ACTIVE,
            description_text="",
            location="Inconnu",
            city="Inconnu"
        )
        self.db.add(listing)
        self.db.commit()
        self.db.refresh(listing)

        try:
            # Run identify_problems
            problems = identify_problems(self.db, hide_rejected=True)
            self.db.refresh(listing)

            self.assertIsNotNone(listing.repair_tags)
            tags = json.loads(listing.repair_tags)
            self.assertIn(MISSING_LOCATION, tags)
            self.assertIn(EMPTY_DESCRIPTION, tags)

            # Test identify_problems_with_details
            details = identify_problems_with_details(self.db, hide_rejected=True)
            self.assertIn(MISSING_LOCATION, details)
            self.assertIn(EMPTY_DESCRIPTION, details)

        finally:
            self.db.delete(listing)
            self.db.commit()

if __name__ == "__main__":
    unittest.main()
