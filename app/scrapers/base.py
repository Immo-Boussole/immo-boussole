import abc
import asyncio
from typing import List, Dict, Optional
from app.config import settings


class BaseScraper(abc.ABC):
    def __init__(self):
        pass

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
        Fetches page content via Playwright connected to a Browserless
        instance over CDP (Chrome DevTools Protocol).
        Handles JavaScript rendering and applies stealth techniques.
        Returns {"html": "<rendered HTML>"} or {} on failure.
        """
        from playwright.async_api import async_playwright
        # Define a robust stealth handler
        async def apply_stealth(p):
            try:
                # Try modern Stealth class first
                from playwright_stealth import Stealth
                await Stealth().apply_stealth_async(p)
            except (ImportError, AttributeError):
                try:
                    # Fallback to older stealth_async function
                    from playwright_stealth import stealth_async
                    await stealth_async(p)
                except (ImportError, AttributeError):
                    # Final fallback: do nothing
                    print("[Scraper] Warning: playwright_stealth not found, modern Stealth class or stealth_async missing. Proceeding without stealth.")
                    pass

        # --- Browserless URL Preparation ---
        base_url = settings.BROWSERLESS_URL.rstrip("/")
        # Append /playwright path if not present (recommended for Browserless Playwright connections)
        if not base_url.endswith("/playwright"):
            base_url = f"{base_url}/playwright"
        
        # Append token if provided
        token = settings.BROWSERLESS_TOKEN
        browserless_url = f"{base_url}?token={token}" if token else base_url
        
        print(f"[Scraper] Extraction via Playwright/Browserless pour : {url}")

        pw = None
        browser = None
        context = None
        
        # Retry logic for the connection
        max_retries = 3
        retry_delay = 5 # seconds
        
        try:
            pw = await async_playwright().start()
            
            # --- Connection with Retries ---
            for attempt in range(1, max_retries + 1):
                try:
                    print(f"[Scraper] Connexion à Browserless (tentative {attempt}/{max_retries})...")
                    browser = await pw.chromium.connect_over_cdp(
                        browserless_url, 
                        timeout=settings.BROWSERLESS_CONNECT_TIMEOUT * 1000
                    )
                    break # Success!
                except Exception as e:
                    if attempt < max_retries:
                        print(f"[Scraper] Échec connexion Browserless (tentative {attempt}): {e}. Nouvel essai dans {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                    else:
                        raise e # Final attempt failed
            
            try:
                # Once connected, proceed with page extraction
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
                
                # Apply stealth
                await apply_stealth(page)

                print(f"[Scraper] Navigation vers : {url}...")
                await page.goto(url, wait_until="networkidle", timeout=60000)
                html = await page.content()
                print(f"[Scraper] Succès Playwright pour {url} ({len(html)} chars)")
                return {"html": html}
            except Exception as e:
                print(f"[Scraper] Erreur durant l'extraction Playwright : {e}")
                return {}
            finally:
                if context:
                    await context.close()
                if browser:
                    await browser.close()
        except Exception as e:
            print(f"[Scraper] Erreur critique Playwright (init) : {e}")
            return {}
        finally:
            if pw:
                await pw.stop()
                print("[Scraper] Playwright stoppé.")

    def _normalize_city(self, location_str: Optional[str]) -> Optional[str]:
        """Normalizes a location string to extract just the city name."""
        if not location_str:
            return None
        # Remove zip codes, extra whitespace, lowercase
        import re
        city = re.sub(r'\b\d{5}\b', '', location_str).strip().lower()
        city = re.sub(r'\s+', ' ', city).strip()
        return city if city else None
