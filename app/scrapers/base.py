import abc
import requests
import asyncio
from typing import List, Dict
from app.config import settings

class BaseScraper(abc.ABC):
    def __init__(self):
        self.api_key = settings.SCRAPINGBEE_API_KEY
        
    @abc.abstractmethod
    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Scrape a given URL and return a list of dictionaries.
        Each dictionary should have: external_id, title, url, price, location, area.
        """
        pass
        
    async def extract_page_content(self, url: str) -> str:
        """
        Fetches the URL content via the ScrapingBee Web Unlocking API.
        It handles proxies, CAPTCHAs, and JS rendering behind the scenes.
        """
        if not self.api_key:
            raise ValueError("SCRAPINGBEE_API_KEY non configurée dans .env")
            
        print(f"Extraction via ScrapingBee pour l'URL : {url}")
        
        # We run the synchronous requests block inside asyncio's to_thread to keep the async flow non-blocking
        def fetch():
            response = requests.get(
                url="https://app.scrapingbee.com/api/v1/",
                params={
                    "api_key": self.api_key,
                    "url": url,
                    "render_js": "true",        # Requis pour LeBonCoin/SeLoger
                    "premium_proxy": "true",    # Requis pour bypasser DataDome
                    "country_code": "fr",       # Requis pour ne pas être géobloqué
                    "wait": "5000",             # Attendre 5s que les annonces chargent
                }
            )
            response.raise_for_status()
            return response.text
             
        try:
            content = await asyncio.to_thread(fetch)
            return content
        except Exception as e:
            print(f"Erreur durant l'appel à ScrapingBee : {e}")
            return ""
