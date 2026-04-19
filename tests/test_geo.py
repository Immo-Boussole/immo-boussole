import httpx
import json

def test():
    city = "Lyon"
    # Geocode city
    url_geocode = f"https://nominatim.openstreetmap.org/search?q={city}&format=json&limit=1"
    res = httpx.get(url_geocode, headers={"User-Agent": "ImmoBoussole/1.0"})
    data = res.json()
    if not data:
        print("City not found")
        return
    lat, lon = data[0]['lat'], data[0]['lon']
    print(f"City {city} -> {lat}, {lon}")

    # Find nearest station
    query = f"""
    [out:json];
    node["railway"="station"](around:10000,{lat},{lon});
    out 1;
    """
    res2 = httpx.post("https://overpass-api.de/api/interpreter", data={"data": query})
    data2 = res2.json()
    if 'elements' not in data2 or not data2['elements']:
        print("No station found")
        return
    
    station = data2['elements'][0]
    s_lat, s_lon = station['lat'], station['lon']
    s_name = station.get('tags', {}).get('name', 'Gare')
    print(f"Station {s_name} -> {s_lat}, {s_lon}")

    # Route
    for mode in ['driving', 'walking', 'cycling']:
        url_osrm = f"http://router.project-osrm.org/route/v1/{mode}/{lon},{lat};{s_lon},{s_lat}?overview=false"
        res3 = httpx.get(url_osrm)
        data3 = res3.json()
        if data3.get('code') == 'Ok':
            duration = data3['routes'][0]['duration'] / 60
            print(f"{mode} -> {duration:.1f} mins")

test()
