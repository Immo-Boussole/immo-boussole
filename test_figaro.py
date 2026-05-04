import asyncio
from app.scrapers.lefigaro import LeFigaroScraper

async def main():
    scraper = LeFigaroScraper()
    details = await scraper.get_listing_details("https://immobilier.lefigaro.fr/annonces/annonce-101684387.html")
    print("Photos found:", len(details.get("photo_urls", [])))
    for p in details.get("photo_urls", []):
        print("-", p)

asyncio.run(main())
