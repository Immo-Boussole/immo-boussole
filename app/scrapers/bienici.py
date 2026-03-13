import re
import json
import httpx
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

class BieniciScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract listings from BienIci.
        BienIci has a very clean JSON API.
        """
        # If the search_url is a web URL, we might need to extract the search filters
        # and hit the API. For now, we'll try to extract from the HTML first.
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            # BienIci often includes JSON in a script tag or uses an API call.
            # The external repo hits https://www.bienici.com/realEstateAds.json directly.
            
            # If we detect it's a search result page, we can try to find the ads in script tags
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html_content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # ads = data.get('ads', [])
                except Exception as e:
                    print(f"[BienIci] Error parsing INITIAL_STATE: {e}")

            # Fallback BS4
            items = soup.find_all(['article', 'div'], class_=re.compile(r'ad-card|listing-item'))
            for item in items:
                try:
                    link = item.find('a', href=True)
                    if not link: continue
                    url = link['href']
                    if not url.startswith('http'):
                        url = "https://www.bienici.com" + url
                    
                    title = item.find(['h2', 'p']).text.strip() if item.find(['h2', 'p']) else "Annonce BienIci"
                    
                    price_elem = item.find(text=re.compile(r'\d+[\s\d]*€'))
                    price = 0.0
                    if price_elem:
                        price_str = re.sub(r'[^\d]', '', price_elem)
                        if price_str: price = float(price_str)
                    
                    ext_id = url.split('/')[-1].split('?')[0]

                    listings.append({
                        "external_id": f"bienici_{ext_id}",
                        "title": title,
                        "url": url,
                        "price": price,
                        "location": "France",
                        "city": None,
                        "area": None,
                        "rooms": None,
                        "photo_urls": [],
                    })
                except Exception as e:
                    print(f"[BienIci] Error parsing item: {e}")
                    continue
        
        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape details for a BienIci listing.
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
        details["title"] = soup.find('title').text.strip() if soup.find('title') else "Annonce BienIci"
        
        # Try to find JSON payload which is very common on BienIci
        match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html_content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                # Map fields from JSON if found
            except Exception as e:
                print(f"[BienIci] Error parsing detail JSON: {e}")

        og_desc = soup.find('meta', attrs={"property": "og:description"})
        details["description_text"] = og_desc.get("content", "") if og_desc else ""

        # Photo URLs
        og_img = soup.find('meta', attrs={"property": "og:image"})
        if og_img:
            details["photo_urls"] = [og_img.get("content")]

        # Price and Attributes
        body_text = soup.get_text().lower()
        if '€' in body_text:
            match = re.search(r'(\d+[\d\s]*)\s*€', body_text)
            if match: details["price"] = float(match.group(1).replace(' ', ''))
        
        if 'm²' in body_text:
            match = re.search(r'(\d+[\d\s,]*)\s*m²', body_text)
            if match:
                details["area"] = float(match.group(1).replace(',', '.').replace(' ', ''))

        ext_id = url.split('/')[-1].split('?')[0]
        details["external_id"] = f"bienici_{ext_id}"

        return details
