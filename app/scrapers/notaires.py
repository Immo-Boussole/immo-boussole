import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

class NotairesScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract listings from Immobilier Notaires.
        """
        # The site uses a JSON API: https://www.immobilier.notaires.fr/api/ads
        # We'll try to extract from the HTML page first.
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            # The site uses specific classes for ads
            items = soup.find_all(['div', 'article'], class_=re.compile(r'annonces-item|card'))
            for item in items:
                try:
                    link = item.find('a', href=True)
                    if not link: continue
                    url = link['href']
                    if not url.startswith('http'):
                        url = "https://www.immobilier.notaires.fr" + url
                    
                    title = item.find(['h2', 'h3']).text.strip() if item.find(['h2', 'h3']) else "Annonce Notaires"
                    
                    price_elem = item.find(text=re.compile(r'\d+[\s\d]*€'))
                    price = 0.0
                    if price_elem:
                        price_str = re.sub(r'[^\d]', '', price_elem)
                        if price_str: price = float(price_str)
                    
                    ext_id = url.split('/')[-1]

                    listings.append({
                        "external_id": f"notaires_{ext_id}",
                        "title": title,
                        "url": url,
                        "price": price,
                        "location": "France",
                    })
                except Exception as e:
                    continue
        
        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape details for an Immobilier Notaires listing.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        details["url"] = url
        details["title"] = soup.find('title').text.strip() if soup.find('title') else "Annonce Notaires"
        
        desc = soup.find('div', class_=re.compile(r'description|corps'))
        details["description_text"] = desc.get_text().strip() if desc else ""

        # Attributes
        text = soup.get_text().lower()
        if 'm²' in text:
            match = re.search(r'(\d+[\d\s,]*)\s*m²', text)
            if match:
                details["area"] = float(match.group(1).replace(',', '.').replace(' ', ''))
        
        ext_id = url.split('/')[-1]
        details["external_id"] = f"notaires_{ext_id}"

        # Photo
        og_img = soup.find('meta', attrs={"property": "og:image"})
        if og_img:
            details["photo_urls"] = [og_img.get("content")]

        return details
