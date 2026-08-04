import unittest
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Listing, ListingStatus, Source
from app.services import create_listing_from_details, refresh_listing_status


class TestPricePerSqm(unittest.TestCase):
    def test_listing_update_price_per_sqm_unit(self):
        """Test model helper method Listing.update_price_per_sqm() directly."""
        listing = Listing(price=300000.0, area=60.0)
        self.assertEqual(listing.update_price_per_sqm(), 5000.0)
        self.assertEqual(listing.price_per_sqm, 5000.0)

        # Float rounding test
        listing.price = 250000.0
        listing.area = 33.33
        self.assertEqual(listing.update_price_per_sqm(), 7500.75)

        # Zero or missing area
        listing.area = 0
        self.assertIsNone(listing.update_price_per_sqm())
        self.assertIsNone(listing.price_per_sqm)

        # Missing price
        listing.price = None
        listing.area = 50.0
        self.assertIsNone(listing.update_price_per_sqm())
        self.assertIsNone(listing.price_per_sqm)

    def test_create_listing_calculates_price_per_sqm(self):
        """Test price_per_sqm calculation during listing import/creation."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        details = {
            "title": "Appartement Lyon 3",
            "price": 240000.0,
            "area": 60.0,
            "city": "Lyon",
        }
        url = "https://example.com/annonce-1"

        listing, is_new = asyncio.run(
            create_listing_from_details(
                db=db,
                details=details,
                source=Source.MANUAL,
                original_url=url,
                download_photos=False,
                status=ListingStatus.ACTIVE,
            )
        )

        self.assertTrue(is_new)
        self.assertEqual(listing.price_per_sqm, 4000.0)

        db.close()

    def test_refresh_listing_calculates_price_per_sqm(self):
        """Test price_per_sqm calculation during listing refresh."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        listing = Listing(
            external_id="ext-refresh-1",
            url="https://example.com/refresh-1",
            title="Appartement à rafraîchir",
            price=150000.0,
            area=50.0,
            price_per_sqm=None,
            status=ListingStatus.ACTIVE,
        )
        db.add(listing)
        db.commit()

        asyncio.run(refresh_listing_status(listing, db, force_update=False))

        db.refresh(listing)
        self.assertEqual(listing.price_per_sqm, 3000.0)

        db.close()

    def test_database_migration_backfill_price_per_sqm(self):
        """Test that backfill SQL query updates missing price_per_sqm in SQLite DB."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        listing1 = Listing(
            external_id="mig-1",
            url="https://example.com/mig-1",
            title="Listing sans ppsqm",
            price=200000.0,
            area=50.0,
            price_per_sqm=None,
        )
        listing2 = Listing(
            external_id="mig-2",
            url="https://example.com/mig-2",
            title="Listing déjà avec ppsqm",
            price=300000.0,
            area=100.0,
            price_per_sqm=3000.0,
        )
        db.add_all([listing1, listing2])
        db.commit()

        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE listings SET price_per_sqm = ROUND(1.0 * price / area, 2) "
                    "WHERE price IS NOT NULL AND price > 0 "
                    "AND area IS NOT NULL AND area > 0 "
                    "AND (price_per_sqm IS NULL OR price_per_sqm = 0)"
                )
            )
            conn.commit()

        db.refresh(listing1)
        db.refresh(listing2)

        self.assertEqual(listing1.price_per_sqm, 4000.0)
        self.assertEqual(listing2.price_per_sqm, 3000.0)

        db.close()


if __name__ == "__main__":
    unittest.main()

