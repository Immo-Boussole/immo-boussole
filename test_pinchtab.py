import argparse
import time
import requests
import json
import base64

API_URL = "http://127.0.0.1:9867"
TEST_URL = "https://www.leboncoin.fr/recherche?category=9&text=paris"

def test_pinchtab():
    print("1. Launching PinchTab Instance...")
    try:
        run_id = int(time.time())
        res = requests.post(f"{API_URL}/instances/launch", json={"name": f"test_lbc_{run_id}", "mode": "headless"})
        res.raise_for_status()
        instance_id = res.json().get("id")
        print(f" -> Instance created: {instance_id}")
        time.sleep(3)
    except Exception as e:
        print(f"Error launching instance: {e}")
        return

    print(f"\n2. Opening Tab to {TEST_URL}...")
    try:
        res = requests.post(f"{API_URL}/instances/{instance_id}/tabs/open", json={"url": TEST_URL})
        res.raise_for_status()
        tab_id = res.json().get("tabId")
        print(f" -> Tab created: {tab_id}")
    except Exception as e:
        print(f"Error opening tab: {e}")
        return

    print("\n3. Waiting 8 seconds for page to load and evade initial basic checks...")
    time.sleep(8)

    print("\n4. Extracting page snapshot to check for DataDome blocks...")
    try:
        # We will retrieve the snapshot to see if datadome is blocking us.
        res = requests.get(f"{API_URL}/tabs/{tab_id}/snapshot")
        res.raise_for_status()
        data = res.json()
        
        # Checking if \"datadome\" is found in the text or title.
        title = data.get("title", "")
        print(f" -> Page Title: {title}")
        
        text_content = data.get("text", "")
        if not text_content: 
            # Fallback to inspecting tree nodes if 'text' isn't natively exported
            text_content = json.dumps(data)

        if "datadome" in text_content.lower() or "geo.captcha-delivery" in text_content.lower() or "veuillez prouver que vous êtes un humain" in text_content.lower():
            print("\n❌ DATA DOME DETECTED! PinchTab failed to bypass the anti-bot protection.")
        elif "paris" in text_content.lower() or "annonces" in text_content.lower() or "leboncoin" in title.lower():
            print("\n✅ SUCCESS! Leboncoin page loaded without immediate block.")
        else:
            print("\n❓ UNKNOWN RESULT. Here is a snippet of the snapshot:")
            print(text_content[:500])
            
    except Exception as e:
        print(f"Error getting snapshot: {e}")
        print("Wait, PinchTab is experimental, checking if the server logs indicate an error.")

if __name__ == "__main__":
    test_pinchtab()
