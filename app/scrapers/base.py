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
        Fetches page content via a self-hosted FlareSolverr instance.
        Handles Cloudflare challenges and returns the rendered HTML.
        """
        print(f"[Scraper] Extraction via FlareSolverr pour : {url}")

        def fetch():
            import time
            api_url = settings.FLARESOLVERR_URL
            
            payload = {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": 60000,
                "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0"
            }

            try:
                # Call FlareSolverr
                response = requests.post(
                    f"{api_url}/v1",
                    json=payload,
                    timeout=70  # Slightly longer than maxTimeout
                )
                response.raise_for_status()
                data = response.json()

                if data.get("status") == "ok":
                    solution = data.get("solution", {})
                    html = solution.get("response", "")
                    print(f"[Scraper] Succès FlareSolverr pour {url}")
                    return {"html": html}
                else:
                    print(f"[Scraper] FlareSolverr erreur : {data.get('message')}")
                    return {}

            except Exception as e:
                print(f"[Scraper] Erreur FlareSolverr : {e}")
                # Fallback to direct HTTP if FlareSolverr fails/is missing? 
                # Better to return empty so calling code knows it failed.
                return {}

        try:
            content = await asyncio.to_thread(fetch)
            return content
        except Exception as e:
            print(f"[Scraper] Erreur async FlareSolverr : {e}")
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
