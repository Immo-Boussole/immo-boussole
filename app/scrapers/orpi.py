import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional


class OrpiScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extracts listings from an Orpi search results page.
        """
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Orpi listings are usually in article or div with class .c-estate-thumb
            ad_cards = soup.select('.c-estate-thumb')
            if not ad_cards:
                # Try alternative selector if the site changed or structure is different
                ad_cards = soup.find_all('article', class_=re.compile(r'estate-card|c-estate-thumb', re.I))

            for ad in ad_cards:
                try:
                    # URL & ID
                    url_elem = ad.select_one('a.c-overlay__link')
                    if not url_elem or not url_elem.get('href'):
                        continue
                    
                    url = url_elem['href']
                    if url.startswith('/'):
                        url = "https://www.orpi.com" + url
                    
                    # Extract external_id
                    external_id = url.strip('/').split('-')[-1]
                    
                    # Title / Estate Info
                    # Orpi uses .c-estate-thumb__title OR .c-estate-thumb__infos__estate
                    title_elem = ad.select_one('.c-estate-thumb__infos__estate, .c-estate-thumb__title')
                    title = title_elem.text.strip() if title_elem else "Annonce Orpi"
                    
                    # Price
                    # Orpi uses .c-estate-thumb__price OR .c-estate-thumb__price-tag__price
                    price_elem = ad.select_one('.c-estate-thumb__price-tag__price, .c-estate-thumb__price')
                    price_str = re.sub(r'[^\d]', '', price_elem.text) if price_elem else "0"
                    price = float(price_str) if price_str else 0.0
                    
                    # Location
                    # Orpi uses .c-estate-thumb__infos__location OR .c-estate-thumb__location
                    loc_elem = ad.select_one('.c-estate-thumb__infos__location, .c-estate-thumb__location')
                    location = loc_elem.text.strip() if loc_elem else "France"
                    
                    # Area & Rooms (often embedded in title/estate info)
                    area_val = None
                    rooms_val = None
                    
                    # Try specific elements first (thumb surface/rooms)
                    surface_elem = ad.select_one('.c-estate-thumb__surface')
                    if surface_elem:
                        area_match = re.search(r'([\d\.,]+)', surface_elem.text)
                        if area_match:
                            area_val = float(area_match.group(1).replace(',', '.'))
                    
                    rooms_elem = ad.select_one('.c-estate-thumb__rooms')
                    if rooms_elem:
                        rooms_match = re.search(r'(\d+)', rooms_elem.text)
                        if rooms_match:
                            rooms_val = int(rooms_match.group(1))

                    # Parse from title/estate info string if still missing
                    # Example: "Achat Maison 4 pièces 117 m2"
                    if title and (area_val is None or rooms_val is None):
                        if area_val is None:
                            # Try matching "117 m2" or "117 m²"
                            area_match = re.search(r'(\d+(?:[\.,]\d+)?)\s*m[2²]', title)
                            if area_match:
                                area_val = float(area_match.group(1).replace(',', '.'))
                        if rooms_val is None:
                            # Try matching "4 pièces"
                            rooms_match = re.search(r'(\d+)\s*pièce', title, re.I)
                            if rooms_match:
                                rooms_val = int(rooms_match.group(1))

                    listings.append({
                        "external_id": f"orpi_{external_id}",
                        "title": title,
                        "url": url,
                        "price": price,
                        "location": location,
                        "city": self._normalize_city(location),
                        "area": area_val,
                        "rooms": rooms_val,
                        "photo_urls": [],
                    })
                except Exception as e:
                    print(f"[OrpiScraper] Error parsing ad card: {e}")
                    continue

        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrapes a single Orpi listing detail page.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        try:
            # Basic info
            # Title
            title_elem = soup.select_one('h1.c-estate-detail-header__title, h1')
            if title_elem:
                # Clean up title (remove excess whitespace/newlines)
                details["title"] = re.sub(r'\s+', ' ', title_elem.text).strip()
            
            # Price
            # Subagent found: strong.u-h2.u-color-primary
            price_elem = soup.select_one('strong.u-h2.u-color-primary, .c-estate-detail-header__price, .c-estate-detail__price')
            if price_elem:
                price_str = re.sub(r'[^\d]', '', price_elem.text)
                details["price"] = float(price_str) if price_str else 0.0

            # Description
            desc_elem = soup.select_one('div.s-cms.u-p, .u-text-pre-line, .c-estate-detail__description, .c-estate-detail__text')
            if desc_elem:
                details["description_text"] = desc_elem.text.strip()

            # Photos
            # Orpi uses a slider with images, sometimes in <img> with data-src or inside a specific gallery class
            photo_urls = []
            img_elems = soup.select('img.u-cover, .c-estate-detail__gallery img, .c-gallery__item img, img.c-estate-thumb__img')
            for img in img_elems:
                src = img.get('data-src') or img.get('src')
                if src:
                    if src.startswith('//'): src = "https:" + src
                    if src.startswith('/'): src = "https://www.orpi.com" + src
                    # Avoid tracking pixels or icons
                    if 'spacer.gif' in src or 'pixel.gif' in src or 'logo' in src.lower(): continue
                    photo_urls.append(src)
            
            # Deduplicate photos
            details["photo_urls"] = list(dict.fromkeys(photo_urls))

            # DPE / GES
            # Orpi uses .c-dpe, .c-energy, or specific rating items
            dpe_elem = soup.select_one('.c-energy-rating--dpe .c-energy-rating__value--active, .c-dpe__rating--dpe')
            if dpe_elem:
                details["dpe_rating"] = dpe_elem.text.strip().upper()[:1]
            
            ges_elem = soup.select_one('.c-energy-rating--ges .c-energy-rating__value--active, .c-dpe__rating--ges')
            if ges_elem:
                details["ges_rating"] = ges_elem.text.strip().upper()[:1]

            # Characteristics (Surface, Rooms, etc.)
            # Subagent found: div#collapse-details li
            char_items = soup.select('div#collapse-details li, ul.c-list-details li, .c-estate-characteristics__item')
            for item in char_items:
                # Some items are label: value, others are just text
                label_elem = item.select_one('.c-estate-characteristics__label')
                value_elem = item.select_one('.c-estate-characteristics__value')
                
                # Some sites use <span> for values inside <li>
                if not value_elem:
                    value_elem = item.select_one('span')

                if label_elem and value_elem:
                    txt_label = label_elem.text.strip().lower()
                    txt_value = value_elem.text.strip()
                else:
                    # Fallback for simple list items (e.g. "4 pièces")
                    txt_full = item.text.strip().lower()
                    txt_label = txt_full
                    txt_value = txt_full

                if 'surface' in txt_label or 'm2' in txt_label or 'm²' in txt_label:
                    match = re.search(r'([\d\.,]+)', txt_value)
                    if match: details["area"] = float(match.group(1).replace(',', '.'))
                elif 'pièce' in txt_label:
                    match = re.search(r'(\d+)', txt_value)
                    if match: details["rooms"] = int(match.group(1))
                elif 'chambre' in txt_label:
                    match = re.search(r'(\d+)', txt_value)
                    if match: details["bedrooms"] = int(match.group(1))
                elif 'étage' in txt_label:
                    match = re.search(r'(\d+)', txt_value)
                    if match: details["floor"] = int(match.group(1))
            
            # Fallback for missing area/rooms: parse from title
            if details.get("title") and (details.get("area") is None or details.get("rooms") is None):
                title_txt = details["title"]
                if details.get("area") is None:
                    area_match = re.search(r'(\d+(?:[\.,]\d+)?)\s*m[2²]', title_txt)
                    if area_match:
                        details["area"] = float(area_match.group(1).replace(',', '.'))
                if details.get("rooms") is None:
                    rooms_match = re.search(r'(\d+)\s*pièce', title_txt, re.I)
                    if rooms_match:
                        details["rooms"] = int(rooms_match.group(1))

            # Location / City
            # Subagent found: span.u-h5.u-flex.u-mt-sm.u-text-normal
            loc_elem = soup.select_one('span.u-h5.u-flex.u-mt-sm.u-text-normal, .c-estate-detail__location, .c-estate-detail-header__location')
            if loc_elem:
                details["location"] = loc_elem.text.strip()
                # Remove icons/extra text if present (Orpi sometimes puts an icon inside)
                details["location"] = re.sub(r'\s+', ' ', details["location"]).strip()
                details["city"] = self._normalize_city(details["location"])
            
            # If city still missing, try searching for it in the title or "Localisation" section
            if not details.get("city") or details.get("city") == "France":
                # Look for "à [Ville]" in title
                title_txt = details.get("title", "")
                city_match = re.search(r'(?:à|en|dans)\s+([A-Z][\w\-\s\'’]+)', title_txt)
                if city_match:
                    details["city"] = self._normalize_city(city_match.group(1))

            # External ID
            details["external_id"] = f"orpi_{url.strip('/').split('-')[-1]}"

        except Exception as e:
            print(f"[OrpiScraper] Error parsing detail page: {e}")

        return details

    async def _handle_cookie_banner(self, page):
        """Clicks the Orpi (Didomi) cookie consent button if present."""
        try:
            # Wait for banner (Didomi can be slow)
            await page.wait_for_timeout(4000)
            
            # JS-based bypass including Shadow DOM support
            # Didomi notice is often inside a shadowRoot of #didomi-host
            await page.evaluate("""() => {
                const getButton = () => {
                    // 1. Check shadow DOM
                    const host = document.querySelector('#didomi-host');
                    if (host && host.shadowRoot) {
                        const btn = host.shadowRoot.querySelector('#didomi-notice-agree-button') || 
                                    host.shadowRoot.querySelector('.didomi-continue-without-agreeing');
                        if (btn) return btn;
                    }
                    // 2. Check main document
                    return document.querySelector('#didomi-notice-agree-button') || 
                           document.querySelector('.didomi-continue-without-agreeing') ||
                           [...document.querySelectorAll('button')].find(b => b.innerText.includes('Accepter'));
                };
                
                const button = getButton();
                if (button) {
                    button.click();
                    return true;
                }
                return false;
            }""")
            
            await page.wait_for_timeout(2000)
            print("[OrpiScraper] Cookie bypass JS executed (Shadow DOM checked).")
        except Exception as e:
            print(f"[OrpiScraper] Warning: Failed to handle cookie banner: {e}")
