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
        # Try to find JSON payload in INITIAL_STATE
        initial_script = soup.find('script', text=re.compile(r'window\.__INITIAL_STATE__\s*='))
        if initial_script and initial_script.string:
            try:
                start_idx = initial_script.string.find('{')
                end_idx = initial_script.string.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_text = initial_script.string[start_idx:end_idx+1]
                    data = json.loads(json_text)
                    # LogicImmo (SeLoger group) structure
                    ad = None
                    if "listingDetail" in data:
                        ad = data["listingDetail"].get("listing")
                    elif "ad" in data:
                        ad = data["ad"]
                    
                    if ad:
                        details["title"] = ad.get("title")
                        details["description_text"] = ad.get("description")
                        details["price"] = ad.get("price")
                        details["area"] = ad.get("surface")
                        details["rooms"] = ad.get("rooms")
                        
                        # Photos
                        photos = []
                        images = ad.get("photos", ad.get("media", []))
                        if isinstance(images, list):
                            for img in images:
                                if isinstance(img, dict):
                                    url = img.get("url") or img.get("large") or img.get("original")
                                    if url: photos.append(url)
                                elif isinstance(img, str):
                                    photos.append(img)
                        
                        if photos:
                            details["photo_urls"] = photos
            except Exception as e:
                print(f"[LogicImmo] Error parsing detail JSON: {e}")

        # Photo URLs Fallback
        if not details.get("photo_urls"):
            og_img = soup.find('meta', attrs={"property": "og:image"})
            if og_img:
                details["photo_urls"] = [og_img.get("content")]

        return details
