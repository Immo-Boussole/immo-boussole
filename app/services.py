"""
Business logic services: scraping, duplicate detection, listing creation.
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Listing, ListingStatus, SearchQuery, Source, Review
from app.scrapers import (
    LeboncoinScraper, SelogerScraper, LeFigaroScraper,
    LogicimmoScraper, BieniciScraper, IadfranceScraper,
    NotairesScraper, VinciScraper, ImmobilierFranceScraper,
    OrpiScraper, ProvimoScraper
)
from app.media import download_listing_photos, photos_to_json, json_to_photos, calculate_images_similarity, compute_image_dhash, compute_image_ahash
from app.geo import fetch_sncf_times_for_city, get_coordinates, get_insee_code, fetch_georisques_data
from app.notifications import send_new_listing_notifications
import httpx
from bs4 import BeautifulSoup




from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
import re
from typing import Tuple


def normalize_listing_url(url: str) -> str:
    """
    Normalizes a listing URL by stripping tracking parameters, normalizing scheme/host,
    and trimming trailing slashes to allow consistent deduplication.
    """
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            if not url.startswith("http://") and not url.startswith("https://"):
                parsed = urlparse("https://" + url)

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Remove standard ports if present
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]

        # Path: strip trailing slash unless it's just "/"
        path = parsed.path
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")

        # For major real estate portals, listing detail pages do not need query params or fragments
        portal_domains = {
            "seloger.com", "leboncoin.fr", "lefigaro.fr", "immobilier.lefigaro.fr",
            "bienici.com", "pap.fr", "logic-immo.com", "ouestfrance-immo.com",
            "bellesdemeures.com", "superimmo.com", "avendrealouer.fr"
        }
        is_portal = any(netloc == pd or netloc.endswith("." + pd) for pd in portal_domains)

        if is_portal:
            query_str = ""
        else:
            # Filter tracking query params for other sources
            tracking_params = {
                "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
                "fbclid", "gclid", "gbraid", "wbraid", "msclkid", "twclid", "dclid",
                "ref", "referrer", "source", "origin", "xtor", "xtref", "cmp", "at_medium",
                "at_campaign", "at_custom1", "at_custom2", "at_custom3", "at_custom4",
                "_gl", "_ga", "mc_cid", "mc_eid"
            }
            query_dict = parse_qs(parsed.query, keep_blank_values=False)
            filtered_query = {k: v for k, v in query_dict.items() if k.lower() not in tracking_params}
            query_str = urlencode(filtered_query, doseq=True)

        normalized_scheme = "https" if scheme in ("http", "https") else scheme

        return urlunparse((normalized_scheme, netloc, path, parsed.params, query_str, ""))
    except Exception:
        return url.strip().rstrip("/")


def is_valid_listing_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validates if a URL is a single listing page URL, and NOT a search results or landing page.
    Returns (is_valid, error_message).
    """
    url_lower = url.lower()
    
    # 1. Broad checks for common search keywords
    search_keywords = ["/recherche", "/resultats", "/search", "projects=", "category=", "/carte"]
    for kw in search_keywords:
        if kw in url_lower:
            return False, f"L'URL semble correspondre à une page de recherche ou de résultats ({kw})."
            
    # 2. Domain-specific structure checks
    if "orpi.com" in url_lower:
        if "/annonce-" not in url_lower:
            return False, "Les URLs Orpi d'annonces valides doivent contenir '/annonce-'."
            
    elif "leboncoin.fr" in url_lower:
        is_lbc_ad = "/ad/" in url_lower or any(cat in url_lower for cat in ["/ventes_immobilieres/", "/locations/", "/colocations/", "/bureaux_commerces/"])
        if not is_lbc_ad:
            return False, "Les URLs LeBonCoin d'annonces valides doivent contenir '/ad/' ou une catégorie d'annonce."

    elif "seloger.com" in url_lower:
        if "/annonces/" not in url_lower and "/annonce/" not in url_lower:
            return False, "Les URLs SeLoger d'annonces valides doivent contenir '/annonce/' ou '/annonces/'."

    elif "lefigaro.fr" in url_lower:
        if "/annonces/" not in url_lower or "/annonce-" not in url_lower:
            return False, "Les URLs Le Figaro d'annonces valides doivent contenir '/annonces/' et '/annonce-'."

    elif "logic-immo.com" in url_lower:
        if "/detail-" not in url_lower:
            return False, "Les URLs Logic-Immo d'annonces valides doivent contenir '/detail-'."

    elif "bienici.com" in url_lower:
        if "/annonce/" not in url_lower:
            return False, "Les URLs Bien'Ici d'annonces valides doivent contenir '/annonce/'."

    elif "iadfrance.fr" in url_lower:
        if "/annonce/" not in url_lower:
            return False, "Les URLs IAD France d'annonces valides doivent contenir '/annonce/'."

    elif "immobilier.notaires.fr" in url_lower:
        if "/annonce/" not in url_lower:
            return False, "Les URLs Notaires d'annonces valides doivent contenir '/annonce/'."

    elif "vinci-immobilier.com" in url_lower:
        if "/achat-immobilier-neuf/" not in url_lower:
            return False, "Les URLs Vinci d'annonces valides doivent contenir '/achat-immobilier-neuf/'."

    elif "immobilier-france.fr" in url_lower:
        if "/annonce/" not in url_lower and "/detail/" not in url_lower:
            return False, "Les URLs Immobilier France d'annonces valides doivent contenir '/annonce/' ou '/detail/'."

    return True, None


def is_search_page_title(title: str) -> bool:
    """
    Checks if a page title indicates it is a search results/landing page instead of a single listing.
    """
    if not title:
        return False
    t = title.lower()
    
    # Common search page title patterns
    indicators = [
        "🏡 : maisons en vente",
        "🏡 : maison en vente",
        "🏡 : appartements en vente",
        "🏡 : appartement en vente",
        "résultats de recherche",
        "annonces immobilières",
        "moteur de recherche",
        "toutes les annonces",
        "liste des annonces",
        "dernières annonces",
        "alertes immo",
        "recherche immobilière",
    ]
    for ind in indicators:
        if ind in t:
            return True
            
    # Plural nouns followed by "à vendre" or "à louer"
    if re.search(r'\b(maisons|appartements|terrains|locaux)\s+à\s+(vendre|louer)\b', t):
        return True
        
    return False


def is_error_or_generic_title(title: Optional[str]) -> bool:
    """
    Returns True if title is an error string, placeholder, or generic title
    (e.g., 'Annonce (https://...) - Erreur 403', 'Annonce (http...)', 'Annonce Le Figaro', 'leboncoin.fr', etc.).
    """
    if not title:
        return True
    t = title.strip()
    t_lower = t.lower()
    
    if t_lower in ("", "none", "null", "leboncoin.fr", "annonce le figaro", "sans titre", "annonce", "bien immobilier"):
        return True
    if re.search(r'\berreur\s*\d{3}\b', t_lower):
        return True
    if re.search(r'\berror\s*\d{3}\b', t_lower):
        return True
    if re.search(r'^annonce\s*\([^\)]*https?://', t_lower):
        return True
    if t.startswith("Annonce (http") or t.startswith("Annonce (https"):
        return True
    if is_search_page_title(t):
        return True
    return False


def clean_extracted_title(title: Optional[str]) -> Optional[str]:
    """
    Cleans an extracted title by unescaping HTML entities, removing portal suffixes
    (e.g., ' - Leboncoin', ' | SeLoger', ' - Le Figaro Immobilier', etc.), and trimming whitespace.
    """
    if not title:
        return None
    import html
    t = html.unescape(str(title)).strip()
    # Remove surrounding quotes
    t = re.sub(r'^["\'«»“”]+|["\'«»“”]+$', '', t).strip()
    # Strip site brand suffixes
    suffixes = [
        r'\s*[-|–—:]\s*leboncoin(?:\.fr)?\s*$',
        r'\s*[-|–—:]\s*seloger(?:\.com)?\s*$',
        r'\s*[-|–—:]\s*le figaro immobilier\s*$',
        r'\s*[-|–—:]\s*figaro immobilier\s*$',
        r'\s*[-|–—:]\s*pap(?:\.fr)?\s*$',
        r'\s*[-|–—:]\s*bien[\']?ici\s*$',
        r'\s*[-|–—:]\s*logic[- ]immo\s*$',
        r'\s*[-|–—:]\s*orpi(?:\.com)?\s*$',
        r'\s*[-|–—:]\s*iad france\s*$',
    ]
    for s in suffixes:
        t = re.sub(s, '', t, flags=re.I).strip()
    # Normalize multiple whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t if t else None


def extract_title_from_url_slug(url: str) -> Optional[str]:
    """
    Attempts to extract a human-readable title from the URL path slug.
    E.g.: 'https://www.leboncoin.fr/ad/ventes_immobilieres/maison-5-pieces-saint-etienne-2881234567'
    -> 'Maison 5 pièces saint etienne'
    """
    if not url:
        return None
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None

    # Filter out generic directories like 'ad', 'ventes_immobilieres', 'locations', 'annonces', 'achat', etc.
    ignore_segments = {
        "ad", "ads", "ventes_immobilieres", "locations", "colocations", "bureaux_commerces",
        "annonces", "annonce", "achat", "vente", "immobilier", "detail", "item", "prop", "fr"
    }

    meaningful_slug = None
    for segment in reversed(parts):
        seg_lower = segment.lower()
        if seg_lower in ignore_segments or seg_lower.endswith(".htm") or seg_lower.endswith(".html"):
            segment_clean = re.sub(r'\.html?$', '', segment, flags=re.I)
            if segment_clean.lower() in ignore_segments:
                continue
            seg_lower = segment_clean.lower()
        else:
            segment_clean = segment

        # Check if segment is solely numeric (e.g., ad ID "2881234567")
        if re.match(r'^\d+$', segment_clean) or re.match(r'^[a-f0-9-]{32,}$', segment_clean):
            continue

        meaningful_slug = segment_clean
        break

    if not meaningful_slug:
        return None

    # Decode percent-encoding
    decoded = urllib.parse.unquote(meaningful_slug)
    # Remove trailing digits/ID attached with hyphen or underscore (e.g. "superbe-maison-123456789")
    decoded = re.sub(r'[-_]\d{3,}$', '', decoded)
    # Replace hyphens and underscores with spaces
    words = re.sub(r'[-_]+', ' ', decoded).strip()
    if not words or len(words) < 5 or words.isdigit():
        return None

    clean_words = words[0].upper() + words[1:]
    if is_error_or_generic_title(clean_words):
        return None
    return clean_words


def generate_synthetic_title_from_listing(listing: Listing) -> Optional[str]:
    """
    Generates a structured, standard real-estate title from listing attributes:
    property_type, rooms, area, and city.
    E.g.: 'Maison 5 pièces 120 m² - Saint-Étienne'
    """
    if not listing:
        return None
    
    # 1. Property Type
    ptype = None
    if listing.property_type and listing.property_type.strip():
        ptype = listing.property_type.strip().capitalize()
    else:
        desc_low = (listing.description_text or "").lower()
        if "maison" in desc_low or "villa" in desc_low:
            ptype = "Maison"
        elif "appartement" in desc_low or "studio" in desc_low or "duplex" in desc_low:
            ptype = "Appartement"
        elif "terrain" in desc_low:
            ptype = "Terrain"
        elif "immeuble" in desc_low:
            ptype = "Immeuble"
        else:
            ptype = "Bien immobilier"

    # 2. Rooms
    rooms_part = f"{listing.rooms} pièces" if listing.rooms and listing.rooms > 0 else ""

    # 3. Area
    area_part = ""
    if listing.area and listing.area > 0:
        area_fmt = int(listing.area) if listing.area == int(listing.area) else round(listing.area, 1)
        area_part = f"{area_fmt} m²"

    # 4. Location
    city_part = (listing.city or listing.location or "").strip()
    city_part = re.sub(r'\s*\(\d{5}\)$', '', city_part).strip()

    title_elements = [ptype]
    if rooms_part:
        title_elements.append(rooms_part)
    if area_part:
        title_elements.append(area_part)
    
    core_title = " ".join(title_elements)
    if city_part:
        return f"{core_title} - {city_part.title()}"
    return core_title


def extract_title_from_description(description: Optional[str]) -> Optional[str]:
    """
    Attempts to extract a title from the first sentence or heading of the listing description.
    """
    if not description:
        return None
    lines = [l.strip() for l in description.splitlines() if l.strip()]
    for line in lines[:4]:
        cleaned = re.sub(r'^[^\w\d]+', '', line)
        cleaned = re.sub(r'^(?:à\s*vendre|a\s*vendre|exclusivité|exclusivite|coup\s*de\s*coeur|opportunité)\s*[:\-–—]\s*', '', cleaned, flags=re.I).strip()
        if 10 <= len(cleaned) <= 120 and not re.search(r'https?://|\d{2}[-.\s]\d{2}[-.\s]\d{2}|\b0[1-9]\d{8}\b', cleaned):
            if re.search(r'\b(maison|appartement|villa|studio|duplex|loft|immeuble|terrain|pièces?|chambres?|m²)\b', cleaned, flags=re.I):
                c = clean_extracted_title(cleaned)
                if c and not is_error_or_generic_title(c):
                    return c
    return None


def has_valid_local_photos(listing: Listing) -> bool:
    """
    Checks if a listing has valid, non-empty local photos on disk.
    """
    if not listing:
        return False
    photos = json_to_photos(listing.photos_local)
    if not photos or not isinstance(photos, list):
        return False
    for p in photos:
        if not p or not isinstance(p, str):
            continue
        clean_p = p.lstrip("/\\")
        candidates = [p, clean_p, os.path.join("static", clean_p)]
        for candidate in candidates:
            if os.path.exists(candidate) and os.path.isfile(candidate):
                try:
                    if os.path.getsize(candidate) > 0:
                        return True
                except Exception:
                    pass
    return False


def is_missing_or_corrupt_photos(listing: Listing) -> bool:
    """
    Returns True if a listing has missing or corrupted photos that require repair.
    Returns False if valid local photo files exist on disk.
    """
    if not listing:
        return False

    return not has_valid_local_photos(listing)


async def repair_listing_photos(listing: Listing, db: Session) -> bool:
    """
    Attempts to repair/recover photos for a listing:
    1. Check original_photo_urls from database and try to download them.
    2. If missing or failed, trigger page extraction (scraper or fetch_basic_metadata) to get fresh photo URLs and download them.
    Returns True if valid photos are available.
    """
    if has_valid_local_photos(listing):
        return True

    # 1. Try from original_photo_urls if present
    photo_urls = []
    if listing.original_photo_urls:
        try:
            parsed = json.loads(listing.original_photo_urls)
            if isinstance(parsed, list):
                photo_urls = [u for u in parsed if isinstance(u, str) and u.startswith("http")]
            elif isinstance(parsed, str) and parsed.startswith("http"):
                photo_urls = [parsed]
        except Exception:
            photo_urls = []
            
    if photo_urls:
        try:
            downloaded = await download_listing_photos(listing.id, photo_urls)
            if downloaded:
                listing.photos_local = photos_to_json(downloaded)
                db.commit()
                if has_valid_local_photos(listing):
                    print(f"[Services] Successfully repaired photos for listing {listing.id} from original_photo_urls ({len(downloaded)} photos)")
                    return True
        except Exception as e:
            print(f"[Services] Repair from original_photo_urls failed for listing {listing.id}: {e}")

    # 2. Try re-extracting from URL
    from app.main import _resolve_scraper
    source, scraper = _resolve_scraper(listing.url)
    details = {}
    if scraper:
        try:
            details = await scraper.get_listing_details(listing.url)
        except Exception as e:
            print(f"[Services] Scraper failed during photo repair for listing {listing.id}: {e}")
            
    if not details or not details.get("photo_urls"):
        try:
            details = await fetch_basic_metadata(listing.url)
        except Exception as e:
            print(f"[Services] Fallback metadata failed during photo repair for listing {listing.id}: {e}")

    fresh_urls = details.get("photo_urls", []) if details else []
    if fresh_urls:
        listing.original_photo_urls = json.dumps(fresh_urls)
        try:
            downloaded = await download_listing_photos(listing.id, fresh_urls)
            if downloaded:
                listing.photos_local = photos_to_json(downloaded)
                db.commit()
                if has_valid_local_photos(listing):
                    print(f"[Services] Successfully repaired photos for listing {listing.id} from fresh scrape ({len(downloaded)} photos)")
                    return True
        except Exception as e:
            print(f"[Services] Photo download failed during fresh repair for listing {listing.id}: {e}")

    db.commit()
    return has_valid_local_photos(listing)


async def repair_listing_title(listing: Listing, db: Session, force: bool = False) -> Tuple[bool, str]:
    """
    Attempts to repair/recover a valid title for a listing if it currently has an error or generic title
    (e.g., 'Annonce (https://www.leboncoin.fr/ad/ventes_immob…) - Erreur 403', 'leboncoin.fr', etc.).

    Recovery pipeline:
    1. Re-scrape via platform scraper or multi-UA fetch_basic_metadata.
    2. Extract meaningful title from URL slug.
    3. Extract title from description_text.
    4. Synthesize standard structured title from attributes (property_type, rooms, area, city).

    Returns:
        (was_repaired: bool, final_title: str)
    """
    if not listing:
        return False, ""
        
    if not force and not is_error_or_generic_title(listing.title):
        return False, listing.title or ""

    print(f"[Services] Attempting title repair for listing #{listing.id} (Current: {listing.title!r})")

    new_title = None

    # ── 1. Try re-extracting from URL via scraper or fetch_basic_metadata ──
    from app.main import _resolve_scraper
    source, scraper = _resolve_scraper(listing.url)
    details = {}
    if scraper:
        try:
            details = await scraper.get_listing_details(listing.url)
        except Exception as e:
            print(f"[Services] Scraper failed during title repair for listing {listing.id}: {e}")

    if not details or is_error_or_generic_title(details.get("title")):
        try:
            fb = await fetch_basic_metadata(listing.url)
            if fb and not is_error_or_generic_title(fb.get("title")):
                details = fb
        except Exception as e:
            print(f"[Services] Metadata fetch failed during title repair for listing {listing.id}: {e}")

    if details and details.get("title") and not is_error_or_generic_title(details.get("title")):
        new_title = clean_extracted_title(details.get("title"))
        # Also populate missing fields if any were extracted
        if details.get("description_text") and not listing.description_text:
            listing.description_text = details.get("description_text")
        if details.get("price") and (not listing.price or listing.price <= 0):
            listing.price = float(details["price"])
        if details.get("city") and not listing.city:
            listing.city = details["city"]
        if details.get("area") and not listing.area:
            listing.area = float(details["area"])
        if details.get("rooms") and not listing.rooms:
            listing.rooms = int(details["rooms"])
        if details.get("photo_urls") and not listing.photos_local:
            listing.original_photo_urls = json.dumps(details["photo_urls"])

    # ── 2. Try URL Slug Extraction ──
    if not new_title or is_error_or_generic_title(new_title):
        slug_title = extract_title_from_url_slug(listing.url)
        if slug_title and not is_error_or_generic_title(slug_title):
            new_title = slug_title
            print(f"[Services] Recovered title from URL slug for listing {listing.id}: {new_title!r}")

    # ── 3. Try Description Extraction ──
    if not new_title or is_error_or_generic_title(new_title):
        desc_title = extract_title_from_description(listing.description_text)
        if desc_title and not is_error_or_generic_title(desc_title):
            new_title = desc_title
            print(f"[Services] Recovered title from description for listing {listing.id}: {new_title!r}")

    # ── 4. Synthesize Structured Title from Listing Attributes ──
    if not new_title or is_error_or_generic_title(new_title):
        syn_title = generate_synthetic_title_from_listing(listing)
        if syn_title and not is_error_or_generic_title(syn_title):
            new_title = syn_title
            print(f"[Services] Synthesized title from attributes for listing {listing.id}: {new_title!r}")

    if new_title and not is_error_or_generic_title(new_title):
        listing.title = new_title
        db.commit()
        db.refresh(listing)
        print(f"[Services] Title successfully repaired for listing #{listing.id} -> {new_title!r}")
        return True, new_title

    return False, listing.title or ""


# ─── Basic Metadata Extraction ────────────────────────────────────────────────

async def fetch_basic_metadata(url: str) -> dict:
    """
    Attempts to retrieve listing metadata (title, description, image, price, location) 
    using resilient HTTP requests with User-Agent rotation (WhatsApp bot, Facebook bot, Googlebot, etc.)
    and extracting from __NEXT_DATA__, JSON-LD, and OpenGraph tags.
    """
    details = {}
    
    USER_AGENTS = [
        "WhatsApp/2.21.19.21 A",
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Twitterbot/1.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/124.0.0.0",
    ]
    
    # If not LeBonCoin, put standard browser UA first
    if "leboncoin.fr" not in url:
        USER_AGENTS.insert(0, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/124.0.0.0")
    
    last_status = 0
    html_content = ""
    for ua in USER_AGENTS:
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.fr/",
        }
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=12) as client:
                resp = await client.get(url, headers=headers)
                last_status = resp.status_code
                if resp.status_code == 200 and len(resp.text) > 200:
                    html_content = resp.text
                    break
        except Exception as e:
            print(f"[Services] Attempt with UA {ua[:20]} failed for {url}: {e}")
            continue

    if html_content:
        # ── 1. LeBonCoin __NEXT_DATA__ bypass ──
        if "leboncoin.fr" in url:
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                html_content, re.DOTALL
            )
            if match:
                try:
                    data = json.loads(match.group(1))
                    ad = data.get("props", {}).get("pageProps", {}).get("ad", {})
                    if ad:
                        subject = ad.get("subject", "")
                        cleaned_sub = clean_extracted_title(subject)
                        details["title"] = cleaned_sub or subject
                        details["description_text"] = ad.get("body", "")
                        price_list = ad.get("price", [0])
                        details["price"] = float(price_list[0]) if price_list else 0.0
                        
                        location = ad.get("location", {})
                        city = location.get("city", "")
                        zipcode = location.get("zipcode", "")
                        details["location"] = f"{city} {zipcode}".strip()
                        details["city"] = city
                        
                        images = ad.get("images", {})
                        urls = images.get("urls_large") or images.get("urls")
                        if isinstance(urls, list):
                            details["photo_urls"] = [u for u in urls if isinstance(u, str)]
                        elif isinstance(urls, str):
                            details["photo_urls"] = [urls]
                            
                        # Attributes
                        for attr in ad.get("attributes", []):
                            key = attr.get("key")
                            val = attr.get("value")
                            if key == "square":
                                try: details["area"] = float(str(val).replace(",", "."))
                                except (ValueError, TypeError): pass
                            elif key == "rooms":
                                try: details["rooms"] = int(val)
                                except (ValueError, TypeError): pass
                            elif key == "real_estate_type":
                                details["property_type"] = str(val).capitalize()
                            elif key == "energy_rate":
                                details["dpe_rating"] = str(val).upper()[:1] if val else None
                            elif key == "ges":
                                details["ges_rating"] = str(val).upper()[:1] if val else None
                            elif key in ("annual_charges", "charges"):
                                try: details["charges"] = float(str(val).replace(",", "."))
                                except (ValueError, TypeError): pass
                        
                        print(f"[Services] LBC Fast Scrape OK: {details['title']} ({len(details.get('photo_urls', []))} photos)")
                        return details
                except Exception as e:
                    print(f"[Services] LBC __NEXT_DATA__ fast extraction failed: {e}")

        # ── 2. JSON-LD schema extraction ──
        soup = BeautifulSoup(html_content, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                if script.string:
                    ld_data = json.loads(script.string)
                    if isinstance(ld_data, dict):
                        ld_name = ld_data.get("name") or ld_data.get("headline")
                        if ld_name and not is_error_or_generic_title(ld_name):
                            c_ld = clean_extracted_title(ld_name)
                            if c_ld:
                                details["title"] = c_ld
                        if ld_data.get("description") and not details.get("description_text"):
                            details["description_text"] = ld_data.get("description")
                        if ld_data.get("image") and not details.get("photo_urls"):
                            imgs = ld_data.get("image")
                            if isinstance(imgs, list):
                                details["photo_urls"] = [i for i in imgs if isinstance(i, str)]
                            elif isinstance(imgs, str):
                                details["photo_urls"] = [imgs]
            except Exception:
                pass

        # ── 3. OpenGraph / Meta tags extraction ──
        og_title = soup.find("meta", attrs={"property": "og:title"})
        tw_title = soup.find("meta", attrs={"name": "twitter:title"})
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        page_title = soup.find("title")
        h1 = soup.find("h1")

        raw_title = (
            details.get("title") or
            (og_title.get("content") if og_title and og_title.get("content") else None) or
            (tw_title.get("content") if tw_title and tw_title.get("content") else None) or
            (h1.get_text().strip() if h1 and len(h1.get_text().strip()) > 3 else None) or
            (page_title.text.strip() if page_title and page_title.text.strip() else None)
        )
        
        fb_title = clean_extracted_title(raw_title)
        if not fb_title or is_error_or_generic_title(fb_title):
            # Try slug from url
            slug_t = extract_title_from_url_slug(url)
            fb_title = slug_t if slug_t else f"Annonce ({url[:40]}…)"
            
        details["title"] = fb_title
        if og_desc and not details.get("description_text"):
            details["description_text"] = og_desc.get("content", "")
        
        # Multiple photos from OpenGraph and Twitter tags
        photo_urls = details.get("photo_urls", [])
        for og_img in soup.find_all("meta", attrs={"property": "og:image"}):
            content = og_img.get("content")
            if content: photo_urls.append(content)
        
        for tw_img in soup.find_all("meta", attrs={"name": "twitter:image"}):
            content = tw_img.get("content")
            if content: photo_urls.append(content)

        # Fallback to certain <img> tags if no meta images found
        if not photo_urls:
            img_tags = soup.find_all("img", src=re.compile(r'ad-image|listing|property|photo|gallery', re.I))
            for img in img_tags:
                src = img.get("src") or img.get("data-src")
                if src and src.startswith("http"):
                    photo_urls.append(src)
        
        if photo_urls:
            details["photo_urls"] = list(dict.fromkeys(photo_urls))
        
        print(f"[Services] Basic metadata OK: {fb_title!r} ({len(details.get('photo_urls', []))} photos)")
    else:
        # If all HTTP attempts failed, try slug before setting error title
        slug_title = extract_title_from_url_slug(url)
        if slug_title:
            details["title"] = slug_title
        elif last_status > 0:
            details["title"] = f"Annonce ({url[:40]}…) - Erreur {last_status}"
        else:
            details["title"] = f"Annonce ({url[:40]}…)"
    
    if is_search_page_title(details.get("title", "")):
        print(f"[Services] fetch_basic_metadata detected search page title: {details['title']}")
        return {"is_invalid_search_page": True, "title": details["title"]}
        
    return details


# ─── Listing Creation from Scraped Data ───────────────────────────────────────

def ensure_city_map_pin(city_name: str, db: Session):
    """
    Checks if a MapPin of type 'city' exists for the given city name (case-insensitive, cleaned).
    If not, geocodes the city name and creates the MapPin.
    """
    if not city_name:
        return
    
    import re
    cleaned = city_name.strip()
    cleaned = re.sub(r'\s*\(\d+\)\s*', '', cleaned)
    cleaned = re.sub(r'\b\d{5}\b', '', cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return
    
    from sqlalchemy import func
    from app.models import MapPin
    existing_pin = db.query(MapPin).filter(
        MapPin.pin_type == "city",
        func.lower(MapPin.title) == cleaned.lower()
    ).first()
    
    if not existing_pin:
        coords = get_coordinates(cleaned)
        if coords:
            lat, lon = coords
            new_pin = MapPin(
                title=cleaned.title(),
                address=cleaned.title(),
                lat=lat,
                lon=lon,
                pin_type="city",
                created_by="System"
            )
            db.add(new_pin)
            db.commit()
            print(f"[Services] Automatically created MapPin for city: {cleaned.title()} at {lat}, {lon}")


async def create_listing_from_details(
    db: Session,
    details: dict,
    source: Source,
    original_url: str,
    download_photos: bool = True,
    status: Optional[ListingStatus] = None,
) -> Tuple[Listing, bool]:
    """
    Creates or updates a listing from scraped details.
    Also checks for duplicates and downloads photos asynchronously.

    Returns:
        (listing, is_new): the created/found listing and whether it's newly created
    """
    external_id = details.get("external_id", f"manual_{hash(original_url)}")
    local_paths = [] # Initialize here to ensure it's always defined

    # Check if already exists by external_id or URL
    existing = db.query(Listing).filter(
        (Listing.external_id == external_id) | (Listing.url == original_url)
    ).first()

    listing = existing if existing else Listing(
        external_id=external_id,
        url=original_url,
        original_url=original_url,
        date_added=datetime.now(timezone.utc)
    )

    # ── Update / Set Fields ──────────────────────────────────────────────
    for key, value in details.items():
        if hasattr(listing, key) and value is not None:
            # Skip fields handled specially or problematic
            if key in ("id", "external_id", "url", "source", "status", "scraped_at", "photo_urls"):
                continue

            # Title protection: do not overwrite valid existing title with an error or generic placeholder
            if key == "title":
                if existing and existing.title and not is_error_or_generic_title(existing.title):
                    if is_error_or_generic_title(value):
                        print(f"[Services] Preserved existing valid title {existing.title!r} instead of error title {value!r}")
                        continue

            # Description protection: do not overwrite valid existing description with empty string
            if key == "description_text":
                if existing and existing.description_text and not value:
                    continue

            # Price protection: do not overwrite valid price with 0 or None when error occurs
            if key == "price":
                if existing and existing.price and existing.price > 0 and (value is None or value <= 0):
                    continue

            # Location & City protection: do not overwrite user-specified / verified address and city
            if key in ("city", "location", "address", "postal_code", "address_precision", "latitude", "longitude"):
                if existing and existing.manual_address_override:
                    continue

            if key in ("city", "location"):
                from app.geo import standardize_and_enrich_city
                std_city, _, _ = standardize_and_enrich_city(value)
                if std_city:
                    value = std_city
            setattr(listing, key, value)

    # Ensure both listing.city and listing.location are standardized and synchronized (only if not manually overridden)
    if not (existing and existing.manual_address_override) and (listing.city or listing.location):
        from app.geo import standardize_and_enrich_city
        src_val = listing.city or listing.location
        std_city, _, _ = standardize_and_enrich_city(src_val)
        if std_city:
            listing.city = std_city
            listing.location = std_city
    
    if "photo_urls" in details:
        urls = details.get("photo_urls") or []
        listing.original_photo_urls = json.dumps(urls)
        if not urls and listing.photos_local is None:
            listing.photos_local = json.dumps([])

    # Store source and update timestamp
    listing.source = source
    listing.scraped_at = datetime.now(timezone.utc)
    
    # Calculate price per sqm
    listing.update_price_per_sqm()
    
    # Set status only for new listings or if explicitly provided
    if status:
        listing.status = status
    elif not existing:
        listing.status = ListingStatus.NEW

    if not existing:
        db.add(listing)
    
    db.commit()
    db.refresh(listing)

    # ── Download photos asynchronously in background ──
    photo_urls = details.get("photo_urls", [])
    if photo_urls and download_photos:
        # Avoid re-downloading if already present
        try:
            downloaded = await download_listing_photos(listing.id, photo_urls)
            if downloaded:
                local_paths = downloaded
                listing.photos_local = photos_to_json(local_paths)
                db.commit()
        except Exception as e:
            print(f"[Services] Error downloading photos for listing {listing.id}: {e}")

    # Fallback photo recovery if listing still has missing/corrupted photos
    if download_photos and is_missing_or_corrupt_photos(listing):
        try:
            await repair_listing_photos(listing, db)
        except Exception as e:
            print(f"[Services] Fallback repair_listing_photos failed for listing {listing.id}: {e}")

    # ── Geocoding ──
    if (listing.location or listing.city) and listing.latitude is None:
        loc = listing.location or listing.city
        coords = get_coordinates(loc)
        if coords:
            listing.latitude, listing.longitude = coords
            db.commit()

    # ── Pre-calculate SNCF Distances ──
    if listing.city and listing.nearest_sncf_station is None:
        from app.models import ZoneRule
        forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
            ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
        ).all()}
        sncf_data = fetch_sncf_times_for_city(listing.city, forbidden_stations)
        if sncf_data:
            listing.nearest_sncf_station = sncf_data.get('nearest_sncf_station')
            listing.walk_time_sncf = sncf_data.get('walk_time_sncf')
            listing.bike_time_sncf = sncf_data.get('bike_time_sncf')
            listing.car_time_sncf = sncf_data.get('car_time_sncf')
            
            listing.second_sncf_station = sncf_data.get('second_sncf_station')
            listing.walk_time_sncf_2 = sncf_data.get('walk_time_sncf_2')
            listing.bike_time_sncf_2 = sncf_data.get('bike_time_sncf_2')
            listing.car_time_sncf_2 = sncf_data.get('car_time_sncf_2')
        else:
            listing.nearest_sncf_station = "NOT_FOUND"
        db.commit()

    # ── Géorisques Risk Report ──
    if listing.georisques_json is None:
        await update_listing_georisques(listing, db)

    # ── Ensure City MapPin exists ──
    if listing.city:
        ensure_city_map_pin(listing.city, db)

    return listing, (not existing)


async def update_listing_georisques(listing: Listing, db: Session):
    """
    Fetches and updates Géorisques data for a listing.
    """
    import re
    
    location = listing.location or ""
    city = listing.city or ""
    
    # Extract zipcode if present
    zip_match = re.search(r'\d{5}', location)
    zipcode = zip_match.group(0) if zip_match else None
    
    # Heuristic for full address: contains a number at start or is notably longer than city+zip
    location_norm = location.strip().lower()
    city_norm = city.strip().lower()
    
    is_address = False
    if location_norm:
        # Check for street number at start
        if re.match(r'^\d+', location_norm):
            is_address = True
        elif city_norm and len(location_norm) > (len(city_norm) + 7):
            is_address = True
            
    report_json = None
    if is_address:
        print(f"[Services] Fetching Géorisques for address: {location}")
        report_json = fetch_georisques_data(address=location)
    elif city:
        insee = get_insee_code(city, zipcode)
        if insee:
            print(f"[Services] Fetching Géorisques for INSEE: {insee} ({city})")
            report_json = fetch_georisques_data(insee_code=insee)
            
    if report_json:
        listing.georisques_json = json.dumps(report_json)
        db.commit()
        print(f"[Services] Géorisques report saved for listing {listing.id}")


# ─── Scrape and Diff (Search Queries) ─────────────────────────────────────────

async def scrape_and_diff(query: SearchQuery, db: Session, ready_search=None):
    """
    Runs the full scrape cycle for a search query:
    1. Scrapes listing results
    2. Marks disappeared listings
    3. Creates new listings with duplicate detection
    
    Args:
        query: The SearchQuery to run (URL + source/platform)
        db: DB session
        ready_search: Optional ReadySearch that triggered this job (used to store
                      platform/criteria origin on new listings for the auto_searches view)
    """
    scrapers = {
        Source.LEBONCOIN: LeboncoinScraper(),
        Source.SELOGER: SelogerScraper(),
        Source.LEFIGARO: LeFigaroScraper(),
        Source.LOGICIMMO: LogicimmoScraper(),
        Source.BIENICI: BieniciScraper(),
        Source.IADFRANCE: IadfranceScraper(),
        Source.NOTAIRES: NotairesScraper(),
        Source.VINCI: VinciScraper(),
        Source.IMMOBILIER_FRANCE: ImmobilierFranceScraper(),
        Source.ORPI: OrpiScraper(),
        Source.PROVIMO: ProvimoScraper(),
    }

    scraper = scrapers.get(query.source)
    if not scraper:
        print(f"[Services] Scraper introuvable pour: {query.source}")
        return

    print(f"[Services] Scraping de {query.url}")
    scraped_listings = await scraper.get_listings(query.url)
    scraped_ids = [str(l["external_id"]) for l in scraped_listings]

    # Find currently active listings for this source
    existing_active = db.query(Listing).filter(
        Listing.source == query.source,
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW])
    ).all()

    existing_ids = [l.external_id for l in existing_active]

    # 1. DISAPPEARED logic (DISABLED here because it's too aggressive with overlapping searches)
    # Disappearance is now handled by refresh_all_listings_status which checks URLs individually.
    disappeared_count = 0
    # for listing in existing_active:
    #     if listing.external_id not in scraped_ids:
    #         listing.status = ListingStatus.DISAPPEARED
    #         disappeared_count += 1

    # 2. Process new listings
    from app.models import ZoneRule
    from app.geo import is_city_in_forbidden_set
    forbidden_cities = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
        ZoneRule.zone_type == "city", ZoneRule.rule == "forbidden"
    ).all()}

    new_count = 0
    new_listing_objects: list[Listing] = []  # collected for notifications
    for item in scraped_listings:
        item_url = item.get("url", "")
        is_valid, _ = is_valid_listing_url(item_url)
        if not is_valid:
            print(f"[Services] Skipping scraped listing with invalid URL: {item_url}")
            continue
            
        if is_search_page_title(item.get("title", "")):
            print(f"[Services] Skipping scraped listing with search page title: {item.get('title')}")
            continue

        ext_id = str(item["external_id"])
        
        city_val = item.get("city")
        loc_val = item.get("location") or city_val
        city_to_check = loc_val or city_val
        
        if city_to_check:
            from app.geo import standardize_and_enrich_city
            std_city, _, _ = standardize_and_enrich_city(city_to_check)
            if std_city:
                city_val = std_city
                loc_val = std_city
                item["city"] = std_city
                item["location"] = std_city
                city_to_check = std_city

            from app.main import _is_city_in_allowed_departments
            if not _is_city_in_allowed_departments(city_to_check, db):
                continue
        
        # Check if listing already exists by external_id OR URL (exact or normalized)
        norm_item_url = normalize_listing_url(item_url)
        existing = db.query(Listing).filter(
            (Listing.external_id == ext_id) | (Listing.url == item_url) | (Listing.original_url == item_url)
        ).first()

        if not existing and norm_item_url:
            for l in db.query(Listing).filter(Listing.url.isnot(None)).all():
                if normalize_listing_url(l.url) == norm_item_url or (l.original_url and normalize_listing_url(l.original_url) == norm_item_url):
                    existing = l
                    break

        if existing:
            # Case: Already exists (active, new, rejected, archived, or disappeared)
            if existing.status == ListingStatus.DISAPPEARED:
                city_to_check_existing = existing.city or existing.location
                if city_to_check_existing and is_city_in_forbidden_set(city_to_check_existing, forbidden_cities) and not existing.to_visit:
                    existing.status = ListingStatus.REJECTED
                else:
                    existing.status = ListingStatus.NEW
                existing.date_updated = datetime.now(timezone.utc)
            
            # Update fields
            existing.price = item.get("price")
            existing.scraped_at = datetime.now(timezone.utc)
            
            # If external_id was None (manual) or changed, update it
            if not existing.external_id or existing.external_id != ext_id:
                existing.external_id = ext_id
            
            # Refresh Géorisques even for existing listings (as requested)
            await update_listing_georisques(existing, db)
        else:
            # Check for photo_urls in item
            photo_urls = item.get("photo_urls", [])
            
            # Case: Brand new listing
            city_val = item.get("city")
            loc_val = item.get("location") or city_val
            
            # Check if listing is in a forbidden zone
            in_forbidden_city = False
            city_to_check_new = city_val or loc_val
            if city_to_check_new and is_city_in_forbidden_set(city_to_check_new, forbidden_cities):
                in_forbidden_city = True

            new_listing = Listing(
                external_id=ext_id,
                title=item.get("title", "Sans titre"),
                url=item_url,
                original_url=item_url,
                price=item.get("price"),
                location=loc_val,
                city=city_val,
                area=item.get("area"),
                rooms=item.get("rooms"),
                source=query.source,
                status=ListingStatus.REJECTED if in_forbidden_city else ListingStatus.NEW,
                scraped_at=datetime.now(timezone.utc),
                is_duplicate=False,
                duplicate_of_id=None,
                # Store the origin ReadySearch for the auto_searches view
                source_ready_search_id=ready_search.id if ready_search else None,
                source_criteria=ready_search.criteria if ready_search else None,
                original_photo_urls=json.dumps(photo_urls) if photo_urls else None,
            )

            # Calculate price per sqm
            new_listing.update_price_per_sqm()

            # Geocoding for new listing
            loc = new_listing.location or new_listing.city
            if loc:
                coords = get_coordinates(loc)
                if coords:
                    new_listing.latitude, new_listing.longitude = coords

            db.add(new_listing)
            try:
                db.commit() # Commit to get ID
                db.refresh(new_listing)
                
                # Download photos if available
                if photo_urls:
                    try:
                        downloaded = await download_listing_photos(new_listing.id, photo_urls)
                        if downloaded:
                            new_listing.photos_local = photos_to_json(downloaded)
                            db.commit()
                    except Exception as e:
                        print(f"[Services] Error downloading photos for NEW listing {new_listing.id}: {e}")

                await update_listing_georisques(new_listing, db)
                if new_listing.city:
                    ensure_city_map_pin(new_listing.city, db)
                if new_listing.status != ListingStatus.REJECTED:
                    new_listing_objects.append(new_listing)
                new_count += 1
            except Exception as e:
                db.rollback()
                print(f"[Services] Erreur lors de l'insertion de l'annonce {ext_id}: {e}")
                continue

    db.commit()

    # Update last_run timestamp
    query.last_run = datetime.now(timezone.utc)
    db.commit()

    print(
        f"[Services] Diff terminé: {len(scraped_ids)} annonces scrapées, "
        f"{new_count} nouvelles."
    )

    # ── Send push notifications for new listings ──
    if new_listing_objects:
        await send_new_listing_notifications(new_listing_objects, db)


async def refresh_listing_status(listing: Listing, db: Session, force_update: bool = False):
    """
    Checks if a listing is still online by visiting its URL.
    Updates status to DISAPPEARED if confirmed not found.
    Also ensures photos are valid; if not, repairs photos.
    If force_update is True, updates listing fields from scraper while preserving valid data.
    """
    from app.main import _resolve_scraper
    source, scraper = _resolve_scraper(listing.url)
    
    print(f"[Services] Refreshing status for listing {listing.id} ({listing.url})")
    
    is_online = True
    is_explicitly_gone = False
    details = {}
    try:
        if scraper:
            details = await scraper.get_listing_details(listing.url)
            if details and details.get("is_disappeared"):
                is_explicitly_gone = True
                is_online = False
            elif not details or not details.get("external_id"):
                # Check fallback before concluding
                fb = await fetch_basic_metadata(listing.url)
                if fb and not is_error_or_generic_title(fb.get("title")):
                    details = fb
                elif fb and ("404" in fb.get("title", "") or "410" in fb.get("title", "")):
                    is_explicitly_gone = True
                    is_online = False
        else:
            details = await fetch_basic_metadata(listing.url)
            if details and ("404" in details.get("title", "") or "410" in details.get("title", "")):
                is_explicitly_gone = True
                is_online = False
    except Exception as e:
        print(f"[Services] Error checking status for {listing.id}: {e}")
        # In case of network error, do not assume it's disappeared
        return

    photo_ok = has_valid_local_photos(listing)

    if is_explicitly_gone:
        if listing.status != ListingStatus.DISAPPEARED:
            print(f"[Services] Listing {listing.id} has DISAPPEARED")
            listing.status = ListingStatus.DISAPPEARED
            db.commit()
    else:
        was_disappeared = (listing.status == ListingStatus.DISAPPEARED)
        
        if was_disappeared or not photo_ok or force_update:
            reason = "BACK ONLINE" if was_disappeared else ("PHOTO BROKEN/MISSING" if not photo_ok else "MANUAL REPAIR")
            print(f"[Services] Listing {listing.id} is {reason}, performing update/repair...")
            
            # Update fields from details safely
            if details:
                for key, value in details.items():
                    if hasattr(listing, key) and value is not None:
                        if key in ("id", "external_id", "url", "source", "status", "scraped_at", "photo_urls"):
                            continue
                        if key == "title":
                            if listing.title and not is_error_or_generic_title(listing.title) and is_error_or_generic_title(value):
                                continue
                        if key == "description_text" and listing.description_text and not value:
                            continue
                        if key == "price" and listing.price and listing.price > 0 and (value is None or value <= 0):
                            continue
                        setattr(listing, key, value)
            
            # Re-download / repair photos if needed
            if not photo_ok or force_update:
                await repair_listing_photos(listing, db)
            
            # Repair title if it is generic or error
            if is_error_or_generic_title(listing.title):
                await repair_listing_title(listing, db)
            
            if was_disappeared:
                print(f"[Services] Listing {listing.id} is BACK ONLINE")
                listing.status = ListingStatus.ACTIVE
            
            db.commit()
    
    listing.update_price_per_sqm()
    listing.scraped_at = datetime.now(timezone.utc)
    db.commit()


async def refresh_all_listings_status(db: Session):
    """
    Iterates through all ACTIVE, NEW and DISAPPEARED listings 
    to refresh their online status.
    """
    listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW, ListingStatus.DISAPPEARED])
    ).all()
    
    print(f"[Services] Starting global status refresh for {len(listings)} listings...")
    for l in listings:
        await refresh_listing_status(l, db)
    print("[Services] Global status refresh completed.")


# ─── Review Management ────────────────────────────────────────────────────────

def get_or_create_review(
    db: Session,
    listing_id: int,
    reviewer: str,
    pros: Optional[str] = None,
    cons: Optional[str] = None,
    rating: Optional[float] = None,
    visit_done: bool = False,
    notes: Optional[str] = None,
) -> Tuple[Review, bool]:
    """
    Creates or updates a review for a listing by a specific reviewer.
    Only one review per (listing_id, reviewer) pair.
    """
    existing = db.query(Review).filter(
        Review.listing_id == listing_id,
        Review.reviewer == reviewer.lower()
    ).first()

    if existing:
        # Update existing review
        if pros is not None:
            existing.pros = pros
        if cons is not None:
            existing.cons = cons
        if rating is not None:
            existing.rating = rating
        if visit_done is not None:
            existing.visit_done = visit_done
        if notes is not None:
            existing.notes = notes
        db.commit()
        db.refresh(existing)
        return existing, False

    # Create new review
    review = Review(
        listing_id=listing_id,
        reviewer=reviewer.lower(),
        pros=pros,
        cons=cons,
        rating=rating,
        visit_done=visit_done,
        notes=notes,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review, True


# ─── Ideal Property Profile ───────────────────────────────────────────────────

def _parse_keywords(raw_list: list) -> list:
    """
    Parse a list of raw pros/cons strings into deduplicated, counted, sorted items.
    Each raw string may contain multiple items separated by newlines or ' - '.
    Returns: [{"text": str, "count": int}, ...] sorted by count desc, then alpha asc.
    """
    from collections import Counter
    counts: Counter = Counter()
    for raw in raw_list:
        if not raw:
            continue
        for block in raw.split('\n'):
            for item in block.split(' - '):
                clean = item.strip().strip('-').strip()
                if clean:
                    counts[clean] += 1
    return [
        {"text": text, "count": count}
        for text, count in sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
    ]


def generate_ideal_profile(db: Session) -> dict:
    """
    Aggregates all well-rated reviews (≥ 7/10) to generate
    an "Ideal Property Profile" highlighting common positives
    and points to avoid.
    """
    # Get all reviews with a rating
    good_reviews = db.query(Review).filter(
        Review.rating >= 7.0,
        Review.pros != None,
    ).all()

    bad_reviews = db.query(Review).filter(
        Review.cons != None,
    ).all()

    # Collect pros and cons as raw strings
    raw_pros = [r.pros for r in good_reviews if r.pros]
    raw_cons = [r.cons for r in bad_reviews if r.cons]

    # Deduplicate, count occurrences, and sort (most frequent first, then alpha)
    all_pros = _parse_keywords(raw_pros)
    all_cons = _parse_keywords(raw_cons)

    # Get statistics from top-rated listings AND favorite listings
    top_listing_ids = list(set(r.listing_id for r in good_reviews))
    favorite_listings = db.query(Listing).filter(Listing.is_favorite == True).all()
    for fl in favorite_listings:
        if fl.id not in top_listing_ids:
            top_listing_ids.append(fl.id)

    top_listings = db.query(Listing).filter(Listing.id.in_(top_listing_ids)).all()

    # Compute averages
    prices = [l.price for l in top_listings if l.price]
    areas = [l.area for l in top_listings if l.area]
    ppsqm = [l.price_per_sqm for l in top_listings if l.price_per_sqm]
    rooms = [l.rooms for l in top_listings if l.rooms]

    avg_price = round(sum(prices) / len(prices), 0) if prices else None
    avg_area = round(sum(areas) / len(areas), 1) if areas else None
    avg_ppsqm = round(sum(ppsqm) / len(ppsqm), 0) if ppsqm else None
    avg_rooms = round(sum(rooms) / len(rooms), 1) if rooms else None

    # DPE distribution
    dpe_ratings = [l.dpe_rating for l in top_listings if l.dpe_rating]
    dpe_dist = {}
    for d in dpe_ratings:
        dpe_dist[d] = dpe_dist.get(d, 0) + 1

    return {
        "based_on": len(good_reviews),
        "avg_price": avg_price,
        "avg_area": avg_area,
        "avg_price_per_sqm": avg_ppsqm,
        "avg_rooms": avg_rooms,
        "dpe_distribution": dpe_dist,
        "common_pros": all_pros,
        "common_cons": all_cons,
        "top_listings": [
            {
                "id": l.id,
                "title": l.title,
                "price": l.price,
                "area": l.area,
                "rooms": l.rooms,
                "location": l.location,
                "dpe_rating": l.dpe_rating,
                "is_favorite": l.is_favorite,
                "source": l.source.value if l.source else None,
                "source_criteria": l.source_criteria,
                "status": l.status.value if l.status else None,
                "url": l.url,
            }
            for l in top_listings
        ],
    }

# ─── Duplicate Hunting ────────────────────────────────────────────────────────

def calculate_listing_similarity(l1: Listing, l2: Listing, hash_cache: dict = None) -> Tuple[float, list]:
    """
    Calculates a similarity score (0 to 100) and common points between two listings.
    """
    import difflib
    score = 0
    common = []
    
    # 1. City (Mandatory for high score)
    c1 = (l1.city or l1.location or "").strip().lower()
    c2 = (l2.city or l2.location or "").strip().lower()
    if c1 and c2 and c1 == c2:
        score += 30
        common.append("city")

    # 2. Price (±5%)
    if l1.price and l2.price:
        diff = abs(l1.price - l2.price)
        max_p = max(l1.price, l2.price)
        if max_p > 0 and (diff / max_p) <= 0.05:
            score += 20
            common.append("price")
        elif max_p > 0 and (diff / max_p) <= 0.10:
            score += 10 # Half points for 10% range

    # 3. Area (±5%)
    if l1.area and l2.area:
        diff = abs(l1.area - l2.area)
        max_a = max(l1.area, l2.area)
        if max_a > 0 and (diff / max_a) <= 0.05:
            score += 20
            common.append("area")
        elif max_a > 0 and (diff / max_a) <= 0.10:
            score += 10

    # 4. Land Area (±5%) - Only if both have it
    if l1.land_area and l2.land_area:
        diff = abs(l1.land_area - l2.land_area)
        max_la = max(l1.land_area, l2.land_area)
        if max_la > 0 and (diff / max_la) <= 0.05:
            score += 10
            common.append("land_area")
            
    # 5. Description Similarity
    if l1.description_text and l2.description_text:
        # Use difflib for a quick ratio
        ratio = difflib.SequenceMatcher(None, l1.description_text[:1000], l2.description_text[:1000]).ratio()
        if ratio > 0.8:
            score += 20
            common.append("description")
        elif ratio > 0.6:
            score += 10

    # 6. First Photo (Visual/Metadata hint via perceptual hashing)
    p1 = json_to_photos(l1.photos_local)
    p2 = json_to_photos(l2.photos_local)
    if p1 and p2:
        path1 = os.path.join(os.getcwd(), p1[0])
        path2 = os.path.join(os.getcwd(), p2[0])
        if os.path.exists(path1) and os.path.exists(path2):
            if hash_cache is not None:
                if path1 not in hash_cache:
                    hash_cache[path1] = (compute_image_dhash(path1), compute_image_ahash(path1))
                if path2 not in hash_cache:
                    hash_cache[path2] = (compute_image_dhash(path2), compute_image_ahash(path2))
                d1, a1 = hash_cache[path1]
                d2, a2 = hash_cache[path2]
                
                if d1 and d2 and a1 and a2:
                    # Hamming distance for 64-bit hashes using fast integer XOR and bit_count
                    # ~16x faster than iterating character-by-character over hex strings
                    def hamming_distance(h1, h2):
                        return (int(h1, 16) ^ int(h2, 16)).bit_count()
                    
                    dist_d = hamming_distance(d1, d2)
                    dist_a = hamming_distance(a1, a2)
                    
                    sim_d = (64 - dist_d) / 64 * 100
                    sim_a = (64 - dist_a) / 64 * 100
                    img_sim = (sim_d + sim_a) / 2.0
                else:
                    img_sim = 0.0
            else:
                img_sim = calculate_images_similarity(path1, path2)

            if img_sim >= 90.0:
                score += 30
                common.append("photo")
            elif img_sim >= 75.0:
                score += 20
                common.append("photo")
            elif img_sim >= 60.0:
                score += 10

    return min(score, 100), common


def find_potential_duplicates(db: Session, limit_listings: int = 200) -> list:
    """
    Finds pairs of listings that might be duplicates.
    Excludes pairs already rejected or already marked as duplicates.
    """
    from app.models import RejectedDuplicate
    
    # Get active/new listings, sorted by date (most recent first)
    listings = db.query(Listing).filter(
        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.NEW]),
        Listing.is_duplicate == False
    ).order_by(Listing.date_added.desc()).limit(limit_listings).all()
    
    # Get rejected pairs
    rejected = db.query(RejectedDuplicate).all()
    rejected_pairs = set()
    for r in rejected:
        rejected_pairs.add(tuple(sorted((r.listing_a_id, r.listing_b_id))))
        
    potential_pairs = []
    hash_cache = {}
    
    for i in range(len(listings)):
        for j in range(i + 1, len(listings)):
            l1 = listings[i]
            l2 = listings[j]
            
            # Skip if same source (usually same platform doesn't have same listing twice with different IDs, 
            # but sometimes they do. However, the goal is often cross-platform duplicates).
            # Actually, the user might want to see them even on same source.
            
            # Skip if already in rejected
            if tuple(sorted((l1.id, l2.id))) in rejected_pairs:
                continue
                
            score, common = calculate_listing_similarity(l1, l2, hash_cache=hash_cache)
            
            if score >= 50: # Threshold for "potential" (ignores duplicates strictly below 50% for performance)
                potential_pairs.append({
                    "l1": l1,
                    "l2": l2,
                    "score": score,
                    "common": common
                })
                
    # Sort by score descending
    potential_pairs.sort(key=lambda x: x["score"], reverse=True)
    return potential_pairs


def enrich_auto_search_duplicates(new_listings: list, db: Session) -> list:
    """
    For each listing in new_listings, finds the best potential duplicate match
    (similarity score >= 50%) among existing ACTIVE listings in DB.
    Excludes pairs already rejected in rejected_duplicates.
    Attaches `_duplicate` dict to each listing if a match >= 50% is found.
    """
    if not new_listings:
        return new_listings

    from app.models import RejectedDuplicate, ListingStatus
    
    # Candidate pool: active listings in the DB
    active_listings = db.query(Listing).filter(
        Listing.status == ListingStatus.ACTIVE,
        Listing.is_duplicate == False
    ).order_by(Listing.date_added.desc()).limit(300).all()

    # Rejected pairs
    rejected = db.query(RejectedDuplicate).all()
    rejected_pairs = {tuple(sorted((r.listing_a_id, r.listing_b_id))) for r in rejected}

    hash_cache = {}

    for new_l in new_listings:
        best_match = None
        best_score = 0
        best_common = []

        for cand in active_listings:
            if cand.id == new_l.id:
                continue
            if tuple(sorted((new_l.id, cand.id))) in rejected_pairs:
                continue

            score, common = calculate_listing_similarity(new_l, cand, hash_cache=hash_cache)
            if score >= 50 and score > best_score:
                best_score = score
                best_match = cand
                best_common = common

        if best_match and best_score >= 50:
            cand_photos = json_to_photos(best_match.photos_local) if best_match.photos_local else []
            cand_photo = cand_photos[0] if cand_photos else None
            new_l._duplicate = {
                "score": best_score,
                "common": best_common,
                "target_id": best_match.id,
                "target_title": best_match.title or "Annonce sans titre",
                "target_price": best_match.price,
                "target_price_per_sqm": best_match.price_per_sqm,
                "target_area": best_match.area,
                "target_rooms": best_match.rooms,
                "target_location": best_match.location or best_match.city,
                "target_photo": cand_photo,
                "target_url": best_match.url,
                "target_source": best_match.source.value.upper() if best_match.source else "MANUEL"
            }
        else:
            new_l._duplicate = None

    return new_listings


def extract_contact_info_from_text(text: str) -> dict:
    """
    Extracts structured contact details (names, phones, emails, agencies) from raw text / descriptions.
    """
    if not text or not isinstance(text, str):
        return {"has_detected": False, "phones": [], "emails": [], "agent_name": None, "agency_name": None, "first_name": None, "last_name": None}

    # 1. Phone numbers (French formats)
    phone_pattern = re.compile(r'(?:(?:\+|00)33[\s.-]?[1-9]|0[1-9])(?:[\s.-]?\d{2}){4}')
    phones_raw = phone_pattern.findall(text)
    phones = []
    for p in phones_raw:
        cleaned = re.sub(r'[\s.-]', '', p)
        if len(cleaned) == 10 and cleaned.startswith('0'):
            formatted = f"{cleaned[:2]} {cleaned[2:4]} {cleaned[4:6]} {cleaned[6:8]} {cleaned[8:10]}"
            if formatted not in phones:
                phones.append(formatted)
        elif cleaned.startswith('+33') and len(cleaned) == 12:
            formatted = f"0{cleaned[3]} {cleaned[4:6]} {cleaned[6:8]} {cleaned[8:10]} {cleaned[10:12]}"
            if formatted not in phones:
                phones.append(formatted)
        elif p not in phones:
            phones.append(p.strip())

    # 2. Emails
    email_pattern = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
    emails_raw = email_pattern.findall(text)
    emails = []
    for e in emails_raw:
        e_clean = e.strip().lower()
        if not any(dummy in e_clean for dummy in ["example.com", "placeholder", "test@"]):
            if e_clean not in emails:
                emails.append(e_clean)

    # 3. Known Networks & Agencies
    known_networks = [
        "iad France", "iad", "Safti", "Capifrance", "Optimhome", "MegAgence", 
        "BSK Immobilier", "BSK", "Efficity", "Dr House Immo", "Proprietes-privees", 
        "Orpi", "Century 21", "Laforêt", "Guy Hoquet", "Stéphane Plaza Immobilier", 
        "Stéphane Plaza", "Foncia", "Human Immobilier", "Nexity", "Square Habitat", 
        "Arthurimmo", "Nestenn", "ERA Immobilier", "ERA", "Cimm Immobilier", "L'Adresse"
    ]
    detected_agency = None
    for net in known_networks:
        pattern = rf'\b{re.escape(net)}\b'
        if re.search(pattern, text, re.IGNORECASE):
            detected_agency = net
            break

    if not detected_agency:
        agency_match = re.search(r'\b(?:agence|cabinet|groupe|immobili[eè]re)\s+([A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+(?:\s+[A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+){0,3})', text, re.IGNORECASE)
        if agency_match:
            cand = agency_match.group(0).strip()
            if len(cand) > 5 and len(cand) < 40:
                detected_agency = cand

    # 4. Agent Name patterns
    detected_name = None
    first_name = None
    last_name = None

    stop_words = {
        "au", "aux", "à", "a", "pour", "sur", "tel", "tél", "le", "la", "les", "en", "de", "du", "des", 
        "france", "immobilier", "immobilière", "agence", "honoraires", "mandat", "charge", "vendeur", 
        "acquéreur", "prix", "chez", "par", "votre", "notre", "contact", "visite", "visiter", "disposition"
    }

    name_patterns = [
        r'(?:contactez|contacter|votre\s+conseill(?:er|ère)|agent\s+commercial|négociat(?:eur|rice)|mandataire)\s*(?:indépendant[e]?)?\s*(?::|-)?\s*([A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+(?:\s+[A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+){1,2})',
        r'(?:M\.|Mme|Monsieur|Madame)\s+([A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+(?:\s+[A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+){1,2})',
        r'(?:EI|RSAC)\s+([A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+(?:\s+[A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+){1,2})',
        r'Contact\s*:\s*([A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+(?:\s+[A-ZÀ-ÖØ-ß][a-zà-öø-ÿ\'-]+){1,2})'
    ]

    for p in name_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            # Clean up candidate words against stop words
            words = [w for w in cand.split() if w.lower() not in stop_words and len(w) >= 2]
            if len(words) >= 2:
                first_name = words[0].capitalize()
                last_name = words[1].upper()
                detected_name = f"{first_name} {last_name}"
                break


    has_detected = bool(phones or emails or detected_name or detected_agency)

    return {
        "has_detected": has_detected,
        "phones": phones,
        "emails": emails,
        "agent_name": detected_name,
        "first_name": first_name,
        "last_name": last_name,
        "agency_name": detected_agency
    }


def update_listing_address(
    db: Session,
    listing: Listing,
    address: str,
    city: Optional[str] = None,
    postal_code: Optional[str] = None,
    precision: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None
) -> Listing:
    """
    Updates a listing's exact address, city, postal code, precision, and coordinates.
    Sets manual_address_override = True and recalculates SNCF travel times.
    """
    from app.geo import resolve_address_details, calculate_station_times, find_nearby_stations, standardize_and_enrich_city
    from app.models import ZoneRule

    address_clean = address.strip() if address else ""
    if not address_clean:
        listing.address = None
        listing.postal_code = None
        listing.address_precision = "city"
        listing.manual_address_override = False
        db.commit()
        db.refresh(listing)
        return listing

    # If coordinates/city are missing, attempt resolution via BAN
    if lat is None or lon is None or not city or not precision:
        details = resolve_address_details(address_clean)
        if details:
            if lat is None or lon is None:
                lat = details.get("lat")
                lon = details.get("lon")
            if not city and details.get("city"):
                city = details.get("city")
            if not postal_code and details.get("postcode"):
                postal_code = details.get("postcode")
            if not precision and details.get("precision"):
                precision = details.get("precision")

    listing.address = address_clean
    if postal_code:
        listing.postal_code = postal_code

    if city:
        std_city, _, _ = standardize_and_enrich_city(city)
        final_city = std_city or city
        listing.city = final_city
        listing.location = f"{address_clean}, {final_city}"
    elif not listing.city:
        listing.location = address_clean

    listing.address_precision = precision or "exact"
    listing.manual_address_override = True

    if lat is not None and lon is not None:
        listing.latitude = lat
        listing.longitude = lon

        # Recalculate SNCF station times
        forbidden_stations = {r.name.strip().lower() for r in db.query(ZoneRule).filter(
            ZoneRule.zone_type == "station", ZoneRule.rule == "forbidden"
        ).all()}
        stations = find_nearby_stations(lat, lon)
        allowed_stations = [s for s in stations if s.get('name', '').strip().lower() not in forbidden_stations]
        if allowed_stations:
            st1 = allowed_stations[0]
            times1 = calculate_station_times(lat, lon, st1['lat'], st1['lon'])
            listing.nearest_sncf_station = st1.get('name')
            listing.walk_time_sncf = times1.get('walk')
            listing.bike_time_sncf = times1.get('bike')
            listing.car_time_sncf = times1.get('car')
            if len(allowed_stations) > 1:
                st2 = allowed_stations[1]
                times2 = calculate_station_times(lat, lon, st2['lat'], st2['lon'])
                listing.second_sncf_station = st2.get('name')
                listing.walk_time_sncf_2 = times2.get('walk')
                listing.bike_time_sncf_2 = times2.get('bike')
                listing.car_time_sncf_2 = times2.get('car')
            else:
                listing.second_sncf_station = None
                listing.walk_time_sncf_2 = None
                listing.bike_time_sncf_2 = None
                listing.car_time_sncf_2 = None
        else:
            listing.nearest_sncf_station = "NOT_FOUND"

    db.commit()
    db.refresh(listing)
    return listing


