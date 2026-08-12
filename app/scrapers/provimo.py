import re
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from app.scrapers.base import BaseScraper

class ProvimoScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract search results from PROVIMO.
        """
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            articles = soup.find_all("article", class_="item")
            
            for idx, art in enumerate(articles):
                try:
                    # Link
                    link_elem = art.find("a", href=True)
                    if not link_elem:
                        continue
                    href = link_elem["href"]
                    url = href if href.startswith("http") else "https://www.provimo.fr" + href
                    
                    # External ID
                    ext_id = None
                    btn = art.find("button", class_="selection-manager")
                    if btn and btn.get("data-add-url"):
                        m = re.search(r'idbien=(\d+)', btn.get("data-add-url"))
                        if m:
                            ext_id = m.group(1)
                    
                    if not ext_id:
                        m = re.search(r'/(\d+)-[^/]*$', url)
                        if m:
                            ext_id = m.group(1)
                    
                    if not ext_id:
                        continue
                        
                    # Title
                    title_elem = art.find(class_="item__block--title") or art.find(class_="item__title")
                    title = ""
                    if title_elem:
                        title = re.sub(r'\s+', ' ', title_elem.get_text()).strip()
                    
                    # Price
                    price_elem = art.find(class_="item__price")
                    price = 0.0
                    if price_elem:
                        price_str = re.sub(r'[^\d]', '', price_elem.get_text())
                        if price_str:
                            price = float(price_str)
                            
                    # Location
                    loc_elem = art.find(class_="title-v1__part1")
                    location = "France"
                    if loc_elem:
                        location = re.sub(r'\s+', ' ', loc_elem.get_text()).strip()
                        
                    # Area
                    area = 0.0
                    area_match = re.search(r'(\d+[\d\s,]*)\s*m²', title.lower())
                    if area_match:
                        area_str = area_match.group(1).replace(',', '.').replace(' ', '')
                        try:
                            area = float(area_str)
                        except ValueError:
                            pass
                            
                    listings.append({
                        "external_id": f"provimo_{ext_id}",
                        "title": title,
                        "url": url,
                        "price": price,
                        "location": location,
                        "area": area
                    })
                except Exception as e:
                    print(f"[ProvimoScraper] Error parsing listing index {idx}: {e}")
                    continue
        
        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape detail page for a PROVIMO listing.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        # Clean tags that interfere with textual searches
        for tag in soup(["script", "style"]):
            tag.decompose()

        details["url"] = url

        # External ID
        ext_id = None
        btn = soup.find("button", class_="selection-manager")
        if btn and btn.get("data-add-url"):
            m = re.search(r'idbien=(\d+)', btn.get("data-add-url"))
            if m:
                ext_id = m.group(1)
        if not ext_id:
            m = re.search(r'/(\d+)-[^/]*$', url)
            if m:
                ext_id = m.group(1)
        if ext_id:
            details["external_id"] = f"provimo_{ext_id}"
        else:
            # If we can't get an ID, return empty as it's likely an invalid/expired page
            return {}

        # Title
        title_elem = soup.find(class_="properties-detail__title")
        if title_elem:
            details["title"] = re.sub(r'\s+', ' ', title_elem.get_text()).strip()
        else:
            title_tag = soup.find("title")
            details["title"] = title_tag.text.strip() if title_tag else "Annonce PROVIMO"

        # Description
        desc_elem = soup.find(class_="js-display-text-content") or soup.find(class_="detail-data-description")
        if desc_elem:
            details["description_text"] = desc_elem.get_text().strip()
        else:
            og_desc = soup.find('meta', attrs={"property": "og:description"})
            details["description_text"] = og_desc.get("content", "").strip() if og_desc else ""

        # Photo URLs (Deduplicated high-resolution swiper images using data-path)
        img_tags = soup.find_all("img")
        photo_urls = []
        seen_paths = set()
        for img in img_tags:
            path = img.get("data-path")
            src = img.get("data-src") or img.get("src")
            
            if path:
                path_clean = path.strip("/")
                if path_clean in seen_paths:
                    continue
                seen_paths.add(path_clean)
                
                # Build high resolution URL
                if path_clean.startswith("images/"):
                    full_url = f"https://reseauprovimo.staticlbi.com/1600xauto/{path_clean}"
                else:
                    full_url = f"https://reseauprovimo.staticlbi.com/1600xauto/images/{path_clean}"
                photo_urls.append(full_url)
            elif src and ("biens" in src or "photo_" in src):
                # Fallback for general images
                full_url = src if src.startswith("http") else ("https:" + src if src.startswith("//") else "https://www.provimo.fr" + src)
                # Normalize resolution prefix to 1600xauto if possible
                full_url = re.sub(r'/(?:\d+x\w+|original)/', '/1600xauto/', full_url)
                if full_url not in photo_urls:
                    photo_urls.append(full_url)
                    
        details["photo_urls"] = photo_urls

        # Parse technical characteristics from list items
        char_div = soup.find(class_="detail_caracteristiques_content")
        if char_div:
            ul = char_div.find("ul")
            if ul:
                for li in ul.find_all("li"):
                    text = li.get_text(strip=True).lower()
                    classes = li.get("class", [])
                    
                    # Surface
                    if "surf" in classes and "surf_carrez" not in classes:
                        m = re.search(r'(\d+[\d\s,]*)\s*m²', text)
                        if m:
                            details["area"] = float(m.group(1).replace(',', '.').replace(' ', ''))
                    
                    # Terrain / Land Area
                    elif "surfterrn" in classes:
                        m = re.search(r'(\d+[\d\s,]*)\s*m²', text)
                        if m:
                            details["land_area"] = float(m.group(1).replace(',', '.').replace(' ', ''))
                            
                    # Construction Year
                    elif "annee_cons" in classes:
                        m = re.search(r'(\d{4})', text)
                        if m:
                            details["building_year"] = int(m.group(1))
                            
                    # Rooms/Chambres/Bains/Garage/Parking/Terrace/Piscine
                    elif "chambre" in text:
                        m = re.search(r'(\d+)', text)
                        if m:
                            details["bedrooms"] = int(m.group(1))
                    elif "salle(s) de bain" in text:
                        m = re.search(r'(\d+)', text)
                        if m:
                            details["bathroom_count"] = details.get("bathroom_count", 0) + int(m.group(1))
                    elif "salle(s) d'eau" in text:
                        m = re.search(r'(\d+)', text)
                        if m:
                            details["bathroom_count"] = details.get("bathroom_count", 0) + int(m.group(1))
                    elif "garage" in text:
                        m = re.search(r'(\d+)', text)
                        if m:
                            details["parking_count"] = details.get("parking_count", 0) + int(m.group(1))
                    elif "parking" in text:
                        m = re.search(r'(\d+)', text)
                        if m:
                            details["parking_count"] = details.get("parking_count", 0) + int(m.group(1))
                    elif "terrasse" in text:
                        details["terrace"] = True
                    elif "piscine" in text:
                        details["pool"] = True
                    elif "cuisine" in text:
                        details["kitchen_type"] = text.replace("cuisine", "").strip()
                    elif "chauffage" in text:
                        h_val = text.replace("chauffage central :", "").replace("chauffage :", "").strip()
                        m = re.search(r'\(([^)]+)\)', h_val)
                        if m:
                            details["heating_type"] = m.group(1)
                        else:
                            details["heating_type"] = h_val

        # Extract total rooms from title
        if details.get("title"):
            m = re.search(r'(\d+)\s*pièce', details["title"].lower())
            if m:
                details["rooms"] = int(m.group(1))
            
            # Fallback if area or bedrooms were not in the characteristics list
            if "area" not in details:
                m = re.search(r'(\d+[\d\s,]*)\s*m²', details["title"].lower())
                if m:
                    details["area"] = float(m.group(1).replace(',', '.').replace(' ', ''))
                    
            if "bedrooms" not in details:
                m = re.search(r'(\d+)\s*chambre', details["title"].lower())
                if m:
                    details["bedrooms"] = int(m.group(1))

        # Check description text for pool fallback
        desc_text = details.get("description_text", "").lower()
        if "piscine" in desc_text:
            details["pool"] = True

        # Extract Copropriété and Procedure
        for text_node in soup.find_all(string=True):
            txt = text_node.strip().lower()
            if "nombre de lots" in txt:
                p = text_node.parent
                for next_sib in p.find_all_next(string=True)[:5]:
                    sib_txt = next_sib.strip()
                    if sib_txt.isdigit():
                        details["copropriete_lots"] = int(sib_txt)
                        break
            elif "statut du syndic" in txt:
                p = text_node.parent
                for next_sib in p.find_all_next(string=True)[:5]:
                    sib_txt = next_sib.strip().lower()
                    if "pas de procédure" in sib_txt or "aucune procédure" in sib_txt:
                        details["procedure_syndic"] = False
                        break
                    elif "procédure en cours" in sib_txt:
                        details["procedure_syndic"] = True
                        break

        # Extract Price (if refreshed)
        price_elem = soup.find(class_="properties-detail__price") or soup.find(string=re.compile(r'Prix de vente honoraires TTC inclus'))
        if price_elem:
            if hasattr(price_elem, "get_text"):
                p_txt = price_elem.get_text()
            else:
                p_txt = ""
                p = price_elem.parent
                for sib in p.find_all_next(string=True)[:5]:
                    if "€" in sib:
                        p_txt = sib
                        break
            price_str = re.sub(r'[^\d]', '', p_txt)
            if price_str:
                details["price"] = float(price_str)

        # Extract location/city from city element
        city_elem = soup.find(class_="properties-detail__city")
        if city_elem:
            details["location"] = re.sub(r'\s+', ' ', city_elem.get_text()).strip()

        return details
