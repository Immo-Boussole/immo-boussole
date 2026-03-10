from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
import json
from typing import List, Dict

class SelogerScraper(BaseScraper):
    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extrait les annonces depuis une page de recherche SeLoger.
        SeLoger inclut souvent les données en JSON dans le code source de la page (ex: window.initialData).
        """
        html_content = await self.extract_page_content(search_url)
        if not html_content:
            return []
            
        soup = BeautifulSoup(html_content, 'html.parser')
        listings = []
        
        # Fallback to HTML parsing if JSON is not easily found
        # Les classes changent souvent, ceci est une structure générique d'exemple
        ads = soup.find_all('div', attrs={"data-test": "sl.cards-container"})
        
        for ad in ads:
            try:
                # Titre / Description génériques
                title_elem = ad.find('div', class_=lambda c: c and 'Card__Title' in c)
                title = title_elem.text.strip() if title_elem else "Annonce immobilière"
                
                url_elem = ad.find('a', href=True)
                url = url_elem['href'] if url_elem else ""
                
                price_elem = ad.find('div', class_=lambda c: c and 'Price' in c)
                price_str = price_elem.text.strip().replace('€', '').replace(' ', '') if price_elem else "0"
                price = float(price_str) if price_str.isdigit() else 0.0
                
                external_id = url.split('/')[-1] if url else "unknown"
                
                listings.append({
                    "external_id": f"sl_{external_id}",
                    "title": title,
                    "url": url,
                    "price": price,
                    "location": "Inconnu",
                    "area": None,
                })
            except Exception as e:
                print(f"Erreur lors de l'extraction d'une annonce SeLoger: {e}")
                continue
                
        return listings
