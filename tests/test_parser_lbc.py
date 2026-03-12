import asyncio
from app.scrapers.leboncoin import LeboncoinScraper

async def test_lbc_parser():
    print("Testing LeBonCoin Scraper with PinchTab...")
    scraper = LeboncoinScraper()
    # Simple search for Paris
    scraper = LeboncoinScraper()
    listings = await scraper.get_listings("https://www.leboncoin.fr/recherche?category=9&text=paris")
    
    print(f"Parsed {len(listings)} listings:")
    for l in listings[:10]:
        print(l)

if __name__ == "__main__":
    asyncio.run(test_lbc_parser())
