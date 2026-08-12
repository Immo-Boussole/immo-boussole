import asyncio
import os
from app.scrapers.leboncoin import LeboncoinScraper

async def main():
    url = "https://www.leboncoin.fr/recherche?category=9&locations=Tain-l%27Hermitage_26600__45.07028_4.83761_5000_5000&price=200000-500000&square=100-500&rooms=4-max&real_estate_type=1&outside_access=garden&global_condition=3,2,1,4"
    scraper = LeboncoinScraper()
    print("Récupération du contenu de la page...")
    html = await scraper.extract_page_content(url)
    html_content = html.get("html", "")
    
    out_path = os.path.join(os.path.dirname(__file__), "lbc_debug.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"HTML sauvegardé dans tests/lbc_debug.html ({len(html_content)} caractères).")
    
    # Let's see what the scraper normally extracts
    listings = await scraper.get_listings(url)
    print(f"{len(listings)} annonces parsées.")

if __name__ == "__main__":
    asyncio.run(main())
