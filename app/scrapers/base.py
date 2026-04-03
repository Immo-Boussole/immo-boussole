import abc
<<<<<<< HEAD
=======

>>>>>>> 16b15c06962da86941aae50b5f0adf15a6b01549
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
<<<<<<< HEAD
        Fetches page content via Playwright connected to a Browserless
        instance over CDP (Chrome DevTools Protocol).
        Handles JavaScript rendering and applies stealth techniques.
        Returns {"html": "<rendered HTML>"} or {} on failure.
        """
        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async

        browserless_url = settings.BROWSERLESS_URL
        print(f"[Scraper] Extraction via Playwright/Browserless pour : {url}")
=======
        Fetches page content via a self-hosted Browserless instance using Playwright.
        Handles dynamic rendering and returns the HTML.
        """
        print(f"[Scraper] Extraction via Browserless/Playwright pour : {url}")

        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async
>>>>>>> 16b15c06962da86941aae50b5f0adf15a6b01549

        browser = None
        context = None
        try:
<<<<<<< HEAD
            pw = await async_playwright().start()
            browser = await pw.chromium.connect_over_cdp(browserless_url)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="fr-FR",
            )
            page = await context.new_page()
            await stealth_async(page)

            await page.goto(url, wait_until="networkidle", timeout=60000)
            html = await page.content()
            print(f"[Scraper] Succès Playwright pour {url} ({len(html)} chars)")
            return {"html": html}

        except Exception as e:
            print(f"[Scraper] Erreur Playwright : {e}")
=======
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
>>>>>>> 16b15c06962da86941aae50b5f0adf15a6b01549
            return {}

        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    def _normalize_city(self, location_str: Optional[str]) -> Optional[str]:
        """Normalizes a location string to extract just the city name."""
        if not location_str:
            return None
        # Remove zip codes, extra whitespace, lowercase
        import re
        city = re.sub(r'\b\d{5}\b', '', location_str).strip().lower()
        city = re.sub(r'\s+', ' ', city).strip()
        return city if city else None
