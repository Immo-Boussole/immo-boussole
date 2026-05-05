import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional


class LeFigaroScraper(BaseScraper):

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: Extract the __NUXT__ / __NUXT_DATA__ state from raw HTML
    # ─────────────────────────────────────────────────────────────────────────
    def _inflate_nuxt_data(self, flat_data: list) -> dict:
        """Inflates a flat Nuxt 3 (unjs/devalue) array into a nested python dict."""
        resolved = {}
        def walk(idx):
            if not isinstance(idx, int) or idx < 0 or idx >= len(flat_data):
                return idx
            if idx in resolved:
                return resolved[idx]
            
            val = flat_data[idx]
            if isinstance(val, dict):
                res = {}
                resolved[idx] = res
                for k, v in val.items():
                    res[k] = walk(v)
                return res
            elif isinstance(val, list):
                # Handle Nuxt reactivity wrappers
                if len(val) == 2 and isinstance(val[0], str) and val[0] in ('ShallowReactive', 'Reactive', 'Ref', 'ShallowRef'):
                    res = walk(val[1])
                    resolved[idx] = res
                    return res
                res = []
                resolved[idx] = res
                for i in val:
                    res.append(walk(i))
                return res
            else:
                resolved[idx] = val
                return val
        
        return walk(0)

    def _extract_nuxt_data(self, html_content: str) -> Optional[dict]:
        """
        Tries several patterns to extract the Nuxt state object from the
        rendered HTML. Returns the parsed dict or None on failure.
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        # Pattern 1: modern Nuxt 3 - flat JSON in script#__NUXT_DATA__
        nuxt_data_tag = soup.find('script', id='__NUXT_DATA__')
        if nuxt_data_tag and nuxt_data_tag.string:
            try:
                flat_data = json.loads(nuxt_data_tag.string)
                if isinstance(flat_data, list):
                    return self._inflate_nuxt_data(flat_data)
            except Exception as e:
                print(f"[LeFigaro] Erreur parse __NUXT_DATA__: {e}", flush=True)

        # Pattern 2: older Nuxt 3 - inline JSON object assignment window.__NUXT__
        for script in soup.find_all('script'):
            text = script.string or ""
            match = re.search(r'window\.__NUXT__\s*=\s*(\{.*)', text, re.DOTALL)
            if match:
                raw = match.group(1).strip().rstrip(';')
                try:
                    depth, end = 0, 0
                    for i, ch in enumerate(raw):
                        if ch == '{': depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                    if end > 0:
                        return json.loads(raw[:end])
                except Exception as e:
                    print(f"[LeFigaro] Erreur parse __NUXT__ (pattern window.__NUXT__): {e}", flush=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: dig into the data structure for classified listings
    # ─────────────────────────────────────────────────────────────────────────
    def _find_classifieds_list(self, data: dict) -> Optional[list]:
        """
        Navigates through the various Nuxt data shapes to find the list of
        classified ads.

        Known paths:
          • Nuxt 3:  data (list of state objects) → classifiedsListResponse.classifieds
          • Nuxt 2:  data.classifiedsListResponse.classifieds
        """
        raw_data = data.get("data")
        if raw_data is None:
            return None

        # Nuxt 3: data is a list of state objects
        if isinstance(raw_data, list):
            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                resp = item.get("classifiedsListResponse", {}) or {}
                classifieds = resp.get("classifieds")
                if isinstance(classifieds, list):
                    print(f"[LeFigaro] classifieds trouvés dans data (liste Nuxt3): {len(classifieds)} annonces", flush=True)
                    return classifieds

        # Nuxt 2: data is a plain dict
        if isinstance(raw_data, dict):
            resp = raw_data.get("classifiedsListResponse", {}) or {}
            classifieds = resp.get("classifieds")
            if isinstance(classifieds, list):
                print(f"[LeFigaro] classifieds trouvés dans data (dict Nuxt2): {len(classifieds)} annonces", flush=True)
                return classifieds

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: find a single classified detail object
    # ─────────────────────────────────────────────────────────────────────────
    def _find_classified_detail(self, data: dict) -> Optional[dict]:
        """
        Returns the single `classified` object from a detail page __NUXT__ state.
        """
        raw_data = data.get("data")
        if raw_data is None:
            return None

        # Nuxt 3
        if isinstance(raw_data, list):
            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                resp = item.get("classifiedDetailResponse", {}) or {}
                classified = resp.get("classified")
                if isinstance(classified, dict):
                    print("[LeFigaro] classified detail trouvé (Nuxt3)", flush=True)
                    return classified

        # Nuxt 2
        if isinstance(raw_data, dict):
            resp = raw_data.get("classifiedDetailResponse", {}) or {}
            classified = resp.get("classified")
            if isinstance(classified, dict):
                print("[LeFigaro] classified detail trouvé (Nuxt2)", flush=True)
                return classified

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # get_listings
    # ─────────────────────────────────────────────────────────────────────────
    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract listings from a LeFigaro search result page.
        Primary strategy: parse window.__NUXT__.data.classifiedsListResponse.classifieds
        Fallback: BeautifulSoup parsing of <article> elements.
        """
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        if not html_content:
            return []

        listings = []

        # ── Strategy 1: __NUXT__ JSON ──────────────────────────────────────
        nuxt_data = self._extract_nuxt_data(html_content)
        if nuxt_data:
            classifieds = self._find_classifieds_list(nuxt_data)
            if classifieds:
                for c in classifieds:
                    try:
                        listings.append(self._classified_to_dict(c))
                    except Exception as e:
                        print(f"[LeFigaro] Erreur conversion classified: {e}", flush=True)

        if listings:
            print(f"[LeFigaro] {len(listings)} annonces extraites via __NUXT__", flush=True)
            return listings

        # ── Strategy 2: BeautifulSoup DOM fallback ─────────────────────────
        print("[LeFigaro] Fallback DOM BeautifulSoup", flush=True)
        soup = BeautifulSoup(html_content, 'html.parser')
        # Current LeFigaro uses <article> tags for each listing
        items = soup.find_all('article')
        for item in items:
            try:
                link = item.find('a', href=True)
                if not link:
                    continue
                url = link['href']
                if not url.startswith('http'):
                    url = "https://immobilier.lefigaro.fr" + url

                # Title / type
                title_elem = item.find(['h2', 'h3', 'p'])
                title = title_elem.text.strip() if title_elem else "Annonce Le Figaro"

                # Price
                price = 0.0
                price_text = item.get_text(" ", strip=True)
                price_match = re.search(r'([\d\s]+)\s*€', price_text)
                if price_match:
                    price_str = re.sub(r'[^\d]', '', price_match.group(1))
                    if price_str:
                        price = float(price_str)

                # Location (e.g., "Paris 3ème (75)")
                location, city = self._parse_location_from_text(price_text)

                ext_id = url.split('-')[-1].split('.')[0]

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
                print(f"[LeFigaro] Erreur parsing article: {e}", flush=True)
                continue

        return listings

    # ─────────────────────────────────────────────────────────────────────────
    # get_listing_details
    # ─────────────────────────────────────────────────────────────────────────
    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape a single LeFigaro listing page for details.
        Primary strategy: parse window.__NUXT__ classifiedDetailResponse.
        Fallback: meta tags + regex.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details: Dict = {"url": url}
        soup = BeautifulSoup(html_content, 'html.parser')

        # ── Strategy 1: __NUXT__ ──────────────────────────────────────────
        nuxt_data = self._extract_nuxt_data(html_content)
        if nuxt_data:
            classified = self._find_classified_detail(nuxt_data)
            if classified:
                nuxt_details = self._classified_to_dict(classified, url=url)
                if nuxt_details.get("title") == "Annonce Le Figaro" and details.get("title"):
                    nuxt_details["title"] = details["title"]
                
                # Check for "vendu" or "indisponible" in description or options
                unavail_keywords = ["vendu", "compromis", "plus disponible", "retiré"]
                desc_lower = nuxt_details.get("description_text", "").lower()
                if any(k in desc_lower for k in unavail_keywords):
                    print(f"[LeFigaro] Listing found but marked as unavailable in description: {url}", flush=True)
                    return {} # Mark as disappeared

                details = {**details, **nuxt_details}
                return details
            else:
                print("[LeFigaro] __NUXT__ trouvé mais aucun classifiedDetailResponse dedans", flush=True)
        else:
            print("[LeFigaro] __NUXT__ absent du HTML", flush=True)

        # ── Strategy 2: DOM fallback (Strict) ──────────────────────────────
        # Try to extract title/desc even for fallback
        og_title = soup.find('meta', attrs={"property": "og:title"})
        title_tag = soup.find('title')
        details["title"] = (
            og_title.get("content", "") if og_title
            else (title_tag.text.strip() if title_tag else "Annonce Le Figaro")
        )

        og_desc = soup.find('meta', attrs={"property": "og:description"})
        details["description_text"] = og_desc.get("content", "") if og_desc else ""

        # Location from title (best-effort)
        loc, city = self._parse_location_from_text(details["title"])
        if loc:
            details["location"] = loc
            details["city"] = city

        # Keywords that indicate the listing is GONE despite the page being up
        gone_keywords = ["n'est plus disponible", "annonce supprimée", "déjà vendu", "déjà loué", "ne sont plus disponibles"]
        page_text_lower = html_content.lower()
        if any(k in page_text_lower for k in gone_keywords):
            print(f"[LeFigaro] Listing marked as GONE in DOM: {url}", flush=True)
            return {}

        # Only proceed if we find a price or specific listing markers
        price_text = soup.get_text(" ", strip=True)
        price_match = re.search(r'([\d\s]+)\s*€', price_text)

        if price_match:
            price_str = re.sub(r'[^\d]', '', price_match.group(1))
            if price_str:
                details["price"] = float(price_str)
                # If we have a price, we assume it's a valid listing page
                ext_id = url.split('-')[-1].split('.')[0]
                details["external_id"] = f"figaro_{ext_id}"
                
                # ── Photo fallback ──
                fb_photos = []
                for img in soup.find_all('img', src=re.compile(r'images\.figaro|media\.figaro|lh3\.googleusercontent\.com')):
                    src = img.get('src')
                    if src and 'thumb' not in src.lower():
                        fb_photos.append(src)
                if fb_photos:
                    # Remove duplicates while preserving order
                    unique_photos = []
                    for p in fb_photos:
                        if p not in unique_photos:
                            unique_photos.append(p)
                    details["photo_urls"] = unique_photos
                else:
                    og_img = soup.find('meta', attrs={"property": "og:image"})
                    if og_img and og_img.get("content"):
                        details["photo_urls"] = [og_img.get("content")]
                
                return details

        print(f"[LeFigaro] No valid listing data found for {url}, marking as disappeared", flush=True)
        return {}

        return details

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _classified_to_dict(self, classified: dict, url: str = None) -> dict:
        """Convert a raw 'classified' dict from __NUXT__ into our standard format."""
        record_link = classified.get("recordLink") or classified.get("url") or url or ""
        if record_link and not record_link.startswith("http"):
            record_link = "https://immobilier.lefigaro.fr" + record_link

        ext_id = classified.get("id") or (record_link.split('-')[-1].split('.')[0] if record_link else "")

        loc_data = classified.get("location", {}) or {}
        city_name = loc_data.get("city") or loc_data.get("cityLabel")
        zip_code = loc_data.get("zipCode") or loc_data.get("postalCode")
        if city_name:
            city = self._normalize_city(city_name)
            location = f"{city_name} ({zip_code[:2]})" if zip_code else city_name
        else:
            city = None
            location = "France"

        # Photos
        photos_list = []
        images_data = classified.get("images", {}) or {}
        raw_photos = (
            images_data.get("photos")
            or classified.get("medias")
            or classified.get("photos")
            or []
        )
        if isinstance(raw_photos, list):
            for p in raw_photos:
                if not isinstance(p, dict):
                    continue
                urls = p.get("url", {}) or {}
                if isinstance(urls, str):
                    photos_list.append(urls)
                elif isinstance(urls, dict):
                    best = (
                        urls.get("extra-large")
                        or urls.get("large")
                        or urls.get("medium")
                        or urls.get("small")
                    )
                    if best:
                        photos_list.append(best)

        # DPE & GES
        dpe_data = classified.get("dpe", {}) or {}
        dpe_rating = dpe_data.get("energyCategory") or dpe_data.get("dpeCategory")
        ges_rating = dpe_data.get("gesCategory")
        dpe_value = dpe_data.get("energy") or dpe_data.get("dpeValue")
        ges_value = dpe_data.get("ges") or dpe_data.get("gesValue")

        # Équipements & Extérieurs
        options = classified.get("options", []) or []
        if isinstance(options, str):
            options = [options]
        options_lower = [str(o).lower() for o in options]
        
        has_balcony = any("balcon" in o for o in options_lower)
        has_terrace = any("terrass" in o for o in options_lower)
        has_garden = any("jardin" in o for o in options_lower)
        has_elevator = any("ascenseur" in o for o in options_lower)
        has_cellar = any("cave" in o for o in options_lower)
        has_pool = any("piscin" in o for o in options_lower)
        has_parking = any(k in o for o in options_lower for k in ["parking", "garage", "box"])

        # Financier & Copropriété
        price_data = classified.get("priceData", {}) or {}
        condominium = classified.get("condominium", {}) or {}
        
        land_tax = None
        prop_tax = price_data.get("propertyTax")
        if isinstance(prop_tax, dict):
            land_tax = prop_tax.get("value")
            
        charges = None
        annual_fees = condominium.get("annualFees")
        if annual_fees:
            try:
                charges = float(annual_fees) / 12.0
            except:
                pass
                
        procedure_syndic = condominium.get("ongoingRecourse")
        copropriete_lots = condominium.get("lotsCount")

        # Handle lists in rooms
        rooms = classified.get("roomCount") or classified.get("rooms")
        if isinstance(rooms, list) and len(rooms) > 0:
            rooms = rooms[0]
            
        bedrooms = (
            classified.get("bedRoomCount") 
            or classified.get("bedroomCount") 
            or classified.get("bedrooms")
        )
        if isinstance(bedrooms, list) and len(bedrooms) > 0:
            bedrooms = bedrooms[0]

        description = (
            classified.get("descriptionFull") 
            or classified.get("fullDescription") 
            or classified.get("description") 
            or classified.get("descriptionText") 
            or ""
        )

        # Mobilité / Transports
        poi_categories = loc_data.get("poiCategories", [])
        transports = []
        if isinstance(poi_categories, list):
            for cat in poi_categories:
                if isinstance(cat, dict) and cat.get("label", "").lower() in ["transports", "mobilité"]:
                    for poi in cat.get("poi", []):
                        if isinstance(poi, dict):
                            count = poi.get("count", 0)
                            label = poi.get("label", "")
                            if count and label:
                                transports.append(f"{count} {label}")
        if transports:
            description += "\n\nTransports : " + ", ".join(transports)

        return {
            "external_id": f"figaro_{ext_id}",
            "title": classified.get("title") or classified.get("subject") or "Annonce Le Figaro",
            "url": record_link,
            "price": classified.get("price") or classified.get("priceValue") or 0.0,
            "location": location,
            "city": city,
            "area": classified.get("surface") or classified.get("area"),
            "rooms": rooms,
            "bedrooms": bedrooms,
            "description_text": description,
            "photo_urls": photos_list,
            
            # Nouvelles données extraites
            "dpe_rating": dpe_rating,
            "ges_rating": ges_rating,
            "dpe_value": dpe_value,
            "ges_value": ges_value,
            
            "balcony": has_balcony,
            "terrace": has_terrace,
            "garden": has_garden,
            "elevator": has_elevator,
            "cellar": has_cellar,
            "pool": has_pool,
            "parking_count": 1 if has_parking else 0,
            
            "land_tax": land_tax,
            "charges": charges,
            "procedure_syndic": procedure_syndic,
            "copropriete_lots": copropriete_lots,
            "property_type": classified.get("type"),
            "heating_type": classified.get("heatingType"),
            "land_area": classified.get("areaGround"),
            "bathroom_count": classified.get("showerRoomCount") or classified.get("bathroomCount"),
        }

    def _parse_location_from_text(self, text: str) -> tuple:
        """
        Try to extract (location_str, normalized_city) from a free-form text.
        Returns ("", None) if nothing found.
        """
        if not text:
            return "", None

        # Pattern: "… à Tournon-sur-Rhône (07300) …"
        match = re.search(r'à (.*?) \((\d{5})\)', text)
        if match:
            city_name = match.group(1).strip()
            zip_code = match.group(2).strip()
            return f"{city_name} ({zip_code[:2]})", self._normalize_city(city_name)

        # Pattern: "Paris 3ème (75)" (already formatted)
        match = re.search(r'([A-Za-zÀ-ÿ\s\-]+)\s+\((\d{2,5})\)', text)
        if match:
            city_name = match.group(1).strip()
            dep = match.group(2).strip()
            return f"{city_name} ({dep[:2]})", self._normalize_city(city_name)

        # Pattern: "… à Paris …"
        match = re.search(r' à ([A-Za-zÀ-ÿ\s\-]+?)(?:[,\.]|$)', text)
        if match:
            city_name = match.group(1).strip()
            return city_name, self._normalize_city(city_name)

        return "", None
