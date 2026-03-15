import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional


class SelogerScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extrait les annonces depuis une page de recherche SeLoger.
        SeLoger inclut souvent les données en JSON dans le code source.
        """
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        text_content = snapshot.get("text", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Try to find embedded JSON data (window.__REDIAL_PROPS__ or similar)
            scripts = soup.find_all('script', type='application/json')
            for script in scripts:
                try:
                    data = json.loads(script.string or "")
                    # Look for listings array in various possible structures
                    ads = self._find_ads_in_json(data)
                    if ads:
                        for ad in ads:
                            listing = self._parse_seloger_ad(ad)
                            if listing:
                                listings.append(listing)
                        if listings:
                            return listings
                except Exception:
                    continue

            # Fallback: HTML scraping
            ad_cards = soup.find_all('div', attrs={"data-test": "sl.cards-container"})
            for ad in ad_cards:
                try:
                    title_elem = ad.find('div', class_=lambda c: c and 'Card__Title' in c)
                    title = title_elem.text.strip() if title_elem else "Annonce immobilière"
                    url_elem = ad.find('a', href=True)
                    url = url_elem['href'] if url_elem else ""
                    price_elem = ad.find('div', class_=lambda c: c and 'Price' in c)
                    price_str = re.sub(r'[^\d]', '', price_elem.text) if price_elem else "0"
                    price = float(price_str) if price_str else 0.0
                    external_id = url.split('/')[-1] if url else "unknown"

                    listings.append({
                        "external_id": f"sl_{external_id}",
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
                    print(f"[SeLoger] Erreur BS4: {e}")
                    continue

        elif text_content:
            print("[SeLoger] Fallback texte regex (données incomplètes)")
            matches = re.findall(
                r'(https://www\.seloger\.com/annonces/[^\s"\'<>]+)',
                text_content
            )
            for m in set(matches):
                external_id = m.split('/')[-1].split('.')[0] if '/' in m else m
                listings.append({
                    "external_id": f"sl_{external_id}",
                    "title": "Annonce SeLoger",
                    "url": m,
                    "price": 0.0,
                    "location": "France",
                    "city": None,
                    "area": None,
                    "rooms": None,
                    "photo_urls": [],
                })

        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrapes a single SeLoger listing detail page.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        # Try to find embedded JSON
        # 1. Standard application/json tags
        scripts = soup.find_all('script', type='application/json')
        for script in scripts:
            try:
                data = json.loads(script.string or "")
                ad_details = self._extract_detail_from_json(data)
                if ad_details and ad_details.get("photo_urls"):
                    details.update(ad_details)
                    break
            except Exception:
                continue

        # 2. Modern window.__UFRN_LIFECYCLE_SERVERREQUEST__ (as JS variable)
        if not details or not details.get("photo_urls"):
            ufrn_script = soup.find('script', text=re.compile(r'window\.__UFRN_LIFECYCLE_SERVERREQUEST__'))
            if ufrn_script and ufrn_script.string:
                try:
                    start_idx = ufrn_script.string.find('{')
                    end_idx = ufrn_script.string.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        json_text = ufrn_script.string[start_idx:end_idx+1]
                        data = json.loads(json_text)
                        ad_details = self._extract_detail_from_json(data)
                        if ad_details:
                            details.update(ad_details)
                except Exception as e:
                    print(f"[SeLoger] Error parsing UFRN JSON: {e}")

        # Fallback HTML meta
        if not details or not details.get("photo_urls"):
            title_tag = soup.find('title')
            if title_tag and not details.get("title"):
                details["title"] = title_tag.text.strip()
            
            og_img = soup.find('meta', attrs={"property": "og:image"})
            if og_img:
                details["photo_urls"] = [og_img.get("content")]

            og_desc = soup.find('meta', attrs={"property": "og:description"})
            if og_desc:
                details["description_text"] = og_desc.get("content", "")

        return details

    # ─── Private Helpers ──────────────────────────────────────────────────────

    def _find_ads_in_json(self, data, depth=0) -> list:
        """Recursively search for a list of ad objects in nested JSON."""
        if depth > 5:
            return []
        if isinstance(data, list) and len(data) > 0:
            if isinstance(data[0], dict) and any(k in data[0] for k in ['id', 'price', 'title', 'url']):
                return data
        if isinstance(data, dict):
            for key in ['listings', 'ads', 'results', 'cards', 'properties']:
                if key in data and isinstance(data[key], list):
                    return data[key]
            for val in data.values():
                result = self._find_ads_in_json(val, depth + 1)
                if result:
                    return result
        return []

    def _parse_seloger_ad(self, ad: dict) -> Optional[Dict]:
        """Parses a SeLoger ad dict to our standard format."""
        try:
            url = ad.get("url", ad.get("permalink", ""))
            if not url:
                return None
            return {
                "external_id": f"sl_{ad.get('id', url.split('/')[-1])}",
                "title": ad.get("title", ad.get("subject", "Annonce SeLoger")),
                "url": url,
                "price": float(ad.get("price", 0)),
                "location": ad.get("city", ""),
                "city": self._normalize_city(ad.get("city", "")),
                "area": ad.get("surface", ad.get("area")),
                "rooms": ad.get("rooms", ad.get("roomCount")),
                "photo_urls": ad.get("photos", []),
            }
        except Exception:
            return None

    def _extract_detail_from_json(self, data) -> Dict:
        """Extracts enriched details from SeLoger's embedded JSON."""
        details = {}
        # Path found by subagent: window.__UFRN_LIFECYCLE_SERVERREQUEST__.app_cldp.data.classified
        classified = None
        if isinstance(data, dict):
            # Check for the UFRN structure
            if "app_cldp" in data and "data" in data["app_cldp"]:
                classified = data["app_cldp"]["data"].get("classified")
            # Fallback check for other common SeLoger keys
            elif "props" in data and "pageProps" in data["props"]:
                classified = data["props"]["pageProps"].get("ad")
            elif "classified" in data:
                classified = data["classified"]

        if classified:
            try:
                details["title"] = classified.get("title", classified.get("subject"))
                details["description_text"] = classified.get("description")
                
                # Prices are usually in pricing or as direct fields
                pricing = classified.get("pricing", {})
                details["price"] = pricing.get("amount") or classified.get("price")
                
                # Location
                tags = classified.get("location", {}).get("tags", [])
                if tags:
                    details["location"] = tags[0] # Often "Paris 15ème"
                    details["city"] = self._normalize_city(tags[0])
                
                # Characteristics
                rooms = classified.get("rooms", {})
                details["rooms"] = rooms.get("total") or classified.get("roomCount")
                details["area"] = classified.get("livingArea") or classified.get("surface")

                # Photos 
                # Path: classified.domains.medias.images
                photos = []
                domains = classified.get("domains", {})
                medias = domains.get("medias", {})
                images = medias.get("images", [])
                
                # Alternative paths for photos
                if not images:
                    images = classified.get("photos", [])
                
                if isinstance(images, list):
                    for img in images:
                        if isinstance(img, dict):
                            url = img.get("url")
                            if url: photos.append(url)
                        elif isinstance(img, str):
                            photos.append(img)
                
                if photos:
                    details["photo_urls"] = photos
            except Exception as e:
                print(f"[SeLoger] Error parsing details from JSON: {e}")

        return details
