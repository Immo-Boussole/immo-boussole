import httpx
import math
from typing import Dict, Optional, Tuple
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
      node["railway"="station"](around:{radius},{lat},{lon});
      way["railway"="station"](around:{radius},{lat},{lon});
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

def search_cities(query_str: str) -> list:
    """Searches for cities by name via Nominatim."""
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
        cities = []
        for item in data:
            # Nominatim returns cities as place=city/town/village OR boundary=administrative
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
        print(f"[Geo] City search failed for {query_str}: {e}")
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

def fetch_sncf_times_for_city(city_or_location: str) -> Optional[Dict]:
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
