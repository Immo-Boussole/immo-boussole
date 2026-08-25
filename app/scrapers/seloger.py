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
                r'(https://www\.seloger\.com/annonces?/[^\s"\'<>]+)',
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
        # 1. Standard application/json tags & JSON-LD
        scripts = soup.find_all('script', type='application/json')
        for script in scripts:
            try:
                data = json.loads(script.string or "")
                ad_details = self._extract_detail_from_json(data)
                if ad_details:
                    # Merge details, prioritizing non-empty values and largest photo list
                    for k, v in ad_details.items():
                        if k == "photo_urls":
                            existing_photos = details.get("photo_urls", [])
                            if len(v) > len(existing_photos):
                                details["photo_urls"] = v
                        elif k == "floorplans":
                            existing_fp = details.get("floorplans", [])
                            merged_fp = list(dict.fromkeys(existing_fp + v))
                            details["floorplans"] = merged_fp
                        elif not details.get(k):
                            details[k] = v
            except Exception:
                continue

        # 2. Modern window.__UFRN_LIFECYCLE_SERVERREQUEST__ / __NEXT_DATA__ (as JS variable)
        ufrn_script = soup.find('script', string=re.compile(r'window\.__UFRN_LIFECYCLE_SERVERREQUEST__|__NEXT_DATA__|__INITIAL_STATE__'))
        if ufrn_script and ufrn_script.string:
            try:
                start_idx = ufrn_script.string.find('{')
                end_idx = ufrn_script.string.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_text = ufrn_script.string[start_idx:end_idx+1]
                    data = json.loads(json_text)
                    ad_details = self._extract_detail_from_json(data)
                    if ad_details:
                        for k, v in ad_details.items():
                            if k == "photo_urls":
                                existing_photos = details.get("photo_urls", [])
                                if len(v) > len(existing_photos):
                                    details["photo_urls"] = v
                            elif k == "floorplans":
                                existing_fp = details.get("floorplans", [])
                                merged_fp = list(dict.fromkeys(existing_fp + v))
                                details["floorplans"] = merged_fp
                            elif not details.get(k):
                                details[k] = v
            except Exception as e:
                print(f"[SeLoger] Error parsing UFRN JSON: {e}")

        # 3. JSON-LD schema extraction
        for ld_script in soup.find_all('script', type='application/ld+json'):
            try:
                ld_data = json.loads(ld_script.string or "")
                items = ld_data if isinstance(ld_data, list) else (ld_data.get("@graph", [ld_data]) if isinstance(ld_data, dict) else [])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if not details.get("title") and (item.get("name") or item.get("headline")):
                        details["title"] = item.get("name") or item.get("headline")
                    if not details.get("description_text") and item.get("description"):
                        details["description_text"] = item.get("description")
                    if item.get("image"):
                        imgs = item.get("image")
                        ld_imgs = imgs if isinstance(imgs, list) else [imgs]
                        clean_ld = [self._normalize_image_url(u) for u in ld_imgs if self._is_valid_property_photo(u)]
                        if clean_ld:
                            curr_photos = details.get("photo_urls", [])
                            merged = list(dict.fromkeys(curr_photos + clean_ld))
                            details["photo_urls"] = merged
            except Exception:
                pass

        # 4. Fallback HTML meta & DOM
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag and not details.get("title"):
            details["title"] = title_tag.text.strip()

        og_img = soup.find('meta', attrs={"property": "og:image"})
        if og_img and og_img.get("content"):
            og_clean = self._normalize_image_url(og_img.get("content"))
            if og_clean and self._is_valid_property_photo(og_clean):
                curr = details.get("photo_urls", [])
                if og_clean not in curr:
                    curr.append(og_clean)
                details["photo_urls"] = curr

        og_desc = soup.find('meta', attrs={"property": "og:description"})
        if og_desc and not details.get("description_text"):
            details["description_text"] = og_desc.get("content", "")

        # 5. Regex extraction across script tags if still very few photos
        if len(details.get("photo_urls", [])) < 3:
            page_str = str(soup)
            regex_imgs = re.findall(
                r'https?:\\?/\\?/[^"\'\s<>]+\.(?:jpg|jpeg|webp|png)(?:\?[^"\'\s<>]*)?',
                page_str,
                re.IGNORECASE
            )
            found_photos = []
            for raw_u in regex_imgs:
                clean_u = raw_u.replace(r'\/', '/')
                norm_u = self._normalize_image_url(clean_u)
                if norm_u and self._is_valid_property_photo(norm_u) and norm_u not in found_photos:
                    found_photos.append(norm_u)
            if len(found_photos) > len(details.get("photo_urls", [])):
                details["photo_urls"] = found_photos

        return details

    # ─── Private Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _normalize_image_url(url: Optional[str]) -> str:
        """Normalizes and upgrades SeLoger/Aviv/Poliris image URLs to HD resolution."""
        if not url or not isinstance(url, str):
            return ""
        u = url.strip()
        if not u:
            return ""

        # Protocol-relative URL
        if u.startswith("//"):
            u = "https:" + u

        # Next.js optimized images (/_next/image?url=https%3A%2F%2F...&w=1920&q=75)
        if "/_next/image" in u and "url=" in u:
            try:
                import urllib.parse
                parsed = urllib.parse.urlparse(u)
                qs = urllib.parse.parse_qs(parsed.query)
                if "url" in qs and qs["url"]:
                    u = urllib.parse.unquote(qs["url"][0])
            except Exception:
                pass

        # Upgrade sizing in URL path to HD (1920x1080)
        u = re.sub(r'/(?:crop|fit-in|resize|thumbnail)/\d+x\d+/', '/fit-in/1920x1080/', u, flags=re.IGNORECASE)
        u = re.sub(r'/\d+x\d+/', '/1920x1080/', u)

        # Upgrade query params sizing
        if "w=" in u or "width=" in u:
            u = re.sub(r'[?&](?:w|width)=\d+', '&w=1920', u)
            u = re.sub(r'[?&](?:h|height)=\d+', '', u)
            u = u.replace('?&', '?')

        return u

    @staticmethod
    def _is_valid_property_photo(url: Optional[str]) -> bool:
        """Filters out logos, icons, avatars, pins, and non-photo assets."""
        if not url or not isinstance(url, str) or not url.startswith("http"):
            return False
        url_lower = url.lower()
        ignore_keywords = [
            'logo', 'avatar', 'icon', 'placeholder', 'rating', 'badge',
            'static-asset', 'pin-map', 'favicon', 'social', 'pixel'
        ]
        return not any(kw in url_lower for kw in ignore_keywords)

    def _extract_all_photos_from_json(self, data, depth=0) -> List[str]:
        """Recursively scans a JSON tree to extract all candidate photo URLs."""
        if not data or depth > 8:
            return []
        photos: List[str] = []

        def _add_url(candidate: Optional[str]):
            if candidate and isinstance(candidate, str):
                norm = self._normalize_image_url(candidate)
                if norm and self._is_valid_property_photo(norm) and norm not in photos:
                    photos.append(norm)

        def _extract_from_item(item):
            if isinstance(item, str):
                _add_url(item)
            elif isinstance(item, dict):
                for key in ['hdUrl', 'largeUrl', 'fullUrl', 'url', 'src', 'path', 'contentUrl', 'uri', 'original', 'large', 'big', 'url_photo', 'url_large', 'rawUrl', 'thumbnail']:
                    val = item.get(key)
                    if val and isinstance(val, str):
                        _add_url(val)
                if isinstance(item.get("image"), (str, dict)):
                    _extract_from_item(item.get("image"))
                if isinstance(item.get("urls"), dict):
                    for u_val in item["urls"].values():
                        if isinstance(u_val, str):
                            _add_url(u_val)

        if isinstance(data, list):
            for elem in data:
                _extract_from_item(elem)
        elif isinstance(data, dict):
            # Check direct photo array keys
            for key in ['images', 'photos', 'medias', 'pictures', 'rawPhotos', 'gallery']:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        for elem in val:
                            _extract_from_item(elem)
                    elif isinstance(val, dict):
                        for sub_k in ['images', 'photos', 'all', 'large', 'list']:
                            if isinstance(val.get(sub_k), list):
                                for elem in val[sub_k]:
                                    _extract_from_item(elem)

            # Recurse into child objects
            for val in data.values():
                if isinstance(val, (dict, list)):
                    sub_photos = self._extract_all_photos_from_json(val, depth + 1)
                    for sp in sub_photos:
                        if sp not in photos:
                            photos.append(sp)

        return photos

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
            loc_name = ad.get("city", "")
            zip_code = ad.get("zipCode") or ad.get("postalCode") or ""
            location_str = f"{loc_name} ({zip_code})".strip() if zip_code else loc_name

            raw_photos = self._extract_all_photos_from_json(ad)

            return {
                "external_id": f"sl_{ad.get('id', url.split('/')[-1])}",
                "title": ad.get("customTitle") or ad.get("headline") or ad.get("title") or ad.get("subject", "Annonce SeLoger"),
                "url": url,
                "price": float(ad.get("price", 0)),
                "location": location_str,
                "city": self._normalize_city(loc_name),
                "postal_code": str(zip_code) if zip_code else None,
                "area": ad.get("surface", ad.get("area", ad.get("livingArea"))),
                "land_area": ad.get("landSurface", ad.get("landArea")),
                "rooms": ad.get("rooms", ad.get("roomCount")),
                "bedrooms": ad.get("bedrooms", ad.get("bedroomCount")),
                "photo_urls": raw_photos,
            }
        except Exception:
            return None

    def _extract_detail_from_json(self, data) -> Dict:
        """Extracts enriched details from SeLoger's embedded JSON."""
        details = {}
        classified = None
        if isinstance(data, dict):
            # Check for various Next.js / UFRN structures
            if "app_cldp" in data and "data" in data["app_cldp"]:
                classified = data["app_cldp"]["data"].get("classified")
            elif "props" in data and "pageProps" in data["props"]:
                page_props = data["props"]["pageProps"]
                listing_data = page_props.get("listingData") or {}
                classified = (
                    listing_data.get("listing") or
                    listing_data.get("classified") or
                    page_props.get("classified") or
                    page_props.get("ad") or
                    page_props.get("initialState", {}).get("classified") or
                    page_props.get("initialState", {}).get("listing")
                )
            elif "listingData" in data:
                classified = data["listingData"].get("listing") or data["listingData"]
            elif "classified" in data:
                classified = data["classified"]
            elif "ad" in data:
                classified = data["ad"]
            elif "listing" in data:
                classified = data["listing"]

        if classified and isinstance(classified, dict):
            try:
                if classified.get("id"):
                    details["external_id"] = f"sl_{classified.get('id')}"

                # Title: prioritize custom headline / title
                title = (
                    classified.get("customTitle") or
                    classified.get("headline") or
                    classified.get("title") or
                    classified.get("subject")
                )
                if title:
                    details["title"] = str(title).strip()

                # Description
                desc = classified.get("description") or classified.get("body")
                if desc:
                    details["description_text"] = str(desc).strip()

                # Pricing & Financials
                pricing = classified.get("pricing", {})
                if isinstance(pricing, dict):
                    details["price"] = pricing.get("amount") or pricing.get("price") or classified.get("price")
                    if pricing.get("charges") is not None:
                        try: details["charges"] = float(pricing.get("charges"))
                        except (ValueError, TypeError): pass
                    if pricing.get("landTax") is not None or pricing.get("propertyTax") is not None:
                        try: details["land_tax"] = float(pricing.get("landTax") or pricing.get("propertyTax"))
                        except (ValueError, TypeError): pass
                else:
                    details["price"] = classified.get("price")

                # Location & Postal Code
                loc = classified.get("location", {})
                city = ""
                zipcode = ""
                if isinstance(loc, dict):
                    city = loc.get("city") or loc.get("cityName") or ""
                    zipcode = loc.get("zipCode") or loc.get("postalCode") or loc.get("postCode") or ""
                    tags = loc.get("tags", [])
                    if not city and tags:
                        city = tags[0]

                if not city and classified.get("city"):
                    city = classified.get("city")
                if not zipcode and classified.get("zipCode"):
                    zipcode = classified.get("zipCode")

                # Extract postal code from city/tag if embedded
                if city and not zipcode:
                    cp_match = re.search(r'\b(\d{5})\b', str(city))
                    if cp_match:
                        zipcode = cp_match.group(1)
                        city = re.sub(r'\(?\d{5}\)?', '', str(city)).strip()

                if city:
                    city_clean = city.strip()
                    details["city"] = city_clean
                    details["postal_code"] = str(zipcode) if zipcode else None
                    details["location"] = f"{city_clean} ({zipcode})" if zipcode else city_clean

                # Characteristics: rooms, bedrooms, areas
                rooms_info = classified.get("rooms", {})
                if isinstance(rooms_info, dict):
                    details["rooms"] = rooms_info.get("total") or rooms_info.get("roomCount") or classified.get("roomCount")
                    details["bedrooms"] = rooms_info.get("bedrooms") or rooms_info.get("bedRooms") or classified.get("bedroomCount")
                    bathrooms = (rooms_info.get("bathRooms") or 0) + (rooms_info.get("showerRooms") or 0)
                    if bathrooms > 0:
                        details["bathroom_count"] = bathrooms
                    toilets = rooms_info.get("toilets") or rooms_info.get("toiletCount")
                    if toilets:
                        details["toilet_count"] = toilets
                else:
                    details["rooms"] = classified.get("rooms") or classified.get("roomCount")
                    details["bedrooms"] = classified.get("bedrooms") or classified.get("bedroomCount")

                # Areas
                details["area"] = classified.get("livingArea") or classified.get("surface") or classified.get("area")
                details["land_area"] = classified.get("landSurface") or classified.get("landArea") or classified.get("groundArea")
                details["property_type"] = classified.get("propertyType") or classified.get("estateType") or classified.get("type")

                # Energy / DPE / GES
                energy = classified.get("energy", {})
                if isinstance(energy, dict):
                    dpe_obj = energy.get("dpe", {})
                    ges_obj = energy.get("ges", {})
                    if isinstance(dpe_obj, dict):
                        details["dpe_rating"] = str(dpe_obj.get("grade") or dpe_obj.get("letter") or "").upper()[:1] or None
                        if dpe_obj.get("consumption") or dpe_obj.get("value"):
                            try: details["dpe_value"] = float(dpe_obj.get("consumption") or dpe_obj.get("value"))
                            except (ValueError, TypeError): pass
                    elif isinstance(dpe_obj, str):
                        details["dpe_rating"] = dpe_obj.upper()[:1]

                    if isinstance(ges_obj, dict):
                        details["ges_rating"] = str(ges_obj.get("grade") or ges_obj.get("letter") or "").upper()[:1] or None
                        if ges_obj.get("emission") or ges_obj.get("value"):
                            try: details["ges_value"] = float(ges_obj.get("emission") or ges_obj.get("value"))
                            except (ValueError, TypeError): pass
                    elif isinstance(ges_obj, str):
                        details["ges_rating"] = ges_obj.upper()[:1]

                if not details.get("dpe_rating") and classified.get("dpeRating"):
                    details["dpe_rating"] = str(classified.get("dpeRating")).upper()[:1]
                if not details.get("ges_rating") and classified.get("gesRating"):
                    details["ges_rating"] = str(classified.get("gesRating")).upper()[:1]

                # Photos & Floorplans
                domains = classified.get("domains", {})
                medias = domains.get("medias", {}) if isinstance(domains, dict) else (classified.get("medias") if isinstance(classified.get("medias"), dict) else {})

                # Floorplans / Plans
                floorplans = []
                fp_list = (
                    (medias.get("floorplans") or medias.get("plans") or medias.get("floorPlans"))
                    if isinstance(medias, dict) else None
                )
                if not fp_list:
                    fp_list = classified.get("floorplans") or classified.get("floorPlans") or classified.get("plans")

                if isinstance(fp_list, list):
                    for fp in fp_list:
                        u = fp.get("url") if isinstance(fp, dict) else fp
                        if isinstance(u, str):
                            norm = self._normalize_image_url(u)
                            if norm and norm not in floorplans:
                                floorplans.append(norm)

                if floorplans:
                    details["floorplans"] = floorplans

                # Comprehensive photo extraction across classified and entire data node
                photos = self._extract_all_photos_from_json(classified)
                if not photos or len(photos) < 2:
                    all_json_photos = self._extract_all_photos_from_json(data)
                    for p in all_json_photos:
                        if p not in photos:
                            photos.append(p)

                # Include floorplans in photos so they render in gallery
                if floorplans:
                    for fp_url in floorplans:
                        if fp_url not in photos:
                            photos.append(fp_url)

                if photos:
                    details["photo_urls"] = list(dict.fromkeys(photos))

            except Exception as e:
                print(f"[SeLoger] Error parsing details from JSON: {e}")

        return details
