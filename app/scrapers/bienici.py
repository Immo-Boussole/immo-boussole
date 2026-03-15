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
        initial_script = soup.find('script', text=re.compile(r'window\.__INITIAL_STATE__\s*='))
        if initial_script and initial_script.string:
            try:
                start_idx = initial_script.string.find('{')
                end_idx = initial_script.string.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_text = initial_script.string[start_idx:end_idx+1]
                    data = json.loads(json_text)
                    # Usually BienIci has ad data under adDetail or similar keys
                    ad = None
                    if "adDetail" in data:
                        ad = data["adDetail"].get("ad")
                    elif "ads" in data and isinstance(data["ads"], dict):
                        # Sometimes it's a map of ID -> ad
                        ad = next(iter(data["ads"].values()), None)
                    
                    if ad:
                        details["title"] = ad.get("title", details.get("title"))
                        details["description_text"] = ad.get("description", details.get("description_text"))
                        details["price"] = ad.get("price")
                        details["area"] = ad.get("surfaceArea")
                        details["rooms"] = ad.get("roomsCount")
                        
                        # Photos
                        photos = []
                        medias = ad.get("photos", ad.get("media", []))
                        if isinstance(medias, list):
                            for m in medias:
                                if isinstance(m, dict):
                                    url = m.get("url")
                                    if url: photos.append(url)
                                elif isinstance(m, str):
                                    photos.append(m)
                        
                        if photos:
                            details["photo_urls"] = photos
                        
                        city = ad.get("city")
                        if city:
                            details["city"] = self._normalize_city(city)
                            details["location"] = city
            except Exception as e:
                print(f"[BienIci] Error parsing detail JSON: {e}")

        # Photo URLs Fallback if nothing found or only one photo
        if not details.get("photo_urls") or len(details.get("photo_urls", [])) <= 1:
            fb_photos = []
            for img in soup.find_all('img', src=re.compile(r'bienici\.com\/image')):
                src = img.get('src')
                if src and 'thumbnail' not in src.lower():
                    fb_photos.append(src)
            
            if fb_photos:
                details["photo_urls"] = list(set(fb_photos + details.get("photo_urls", [])))
            elif not details.get("photo_urls"):
                og_img = soup.find('meta', attrs={"property": "og:image"})
                if og_img:
                    details["photo_urls"] = [og_img.get("content")]

        return details
