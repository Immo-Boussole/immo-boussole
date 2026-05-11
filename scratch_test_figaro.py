import asyncio
from app.scrapers.lefigaro import LeFigaroScraper

async def main():
    scraper = LeFigaroScraper()
    # Expired listing
    url1 = "https://immobilier.lefigaro.fr/annonces/annonce-85365298.html"
    print(f"Testing {url1}")
    res = await scraper.get_listing_details(url1)
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
