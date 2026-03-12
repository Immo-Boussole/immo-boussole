import tls_client

url = "https://www.leboncoin.fr/recherche?category=9&locations=Tain-l%27Hermitage_26600__45.07028_4.83761_5000_5000&price=200000-500000&square=100-500&rooms=4-max&real_estate_type=1&outside_access=garden&global_condition=3,2,1,4"

session = tls_client.Session(
    client_identifier="chrome_120",
    random_tls_extension_order=True
)

headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "priority": "u=0, i",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1"
}

print("Envoi de la requête via tls-client...")
response = session.get(url, headers=headers)
html = response.text

print(f"Statut : {response.status_code}")
print(f"Taille : {len(html)} char")

with open("tls_debug.html", "w", encoding="utf-8") as f:
    f.write(html)
