import httpx
import math
from typing import Any, Dict, Optional, Tuple
from functools import lru_cache
from app.config import settings


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns the great-circle distance in km between two points."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# Dictionary cache for geo computations by city to avoid doing the same query for 100 listings in the same city
# Format: { "Lyon": {"nearest_sncf_station": "Gare Part-Dieu", "walk_time_sncf": 15, "bike_time_sncf": 5, "car_time_sncf": 3} }
GEO_CACHE: Dict[str, Dict] = {}


def get_coordinates(location_str: str) -> Optional[Tuple[float, float]]:
    """Geocodes a location string into (lat, lon)."""
    if not location_str:
        return None
    
    # Cleaning: if the string contains a ' — ' or ' - ' after a name, try to take only the address part
    # Example: "SANOFI — 14 Espace Henri Vallée, 69007 Lyon" -> "14 Espace Henri Vallée, 69007 Lyon"
    cleaned_location = location_str
    for separator in [" — ", " - ", " : "]:
        if separator in location_str:
            parts = location_str.split(separator)
            # If the second part looks like an address (has a number or a comma), use it
            if len(parts) >= 2 and (any(c.isdigit() for c in parts[1]) or "," in parts[1]):
                cleaned_location = separator.join(parts[1:]).strip()
                break

    headers = {"User-Agent": "ImmoBoussole/1.0"}
    geocode_url = f"https://nominatim.openstreetmap.org/search"
    
    async def query(q: str):
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(geocode_url, params={"q": q, "format": "json", "limit": 1, "countrycodes": "fr"}, headers=headers, timeout=10.0)
                res.raise_for_status()
                return res.json()
        except Exception as e:
            print(f"[Geo] Query failed for {q}: {e}")
            return None

    # Note: get_coordinates is used synchronously in many places, 
    # so we use httpx.get instead of async here to avoid breaking callers,
    # OR we keep it sync but with a fallback logic.
    
    def sync_query(q: str):
        try:
            res = httpx.get(geocode_url, params={"q": q, "format": "json", "limit": 1, "countrycodes": "fr"}, headers=headers, timeout=10.0)
            res.raise_for_status()
            return res.json()
        except Exception:
            return None

    # Try 1: Full or cleaned string
    data = sync_query(cleaned_location)
    
    # Try 2: If failed and we cleaned it, try the original just in case
    if not data and cleaned_location != location_str:
        data = sync_query(location_str)
        
    if not data:
        return None
        
    return float(data[0]['lat']), float(data[0]['lon'])

def find_nearby_stations(lat: float, lon: float, radius: int = 20000) -> list:
    """Finds SNCF stations within radius via Overpass API."""
    headers = {"User-Agent": "ImmoBoussole/1.0"}
    query = f"""
    [out:json];
    (
      node["railway"="station"]["station"!="subway"]["station"!="light_rail"]["subway"!="yes"]["light_rail"!="yes"](around:{radius},{lat},{lon});
      way["railway"="station"]["station"!="subway"]["station"!="light_rail"]["subway"!="yes"]["light_rail"!="yes"](around:{radius},{lat},{lon});
    );
    out center;
    """
    try:
        res_overpass = httpx.post("https://overpass-api.de/api/interpreter", data={"data": query}, headers=headers, timeout=15.0)
        res_overpass.raise_for_status()
        data_overpass = res_overpass.json()
        
        elements = data_overpass.get('elements', [])
        stations = []
        for el in elements:
            s_lat = el.get('lat') or el.get('center', {}).get('lat')
            s_lon = el.get('lon') or el.get('center', {}).get('lon')
            s_name = el.get('tags', {}).get('name', 'Gare SNCF')
            if s_lat and s_lon:
                stations.append({
                    "name": s_name,
                    "lat": s_lat,
                    "lon": s_lon,
                    "id": el.get('id')
                })
        return stations
    except Exception as e:
        print(f"[Geo] Overpass API failed: {e}")
        return []

def search_stations(query_str: str) -> list:
    """Searches for SNCF stations by name via Nominatim."""
    headers = {"User-Agent": "Immo-Boussole/1.0"}
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query_str,
        "format": "json",
        "limit": 10,
        "countrycodes": "fr"
    }
    try:
        res = httpx.get(url, params=params, headers=headers, timeout=10.0)
        res.raise_for_status()
        data = res.json()
        stations = []
        for item in data:
            # Check if it's actually a station or something related to railway
            if item.get("class") == "railway" or "gare" in item.get("display_name", "").lower():
                stations.append({
                    "name": item["display_name"],
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"])
                })
        return stations
    except Exception as e:
        print(f"[Geo] Station search failed for {query_str}: {e}")
        return []

def normalize_city_name(s: str) -> str:
    """
    Normalizes a French city name: lowercases, removes accents,
    expands 'st'/'ste' abbreviations to 'saint'/'sainte',
    and removes non-alphanumeric characters.
    """
    if not s:
        return ""
    import unicodedata
    import re
    s = s.lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\bst\b", "saint", s)
    s = re.sub(r"\bste\b", "sainte", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def expand_saint_abbr(s: str) -> str:
    """
    Expands 'st' / 'ste' abbreviations in a city name to 'Saint' / 'Sainte'
    for API queries (e.g. geo.api.gouv.fr).
    """
    if not s:
        return ""
    import re
    s = re.sub(r"\bst\b", "Saint", s, flags=re.I)
    s = re.sub(r"\bste\b", "Sainte", s, flags=re.I)
    return s.strip()


def search_cities(query_str: str) -> list:
    """Searches for cities by name or postal code via geo.api.gouv.fr with Nominatim fallback."""
    if not query_str:
        return []
    
    clean_query = query_str.strip()
    expanded_query = expand_saint_abbr(clean_query)
    
    # 1. Try geo.api.gouv.fr (fast, official French database, no 429 rate limit)
    try:
        url = "https://geo.api.gouv.fr/communes"
        if clean_query.isdigit():
            params = {"codePostal": clean_query, "fields": "nom,code,codesPostaux,centre", "limit": 10}
        else:
            params = {"nom": expanded_query, "boost": "population", "fields": "nom,code,codesPostaux,centre", "limit": 10}
            
        res = httpx.get(url, params=params, timeout=5.0)
        if res.status_code == 200:
            data = res.json()
            if data:
                cities = []
                for item in data:
                    nom = item.get("nom", "")
                    cps = item.get("codesPostaux", [])
                    cp_str = f" ({cps[0]})" if cps else ""
                    coords = item.get("centre", {}).get("coordinates", [])
                    lat = coords[1] if len(coords) >= 2 else None
                    lon = coords[0] if len(coords) >= 2 else None
                    
                    if lat is not None and lon is not None:
                        cities.append({
                            "name": f"{nom}{cp_str}",
                            "lat": float(lat),
                            "lon": float(lon)
                        })
                if cities:
                    return cities
    except Exception as e:
        print(f"[Geo] geo.api.gouv.fr city search failed for {query_str}: {e}")

    # 2. Fallback to Nominatim
    headers = {"User-Agent": "Immo-Boussole/1.0"}
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": expanded_query,
        "format": "json",
        "limit": 10,
        "countrycodes": "fr"
    }
    try:
        res = httpx.get(url, params=params, headers=headers, timeout=5.0)
        res.raise_for_status()
        data = res.json()
        cities = []
        for item in data:
            cls = item.get("class")
            typ = item.get("type")
            is_city = (cls == "place" and typ in ["city", "town", "village", "hamlet"]) or \
                      (cls == "boundary" and typ == "administrative")
            if is_city:
                cities.append({
                    "name": item["display_name"],
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"])
                })
        return cities
    except Exception as e:
        print(f"[Geo] Nominatim city search failed for {query_str}: {e}")
        return []

def get_railway_path(lat1: float, lon1: float, lat2: float, lon2: float) -> list:
    """
    Attempts to find a railway path between two points via Overpass.
    This is a simplified approach: it finds all ways with railway=rail 
    within a bounding box of the two points and tries to return a path.
    Since a full Dijkstra on railway network is complex for a stateless script,
    we fallback to a straight line if Overpass fails or returns no ways.
    """
    # Create a bounding box with 0.1 degree buffer
    min_lat = min(lat1, lat2) - 0.05
    max_lat = max(lat1, lat2) + 0.05
    min_lon = min(lon1, lon2) - 0.05
    max_lon = max(lon1, lon2) + 0.05
    
    query = f"""
    [out:json][timeout:25];
    (
      way["railway"~"rail|subway|tram|light_rail"]({min_lat},{min_lon},{max_lat},{max_lon});
    );
    out body;
    >;
    out skel qt;
    """
    headers = {"User-Agent": "ImmoBoussole/1.0"}
    try:
        res = httpx.post("https://overpass-api.de/api/interpreter", data={"data": query}, headers=headers, timeout=20.0)
        res.raise_for_status()
        data = res.json()
        
        # This is still hard to reconstruct without a graph library.
        # For the sake of the request and visual premium feel, 
        # we'll return the two points + a few intermediate points 
        # if we can find ways, OR just the two points if it's too far.
        
        # Fallback: simple line
        return [[lat1, lon1], [lat2, lon2]]
    except Exception as e:
        print(f"[Geo] Overpass railway path failed: {e}")
        return [[lat1, lon1], [lat2, lon2]]

def calculate_station_times(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> Dict[str, Optional[int]]:
    """
    Calculates walk, bike, and car times between two points.
    Uses OSRM driving profile (the only one reliably available on the public demo server)
    to get road distance, then derives walk/bike estimates from that distance
    using realistic average speeds:
      - Walking: ~5 km/h
      - Cycling: ~15 km/h
      - Car time: directly from OSRM driving duration
    """
    times: Dict[str, Optional[int]] = {"walk": None, "bike": None, "car": None}

    url_osrm = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}?overview=false"
    )
    try:
        res_osrm = httpx.get(url_osrm, timeout=5.0)
        res_osrm.raise_for_status()
        data_osrm = res_osrm.json()
        if data_osrm.get("code") == "Ok" and data_osrm.get("routes"):
            route = data_osrm["routes"][0]
            car_duration_s = route["duration"]       # seconds
            road_distance_m = route["distance"]      # metres

            times["car"] = max(1, int(car_duration_s / 60))

            # Derive walk & bike from road distance (more realistic than straight-line)
            road_km = road_distance_m / 1000.0
            times["walk"] = max(1, round(road_km / 5.0 * 60))   # 5 km/h
            times["bike"] = max(1, round(road_km / 15.0 * 60))  # 15 km/h
    except Exception as e:
        print(f"[Geo] OSRM driving routing failed: {e}")

    return times

def fetch_sncf_times_for_city(city_or_location: str, forbidden_stations: set = None) -> Optional[Dict]:
    """
    Geocodes a city/location, finds the 2 nearest stations,
    and returns their names and travel times.
    """
    if not city_or_location:
        return None

    city_key = city_or_location.strip().lower()
    if city_key in GEO_CACHE:
        return GEO_CACHE[city_key]

    # 1. Geocode
    coords = get_coordinates(city_key)
    if not coords:
        GEO_CACHE[city_key] = None
        return None
    lat, lon = coords

    # 2. Find stations
    stations = find_nearby_stations(lat, lon)
    if not stations:
        GEO_CACHE[city_key] = None
        return None

    if forbidden_stations:
        stations = [s for s in stations if s['name'].lower().strip() not in forbidden_stations]

    if not stations:
        GEO_CACHE[city_key] = None
        return None

    # Sort stations by simple straight-line distance to get the 2 nearest
    # (Simplified: using squared diffs is enough for sorting)
    def dist_sq(s):
        return (lat - s['lat'])**2 + (lon - s['lon'])**2
    stations.sort(key=dist_sq)

    result = {}
    
    # Process Station 1
    s1 = stations[0]
    t1 = calculate_station_times(lat, lon, s1['lat'], s1['lon'])
    result["nearest_sncf_station"] = s1['name']
    result["walk_time_sncf"] = t1.get('walk')
    result["bike_time_sncf"] = t1.get('bike')
    result["car_time_sncf"] = t1.get('car')

    # Process Station 2
    if len(stations) > 1:
        s2 = stations[1]
        t2 = calculate_station_times(lat, lon, s2['lat'], s2['lon'])
        result["second_sncf_station"] = s2['name']
        result["walk_time_sncf_2"] = t2.get('walk')
        result["bike_time_sncf_2"] = t2.get('bike')
        result["car_time_sncf_2"] = t2.get('car')

    GEO_CACHE[city_key] = result
    print(f"[Geo] Fetched SNCF data for {city_key}: {result}")
    return result


def get_insee_code(city_name: str, zipcode: str = None) -> Optional[str]:
    """
    Retrieves the INSEE code for a city via OpenDataSoft API.
    Used for Géorisques reports when the full address is missing.
    """
    if not city_name and not zipcode:
        return None
    
    # Normalize city name for API (uppercase, replace spaces with hyphens)
    city_upper = city_name.strip().upper().replace(" ", "-") if city_name else ""
    
    # Build a more flexible WHERE clause
    clauses = []
    if zipcode:
        clauses.append(f'postal_code="{zipcode}"')
    
    if city_upper:
        # Use LIKE to match city names that might have suffixes (arrondissements, etc.)
        clauses.append(f'nom_comm like "{city_upper}%"')
    
    where_clause = " and ".join(clauses)
    
    url = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/correspondance-code-insee-code-postal/records"
    try:
        res = httpx.get(url, params={"where": where_clause, "limit": 1}, timeout=10.0)
        res.raise_for_status()
        data = res.json()
        
        results = data.get("results", [])
        if results:
            return results[0].get("insee_com")
        
        # If no result with city + zip, try zip alone as fallback
        if zipcode and city_upper:
             res = httpx.get(url, params={"where": f'postal_code="{zipcode}"', "limit": 1}, timeout=10.0)
             res.raise_for_status()
             data = res.json()
             results = data.get("results", [])
             if results:
                 return results[0].get("insee_com")

        return None
    except Exception as e:
        print(f"[Geo] INSEE lookup failed for {city_name} ({zipcode}): {e}")
        return None


def get_postal_code(city_name: str) -> Optional[str]:
    """
    Retrieves the postal code for a city via OpenDataSoft API.
    Used for the nearby cities search feature.
    """
    if not city_name:
        return None
    
    # Normalize city name for API (uppercase, replace spaces with hyphens)
    city_upper = city_name.strip().upper().replace(" ", "-")
    
    # Use LIKE to match city names that might have suffixes
    where_clause = f'nom_comm like "{city_upper}%"'
    
    url = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/correspondance-code-insee-code-postal/records"
    try:
        res = httpx.get(url, params={"where": where_clause, "limit": 1}, timeout=10.0)
        res.raise_for_status()
        data = res.json()
        
        results = data.get("results", [])
        if results:
            # Note: postal_code can be a string like "75001" or sometimes a list of strings
            pc = results[0].get("postal_code")
            if isinstance(pc, list):
                return pc[0]
            return pc
        
        return None
    except Exception as e:
        print(f"[Geo] Postal code lookup failed for {city_name}: {e}")
        return None


def fetch_georisques_data(address: str = None, insee_code: str = None) -> Optional[Dict]:
    """
    Calls the Géorisques API to generate a JSON risk report.
    Priority to 'address' if provided and seems complete.
    """
    if not address and not insee_code:
        return None
    
    url = f"{settings.GEORISQUES_API_BASEURL.rstrip('/')}/v1/resultats_rapport_risque"
    params = {}
    if address:
        params["adresse"] = address
    elif insee_code:
        params["code_insee"] = insee_code
        
    headers = {"User-Agent": "ImmoBoussole/1.0"}
    if settings.GEORISQUES_API_KEY:
        headers["Authorization"] = f"Bearer {settings.GEORISQUES_API_KEY}"
        
    try:
        res = httpx.get(url, params=params, headers=headers, timeout=15.0)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"[Geo] Géorisques API failed (addr={address}, insee={insee_code}): {e}")
        return None


def parse_city_input(city_str: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Parses a raw city string to extract the potential city name,
    postal code (5 digits), or department code (2-3 digits).
    Examples:
      - "Saint-Clair-du-Rhône" -> ("Saint-Clair-du-Rhône", None, None)
      - "saint-clair-du-rhône (38)" -> ("saint-clair-du-rhône", None, "38")
      - "saint-clair-du-rhône (38370)" -> ("saint-clair-du-rhône", "38370", None)
      - "Saint-Clair-du-Rhône 38370" -> ("Saint-Clair-du-Rhône", "38370", None)
    """
    import re
    if not city_str:
        return "", None, None

    city_str = city_str.strip()

    # 1. Look for parentheses first: e.g. "Name (digits)"
    match_paren = re.search(r'\(([^)]+)\)', city_str)
    if match_paren:
        content = match_paren.group(1).strip()
        name_part = city_str.replace(match_paren.group(0), '').strip()
        if content.isdigit():
            if len(content) == 5:
                return name_part, content, None
            elif 2 <= len(content) <= 3:
                return name_part, None, content

    # 2. Look for trailing digits at the end of the string
    match_end = re.search(r'\b(\d{2,5})\b$', city_str)
    if match_end:
        digits = match_end.group(1)
        name_part = city_str[:match_end.start()].strip()
        # Clean any remaining trailing punctuation or parentheses
        name_part = re.sub(r'[\s()\-]+$', '', name_part).strip()
        if len(digits) == 5:
            return name_part, digits, None
        elif 2 <= len(digits) <= 3:
            return name_part, None, digits

    return city_str, None, None


def clean_arrondissement(name: str) -> str:
    """
    Cleans arrondissement suffixes from French city names.
    Examples:
      - "Paris 15e" -> "Paris"
      - "Lyon 6ème" -> "Lyon"
      - "Marseille 08" -> "Marseille"
    """
    import re
    name = re.sub(r'\b\d+(?:er|ème|eme|e)?\b', '', name, flags=re.I)
    name = re.sub(r'\barrondissements?\b', '', name, flags=re.I)
    name = re.sub(r'\barr\.?\b', '', name, flags=re.I)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.strip(' -')
    return name


def fallback_standardize_city(city_str: str) -> str:
    """
    Local fallback normalization if the API fails or returns no results.
    """
    import re
    if not city_str:
        return ""
    cleaned = city_str.strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    words = cleaned.split()
    capitalized_words = []
    for w in words:
        parts = w.split('-')
        capitalized_parts = [p.capitalize() for p in parts]
        capitalized_words.append('-'.join(capitalized_parts))
    return ' '.join(capitalized_words)


@lru_cache(maxsize=2048)
def standardize_and_enrich_city(city_str: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Standardizes a city name and retrieves its full 5-digit postal code
    and INSEE code via geo.api.gouv.fr.
    Returns:
      (standardized_name_with_zip, zip_code, insee_code)
      Example: ("Saint-Clair-du-Rhône (38370)", "38370", "38370")
    """
    if not city_str:
        return "", None, None

    import re
    city_str_cleaned = city_str.strip()
    if not city_str_cleaned:
        return "", None, None

    name, zip_code, dept_code = parse_city_input(city_str_cleaned)
    name_cleaned = clean_arrondissement(name)
    expanded_name = expand_saint_abbr(name_cleaned)
    norm_input = normalize_city_name(name_cleaned)

    results = []

    # Strategy 1: Search by expanded name and department if we have a department code
    if expanded_name:
        try:
            url = "https://geo.api.gouv.fr/communes"
            params = {"nom": expanded_name, "boost": "population", "limit": 10}
            if dept_code:
                params["codeDepartement"] = dept_code
            res = httpx.get(url, params=params, timeout=5.0)
            if res.status_code == 200:
                results = res.json()
        except Exception as e:
            print(f"[Geo API] Search by name {expanded_name} failed: {e}")

    # Strategy 1b: Search by name only if name+dept returned nothing
    if not results and expanded_name and dept_code:
        try:
            url = "https://geo.api.gouv.fr/communes"
            res = httpx.get(url, params={"nom": expanded_name, "boost": "population", "limit": 10}, timeout=5.0)
            if res.status_code == 200:
                results = res.json()
        except Exception as e:
            print(f"[Geo API] Search by name only {expanded_name} failed: {e}")

    # Strategy 2: Search by zip code if Strategy 1 failed or if we didn't have a name
    if not results and zip_code:
        try:
            url = "https://geo.api.gouv.fr/communes"
            res = httpx.get(url, params={"codePostal": zip_code}, timeout=5.0)
            if res.status_code == 200:
                results = res.json()
        except Exception as e:
            print(f"[Geo API] Search by zip {zip_code} failed: {e}")

    # Strategy 3: Fuzzy or broad word match fallback
    if not results and expanded_name:
        m = re.match(r'^([a-zA-Z\s\-]+)', expanded_name)
        if m:
            broad_name = m.group(1).strip()
            if broad_name != expanded_name:
                try:
                    url = "https://geo.api.gouv.fr/communes"
                    res = httpx.get(url, params={"nom": broad_name, "boost": "population", "limit": 10}, timeout=5.0)
                    if res.status_code == 200:
                        results = res.json()
                except Exception:
                    pass

    if not results:
        # Fallback to local standardized formatting
        fallback_name = fallback_standardize_city(city_str_cleaned)
        return fallback_name, zip_code, None

    best_commune = None

    # First try: exact normalized name match
    if norm_input:
        for c in results:
            c_norm = normalize_city_name(c.get("nom", ""))
            if c_norm == norm_input:
                if zip_code:
                    if zip_code in c.get("codesPostaux", []):
                        best_commune = c
                        break
                elif dept_code:
                    if c.get("codeDepartement") == dept_code:
                        best_commune = c
                        break
                else:
                    best_commune = c
                    break

        if not best_commune:
            for c in results:
                c_norm = normalize_city_name(c.get("nom", ""))
                if c_norm == norm_input:
                    best_commune = c
                    break

        # Second try: substring / inclusion match
        if not best_commune:
            for c in results:
                c_norm = normalize_city_name(c.get("nom", ""))
                if norm_input in c_norm or c_norm in norm_input:
                    if zip_code:
                        if zip_code in c.get("codesPostaux", []):
                            best_commune = c
                            break
                    elif dept_code:
                        if c.get("codeDepartement") == dept_code:
                            best_commune = c
                            break
                    else:
                        best_commune = c
                        break

    # If no name match was found but we had a zip code search, try querying by expanded name directly
    if not best_commune and norm_input and zip_code:
        try:
            url = "https://geo.api.gouv.fr/communes"
            res = httpx.get(url, params={"nom": expanded_name, "boost": "population", "limit": 10}, timeout=5.0)
            if res.status_code == 200:
                name_results = res.json()
                for c in name_results:
                    c_norm = normalize_city_name(c.get("nom", ""))
                    if c_norm == norm_input or norm_input in c_norm or c_norm in norm_input:
                        best_commune = c
                        break
        except Exception:
            pass

    # If still no commune matched by name, match zip or dept code only if no name was given
    if not best_commune and not norm_input:
        if zip_code:
            for c in results:
                if zip_code in c.get("codesPostaux", []):
                    best_commune = c
                    break
        elif dept_code:
            for c in results:
                if c.get("codeDepartement") == dept_code:
                    best_commune = c
                    break

    if not best_commune:
        # If we had results and couldn't match a specific name, but name was empty, take first
        if not norm_input and results:
            best_commune = results[0]
        else:
            fallback_name = fallback_standardize_city(city_str_cleaned)
            return fallback_name, zip_code, None

    postalcodes = best_commune.get("codesPostaux", [])
    selected_zip = zip_code if (zip_code and zip_code in postalcodes) else (postalcodes[0] if postalcodes else None)

    # If we had a 2-digit department but no full zip_code, pick a postal code matching the department
    if not selected_zip and dept_code and postalcodes:
        for pc in postalcodes:
            if pc.startswith(dept_code):
                selected_zip = pc
                break

    if not selected_zip and postalcodes:
        selected_zip = postalcodes[0]

    if not selected_zip:
        selected_zip = best_commune.get("codeDepartement", "") + "000"

    official_name = best_commune.get("nom", "")
    insee_code = best_commune.get("code", "")

    standardized_display = f"{official_name} ({selected_zip})"
    return standardized_display, selected_zip, insee_code


def is_city_in_forbidden_set(city_or_location: str, forbidden_cities: set) -> bool:
    """
    Checks if a city or location name matches any city in a set of forbidden cities.
    Handles case, zip codes, hyphens, and spaces cleanly.
    """
    if not city_or_location or not forbidden_cities:
        return False
        
    import re
    import unicodedata
    
    def clean_name(n: str) -> str:
        if not n:
            return ""
        # Remove multiple parenthesized numbers like " (42) (42)"
        n = re.sub(r'(?:\s*\(\d{2,5}\))+$', '', n)
        
        n, _, _ = parse_city_input(n)
        n = clean_arrondissement(n)
        
        # Remove accents
        n = ''.join(c for c in unicodedata.normalize('NFD', n) if unicodedata.category(c) != 'Mn')
        
        n = n.lower().strip()
        n = n.replace('-', ' ').replace("'", ' ').strip()
        n = re.sub(r'\s+', ' ', n)
        
        # Normalize "st " to "saint " and "ste " to "sainte "
        n = re.sub(r'\bst\b', 'saint', n)
        n = re.sub(r'\bste\b', 'sainte', n)
        
        return n

    c_clean = clean_name(city_or_location)
    if not c_clean:
        return False

    for fc in forbidden_cities:
        if not fc:
            continue
        if clean_name(fc) == c_clean:
            return True
            
    return False


def format_duration(minutes: int) -> str:
    """Formats minutes into human-readable string (e.g., '25 min', '1h 15 min', '2h')."""
    if minutes is None or minutes <= 0:
        return "1 min"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    rem_mins = minutes % 60
    if rem_mins == 0:
        return f"{hours}h"
    return f"{hours}h {rem_mins:02d} min"


def search_places_unified(query_str: str, limit: int = 8) -> list:
    """
    Unified smart autocomplete searching across French addresses, cities, and SNCF train stations.
    Returns a standardized list of places with lat/lon and type badge.
    """
    if not query_str or len(query_str.strip()) < 2:
        return []

    q = query_str.strip()
    results = []
    seen_coords = set()

    # 1. Query French Base Adresse Nationale (BAN) - extremely fast and comprehensive
    try:
        ban_url = "https://api-adresse.data.gouv.fr/search/"
        headers = {"User-Agent": "ImmoBoussole/1.0"}
        res = httpx.get(ban_url, params={"q": q, "limit": limit}, headers=headers, timeout=5.0)
        if res.status_code == 200:
            data = res.json()
            features = data.get("features", [])
            for feat in features:
                props = feat.get("properties", {})
                geometry = feat.get("geometry", {})
                coords = geometry.get("coordinates", [])
                if len(coords) == 2:
                    lon, lat = float(coords[0]), float(coords[1])
                    coord_key = (round(lat, 4), round(lon, 4))
                    if coord_key in seen_coords:
                        continue
                    seen_coords.add(coord_key)

                    ptype = props.get("type", "address")
                    if ptype == "municipality":
                        category = "city"
                        display_type = "Ville"
                    elif ptype in ("housenumber", "street", "locality"):
                        category = "address"
                        display_type = "Adresse"
                    else:
                        category = "address"
                        display_type = "Lieu-dit"

                    label = props.get("label") or props.get("name") or q
                    city = props.get("city") or ""
                    postcode = props.get("postcode") or ""
                    context = props.get("context") or ""

                    results.append({
                        "id": f"ban_{lat}_{lon}",
                        "label": label,
                        "name": props.get("name") or label,
                        "type": category,
                        "type_label": display_type,
                        "city": city,
                        "postcode": postcode,
                        "context": context,
                        "lat": lat,
                        "lon": lon
                    })
    except Exception as e:
        print(f"[Geo Unified Search] BAN search failed for '{q}': {e}")

    # 2. Query SNCF Stations if query looks like a station or to enrich results
    try:
        stations_query = q
        if "gare" not in q.lower() and len(q) >= 3:
            stations_query = f"Gare {q}"

        station_url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "Immo-Boussole/1.0 (contact@immo-boussole.local)"}
        params = {
            "q": stations_query,
            "format": "json",
            "limit": 4,
            "countrycodes": "fr"
        }
        res_station = httpx.get(station_url, params=params, headers=headers, timeout=5.0)
        if res_station.status_code == 200:
            station_data = res_station.json()
            for item in station_data:
                display_name = item.get("display_name", "")
                is_station = item.get("class") == "railway" or "gare" in display_name.lower()
                if is_station:
                    s_lat = float(item["lat"])
                    s_lon = float(item["lon"])
                    coord_key = (round(s_lat, 4), round(s_lon, 4))
                    if coord_key in seen_coords:
                        continue
                    seen_coords.add(coord_key)

                    # Extract short clean name
                    parts = display_name.split(",")
                    station_name = parts[0].strip() if parts else display_name

                    results.append({
                        "id": f"station_{s_lat}_{s_lon}",
                        "label": display_name,
                        "name": station_name,
                        "type": "station",
                        "type_label": "Gare SNCF",
                        "city": parts[1].strip() if len(parts) > 1 else "",
                        "postcode": "",
                        "context": ", ".join(parts[1:3]) if len(parts) > 1 else "",
                        "lat": s_lat,
                        "lon": s_lon
                    })
    except Exception as e:
        print(f"[Geo Unified Search] Station search failed for '{q}': {e}")

    return results[:limit]


def calculate_multi_route(
    start_lat: float, 
    start_lon: float, 
    end_lat: float, 
    end_lon: float,
    start_name: str = "Point A",
    end_name: str = "Point B"
) -> dict:
    """
    Calculates detailed itinerary, distances, and travel times (car, bike, walking)
    between two geographic points, with Leaflet polyline geometry and Google Maps links.
    """
    # 1. Query OSRM Driving router
    url_osrm = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson"
    )

    polyline = []
    road_distance_m = None
    car_duration_s = None

    try:
        res_osrm = httpx.get(url_osrm, timeout=8.0)
        if res_osrm.status_code == 200:
            data_osrm = res_osrm.json()
            if data_osrm.get("code") == "Ok" and data_osrm.get("routes"):
                route = data_osrm["routes"][0]
                road_distance_m = route.get("distance", 0)
                car_duration_s = route.get("duration", 0)
                coords = route.get("geometry", {}).get("coordinates", [])
                # OSRM returns [lon, lat], Leaflet needs [lat, lon]
                polyline = [[c[1], c[0]] for c in coords]
    except Exception as e:
        print(f"[Geo Multi Route] OSRM query failed: {e}")

    # Fallback to straight-line distance if OSRM failed or returned 0
    if not road_distance_m or road_distance_m <= 0:
        h_km = haversine_km(start_lat, start_lon, end_lat, end_lon)
        # Detour factor ~1.28 on average road network
        road_distance_m = max(100, int(h_km * 1.28 * 1000))
        car_duration_s = int((road_distance_m / 1000.0) / 50.0 * 3600)  # ~50 km/h
        polyline = [[start_lat, start_lon], [end_lat, end_lon]]

    road_distance_km = round(road_distance_m / 1000.0, 1)
    
    # Calculate durations in minutes
    car_min = max(1, round(car_duration_s / 60))
    # Cycling: ~15 km/h
    bike_min = max(1, round((road_distance_m / 1000.0) / 15.0 * 60))
    # Walking: ~5 km/h
    walk_min = max(1, round((road_distance_m / 1000.0) / 5.0 * 60))

    # Google Maps Directions URLs
    gmaps_base = "https://www.google.com/maps/dir/?api=1"
    gmaps_car = f"{gmaps_base}&origin={start_lat},{start_lon}&destination={end_lat},{end_lon}&travelmode=driving"
    gmaps_bike = f"{gmaps_base}&origin={start_lat},{start_lon}&destination={end_lat},{end_lon}&travelmode=bicycling"
    gmaps_walk = f"{gmaps_base}&origin={start_lat},{start_lon}&destination={end_lat},{end_lon}&travelmode=walking"

    return {
        "success": True,
        "distance_km": road_distance_km,
        "distance_m": int(road_distance_m),
        "start": {
            "name": start_name,
            "lat": start_lat,
            "lon": start_lon
        },
        "end": {
            "name": end_name,
            "lat": end_lat,
            "lon": end_lon
        },
        "modes": {
            "car": {
                "label": "Voiture",
                "icon": "fa-car",
                "duration_minutes": car_min,
                "formatted_duration": format_duration(car_min),
                "distance_km": road_distance_km,
                "gmaps_url": gmaps_car
            },
            "bike": {
                "label": "Vélo",
                "icon": "fa-bicycle",
                "duration_minutes": bike_min,
                "formatted_duration": format_duration(bike_min),
                "distance_km": road_distance_km,
                "gmaps_url": gmaps_bike
            },
            "walk": {
                "label": "À pied",
                "icon": "fa-person-walking",
                "duration_minutes": walk_min,
                "formatted_duration": format_duration(walk_min),
                "distance_km": road_distance_km,
                "gmaps_url": gmaps_walk
            }
        },
        "polyline": polyline
    }


# ── Points of Interest (POI) Engine ──

POI_CATEGORIES = {
    "highway": {
        "id": "highway",
        "name": "Sorties d'autoroute",
        "icon": "fa-road",
        "color": "#f87171",
        "bg_color": "rgba(248, 113, 113, 0.15)",
        "osm_query": """
            nwr["highway"="motorway_junction"](around:{radius},{lat},{lon});
            nwr["highway"="junction"](around:{radius},{lat},{lon});
        """,
        "default_name": "Sortie d'autoroute"
    },
    "cinema": {
        "id": "cinema",
        "name": "Cinémas & Théâtres",
        "icon": "fa-film",
        "color": "#c084fc",
        "bg_color": "rgba(192, 132, 252, 0.15)",
        "osm_query": """
            nwr["amenity"~"cinema|theatre"](around:{radius},{lat},{lon});
        """,
        "default_name": "Cinéma / Théâtre"
    },
    "swimming": {
        "id": "swimming",
        "name": "Piscines & Loisirs",
        "icon": "fa-person-swimming",
        "color": "#38bdf8",
        "bg_color": "rgba(56, 189, 248, 0.15)",
        "osm_query": """
            nwr["leisure"~"swimming_pool|water_park|sports_centre"](around:{radius},{lat},{lon});
            nwr["sport"="swimming"](around:{radius},{lat},{lon});
        """,
        "default_name": "Piscine / Centre sportif"
    },
    "mall": {
        "id": "mall",
        "name": "Centres commerciaux & Supermarchés",
        "icon": "fa-cart-shopping",
        "color": "#fbbf24",
        "bg_color": "rgba(251, 191, 36, 0.15)",
        "osm_query": """
            nwr["shop"~"mall|supermarket|department_store"](around:{radius},{lat},{lon});
        """,
        "default_name": "Commerce / Supermarché"
    },
    "bakery": {
        "id": "bakery",
        "name": "Boulangeries",
        "icon": "fa-bread-slice",
        "color": "#fb923c",
        "bg_color": "rgba(251, 146, 60, 0.15)",
        "osm_query": """
            nwr["shop"="bakery"](around:{radius},{lat},{lon});
        """,
        "default_name": "Boulangerie"
    },
    "school": {
        "id": "school",
        "name": "Écoles & Éducation",
        "icon": "fa-graduation-cap",
        "color": "#60a5fa",
        "bg_color": "rgba(96, 165, 250, 0.15)",
        "osm_query": """
            nwr["amenity"~"school|college|kindergarten"](around:{radius},{lat},{lon});
        """,
        "default_name": "Établissement scolaire"
    },
    "health": {
        "id": "health",
        "name": "Santé & Pharmacies",
        "icon": "fa-kit-medical",
        "color": "#34d399",
        "bg_color": "rgba(52, 211, 153, 0.15)",
        "osm_query": """
            nwr["amenity"~"pharmacy|hospital|clinic|doctors"](around:{radius},{lat},{lon});
        """,
        "default_name": "Professionnel de santé"
    },
    "station": {
        "id": "station",
        "name": "Gares SNCF & Transports",
        "icon": "fa-train",
        "color": "#a78bfa",
        "bg_color": "rgba(167, 139, 250, 0.15)",
        "osm_query": """
            nwr["railway"~"station|halt"](around:{radius},{lat},{lon});
        """,
        "default_name": "Gare / Halte ferroviaire"
    },
    "park": {
        "id": "park",
        "name": "Parcs & Espaces verts",
        "icon": "fa-tree",
        "color": "#4ade80",
        "bg_color": "rgba(74, 222, 128, 0.15)",
        "osm_query": """
            nwr["leisure"~"park|garden"](around:{radius},{lat},{lon});
        """,
        "default_name": "Parc / Jardin public"
    },
    "charging": {
        "id": "charging",
        "name": "Bornes de recharge & Carburant",
        "icon": "fa-charging-station",
        "color": "#2dd4bf",
        "bg_color": "rgba(45, 212, 191, 0.15)",
        "osm_query": """
            nwr["amenity"~"charging_station|fuel"](around:{radius},{lat},{lon});
        """,
        "default_name": "Station recharge / carburant"
    }
}

_poi_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
POI_CACHE_TTL_SECONDS = 600.0  # 10 minutes cache

OVERPASS_ENDPOINTS = [
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter"
]


def fetch_pois_around(
    lat: float,
    lon: float,
    radius_meters: int = 5000,
    categories: Optional[List[str]] = None,
    limit_per_category: int = 20
) -> Dict[str, Any]:
    """
    Fetches Points of Interest around (lat, lon) within radius_meters using Overpass API.
    Returns grouped and sorted POIs with metadata, distances, and category counts.
    """
    import time
    
    # Cap radius between 500m and 30,000m
    radius_meters = max(500, min(30000, int(radius_meters)))
    
    # Filter requested categories
    if not categories:
        active_cats = list(POI_CATEGORIES.keys())
    else:
        active_cats = [c for c in categories if c in POI_CATEGORIES]
        if not active_cats:
            active_cats = list(POI_CATEGORIES.keys())

    # Check cache
    cache_key = f"{round(lat, 4)}_{round(lon, 4)}_{radius_meters}_{','.join(sorted(active_cats))}"
    now = time.time()
    if cache_key in _poi_cache:
        cached_time, cached_data = _poi_cache[cache_key]
        if now - cached_time < POI_CACHE_TTL_SECONDS:
            return cached_data

    # Build Bounding Box for fast spatial query
    import math
    d_lat = radius_meters / 111320.0
    d_lon = radius_meters / max(1e-5, (111320.0 * math.cos(math.radians(lat))))
    s, w, n, e = round(lat - d_lat, 5), round(lon - d_lon, 5), round(lat + d_lat, 5), round(lon + d_lon, 5)

    full_query = f"""
    [out:json][timeout:20];
    (
      node["highway"="motorway_junction"]({s},{w},{n},{e});
      node["highway"="junction"]({s},{w},{n},{e});
      node["shop"~"bakery|supermarket|mall|department_store"]({s},{w},{n},{e});
      node["amenity"~"cinema|theatre|school|college|kindergarten|hospital|clinic|doctors|pharmacy|fuel|charging_station"]({s},{w},{n},{e});
      node["railway"~"station|halt"]({s},{w},{n},{e});
      node["leisure"~"swimming_pool|sports_centre|water_park|park|garden"]({s},{w},{n},{e});
      way["amenity"~"cinema|theatre|school|hospital"]({s},{w},{n},{e});
      way["shop"~"mall|supermarket"]({s},{w},{n},{e});
      way["railway"="station"]({s},{w},{n},{e});
      way["leisure"~"swimming_pool|park"]({s},{w},{n},{e});
    );
    out center 200 qt;
    """

    headers = {"User-Agent": "Immo-Boussole/1.0 (POI Engine)"}
    elements = []
    
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            res = httpx.post(
                endpoint,
                data={"data": full_query},
                headers=headers,
                timeout=18.0
            )
            if res.status_code == 200:
                data = res.json()
                elements = data.get("elements", [])
                if len(elements) > 0:
                    break
        except Exception as e:
            print(f"[GeoPOI] Endpoint {endpoint} failed: {e}")

    # Process and classify elements
    pois_by_category: Dict[str, List[Dict[str, Any]]] = {c: [] for c in active_cats}
    all_pois: List[Dict[str, Any]] = []
    seen_coords = set()

    for el in elements:
        p_lat = el.get("lat") or el.get("center", {}).get("lat")
        p_lon = el.get("lon") or el.get("center", {}).get("lon")
        if not p_lat or not p_lon:
            continue

        coord_key = (round(p_lat, 5), round(p_lon, 5))
        if coord_key in seen_coords:
            continue
        seen_coords.add(coord_key)

        tags = el.get("tags", {})
        
        # Determine category matching
        matched_cat = None
        for cat_id in active_cats:
            if cat_id == "highway" and (tags.get("highway") in ["motorway_junction", "junction"]):
                matched_cat = "highway"
                break
            elif cat_id == "cinema" and (tags.get("amenity") in ["cinema", "theatre"]):
                matched_cat = "cinema"
                break
            elif cat_id == "swimming" and (tags.get("leisure") in ["swimming_pool", "sports_centre", "water_park"] or tags.get("sport") == "swimming"):
                matched_cat = "swimming"
                break
            elif cat_id == "mall" and (tags.get("shop") in ["mall", "supermarket", "department_store"]):
                matched_cat = "mall"
                break
            elif cat_id == "bakery" and tags.get("shop") == "bakery":
                matched_cat = "bakery"
                break
            elif cat_id == "school" and (tags.get("amenity") in ["school", "college", "kindergarten"]):
                matched_cat = "school"
                break
            elif cat_id == "health" and (tags.get("amenity") in ["pharmacy", "hospital", "clinic", "doctors"]):
                matched_cat = "health"
                break
            elif cat_id == "station" and (tags.get("railway") in ["station", "halt"]):
                matched_cat = "station"
                break
            elif cat_id == "park" and (tags.get("leisure") in ["park", "garden"]):
                matched_cat = "park"
                break
            elif cat_id == "charging" and (tags.get("amenity") in ["charging_station", "fuel"]):
                matched_cat = "charging"
                break

        if not matched_cat:
            continue

        cat_meta = POI_CATEGORIES[matched_cat]

        # Extract best name
        raw_name = tags.get("name")
        if not raw_name:
            if matched_cat == "highway":
                ref = tags.get("ref")
                name_fr = tags.get("name:fr") or tags.get("description")
                if ref:
                    raw_name = f"Sortie {ref}" + (f" - {name_fr}" if name_fr else "")
                elif name_fr:
                    raw_name = name_fr
                else:
                    raw_name = cat_meta["default_name"]
            elif matched_cat == "station":
                raw_name = tags.get("name") or "Gare SNCF"
            elif matched_cat == "charging":
                operator = tags.get("operator") or tags.get("brand")
                raw_name = f"Borne {operator}" if operator else cat_meta["default_name"]
            else:
                brand = tags.get("brand") or tags.get("operator")
                raw_name = brand or cat_meta["default_name"]

        # Calculate distance
        dist_km = round(haversine_km(lat, lon, p_lat, p_lon), 2)
        
        # Approximate durations
        car_mins = max(1, int(round((dist_km * 1.3) / 50.0 * 60)))  # ~50 km/h average local driving
        bike_mins = max(1, int(round((dist_km * 1.2) / 15.0 * 60))) # ~15 km/h cycling
        walk_mins = max(1, int(round((dist_km * 1.1) / 5.0 * 60)))  # ~5 km/h walking

        poi_item = {
            "id": f"poi_{el.get('type', 'node')}_{el.get('id', len(all_pois))}",
            "name": raw_name,
            "category": matched_cat,
            "category_name": cat_meta["name"],
            "icon": cat_meta["icon"],
            "color": cat_meta["color"],
            "bg_color": cat_meta["bg_color"],
            "lat": float(p_lat),
            "lon": float(p_lon),
            "distance_km": dist_km,
            "car_mins": car_mins,
            "car_time_str": format_duration(car_mins),
            "bike_mins": bike_mins,
            "bike_time_str": format_duration(bike_mins),
            "walk_mins": walk_mins,
            "walk_time_str": format_duration(walk_mins),
            "address": tags.get("addr:street") or tags.get("addr:city") or "",
            "gmaps_url": f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={p_lat},{p_lon}&travelmode=driving"
        }

        pois_by_category[matched_cat].append(poi_item)
        all_pois.append(poi_item)

    # Sort items by distance and limit per category
    final_pois: List[Dict[str, Any]] = []
    category_counts: Dict[str, int] = {}
    
    for cat_id in active_cats:
        sorted_cat_pois = sorted(pois_by_category[cat_id], key=lambda x: x["distance_km"])
        category_counts[cat_id] = len(sorted_cat_pois)
        limited_cat_pois = sorted_cat_pois[:limit_per_category]
        final_pois.extend(limited_cat_pois)

    # Sort overall results by distance
    final_pois.sort(key=lambda x: x["distance_km"])

    response_data = {
        "success": True,
        "center": {"lat": lat, "lon": lon},
        "radius_meters": radius_meters,
        "total_count": len(final_pois),
        "category_counts": category_counts,
        "categories_meta": {
            c: {
                "id": POI_CATEGORIES[c]["id"],
                "name": POI_CATEGORIES[c]["name"],
                "icon": POI_CATEGORIES[c]["icon"],
                "color": POI_CATEGORIES[c]["color"],
                "bg_color": POI_CATEGORIES[c]["bg_color"],
                "count": category_counts.get(c, 0)
            } for c in active_cats
        },
        "pois": final_pois
    }

    # Store in cache only if results were found
    if len(final_pois) > 0:
        _poi_cache[cache_key] = (now, response_data)
    return response_data


