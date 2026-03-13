import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

class LogicimmoScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract listings from a LogicImmo search result page.
        """
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            # LogicImmo often uses a script tag with search data
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html_content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # Extract ads from JSON if possible
                except Exception as e:
                    print(f"[LogicImmo] Error parsing INITIAL_STATE: {e}")

            # Fallback: BeautifulSoup parsing
            items = soup.find_all(['div', 'article'], class_=re.compile(r'announcement|card|ad-item'))
            for item in items:
                try:
                    link = item.find('a', href=True)
                    if not link: continue
                    url = link['href']
                    if not url.startswith('http'):
                        url = "https://www.logic-immo.com" + url
                    
                    title = item.find(['h2', 'span']).text.strip() if item.find(['h2', 'span']) else "Annonce Logic-Immo"
                    
                    price_elem = item.find(text=re.compile(r'\d+[\s\d]*€'))
                    price = 0.0
                    if price_elem:
                        price_str = re.sub(r'[^\d]', '', price_elem)
                        if price_str: price = float(price_str)
                    
                    # Estimate area and rooms from title or description snippet
                    area = None
                    rooms = None
                    text = item.get_text()
                    area_match = re.search(r'(\d+)\s*m²', text)
                    if area_match: area = float(area_match.group(1))
                    room_match = re.search(r'(\d+)\s*pièce', text)
                    if room_match: rooms = int(room_match.group(1))

                    ext_id = url.split('-')[-1].split('.')[0]

                    listings.append({
                        "external_id": f"logic_{ext_id}",
                        "title": title,
                        "url": url,
                        "price": price,
                        "location": "France",
                        "city": None,
                        "area": area,
                        "rooms": rooms,
                        "photo_urls": [],
                    })
                except Exception as e:
                    print(f"[LogicImmo] Error parsing item: {e}")
                    continue

        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape a single LogicImmo listing page for details.
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
        details["title"] = soup.find('title').text.strip() if soup.find('title') else "Annonce Logic-Immo"
        
        og_desc = soup.find('meta', attrs={"property": "og:description"})
        details["description_text"] = og_desc.get("content", "") if og_desc else ""

        # Price
        price_elem = soup.find(text=re.compile(r'\d+[\s\d]*€'))
        if price_elem:
            price_str = re.sub(r'[^\d]', '', price_elem)
            if price_str: details["price"] = float(price_str)

        ext_id = url.split('-')[-1].split('.')[0]
        details["external_id"] = f"logic_{ext_id}"

        # Attributes
        chars = soup.get_text().lower()
        if 'm²' in chars:
            match = re.search(r'(\d+[\d\s,]*)\s*m²', chars)
            if match:
                details["area"] = float(match.group(1).replace(',', '.').replace(' ', ''))
        if 'pièce' in chars:
            match = re.search(r'(\d+)\s*pièce', chars)
            if match:
                details["rooms"] = int(match.group(1))

        # Photo URLs
        og_img = soup.find('meta', attrs={"property": "og:image"})
        if og_img:
            details["photo_urls"] = [og_img.get("content")]

        return details
