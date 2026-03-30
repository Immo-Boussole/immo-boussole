import abc

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
        Fetches page content via a self-hosted Browserless instance using Playwright.
        Handles dynamic rendering and returns the HTML.
        """
        print(f"[Scraper] Extraction via Browserless/Playwright pour : {url}")

        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async

        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(settings.BROWSERLESS_URL)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await stealth_async(page)
                
                await page.goto(url, wait_until="networkidle", timeout=60000)
                html = await page.content()
                
                await browser.close()
                
                print(f"[Scraper] Succès Browserless pour {url}")
                return {"html": html}

        except Exception as e:
            print(f"[Scraper] Erreur async Browserless : {e}")
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
