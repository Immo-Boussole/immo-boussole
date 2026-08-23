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
                    details.update(ad_details)
                    if details.get("photo_urls"):
                        break
            except Exception:
                continue

        # 2. Modern window.__UFRN_LIFECYCLE_SERVERREQUEST__ / __NEXT_DATA__ (as JS variable)
        if not details or not details.get("photo_urls"):
            ufrn_script = soup.find('script', string=re.compile(r'window\.__UFRN_LIFECYCLE_SERVERREQUEST__|__NEXT_DATA__'))
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

        # 3. JSON-LD schema extraction
        for ld_script in soup.find_all('script', type='application/ld+json'):
            try:
                ld_data = json.loads(ld_script.string or "")
                if isinstance(ld_data, dict):
                    if not details.get("title") and (ld_data.get("name") or ld_data.get("headline")):
                        details["title"] = ld_data.get("name") or ld_data.get("headline")
                    if not details.get("description_text") and ld_data.get("description"):
                        details["description_text"] = ld_data.get("description")
                    if not details.get("photo_urls") and ld_data.get("image"):
                        imgs = ld_data.get("image")
                        details["photo_urls"] = imgs if isinstance(imgs, list) else [imgs]
            except Exception:
                pass

        # 4. Fallback HTML meta & DOM
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag and not details.get("title"):
            details["title"] = title_tag.text.strip()
        
        og_img = soup.find('meta', attrs={"property": "og:image"})
        if og_img and not details.get("photo_urls"):
            details["photo_urls"] = [og_img.get("content")]

        og_desc = soup.find('meta', attrs={"property": "og:description"})
        if og_desc and not details.get("description_text"):
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
            loc_name = ad.get("city", "")
            zip_code = ad.get("zipCode") or ad.get("postalCode") or ""
            location_str = f"{loc_name} ({zip_code})".strip() if zip_code else loc_name

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
                "photo_urls": ad.get("photos", []),
            }
        except Exception:
            return None

    def _extract_detail_from_json(self, data) -> Dict:
        """Extracts enriched details from SeLoger's embedded JSON."""
        details = {}
        classified = None
        if isinstance(data, dict):
            # Check for UFRN structures
            if "app_cldp" in data and "data" in data["app_cldp"]:
                classified = data["app_cldp"]["data"].get("classified")
            elif "props" in data and "pageProps" in data["props"]:
                classified = data["props"]["pageProps"].get("classified") or data["props"]["pageProps"].get("ad")
            elif "classified" in data:
                classified = data["classified"]
            elif "ad" in data:
                classified = data["ad"]

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
                medias = domains.get("medias", {}) if isinstance(domains, dict) else {}
                
                # Photos
                photos = []
                images = medias.get("images", []) if isinstance(medias, dict) else []
                if not images:
                    images = classified.get("photos", [])
                
                if isinstance(images, list):
                    for img in images:
                        if isinstance(img, dict) and img.get("url"):
                            photos.append(img["url"])
                        elif isinstance(img, str):
                            photos.append(img)

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
                        if isinstance(fp, dict) and fp.get("url"):
                            floorplans.append(fp["url"])
                        elif isinstance(fp, str):
                            floorplans.append(fp)

                if floorplans:
                    details["floorplans"] = list(dict.fromkeys(floorplans))
                    # Also append floorplans to photo_urls so they are visible in the photo gallery
                    for fp_url in details["floorplans"]:
                        if fp_url not in photos:
                            photos.append(fp_url)

                if photos:
                    details["photo_urls"] = list(dict.fromkeys(photos))

            except Exception as e:
                print(f"[SeLoger] Error parsing details from JSON: {e}")

        return details
