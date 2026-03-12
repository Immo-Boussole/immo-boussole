import abc
import requests
import asyncio
from typing import List, Dict, Optional
from app.config import settings


class BaseScraper(abc.ABC):
    def __init__(self):
        self.api_key = settings.SCRAPINGBEE_API_KEY

    @abc.abstractmethod
    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Scrape a search results page and return a list of listing dictionaries.
        Each dict should have: external_id, title, url, price, location, area.
        """
        pass

    @abc.abstractmethod
    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape a single listing detail page and return an enriched dict.
        Should include: dpe_rating, ges_rating, rooms, floor, land_tax,
        charges, description_text, photo_urls, etc.
        """
        pass

    async def extract_page_content(self, url: str) -> Dict:
        """
        Fetches page content via the local PinchTab headless browser API.
        Handles proxies, CAPTCHAs, and JS rendering.
        """
        print(f"[Scraper] Extraction via PinchTab pour : {url}")

        def fetch():
            import time
            import random

            api_url = settings.PINCHTAB_URL
            run_id = int(time.time())
            instance_id = None

            # Human emulation: random delay before request
            pre_launch_delay = random.uniform(5, 15)
            print(f"[Scraper] Attente anti-bot de {pre_launch_delay:.1f}s avant PinchTab...")
            time.sleep(pre_launch_delay)

            try:
                # 1. Launch instance (headed mode to bypass bot checks)
                res_inst = requests.post(f"{api_url}/instances/launch", json={
                    "name": f"scraper_{run_id}",
                    "mode": "headed"
                })
                res_inst.raise_for_status()
                instance_id = res_inst.json().get("id")

                # 2. Open Tab with retry logic for instance boot
                res_tab = None
                for attempt in range(10):
                    time.sleep(2)
                    res_tab = requests.post(
                        f"{api_url}/instances/{instance_id}/tabs/open",
                        json={"url": url}
                    )
                    if res_tab.status_code == 503:
                        print(f"[Scraper] Instance {instance_id} démarre, tentative {attempt + 1}/10...")
                        continue
                    res_tab.raise_for_status()
                    break

                if res_tab is None or res_tab.status_code == 503:
                    raise Exception(f"Instance {instance_id} non prête après 20s.")

                tab_id = res_tab.json().get("tabId")

                # 3. Wait for JS rendering and bot protection layers
                post_launch_delay = random.uniform(8, 15)
                print(f"[Scraper] Attente de rendu JS de {post_launch_delay:.1f}s...")
                time.sleep(post_launch_delay)

                # 4. Get full HTML via JS execution
                try:
                    res_script = requests.post(
                        f"{api_url}/tabs/{tab_id}/script",
                        json={"script": "return document.documentElement.outerHTML;"}
                    )
                    res_script.raise_for_status()
                    content = res_script.json().get("result", "")
                    if content:
                        return {"html": content}
                except Exception as eval_err:
                    print(f"[Scraper] Erreur JS, fallback texte: {eval_err}")

                # 5. Fallback: raw text extraction
                res_text = requests.get(f"{api_url}/tabs/{tab_id}/text")
                res_text.raise_for_status()
                return {"text": res_text.json().get("text", "")}

            except Exception as req_err:
                print(f"[Scraper] Erreur PinchTab : {req_err}")
                return {}

            finally:
                # Always cleanup instance to prevent memory leaks
                if instance_id:
                    try:
                        requests.delete(f"{api_url}/instances/{instance_id}")
                        print(f"[Scraper] Instance {instance_id} nettoyée.")
                    except Exception as cleanup_err:
                        print(f"[Scraper] Erreur nettoyage instance ({instance_id}): {cleanup_err}")

        try:
            content = await asyncio.to_thread(fetch)
            return content
        except Exception as e:
            print(f"[Scraper] Erreur async PinchTab : {e}")
            return {}

    def _normalize_city(self, location_str: Optional[str]) -> Optional[str]:
        """Normalizes a location string to extract just the city name."""
        if not location_str:
            return None
        # Remove zip codes, extra whitespace, lowercase
        import re
        city = re.sub(r'\b\d{5}\b', '', location_str).strip().lower()
        city = re.sub(r'\s+', ' ', city).strip()
        return city if city else None
