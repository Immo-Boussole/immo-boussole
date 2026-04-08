import httpx
from typing import Dict, Optional, Tuple
from functools import lru_cache

# Dictionary cache for geo computations by city to avoid doing the same query for 100 listings in the same city
# Format: { "Lyon": {"nearest_sncf_station": "Gare Part-Dieu", "walk_time_sncf": 15, "bike_time_sncf": 5, "car_time_sncf": 3} }
GEO_CACHE: Dict[str, Dict] = {}


def fetch_sncf_times_for_city(city_or_location: str) -> Optional[Dict]:
    """
    Geocodes a city/location, finds the nearest SNCF station via Overpass API,
    and returns travel times using OSRM for walking, cycling, and driving.
    """
    if not city_or_location:
        return None

    city_key = city_or_location.strip().lower()
    if city_key in GEO_CACHE:
        return GEO_CACHE[city_key]

    headers = {"User-Agent": "ImmoBoussole/1.0"}

    # 1. Geocode the city
    geocode_url = f"https://nominatim.openstreetmap.org/search"
    try:
        res = httpx.get(geocode_url, params={"q": city_key, "format": "json", "limit": 1}, headers=headers, timeout=10.0)
        res.raise_for_status()
        data = res.json()
        if not data:
            GEO_CACHE[city_key] = None
            return None
        
        lat = data[0]['lat']
        lon = data[0]['lon']
    except Exception as e:
        print(f"[Geo] Geocoding failed for {city_key}: {e}")
        return None

    # 2. Find nearest SNCF station using Overpass
    # We look for nodes or ways with railway=station and network~SNCF or name containing "Gare"
    # To keep it robust, we search for railway=station within 20km.
    query = f"""
    [out:json];
    (
      node["railway"="station"](around:20000,{lat},{lon});
      way["railway"="station"](around:20000,{lat},{lon});
    );
    out center 1;
    """
    try:
        res_overpass = httpx.post("https://overpass-api.de/api/interpreter", data={"data": query}, headers=headers, timeout=10.0)
        res_overpass.raise_for_status()
        data_overpass = res_overpass.json()
        
        elements = data_overpass.get('elements', [])
        if not elements:
            GEO_CACHE[city_key] = None
            return None

        station = elements[0]
        # For 'way' elements, the coordinate is 'center', for 'node', it's 'lat'/'lon' directly.
        s_lat = station.get('lat') or station.get('center', {}).get('lat')
        s_lon = station.get('lon') or station.get('center', {}).get('lon')
        s_name = station.get('tags', {}).get('name', 'Gare SNCF')
        
    except Exception as e:
        print(f"[Geo] Overpass API failed for {city_key}: {e}")
        return None

    if not s_lat or not s_lon:
        GEO_CACHE[city_key] = None
        return None

    # 3. Calculate OSRM routes
    times = {}
    for mode, key in [('foot', 'walk_time_sncf'), ('bike', 'bike_time_sncf'), ('car', 'car_time_sncf')]:
        # osrm profiles: foot, bike (or bicycle), car
        profile = mode
        if mode == 'car': profile = 'driving'
        elif mode == 'bike': profile = 'cycling'
        elif mode == 'foot': profile = 'walking'

        url_osrm = f"http://router.project-osrm.org/route/v1/{profile}/{lon},{lat};{s_lon},{s_lat}?overview=false"
        try:
            res_osrm = httpx.get(url_osrm, timeout=5.0)
            res_osrm.raise_for_status()
            data_osrm = res_osrm.json()
            if data_osrm.get('code') == 'Ok' and data_osrm.get('routes'):
                duration_seconds = data_osrm['routes'][0]['duration']
                times[key] = int(duration_seconds / 60)
        except Exception as e:
            print(f"[Geo] OSRM {mode} routing failed for {city_key}: {e}")
            pass

    if 'walk_time_sncf' not in times and 'car_time_sncf' not in times:
        GEO_CACHE[city_key] = None
        return None

    result = {
        "nearest_sncf_station": s_name,
        "walk_time_sncf": times.get('walk_time_sncf'),
        "bike_time_sncf": times.get('bike_time_sncf'),
        "car_time_sncf": times.get('car_time_sncf')
    }
    GEO_CACHE[city_key] = result
    print(f"[Geo] Fetched SNCF data for {city_key}: {result}")
    return result
