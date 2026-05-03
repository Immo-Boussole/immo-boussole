import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional


class LeFigaroScraper(BaseScraper):

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: extract the __NUXT__ JSON blob from raw HTML
    # ─────────────────────────────────────────────────────────────────────────
    def _extract_nuxt_data(self, html_content: str) -> Optional[dict]:
        """
        Tries several patterns to extract the __NUXT__ state object from the
        rendered HTML.  Returns the parsed dict or None on failure.
        """
        soup = BeautifulSoup(html_content, 'html.parser')

        # Pattern 1: modern Nuxt 3 – inline JSON object assignment
        # e.g.  window.__NUXT__={"data":[...],"state":...}
        for script in soup.find_all('script'):
            text = script.string or ""
            match = re.search(r'window\.__NUXT__\s*=\s*(\{.*)', text, re.DOTALL)
            if match:
                raw = match.group(1).strip().rstrip(';')
                try:
                    # Balanced-brace extraction to avoid trailing JS
                    depth, end = 0, 0
                    for i, ch in enumerate(raw):
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                    return json.loads(raw[:end])
                except Exception as e:
                    print(f"[LeFigaro] Erreur parse __NUXT__ (pattern 1): {e}", flush=True)

        # Pattern 2: Nuxt 2 – function call form
        # e.g.  __NUXT__=(function(a,b,...){return {...}}(...))
        for script in soup.find_all('script'):
            text = script.string or ""
            if '__NUXT__' in text and 'function' in text:
                print("[LeFigaro] __NUXT__ via function() – parsing non supporté pour l'instant", flush=True)
                break

        return None

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

        # ── Fallback meta / title defaults ────────────────────────────────
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

        # Price regex fallback
        price_text = soup.get_text(" ", strip=True)
        price_match = re.search(r'([\d\s]+)\s*€', price_text)
        if price_match:
            price_str = re.sub(r'[^\d]', '', price_match.group(1))
            if price_str:
                details["price"] = float(price_str)

        ext_id = url.split('-')[-1].split('.')[0]
        details["external_id"] = f"figaro_{ext_id}"

        # ── Strategy 1: __NUXT__ ──────────────────────────────────────────
        nuxt_data = self._extract_nuxt_data(html_content)
        if nuxt_data:
            classified = self._find_classified_detail(nuxt_data)
            if classified:
                details = {**details, **self._classified_to_dict(classified, url=url)}
                return details
            else:
                print("[LeFigaro] __NUXT__ trouvé mais aucun classifiedDetailResponse dedans", flush=True)
        else:
            print("[LeFigaro] __NUXT__ absent du HTML", flush=True)

        # ── Photo fallback ─────────────────────────────────────────────────
        if not details.get("photo_urls"):
            fb_photos = []
            for img in soup.find_all('img', src=re.compile(r'images\.figaro|media\.figaro')):
                src = img.get('src')
                if src and 'thumb' not in src.lower():
                    fb_photos.append(src)
            if fb_photos:
                details["photo_urls"] = list(set(fb_photos))
            else:
                og_img = soup.find('meta', attrs={"property": "og:image"})
                if og_img and og_img.get("content"):
                    details["photo_urls"] = [og_img.get("content")]

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

        return {
            "external_id": f"figaro_{ext_id}",
            "title": classified.get("title") or classified.get("subject") or "Annonce Le Figaro",
            "url": record_link,
            "price": classified.get("price") or classified.get("priceValue") or 0.0,
            "location": location,
            "city": city,
            "area": classified.get("surface") or classified.get("area"),
            "rooms": classified.get("roomCount") or classified.get("rooms"),
            "bedrooms": classified.get("bedroomCount") or classified.get("bedrooms"),
            "description_text": classified.get("description") or classified.get("descriptionText") or "",
            "photo_urls": photos_list,
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
