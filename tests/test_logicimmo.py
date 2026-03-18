import asyncio
from app.scrapers.logicimmo import LogicimmoScraper

async def test():
    scraper = LogicimmoScraper()
    print("Fetching listings...")
    search_url = "https://www.logic-immo.com/achat-immobilier-paris-75,100_1/options/groupparam_1_1=1,2,3"
    listings = await scraper.get_listings(search_url)
    if not listings:
        print("No listings found, dumping HTML")
        snapshot = await scraper.extract_page_content(search_url)
        with open("logicimmo_search.html", "w", encoding="utf-8") as f:
            f.write(snapshot.get("html", ""))
        return
        
    print(f"Found {len(listings)} listings")
    first_listing_url = listings[0]['url']
    print(f"Testing detail for: {first_listing_url}")
    
    details = await scraper.get_listing_details(first_listing_url)
    print(f"Photos found: {len(details.get('photo_urls', []))}")
    for p in details.get('photo_urls', []):
        print(p)
        
    if len(details.get('photo_urls', [])) <= 1:
        print("Only found 1 photo or none, extracting HTML...")
        snapshot = await scraper.extract_page_content(first_listing_url)
        html = snapshot.get("html", "")
        with open("logicimmo_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved raw HTML to logicimmo_page.html")

if __name__ == "__main__":
    import asyncio
    
    import sys
    import os
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))
    
    asyncio.run(test())
