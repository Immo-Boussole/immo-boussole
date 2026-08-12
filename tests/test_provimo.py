import sys
import os
import asyncio

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.scrapers.provimo import ProvimoScraper

async def test():
    scraper = ProvimoScraper()
    print("Fetching listings from PROVIMO...")
    search_url = "https://www.provimo.fr/nos-biens/xdpfkwxpp4buyddhn99h7jrrgwrxwksukonubgif6na1e7r7kdxz4ptjom65n9ft79sjaiha9e9gbbadmo9wbo78om4dzeayycfph4aqewohn1spj6s9gfn7wjwaj43kmbpq93b7z4cws3jm78inojtzs4syrfw6bmdgcjucgr3pcefo9i3rgr4qb6aszdohm9wta4bdiwabyuhdakkkkkp3ny3n7mqs4e55ob7dtc4smepzpmd8kmmfdax3xwb55fubqci48bkdf1yhkqqoebyh71nnnqy4j9p7jf4dr1btxu9ksqfc415wfah5c4of49ahqe3sotbeej95hs6j69uq8so69tr19wtrwmib34mks5rj5egimbhipe3ineik49fqi99kpj5nnwp5xym1ocebzhm3whqygfa97gf8jdpaoq5toj5ow4kbzaid39ay38d4w1e/1"
    
    listings = await scraper.get_listings(search_url)
    if not listings:
        print("No listings found, dumping HTML")
        snapshot = await scraper.extract_page_content(search_url)
        out_path = os.path.join(os.path.dirname(__file__), "provimo_search.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(snapshot.get("html", ""))
        sys.exit(1)
        
    print(f"Found {len(listings)} listings")
    for idx, l in enumerate(listings):
        print(f"  Listing {idx+1}: ID={l['external_id']}, Title={l['title']}, Price={l['price']}, Loc={l['location']}, Area={l['area']}")
        
    first_listing_url = listings[0]['url']
    print(f"\nTesting details extraction for: {first_listing_url}")
    
    details = await scraper.get_listing_details(first_listing_url)
    if not details:
        print("Failed to get listing details")
        sys.exit(1)
        
    print("\nExtracted Details:")
    print(f"  ID: {details.get('external_id')}")
    print(f"  Title: {details.get('title')}")
    print(f"  Area: {details.get('area')} m²")
    print(f"  Land Area: {details.get('land_area')} m²")
    print(f"  Rooms: {details.get('rooms')}")
    print(f"  Bedrooms: {details.get('bedrooms')}")
    print(f"  Bathroom Count: {details.get('bathroom_count')}")
    print(f"  Parking Count: {details.get('parking_count')}")
    print(f"  Has Terrace: {details.get('terrace')}")
    print(f"  Has Pool: {details.get('pool')}")
    print(f"  Building Year: {details.get('building_year')}")
    print(f"  Heating Type: {details.get('heating_type')}")
    print(f"  Kitchen Type: {details.get('kitchen_type')}")
    print(f"  Copropriete Lots: {details.get('copropriete_lots')}")
    print(f"  Procedure Syndic: {details.get('procedure_syndic')}")
    print(f"  Price: {details.get('price')} €")
    print(f"  Location: {details.get('location')}")
    print(f"  Photos Found: {len(details.get('photo_urls', []))}")
    
    for p in details.get('photo_urls', []):
        print(f"    Photo: {p}")
        
    if not details.get('photo_urls'):
        print("Error: No photo URLs found")
        sys.exit(1)
        
    print("Test passed successfully!")
    sys.exit(0)

if __name__ == "__main__":
    asyncio.run(test())
