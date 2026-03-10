from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict

class LeboncoinScraper(BaseScraper):
    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extrait les annonces depuis une page de recherche LeBonCoin.
        NOTE: LeBonCoin a des protections cloudflare/datadome trs fortes. 
        Cette approche tente d'utiliser BeautifulSoup après avoir laissé Playwright s'exécuter.
        """
        html_content = await self.extract_page_content(search_url)
        if not html_content:
            return []
            
        soup = BeautifulSoup(html_content, 'html.parser')
        listings = []
        
        # Ce sélecteur (a[data-qa-id="aditem_container"]) est souvent utilisé, 
        # mais peut changer au gré des mises à jour du site.
        ads = soup.find_all('a', attrs={"data-qa-id": "aditem_container"})
        
        for ad in ads:
            try:
                url = "https://www.leboncoin.fr" + ad.get('href', '')
                
                # Title
                title_elem = ad.find('p', attrs={"data-qa-id": "aditem_title"})
                title = title_elem.text.strip() if title_elem else "Sans titre"
                
                # Price
                price_elem = ad.find('p', attrs={"data-test-id": "price"})
                price_str = price_elem.text.strip().replace('€', '').replace(' ', '') if price_elem else "0"
                price = float(price_str) if price_str.isdigit() else 0.0
                
                # External ID (from URL usually end of path)
                # e.g., /ventes_immobilieres/123456789.htm
                external_id = url.split('/')[-1].split('.')[0] if url.split('/')[-1] else url
                
                # Location (sometimes available in specific tags)
                loc_elem = ad.find('p', attrs={"aria-label": lambda x: x and "Située à" in x})
                location = loc_elem.text.strip() if loc_elem else "Inconnu"
                
                listings.append({
                    "external_id": f"lbc_{external_id}",
                    "title": title,
                    "url": url,
                    "price": price,
                    "location": location,
                    "area": None, # Needs deeper parsing
                })
            except Exception as e:
                print(f"Erreur lors de l'extraction d'une annonce LBC: {e}")
                continue
                
        return listings
