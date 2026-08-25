import re
import urllib.parse
from typing import List, Dict, Optional
import httpx
from bs4 import BeautifulSoup
from app.scrapers.base import BaseScraper

HEKTOR_PUBLIC_QUERY = """
fragment PublicPropertyOfficialDistrict on OfficialDistrictInterface {
  name
  code
  municipality
  centroid {
    latitude
    longitude
  }
}

fragment PublicPropertyCharacteristics on Annonce {
  folderNumber
  mandateNumber
  bedroomCount
  hasCondominium
  condominiumAnnualCharges
  carrezSurface
  exposition
  hasBuildableLand
  hasServicedLand
  hasDivisibleLand
  hasWaterConnection
  hasGasConnection
  hasElectricityConnection
  hasTelephoneConnection
  hasPossibleSewerConnection
  canInstallPool
  hasPool
  hasTreedLand
  landSurface
  hasFencedLand
  floorLevel
  totalFloors
  levelCount
  garageCount
  garageSurface
  exteriorParkingCount
  interiorParkingCount
  bathroomCount
  showerCount
  toiletCount
  hasGarden
  gardenSurface
  hasBalcony
  balconySurface
  balconyCount
  hasCellar
  cellarSurface
  hasTerrace
  terraceSurface
  terraceCount
  propertyTax
  hasAirConditioning
  hasElectricShutters
  hasDoubleGlazing
  hasWheelchairAccess
  hasElevator
  kitchenType
  kitchenEquipment
  floorAreaRatio
  residualFloorAreaRatio
  sharedWalls
  residenceSecurity
  residenceType
  view
  transport
  proximity
  energeticGrade {
    score
    color
  }
}

query PublicPropertyPage($propertyId: ID!, $lang: String!, $senderUserId: ID!) {
  sender: user(id: $senderUserId) {
    id
    userObject {
      ... on Owner {
        id
        displayName
        softwareLogo
        urlAvatar
        email
        phoneNumber
        hoguetLegalMention
      }
      ... on Agence {
        locality {
          id
          address
          city {
            id
            humanName
          }
          zipCode {
            id
            code
          }
        }
      }
    }
  }
  property(id: $propertyId) {
    id
    url
    ...PublicPropertyCharacteristics
    description(lang: $lang, strip: false)
    price
    status
    surface
    roomCount
    isMasked
    isArchived
    isDraft
    isBroadcasted
    isRental
    chargesIncluded
    alurLegalMention(lang: $lang)
    hasClearing
    baseRent
    increasedReferenceRent
    rentSupplement
    rentSupplementIncluded
    isSubjectToRentControl
    condominiumUnitsCount
    condominiumSyndicateStatus
    photos(isVisible: true) {
      id
      url(watermark: true, size: ORIGINAL)
      legende
    }
    offer {
      id
      label
      type
    }
    type {
      id
      name
      familyId
      isCustom
    }
    ville {
      id
      nom
    }
    officialDistricts {
      ...PublicPropertyOfficialDistrict
      ... on Iris {
        id
        type
      }
      ... on LargeDistrict {
        irises {
          ...PublicPropertyOfficialDistrict
          id
          type
        }
      }
    }
    gasesEmissionImage
    energeticConsumptionImage
    energyDiagnosticDate
    estimatedEnergyCostsReport(lang: $lang)
    agency {
      site
    }
    fees {
      seller
      buyer
    }
    pdfUrl(type: PUBLIC, lang: $lang)
    virtualVisits(isVisible: true) {
      id
      url
    }
    videos(isVisible: true) {
      id
      url
    }
  }
}
"""


class HektorScraper(BaseScraper):
    """
    Scraper for real estate agencies running on the Hektor / Ma-Boîte-Immo platform
    (e.g., immoreve.fr, generic Hektor CRM public sharing links).
    """

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract search results from a Hektor-powered agency search page.
        """
        html_content = ""
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(
                    search_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    }
                )
                if resp.status_code == 200 and len(resp.text) > 1000:
                    html_content = resp.text
        except Exception:
            pass

        if not html_content:
            snapshot = await self.extract_page_content(search_url)
            if snapshot:
                html_content = snapshot.get("html", "")

        if not html_content:
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        listings = []

        parsed_url = urllib.parse.urlparse(search_url)
        base_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

        card_links = soup.find_all("a", href=re.compile(r'/(?:vente|location|annonce|bien|propriete|villa|maison|appartement|terrain|immeuble)/.*(?:\d+)'))
        seen_urls = set()

        for a in card_links:
            href = a.get("href", "")
            if not href or href in seen_urls or href == "#" or href.endswith('/1') or href.endswith('/1/'):
                continue

            full_url = href if href.startswith("http") else urllib.parse.urljoin(base_origin, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Match ID from pattern /882-villa... or id=882
            m = re.search(r'/(\d+)(?:-[^/?#]+)?(?:[?#]|$)', href) or re.search(r'id=(\d+)', href)
            ext_id = m.group(1) if m else None

            # Look for card container (article.item or parent div)
            card = a.find_parent(["article", "div", "li"])
            card_text = card.get_text(" ", strip=True) if card else ""

            # Title
            title = ""
            if card:
                title_elem = card.find(["h2", "h3", "h4", ".title", ".item__title"])
                if title_elem:
                    title = title_elem.get_text(strip=True)
            if not title:
                title = a.get_text(strip=True) or a.get("title", "")
            if not title or title.lower() in ["voir le bien", "en savoir plus", "détails"]:
                # Construct title from URL slug
                slug = href.rstrip('/').split('/')[-1]
                clean_slug = re.sub(r'^\d+-', '', slug).replace('-', ' ').capitalize()
                title = clean_slug if clean_slug else "Annonce Hektor"

            # Price
            price = 0.0
            if card:
                price_elem = card.find(class_=re.compile(r'price|prix', re.I))
                price_text = price_elem.get_text(strip=True) if price_elem else card_text
                p_m = re.search(r'([\d\s\u00a0]+)\s*€', price_text)
                if p_m:
                    try:
                        p_val = float(re.sub(r'[^\d]', '', p_m.group(1)))
                        if p_val > 1000:
                            price = p_val
                    except ValueError:
                        pass

            # Location / City
            location = "France"
            if card:
                city_elem = card.find(class_=re.compile(r'city|ville|postal|location', re.I))
                if city_elem:
                    location = city_elem.get_text(" ", strip=True)
                else:
                    c_m = re.search(r'([A-Za-zÀ-ÿ\s\'-]+)\s*\(\s*(\d{5})\s*\)', card_text)
                    if c_m:
                        location = f"{c_m.group(1).strip()} ({c_m.group(2)})"

            # Surface / Area
            area = 0.0
            if card:
                surf_m = re.search(r'(\d+[\d\s,]*)\s*m²', card_text, re.I)
                if surf_m:
                    try:
                        area = float(surf_m.group(1).replace(',', '.').replace(' ', ''))
                    except ValueError:
                        pass

            listings.append({
                "external_id": f"hektor_{ext_id}" if ext_id else None,
                "title": title,
                "url": full_url,
                "price": price,
                "location": location,
                "area": area
            })

        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape listing details from a Hektor URL.
        Supports both direct GraphQL API extraction (for CRM share links with token)
        and HTML / DOM extraction (for standard website property pages).
        """
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        token = params.get("token", [None])[0]
        prop_id = params.get("id", [None])[0] or params.get("propertyId", [None])[0]
        sender_user_id = params.get("senderUserId", ["0"])[0]

        # ── 1. Direct GraphQL API Extraction ──────────────────────────────────
        if token and prop_id:
            try:
                base_origin = f"{parsed.scheme}://{parsed.netloc}"
                graphql_endpoint = f"{base_origin}/ws/GraphQL_Web"

                payload = {
                    "query": HEKTOR_PUBLIC_QUERY,
                    "variables": {
                        "propertyId": str(prop_id),
                        "lang": "fr",
                        "senderUserId": str(sender_user_id)
                    }
                }

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        graphql_endpoint,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "X-Public-Token": token,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        }
                    )

                if resp.status_code == 200:
                    res_data = resp.json()
                    data = res_data.get("data", {})
                    prop = data.get("property")
                    sender = data.get("sender")

                    if prop:
                        return self._parse_graphql_property(prop, sender, url)
            except Exception as e:
                print(f"[HektorScraper] GraphQL query failed for {url}: {e}")

        # ── 2. HTML Extraction: Direct HTTP Fast Path ─────────────────────────
        html = ""
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    }
                )
                if resp.status_code == 200 and len(resp.text) > 1000:
                    html = resp.text
        except Exception as e:
            print(f"[HektorScraper] Direct HTTP fetch failed for {url}: {e}")

        # ── 3. Fallback: Browserless / Playwright Rendering ───────────────────
        if not html:
            snapshot = await self.extract_page_content(url)
            if snapshot:
                html = snapshot.get("html", "")

        if not html:
            return {}

        return self._parse_html_property(html, url)

    def _parse_graphql_property(self, prop: Dict, sender: Optional[Dict], url: str) -> Dict:
        """
        Maps a Hektor GraphQL Property payload to an enriched Immo-Boussole details dictionary.
        """
        details = {"url": url}

        prop_id = prop.get("id")
        if prop_id:
            details["external_id"] = f"hektor_{prop_id}"

        # Pricing
        raw_price = prop.get("price")
        if raw_price is not None:
            try:
                details["price"] = float(raw_price)
            except (ValueError, TypeError):
                pass

        # Surfaces & Rooms
        if prop.get("surface") is not None:
            try:
                details["area"] = float(prop["surface"])
            except (ValueError, TypeError):
                pass

        if prop.get("carrezSurface") is not None:
            try:
                details["carrez_surface"] = float(prop["carrezSurface"])
            except (ValueError, TypeError):
                pass

        if prop.get("landSurface") is not None:
            try:
                details["land_area"] = float(prop["landSurface"])
            except (ValueError, TypeError):
                pass

        if prop.get("roomCount") is not None:
            try:
                details["rooms"] = int(prop["roomCount"])
            except (ValueError, TypeError):
                pass

        if prop.get("bedroomCount") is not None:
            try:
                details["bedrooms"] = int(prop["bedroomCount"])
            except (ValueError, TypeError):
                pass

        bathrooms = (prop.get("bathroomCount") or 0) + (prop.get("showerCount") or 0)
        if bathrooms > 0:
            details["bathroom_count"] = bathrooms

        if prop.get("toiletCount") is not None:
            details["toilets"] = int(prop["toiletCount"])

        if prop.get("floorLevel") is not None:
            details["floor"] = int(prop["floorLevel"])

        if prop.get("totalFloors") is not None:
            details["total_floors"] = int(prop["totalFloors"])

        # Amenities
        details["elevator"] = bool(prop.get("hasElevator"))
        details["balcony"] = bool(prop.get("hasBalcony"))
        details["terrace"] = bool(prop.get("hasTerrace"))
        details["garden"] = bool(prop.get("hasGarden"))
        details["pool"] = bool(prop.get("hasPool"))
        details["cellar"] = bool(prop.get("hasCellar"))

        parking = (prop.get("garageCount") or 0) + (prop.get("exteriorParkingCount") or 0) + (prop.get("interiorParkingCount") or 0)
        if parking > 0:
            details["parking_count"] = parking

        # Financials
        if prop.get("condominiumAnnualCharges") is not None:
            try:
                details["charges"] = float(prop["condominiumAnnualCharges"])
            except (ValueError, TypeError):
                pass

        if prop.get("propertyTax") is not None:
            try:
                details["land_tax"] = float(prop["propertyTax"])
            except (ValueError, TypeError):
                pass

        # Energy & DPE
        energetic_grade = prop.get("energeticGrade")
        if energetic_grade and isinstance(energetic_grade, dict) and energetic_grade.get("score"):
            score = str(energetic_grade["score"]).strip().upper()
            if score in ["A", "B", "C", "D", "E", "F", "G"]:
                details["dpe_rating"] = score

        # Photos (Full resolution original images)
        photos = prop.get("photos") or []
        photo_urls = []
        for p in photos:
            if isinstance(p, dict) and p.get("url"):
                photo_urls.append(p["url"])
        details["photo_urls"] = photo_urls

        # Description
        desc = prop.get("description") or ""
        details["description_text"] = desc.strip()

        # Location / City / Postal code / Coordinates
        ville_raw = prop.get("ville", {})
        ville_nom = ville_raw.get("nom", "") if isinstance(ville_raw, dict) else ""

        city = ""
        postal_code = ""

        if ville_nom:
            # Matches format "City Name 38370" or "38370 City Name"
            m_cp = re.search(r'\b(\d{5})\b', ville_nom)
            if m_cp:
                postal_code = m_cp.group(1)
                city = ville_nom.replace(postal_code, '').strip(' -_()')
            else:
                city = ville_nom.strip()

        # Coordinates from officialDistricts centroid if available
        districts = prop.get("officialDistricts") or []
        if districts and isinstance(districts, list) and len(districts) > 0:
            first_d = districts[0]
            if isinstance(first_d, dict):
                centroid = first_d.get("centroid") or {}
                if centroid.get("latitude") and centroid.get("longitude"):
                    try:
                        details["latitude"] = float(centroid["latitude"])
                        details["longitude"] = float(centroid["longitude"])
                    except (ValueError, TypeError):
                        pass
                if not city and first_d.get("name"):
                    city = first_d["name"]

        if city:
            details["city"] = city
        if postal_code:
            details["postal_code"] = postal_code
        details["location"] = f"{city} ({postal_code})" if city and postal_code else (city or postal_code or "France")

        # Title construction
        type_info = prop.get("type", {})
        type_name = type_info.get("name") if isinstance(type_info, dict) else "Bien"
        surface_str = f" {int(details['area'])} m²" if details.get("area") else ""
        city_str = f" à {city}" if city else ""
        details["title"] = f"{type_name}{surface_str}{city_str}".strip()

        # Contact / Agent details
        if sender and isinstance(sender, dict):
            u_obj = sender.get("userObject") or sender.get("parentObject") or {}
            if isinstance(u_obj, dict):
                if u_obj.get("displayName"):
                    details["contact_name"] = u_obj["displayName"]
                if u_obj.get("phoneNumber"):
                    details["contact_phone"] = u_obj["phoneNumber"]
                if u_obj.get("email"):
                    details["contact_email"] = u_obj["email"]

        agency = prop.get("agency")
        if agency and isinstance(agency, dict) and agency.get("site"):
            details["agency_name"] = agency["site"]

        return details

    def _parse_html_property(self, html: str, url: str) -> Dict:
        """
        Parser for Hektor and Immorêve public web pages (e.g. /vente/160-chavanay/maison/882-villa...).
        """
        soup = BeautifulSoup(html, 'html.parser')
        details = {"url": url}

        # Keep a raw copy for regex searches before removing script/style
        raw_html = html

        for tag in soup(["script", "style"]):
            tag.decompose()

        # 1. External ID
        # Matches /882-villa... or id=882 or idann=882
        m = re.search(r'/(\d+)(?:-[^/?#]+)?(?:[?#]|$)', url)
        if not m:
            m = re.search(r'id(?:ann)?=(\d+)', url)
        if not m:
            m = re.search(r'idann=(\d+)', raw_html)

        if m:
            details["external_id"] = f"hektor_{m.group(1)}"

        # 2. Title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            details["title"] = og_title["content"].strip()
        else:
            title_el = soup.find(class_=re.compile(r'properties-detail__title|title-detail', re.I)) or soup.find("h1")
            if title_el:
                details["title"] = title_el.get_text(" ", strip=True)
            else:
                title_tag = soup.find("title")
                raw_title = title_tag.text.strip() if title_tag else "Annonce Hektor"
                details["title"] = re.sub(r'\s*\|\s*Immor[^\s]+.*$', '', raw_title, flags=re.I).strip()

        # 3. Price
        price_el = soup.find(class_=re.compile(r'properties-detail__price|price_finance|finance_content--prix_honoraires_inclus', re.I))
        if price_el:
            p_text = price_el.get_text(strip=True)
            p_m = re.search(r'([\d\s\u00a0]+)\s*€', p_text)
            if p_m:
                try:
                    p_val = float(re.sub(r'[^\d]', '', p_m.group(1)))
                    if p_val > 1000:
                        details["price"] = p_val
                except ValueError:
                    pass

        if "price" not in details:
            price_match = re.search(r'([\d\s\u00a0]+)\s*€', soup.get_text())
            if price_match:
                try:
                    p_val = float(re.sub(r'[^\d]', '', price_match.group(1)))
                    if p_val > 1000:
                        details["price"] = p_val
                except ValueError:
                    pass

        # 4. Location / City / Postal code
        city_el = soup.find(class_=re.compile(r'properties-detail__city|item__block--city|detail-city', re.I))
        if city_el:
            city_raw = city_el.get_text(" ", strip=True)
            # Format: "Chavanay (42410)" or "42410 Chavanay"
            m_cp = re.search(r'([^\d()]+?)\s*\(\s*(\d{5})\s*\)', city_raw)
            if m_cp:
                details["city"] = m_cp.group(1).strip()
                details["postal_code"] = m_cp.group(2).strip()
            else:
                m_cp2 = re.search(r'\b(\d{5})\b', city_raw)
                if m_cp2:
                    details["postal_code"] = m_cp2.group(1)
                    details["city"] = city_raw.replace(details["postal_code"], '').strip(' -_()')
                else:
                    details["city"] = city_raw.strip()

        if not details.get("city"):
            # Fallback to breadcrumbs
            breadcrumbs = soup.find_all(class_=re.compile(r'breadcrumb__item|breadcrumb', re.I))
            for bc in breadcrumbs:
                bc_text = bc.get_text(" ", strip=True)
                parts = [p.strip() for p in bc_text.split() if p.strip() and p.strip().lower() not in ['accueil', 'vente', 'location', 'nos', 'biens', 'maison', 'appartement', 'terrain', 'immeuble']]
                if parts:
                    details["city"] = parts[0]
                    break

        city = details.get("city", "")
        postal_code = details.get("postal_code", "")
        if city and postal_code:
            details["location"] = f"{city} ({postal_code})"
        elif city or postal_code:
            details["location"] = city or postal_code

        # 5. Description
        og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_desc and og_desc.get("content"):
            details["description_text"] = og_desc["content"].strip()
        else:
            desc_elem = soup.find(class_=re.compile(r'detail_description|properties-detail__description|description|detail-data-description', re.I))
            if desc_elem:
                details["description_text"] = desc_elem.get_text("\n", strip=True)

        # 6. Characteristics & Amenities
        carac_items = soup.find_all(class_=re.compile(r'list_item|detail_caracteristiques|caracteristiques', re.I))
        all_carac_text = " ".join([ci.get_text(" ", strip=True) for ci in carac_items])
        body_text = soup.get_text(" ", strip=True)

        # Surface habitable
        surf_m = re.search(r'Surface\s*(\d+[\d\s,]*)\s*m²', all_carac_text, re.I) or re.search(r'(\d+[\d\s,]*)\s*m²\s*habitable', body_text, re.I) or re.search(r'(\d+[\d\s,]*)\s*m²', all_carac_text, re.I)
        if surf_m:
            try:
                details["area"] = float(surf_m.group(1).replace(',', '.').replace(' ', ''))
            except ValueError:
                pass

        # Carrez surface
        carrez_m = re.search(r'carrez\s*(\d+[\d\s,]*)\s*m²', all_carac_text, re.I)
        if carrez_m:
            try:
                details["carrez_surface"] = float(carrez_m.group(1).replace(',', '.').replace(' ', ''))
            except ValueError:
                pass

        # Land area / Terrain
        land_m = re.search(r'terrain\s*(\d+[\d\s,]*)\s*m²', all_carac_text, re.I)
        if land_m:
            try:
                details["land_area"] = float(land_m.group(1).replace(',', '.').replace(' ', ''))
            except ValueError:
                pass

        # Rooms / Pièces
        rooms_m = re.search(r'(\d+)\s*pi[èe]ce(?:\(s\)|s)?', body_text, re.I)
        if rooms_m:
            try:
                details["rooms"] = int(rooms_m.group(1))
            except ValueError:
                pass

        # Bedrooms / Chambres
        beds_m = re.search(r'(\d+)\s*chambre(?:\(s\)|s)?', all_carac_text, re.I) or re.search(r'(\d+)\s*chambre(?:\(s\)|s)?', body_text, re.I)
        if beds_m:
            try:
                details["bedrooms"] = int(beds_m.group(1))
            except ValueError:
                pass

        # Bathrooms / Salles de bain / Salles d'eau
        baths_m = re.search(r'(\d+)\s*salle(?:\(s\)|s)?\s*(?:de\s*bain|d[\'’]eau)', all_carac_text, re.I) or re.search(r'(\d+)\s*salle(?:\(s\)|s)?\s*(?:de\s*bain|d[\'’]eau)', body_text, re.I)
        if baths_m:
            try:
                details["bathroom_count"] = int(baths_m.group(1))
            except ValueError:
                pass

        # Toilets
        wc_m = re.search(r'(\d+)\s*toilette(?:\(s\)|s)?|(\d+)\s*wc', all_carac_text, re.I) or re.search(r'(\d+)\s*toilette(?:\(s\)|s)?|(\d+)\s*wc', body_text, re.I)
        if wc_m:
            try:
                details["toilets"] = int(wc_m.group(1) or wc_m.group(2))
            except ValueError:
                pass

        # Garage / Parking
        gar_m = re.search(r'(\d+)\s*(?:garage(?:\(s\)|s)?|parking(?:\(s\)|s)?|stationnement(?:\(s\)|s)?)', all_carac_text, re.I) or re.search(r'(\d+)\s*(?:garage(?:\(s\)|s)?|parking(?:\(s\)|s)?|stationnement(?:\(s\)|s)?)', body_text, re.I)
        if gar_m:
            try:
                details["parking_count"] = int(gar_m.group(1))
            except ValueError:
                pass

        # Floors / Niveaux
        niv_m = re.search(r'(\d+)\s*niveau(?:\(x\)|x)?', all_carac_text, re.I) or re.search(r'(\d+)\s*niveau(?:\(x\)|x)?', body_text, re.I)
        if niv_m:
            try:
                details["total_floors"] = int(niv_m.group(1))
            except ValueError:
                pass


        # Amenities flags
        details["terrace"] = bool(re.search(r'\bterrasse\b', all_carac_text, re.I))
        details["balcony"] = bool(re.search(r'\bbalcon\b', all_carac_text, re.I))
        details["garden"] = bool(re.search(r'\bjardin\b|\barboré\b', all_carac_text, re.I))
        details["pool"] = bool(re.search(r'\bpiscine\b|\bpiscinable\b', all_carac_text, re.I))
        details["cellar"] = bool(re.search(r'\bcave\b|\bsous-sol\b', all_carac_text, re.I) or re.search(r'sous-sol', details.get("title", ""), re.I))
        details["elevator"] = bool(re.search(r'\bascenseur\b', all_carac_text, re.I))

        # Property type
        if re.search(r'\bmaison\b|\bvilla\b', details.get("title", "") + " " + all_carac_text, re.I):
            details["property_type"] = "Maison"
        elif re.search(r'\bappartement\b', details.get("title", "") + " " + all_carac_text, re.I):
            details["property_type"] = "Appartement"
        elif re.search(r'\bterrain\b', details.get("title", "") + " " + all_carac_text, re.I):
            details["property_type"] = "Terrain"
        elif re.search(r'\bimmeuble\b', details.get("title", "") + " " + all_carac_text, re.I):
            details["property_type"] = "Immeuble"

        # Energy costs
        energy_m = re.search(r'compris entre\s*([\d\s]+)\s*€\s*et\s*([\d\s]+)\s*€', body_text, re.I)
        if energy_m:
            try:
                details["estimated_annual_energy_cost_min"] = float(energy_m.group(1).replace(' ', ''))
                details["estimated_annual_energy_cost_max"] = float(energy_m.group(2).replace(' ', ''))
            except ValueError:
                pass

        # Agency & Contact
        agency_title = soup.find(class_=re.compile(r'card-contact__title', re.I))
        if agency_title:
            details["agency_name"] = agency_title.get_text(strip=True)
        else:
            agency_el = soup.find(class_=re.compile(r'detail-contact__property-contact', re.I))
            if agency_el:
                details["agency_name"] = agency_el.get_text(strip=True).split('\n')[0]

        phone_m = re.search(r'(\b0[1-9](?:[\s.-]?\d{2}){4}\b)', body_text)
        if phone_m:
            details["contact_phone"] = phone_m.group(1).replace('.', ' ').replace('-', ' ')

        email_m = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', raw_html)
        if email_m:
            details["contact_email"] = email_m.group(1)

        # 7. Photos
        photo_urls = []
        main_media = soup.find(class_=re.compile(r'properties-detail-v2__media|property-detail-v2__slide|slider__main|property-slider__list|modal-swiper-gallery', re.I)) or soup
        for img in main_media.find_all("img"):
            if img.find_parent(class_=re.compile(r'item__block|card-similar|suggestions|footer', re.I)):
                continue
            src = img.get("data-splide-lazy") or img.get("data-src") or img.get("src") or img.get("data-lazy")
            if src and any(kw in src for kw in ["biens", "photo_"]) and "dpe.php" not in src:
                full_src = src if src.startswith("http") else ("https:" + src if src.startswith("//") else urllib.parse.urljoin(url, src))
                # Convert thumbnails / dimensions to high-resolution original
                full_src = re.sub(r'/(?:\d+x\w+|thumbnail)/', '/original/', full_src)
                if full_src not in photo_urls:
                    photo_urls.append(full_src)

        details["photo_urls"] = photo_urls

        return details

