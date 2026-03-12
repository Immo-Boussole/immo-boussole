import requests
import json
import time

API_URL = "http://127.0.0.1:9867"
url = "https://www.leboncoin.fr/recherche?category=9&text=paris"
run_id = int(time.time())

print("Launching instance...")
res_inst = requests.post(f"{API_URL}/instances/launch", json={"name": f"debug_{run_id}", "mode": "headless"})
instance_id = res_inst.json().get("id")

print("Opening tab...")
for attempt in range(10):
    time.sleep(2)
    res_tab = requests.post(f"{API_URL}/instances/{instance_id}/tabs/open", json={"url": url})
    if res_tab.status_code == 200 or res_tab.status_code == 201:
        break

tab_id = res_tab.json().get("tabId")

print("Waiting 6s...")
time.sleep(6)

print("Getting snapshot...")
res_snap = requests.get(f"{API_URL}/tabs/{tab_id}/snapshot?filter=all")
data = res_snap.json()

with open("nodes_debug.json", "w", encoding="utf-8") as f:
    json.dump(data.get("nodes", []), f, indent=2, ensure_ascii=False)

print("Saved to nodes_debug.json")
requests.delete(f"{API_URL}/instances/{instance_id}")
