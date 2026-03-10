from sqlalchemy.orm import Session
from app.models import Listing, ListingStatus, SearchQuery, Source
from app.scrapers.leboncoin import LeboncoinScraper
from app.scrapers.seloger import SelogerScraper

async def scrape_and_diff(query: SearchQuery, db: Session):
    scrapers = {
        Source.LEBONCOIN: LeboncoinScraper(),
        Source.SELOGER: SelogerScraper()
    }
    
    scraper = scrapers.get(query.source)
    if not scraper:
        print(f"Scraper introuvable pour la source: {query.source}")
        return
        
    print(f"Extraction des annonces depuis {query.url}")
    scraped_listings = await scraper.get_listings(query.url)
    scraped_ids = [str(l["external_id"]) for l in scraped_listings]
    
    # Find currently active listings for this query's source
    existing_active = db.query(Listing).filter(
        Listing.source == query.source,
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW])
    ).all()
    
    existing_ids = [l.external_id for l in existing_active]
    
    # 1. Identify disappeared listings
    for listing in existing_active:
        if listing.external_id not in scraped_ids:
            listing.status = ListingStatus.DISAPPEARED
            
    # 2. Identify new listings
    for item in scraped_listings:
        if str(item["external_id"]) not in existing_ids:
            # Check if it existed before as disappeared
            existing = db.query(Listing).filter(Listing.external_id == str(item["external_id"])).first()
            if existing:
                existing.status = ListingStatus.NEW
                existing.price = item["price"]
                existing.title = item["title"]
            else:
                new_listing = Listing(
                    external_id=str(item["external_id"]),
                    title=item["title"],
                    url=item["url"],
                    price=item["price"],
                    location=item["location"],
                    area=item["area"],
                    source=query.source,
                    status=ListingStatus.NEW
                )
                db.add(new_listing)
                
    db.commit()
    print(f"Diff terminé. {len(scraped_ids)} annonces trouvées, base de données mise à jour.")
