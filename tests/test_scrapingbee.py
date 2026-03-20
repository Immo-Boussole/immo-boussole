import requests
import sys

import os
API_KEY = os.getenv("SCRAPINGBEE_API_KEY", "YOUR_API_KEY_HERE")
URL_TO_SCRAPE = "https://www.leboncoin.fr/recherche?category=9&locations=Tain-l%27Hermitage_26600__45.07028_4.83761_5000_5000&price=200000-500000&square=100-500&rooms=4-max&real_estate_type=1&outside_access=garden&global_condition=3,2,1,4"

# Test 1: Simple GET sans aucun paramètre avancé
print("=== Test 1: GET simple ===")
response = requests.get(
    url="https://app.scrapingbee.com/api/v1/",
    params={
        "api_key": API_KEY,
        "url": URL_TO_SCRAPE,
    }
)
print(f"Status Code: {response.status_code}")
if response.status_code != 200:
    print(f"Error ({response.status_code}): {response.text}")
else:
    print("Succès! Première requête passée.")

# Test 2: render_js
print("\n=== Test 2: render_js=True ===")
response2 = requests.get(
    url="https://app.scrapingbee.com/api/v1/",
    params={
        "api_key": API_KEY,
        "url": URL_TO_SCRAPE,
        "render_js": "true"
    }
)
print(f"Status Code: {response2.status_code}")
if response2.status_code != 200:
    print(f"Error ({response2.status_code}): {response2.text}")
    
# Test 3: render_js + premium_proxy
print("\n=== Test 3: render_js=True & premium_proxy=True & block_resources=False ===")
response3 = requests.get(
    url="https://app.scrapingbee.com/api/v1/",
    params={
        "api_key": API_KEY,
        "url": URL_TO_SCRAPE,
        "render_js": "true",
        "premium_proxy": "true",
        "block_resources": "false",
        "country_code": "fr"
    }
)
print(f"Status Code: {response3.status_code}")
if response3.status_code != 200:
    print(f"Error ({response3.status_code}): {response3.text}")
else:
    print(f"Succès! Taille du contenu: {len(response3.text)}")
    with open("srb_debug.html", "w", encoding="utf-8") as f:
        f.write(response3.text)
