import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional


class LeboncoinScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extrait les annonces depuis une page de recherche LeBonCoin.
        Priorité au payload __NEXT_DATA__ JSON intégré dans le HTML.
        """
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        text_content = snapshot.get("text", "")
        listings = []

        if html_content:
            # Primary: extract from __NEXT_DATA__ JSON payload
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                html_content, re.DOTALL
            )
            if match:
                try:
                    data = json.loads(match.group(1))
                    ads = (
                        data.get("props", {})
                        .get("pageProps", {})
                        .get("searchData", {})
                        .get("ads", [])
                    )
                    for ad in ads:
                        location = ad.get("location", {})
                        city = location.get("city", "")
                        zip_code = location.get("zipcode", "")
                        location_str = f"{city} {zip_code}".strip() if zip_code else city

                        price = ad.get("price", [0])
                        price_val = price[0] if isinstance(price, list) and price else 0.0

                        area = self._extract_area_from_attrs(ad.get("attributes", []))
                        rooms = self._extract_rooms_from_attrs(ad.get("attributes", []))

                        listings.append({
                            "external_id": f"lbc_{ad.get('list_id')}",
                            "title": ad.get("subject", "Sans titre"),
                            "url": f"https://www.leboncoin.fr{ad.get('url', '')}",
                            "price": float(price_val),
                            "location": location_str,
                            "city": self._normalize_city(city),
                            "area": area,
                            "rooms": rooms,
                            "photo_urls": [],  # Will be fetched on detail page
                        })
                    return listings
                except Exception as e:
                    print(f"[LBC] Erreur parsing JSON NEXT_DATA: {e}")

            # Fallback: BeautifulSoup HTML parsing
            soup = BeautifulSoup(html_content, 'html.parser')
            ads = soup.find_all('a', attrs={"data-qa-id": "aditem_container"})

            for ad in ads:
                try:
                    url = "https://www.leboncoin.fr" + ad.get('href', '')
                    title_elem = ad.find('p', attrs={"data-qa-id": "aditem_title"})
                    title = title_elem.text.strip() if title_elem else "Sans titre"
                    price_elem = ad.find('p', attrs={"data-test-id": "price"})
                    price_str = re.sub(r'[^\d]', '', price_elem.text) if price_elem else "0"
                    price = float(price_str) if price_str.isdigit() else 0.0
                    external_id = url.split('/')[-1].split('.')[0] if url.split('/')[-1] else url

                    listings.append({
                        "external_id": f"lbc_{external_id}",
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
                    print(f"[LBC] Erreur BS4: {e}")
                    continue

        elif text_content:
            print("[LBC] Fallback texte regex (données incomplètes)")
            matches = re.findall(
                r'(https://www\.leboncoin\.fr/(?:ventes_immobilieres|locations)/[^\s"\'<>]+)',
                text_content
            )
            for m in set(matches):
                external_id = m.split('/')[-1].split('.')[0]
                listings.append({
                    "external_id": f"lbc_{external_id}",
                    "title": "Annonce LeBonCoin",
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
        Scrape a single LeBonCoin listing page for enriched details:
        DPE, GES, rooms, floor, land_tax, charges, photos, description.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details = {}

        # Primary: parse __NEXT_DATA__ JSON for detail page
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html_content, re.DOTALL
        )
        if match:
            try:
                data = json.loads(match.group(1))
                ad = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("ad", {})
                )

                if ad:
                    # Extract location
                    location = ad.get("location", {})
                    city = location.get("city", "")
                    zip_code = location.get("zipcode", "")
                    details["location"] = f"{city} {zip_code}".strip()
                    details["city"] = self._normalize_city(city)
                    details["title"] = ad.get("subject", "")
                    details["description_text"] = ad.get("body", "")

                    # Price
                    price_list = ad.get("price", [0])
                    details["price"] = float(price_list[0]) if price_list else 0.0

                    # External ID
                    details["external_id"] = f"lbc_{ad.get('list_id', '')}"

                    # Photos: get all images
                    images = ad.get("images", {})
                    urls = images.get("urls_large") or images.get("urls")
                    if isinstance(urls, list):
                        details["photo_urls"] = [u for u in urls if isinstance(u, str)]
                    elif isinstance(urls, str):
                        details["photo_urls"] = [urls]
                    else:
                        details["photo_urls"] = []

                    # Fallback to HTML if JSON images are missing or only one
                    if len(details["photo_urls"]) <= 1:
                        fb_photos = []
                        # Look for images in the gallery container if possible
                        for img in soup.find_all('img', src=re.compile(r'img\.leboncoin\.fr')):
                            src = img.get('src') or img.get('data-src')
                            if src and 'thumb' not in src.lower() and 'small' not in src.lower():
                                fb_photos.append(src)
                        if fb_photos:
                            details["photo_urls"] = list(set(fb_photos + details["photo_urls"]))

                    # Attributes: DPE, GES, rooms, floor, taxes, charges, area
                    attrs = ad.get("attributes", [])
                    details.update(self._parse_attributes(attrs))

                    # Calculate price per m²
                    area = details.get("area")
                    price = details.get("price", 0)
                    if area and area > 0 and price > 0:
                        details["price_per_sqm"] = round(price / area, 2)

                    return details

            except Exception as e:
                print(f"[LBC] Erreur parsing détail JSON: {e}")

        # Fallback: BeautifulSoup for meta tags and LeBonCoin-specific selectors
        soup = BeautifulSoup(html_content, 'html.parser')
        title_tag = soup.find('title')
        if title_tag:
            details["title"] = title_tag.text.strip()

        # LeBonCoin-specific: full description text
        desc_container = soup.find('div', attrs={"data-qa-id": "adview_description_container"})
        if desc_container:
            details["description_text"] = desc_container.get_text(separator="\n", strip=True)
        else:
            # Fallback to og:description meta tag
            og_desc = soup.find('meta', attrs={"property": "og:description"})
            if og_desc:
                details["description_text"] = og_desc.get("content", "")

        # LeBonCoin-specific: location block (city + zip code)
        location_block = soup.find('div', class_="mb-lg")
        if location_block:
            location_text = location_block.get_text(separator=" ", strip=True)
            if location_text:
                details["location"] = location_text
                details["city"] = self._normalize_city(location_text)

        return details


    # ─── Private Helpers ──────────────────────────────────────────────────────

    def _parse_attributes(self, attrs: list) -> Dict:
        """
        Parses the LeBonCoin 'attributes' list from JSON to extract
        all property characteristics exposed on the detail page.
        """
        result = {}

        for attr in attrs:
            key = attr.get("key", "")
            val = attr.get("value", attr.get("value_label", ""))
            label = attr.get("value_label", val)  # Human-readable label when available

            # ── Energy ─────────────────────────────────────────────────────
            if key == "energy_rate":
                result["dpe_rating"] = str(val).upper()[:1] if val else None

            elif key == "ges":
                result["ges_rating"] = str(val).upper()[:1] if val else None

            elif key == "energy_value":
                try:
                    result["dpe_value"] = float(str(val).replace(",", ".").replace(" ", ""))
                except (ValueError, TypeError):
                    pass

            elif key == "ges_value":
                try:
                    result["ges_value"] = float(str(val).replace(",", ".").replace(" ", ""))
                except (ValueError, TypeError):
                    pass

            # ── Surfaces ────────────────────────────────────────────────────
            elif key == "square":
                try:
                    result["area"] = float(str(val).replace(",", ".").replace(" ", ""))
                except (ValueError, TypeError):
                    pass

            elif key == "land_plot_square":
                try:
                    result["land_area"] = float(str(val).replace(",", ".").replace(" ", ""))
                except (ValueError, TypeError):
                    pass

            elif key == "balcony_surface":
                try:
                    result["balcony_area"] = float(str(val).replace(",", ".").replace(" ", ""))
                    result["balcony"] = True
                except (ValueError, TypeError):
                    pass

            elif key == "terrace_surface":
                try:
                    result["terrace_area"] = float(str(val).replace(",", ".").replace(" ", ""))
                    result["terrace"] = True
                except (ValueError, TypeError):
                    pass

            elif key == "garden_surface":
                try:
                    result["garden_area"] = float(str(val).replace(",", ".").replace(" ", ""))
                    result["garden"] = True
                except (ValueError, TypeError):
                    pass

            # ── Rooms / Counts ──────────────────────────────────────────────
            elif key == "rooms":
                try:
                    result["rooms"] = int(val)
                except (ValueError, TypeError):
                    pass

            elif key == "bedrooms":
                try:
                    result["bedrooms"] = int(val)
                except (ValueError, TypeError):
                    pass

            elif key == "nb_bathrooms":
                try:
                    result["bathroom_count"] = int(val)
                except (ValueError, TypeError):
                    pass

            elif key == "nb_toilets":
                try:
                    result["toilet_count"] = int(val)
                except (ValueError, TypeError):
                    pass

            elif key == "floor_number":
                try:
                    result["floor"] = int(val)
                except (ValueError, TypeError):
                    pass

            elif key == "nb_floors_building":
                try:
                    result["total_floors"] = int(val)
                except (ValueError, TypeError):
                    pass

            elif key == "parking_places_nb":
                try:
                    result["parking_count"] = int(val)
                except (ValueError, TypeError):
                    pass

            elif key == "nb_lots":
                try:
                    result["copropriete_lots"] = int(val)
                except (ValueError, TypeError):
                    pass

            # ── Boolean amenities ───────────────────────────────────────────
            elif key == "balcony_count":
                try:
                    result["balcony"] = int(val) > 0
                except (ValueError, TypeError):
                    result["balcony"] = bool(val)

            elif key == "terrace_count":
                try:
                    result["terrace"] = int(val) > 0
                except (ValueError, TypeError):
                    result["terrace"] = bool(val)

            elif key in ("garden", "has_garden"):
                result["garden"] = str(val).lower() not in ("0", "false", "non", "no", "")

            elif key == "swimming_pool":
                result["pool"] = str(val).lower() not in ("0", "false", "non", "no", "")

            elif key == "elevator":
                result["elevator"] = str(val).lower() not in ("0", "false", "non", "no", "")

            elif key == "cellar":
                result["cellar"] = str(val).lower() not in ("0", "false", "non", "no", "")

            elif key == "intercom":
                result["interphone"] = str(val).lower() not in ("0", "false", "non", "no", "")

            elif key == "guardian":
                result["guardian"] = str(val).lower() not in ("0", "false", "non", "no", "")

            elif key == "furnished":
                result["furnished"] = str(val).lower() not in ("0", "false", "non", "no", "")

            elif key == "procedure_in_progress":
                result["procedure_syndic"] = str(val).lower() not in ("0", "false", "non", "no", "")

            # ── Text characteristics ────────────────────────────────────────
            elif key == "real_estate_type":
                result["property_type"] = str(label).lower() if label else None

            elif key == "estate_condition":
                result["condition"] = str(label).lower() if label else None

            elif key == "heating":
                result["heating_type"] = str(label).lower() if label else None

            elif key == "heating_mode":
                result["heating_mode"] = str(label).lower() if label else None

            elif key == "kitchen":
                result["kitchen_type"] = str(label).lower() if label else None

            elif key == "orientation":
                result["orientation"] = str(label) if label else None

            elif key == "view":
                result["view"] = str(label) if label else None

            elif key in ("annual_charges", "charges"):
                try:
                    result["charges"] = float(str(val).replace(",", ".").replace(" ", ""))
                except (ValueError, TypeError):
                    pass

            elif key == "fai_included":
                result["honoraires_a_charge"] = str(label) if label else None

        return result

    def _extract_land_tax_from_text(self, text: str) -> Optional[float]:
        """Attempts to find land tax from description text."""
        patterns = [
            r'taxe foncière[^\d]*(\d[\d\s]*)\s*€',
            r'tf[^\d]*(\d[\d\s]*)\s*€',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(" ", ""))
                except ValueError:
                    pass
        return None

    def _extract_area_from_attrs(self, attrs: list) -> Optional[float]:
        """Extracts area from attributes list (for search results)."""
        for attr in attrs:
            if attr.get("key") == "square":
                try:
                    return float(str(attr.get("value", "0")).replace(",", "."))
                except (ValueError, TypeError):
                    pass
        return None

    def _extract_rooms_from_attrs(self, attrs: list) -> Optional[int]:
        """Extracts room count from attributes list (for search results)."""
        for attr in attrs:
            if attr.get("key") == "rooms":
                try:
                    return int(attr.get("value", 0))
                except (ValueError, TypeError):
                    pass
        return None

