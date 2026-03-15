import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

class LeFigaroScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract listings from a LeFigaro search result page.
        """
        # Le Figaro search API is often used, but we'll try to extract from the HTML first
        # as the search_url provided by the user is likely a web URL.
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            # Look for JSON payload in script tags if available, similar to LBC
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html_content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # The exact path in INITIAL_STATE depends on the page version
                    # This is a placeholder for the logic found in the external repo
                    # which often targets api.figaro.fr directly.
                    pass
                except Exception as e:
                    print(f"[LeFigaro] Error parsing INITIAL_STATE: {e}")

            # Fallback: BeautifulSoup parsing
            # Le Figaro uses specific classes for listing items
            items = soup.find_all('div', class_=re.compile(r'class-item|ad-item'))
            for item in items:
                try:
                    link = item.find('a', href=True)
                    if not link: continue
                    url = link['href']
                    if not url.startswith('http'):
                        url = "https://immobilier.lefigaro.fr" + url
                    
                    title_elem = item.find(['h2', 'span'], class_=re.compile(r'title|subject'))
                    title = title_elem.text.strip() if title_elem else "Annonce Le Figaro"
                    
                    price_elem = item.find(text=re.compile(r'(\d+[\d\s]*)\s*€'))
                    price = 0.0
                    if price_elem:
                        match = re.search(r'(\d+[\d\s]*)\s*€', price_elem)
                        if match:
                            price_str = re.sub(r'[^\d]', '', match.group(1))
                            if price_str: price = float(price_str)
                    
                    ext_id = url.split('-')[-1].split('.')[0]
                    
                    # Extract city from title if possible
                    # Example title: "Vente maison 4 pièces 142.87 m² à Tournon-sur-Rhône (07300), 290 000 €"
                    city = None
                    location = "France"
                    match_loc = re.search(r'à (.*?) \((\d{5})\)', title)
                    if match_loc:
                        city_name = match_loc.group(1).strip()
                        zip_code = match_loc.group(2).strip()
                        city = self._normalize_city(city_name)
                        location = f"{city_name} ({zip_code[:2]})"
                    elif ' à ' in title:
                        parts = title.split(' à ')
                        if len(parts) > 1:
                            potential_city = parts[1].split(',')[0].strip()
                            city = self._normalize_city(potential_city)
                            location = potential_city

                    listings.append({
                        "external_id": f"figaro_{ext_id}",
                        "title": title,
                        "url": url,
                        "price": price,
                        "location": location,
                        "city": city,
                        "area": None,
                        "rooms": None,
                        "photo_urls": [],
                    })
                except Exception as e:
                    print(f"[LeFigaro] Error parsing item: {e}")
                    continue

        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape a single LeFigaro listing page for details.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        # Extract basic info from meta tags
        details["url"] = url
        og_title = soup.find('meta', attrs={"property": "og:title"})
        title = og_title.get("content", "") if og_title else (soup.find('title').text.strip() if soup.find('title') else "Annonce Le Figaro")
        details["title"] = title
        
        # Extract city and location from title
        match_loc = re.search(r'à (.*?) \((\d{5})\)', title)
        if match_loc:
            city_name = match_loc.group(1).strip()
            zip_code = match_loc.group(2).strip()
            details["city"] = self._normalize_city(city_name)
            details["location"] = f"{city_name} ({zip_code[:2]})"
        elif ' à ' in title:
            parts = title.split(' à ')
            if len(parts) > 1:
                potential_city = parts[1].split(',')[0].strip()
                details["city"] = self._normalize_city(potential_city)
                details["location"] = potential_city

        og_desc = soup.find('meta', attrs={"property": "og:description"})
        details["description_text"] = og_desc.get("content", "") if og_desc else ""

        # Extract price
        price_elem = soup.find(text=re.compile(r'(\d+[\d\s]*)\s*€'))
        if price_elem:
            match = re.search(r'(\d+[\d\s]*)\s*€', price_elem)
            if match:
                price_str = re.sub(r'[^\d]', '', match.group(1))
                if price_str: details["price"] = float(price_str)

        # External ID
        ext_id = url.split('-')[-1].split('.')[0]
        details["external_id"] = f"figaro_{ext_id}"

        # ── EXTRACT DATA FROM window.__NUXT__ (Modern Figaro) ──
        # ── EXTRACT DATA FROM window.__NUXT__ (Modern Figaro) ──
        # Search for the script tag containing __NUXT__
        nuxt_script = None
        for s in soup.find_all('script'):
            if s.string and 'window.__NUXT__' in s.string:
                nuxt_script = s
                break
        
        if nuxt_script and nuxt_script.string:
            print(f"[LeFigaro] Script __NUXT__ trouvé (taille: {len(nuxt_script.string)})", flush=True)
            try:
                # Find the JSON part between the first { and the last }
                start_idx = nuxt_script.string.find('{')
                end_idx = nuxt_script.string.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_text = nuxt_script.string[start_idx:end_idx+1]
                    data = json.loads(json_text)
                    
                    classified = None
                    if "data" in data:
                        # Case: data is a list (common in Nuxt 3)
                        if isinstance(data["data"], list):
                            for item in data["data"]:
                                if isinstance(item, dict) and "classifiedDetailResponse" in item:
                                    classified = item["classifiedDetailResponse"].get("classified")
                                    print("[LeFigaro] Classified trouvé dans data (liste)", flush=True)
                                    break
                        # Case: data is a dict (Nuxt 2)
                        elif isinstance(data["data"], dict):
                            classified = data["data"].get("classifiedDetailResponse", {}).get("classified")
                            if classified: print("[LeFigaro] Classified trouvé dans data (dict)", flush=True)
                    
                    if classified:
                        details["title"] = classified.get("title", details.get("title"))
                        details["description_text"] = classified.get("description", details.get("description_text"))
                        details["price"] = classified.get("price", details.get("price"))
                        
                        # Location
                        loc_data = classified.get("location", {})
                        city_name = loc_data.get("city")
                        zip_code = loc_data.get("zipCode")
                        if city_name:
                            details["city"] = self._normalize_city(city_name)
                            details["location"] = f"{city_name} ({zip_code[:2]})" if zip_code else city_name

                        # Caracteristics
                        details["area"] = classified.get("surface", details.get("area"))
                        details["rooms"] = classified.get("roomCount", details.get("rooms"))
                        details["bedrooms"] = classified.get("bedroomCount")
                        
                        # Photos
                        photos_list = []
                        images_data = classified.get("images", {}) or {}
                        raw_photos = images_data.get("photos") or classified.get("medias") or []
                        print(f"[LeFigaro] Raw photos found: {len(raw_photos) if isinstance(raw_photos, list) else 'NOT A LIST'}", flush=True)
                        
                        if isinstance(raw_photos, list):
                            for p in raw_photos:
                                if not isinstance(p, dict): continue
                                urls = p.get("url", {})
                                best_url = (urls.get("extra-large") or urls.get("large") or 
                                           urls.get("medium") or urls.get("small"))
                                if best_url:
                                    photos_list.append(best_url)
                        
                        if photos_list:
                            details["photo_urls"] = photos_list
                            print(f"[LeFigaro] Extrait {len(photos_list)} photos du Nuxt", flush=True)
            except Exception as e:
                print(f"[LeFigaro] Erreur parsing Nuxt : {e}", flush=True)
        else:
            print("[LeFigaro] Script __NUXT__ non trouvé dans le HTML", flush=True)

        # Photo URLs Fallback if nothing found or incomplete
        if not details.get("photo_urls") or len(details.get("photo_urls", [])) <= 1:
            # Try to find all picture tags or img tags with certain classes
            fb_photos = []
            for img in soup.find_all('img', src=re.compile(r'images\.figaro|media\.figaro')):
                src = img.get('src')
                if src and 'thumb' not in src.lower():
                    fb_photos.append(src)
            
            if fb_photos:
                details["photo_urls"] = list(set(fb_photos + details.get("photo_urls", [])))
            elif not details.get("photo_urls"):
                og_img = soup.find('meta', attrs={"property": "og:image"})
                if og_img:
                    details["photo_urls"] = [og_img.get("content")]

        return details
