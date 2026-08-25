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
        Fetches page content, rotating through the platform's proxy chain
        if blocks or captchas are encountered.
        """
        platform = self.__class__.__name__.replace("Scraper", "").lower()
        from app.proxy_router import proxy_router

        chain = proxy_router.get_proxy_chain(platform)
        start_idx = proxy_router.default_proxy_index.get(platform, 0)

        snapshot = {}
        for i in range(len(chain)):
            attempt_idx = (start_idx + i) % len(chain)
            proxy = proxy_router.get_current_proxy(platform, attempt_idx)

            try:
                snapshot = await self._execute_extraction(url, proxy)
            except Exception as e:
                print(f"[Scraper] Exception during extraction with proxy {proxy}: {e}")
                snapshot = {}

            html = snapshot.get("html", "")
            status_code = snapshot.get("status_code", 0)

            # Detect DataDome blocks
            is_blocked = (
                status_code == 403 or
                "geo.captcha-delivery.com/captcha/" in html or
                "<title>leboncoin.fr</title>" in html or
                "<title>seloger.com</title>" in html or
                "var dd={'rt':'c'" in html or
                "var dd={'rt':'b'" in html
            )

            if is_blocked:
                print(f"[Scraper] Bloqué par DataDome avec le proxy {proxy} (status: {status_code})")
                proxy_router.report_block(platform, proxy)
                # Fallback to the next proxy in the chain
                continue
            elif not html:
                print(f"[Scraper] Aucun contenu HTML retourné avec le proxy {proxy}")
                continue
            else:
                # Success!
                proxy_router.report_success(platform, proxy)
                return snapshot

        print(f"[Scraper] Échec de l'extraction de {url} : tous les proxys de la chaîne ont échoué ou été bloqués.")
        return {}

    async def _execute_extraction(self, url: str, proxy: str) -> Dict:
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
        
        # Append token and stealth if provided
        token = settings.BROWSERLESS_TOKEN
        browserless_url = f"{base_url}?stealth=true"
        if token:
            browserless_url += f"&token={token}"

        # Append external proxy if provided
        if proxy and proxy != "direct":
            import urllib.parse
            encoded_proxy = urllib.parse.quote_plus(proxy)
            browserless_url += f"&--proxy-server={proxy}&externalProxyServer={encoded_proxy}"
        
        print(f"[Scraper] Extraction via Playwright/Browserless CDP pour : {url} (proxy: {proxy})")

        pw = None
        browser = None
        context = None
        
        # Retry logic for the connection
        max_retries = 3
        retry_delay = 5 # seconds
        
        try:
            pw = await async_playwright().start()
            
            # --- Connection with Retries ---
            browser = None
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
                        print(f"[Scraper] Échec connexion Browserless après {max_retries} tentatives: {e}")
            
            if not browser:
                print("[Scraper] Fallback: Lancement de Chromium local...")
                try:
                    browser = await pw.chromium.launch(headless=True)
                except Exception as launch_err:
                    print(f"[Scraper] Échec critique: Impossible de lancer Chromium en local: {launch_err}")
                    raise launch_err
            
            try:
                # Once connected, proceed with page extraction
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    locale="fr-FR",
                )
                page = await context.new_page()
                
                # Apply stealth
                await apply_stealth(page)

                print(f"[Scraper] Navigation vers : {url}...")
                response = await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Handle cookie banners if needed
                await self._handle_cookie_banner(page)
                
                html = await page.content()
                status_code = response.status if response else 200
                print(f"[Scraper] Playwright success for {url} ({len(html)} chars, status {status_code})")
                return {"html": html, "status_code": status_code}
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

    async def _handle_cookie_banner(self, page):
        """Override this in subclasses to click cookie consent buttons."""
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
