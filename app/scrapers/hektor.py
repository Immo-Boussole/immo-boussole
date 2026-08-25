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
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        if not html_content:
            return []

        soup = BeautifulSoup(html_content, 'html.parser')
        listings = []

        parsed_url = urllib.parse.urlparse(search_url)
        base_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

        card_links = soup.find_all("a", href=re.compile(r'/(?:vente|location|annonce|bien)/.*(?:\d+)'))
        seen_urls = set()

        for a in card_links:
            href = a.get("href", "")
            if not href or href in seen_urls or href == "#":
                continue

            full_url = href if href.startswith("http") else urllib.parse.urljoin(base_origin, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            m = re.search(r'/(\d+)[^/]*$', href) or re.search(r'id=(\d+)', href)
            ext_id = m.group(1) if m else None

            title = a.get_text(strip=True) or a.get("title", "")
            if not title:
                parent = a.find_parent(["article", "div", "li"])
                if parent:
                    title_elem = parent.find(["h2", "h3", "h4", ".title"])
                    if title_elem:
                        title = title_elem.get_text(strip=True)

            if not title:
                title = "Annonce Hektor"

            listings.append({
                "external_id": f"hektor_{ext_id}" if ext_id else None,
                "title": title,
                "url": full_url,
                "price": 0.0,
                "location": "France",
                "area": 0.0
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

        # ── 2. Fallback: HTML / OpenGraph Extraction ──────────────────────────
        return await self._parse_html_property(url)

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

    async def _parse_html_property(self, url: str) -> Dict:
        """
        Fallback parser for Hektor public web pages (e.g. /vente/123-titre).
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html = snapshot.get("html", "")
        if not html:
            return {}

        soup = BeautifulSoup(html, 'html.parser')
        details = {"url": url}

        # Clean tags
        for tag in soup(["script", "style"]):
            tag.decompose()

        # External ID
        m = re.search(r'/(\d+)[^/]*$', url) or re.search(r'id=(\d+)', url)
        if m:
            details["external_id"] = f"hektor_{m.group(1)}"

        # Title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            details["title"] = og_title["content"].strip()
        else:
            title_tag = soup.find("title")
            details["title"] = title_tag.text.strip() if title_tag else "Annonce Hektor"

        # Description
        og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
        if og_desc and og_desc.get("content"):
            details["description_text"] = og_desc["content"].strip()
        else:
            desc_elem = soup.find(class_=re.compile(r'description|detail-data-description', re.I))
            if desc_elem:
                details["description_text"] = desc_elem.get_text(strip=True)

        # Photos
        photo_urls = []
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src") or img.get("data-lazy")
            if src and any(kw in src for kw in ["biens", "photos", "photo_"]):
                full_src = src if src.startswith("http") else ("https:" + src if src.startswith("//") else src)
                full_src = re.sub(r'/(?:\d+x\w+|thumbnail)/', '/original/', full_src)
                if full_src not in photo_urls:
                    photo_urls.append(full_src)
        details["photo_urls"] = photo_urls

        # Price
        price_match = re.search(r'([\d\s\u00a0]+)\s*€', soup.get_text())
        if price_match:
            try:
                p_val = float(re.sub(r'[^\d]', '', price_match.group(1)))
                if p_val > 1000:
                    details["price"] = p_val
            except ValueError:
                pass

        # Surface
        surf_match = re.search(r'(\d+[\d\s,]*)\s*m²', soup.get_text(), re.I)
        if surf_match:
            try:
                details["area"] = float(surf_match.group(1).replace(',', '.').replace(' ', ''))
            except ValueError:
                pass

        return details
