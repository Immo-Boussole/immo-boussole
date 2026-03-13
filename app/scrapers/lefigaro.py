import re
import json
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

class LeFigaroScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract listings from a LeFigaro search result page.
        """
        # Le Figaro search API is often used, but we'll try to extract from the HTML first
        # as the search_url provided by the user is likely a web URL.
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            # Look for JSON payload in script tags if available, similar to LBC
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html_content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # The exact path in INITIAL_STATE depends on the page version
                    # This is a placeholder for the logic found in the external repo
                    # which often targets api.figaro.fr directly.
                    pass
                except Exception as e:
                    print(f"[LeFigaro] Error parsing INITIAL_STATE: {e}")

            # Fallback: BeautifulSoup parsing
            # Le Figaro uses specific classes for listing items
            items = soup.find_all('div', class_=re.compile(r'class-item|ad-item'))
            for item in items:
                try:
                    link = item.find('a', href=True)
                    if not link: continue
                    url = link['href']
                    if not url.startswith('http'):
                        url = "https://immobilier.lefigaro.fr" + url
                    
                    title_elem = item.find(['h2', 'span'], class_=re.compile(r'title|subject'))
                    title = title_elem.text.strip() if title_elem else "Annonce Le Figaro"
                    
                    price_elem = item.find(text=re.compile(r'(\d+[\d\s]*)\s*€'))
                    price = 0.0
                    if price_elem:
                        match = re.search(r'(\d+[\d\s]*)\s*€', price_elem)
                        if match:
                            price_str = re.sub(r'[^\d]', '', match.group(1))
                            if price_str: price = float(price_str)
                    
                    ext_id = url.split('-')[-1].split('.')[0]

                    listings.append({
                        "external_id": f"figaro_{ext_id}",
                        "title": title,
                        "url": url,
                        "price": price,
                        "location": "France",
                        "city": None,
                        "area": None,
                        "rooms": None,
                        "photo_urls": [],
                    })
                except Exception as e:
                    print(f"[LeFigaro] Error parsing item: {e}")
                    continue

        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape a single LeFigaro listing page for details.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        # Extract basic info from meta tags
        details["url"] = url
        details["title"] = soup.find('title').text.strip() if soup.find('title') else "Annonce Le Figaro"
        
        og_desc = soup.find('meta', attrs={"property": "og:description"})
        details["description_text"] = og_desc.get("content", "") if og_desc else ""

        # Extract price
        price_elem = soup.find(text=re.compile(r'(\d+[\d\s]*)\s*€'))
        if price_elem:
            match = re.search(r'(\d+[\d\s]*)\s*€', price_elem)
            if match:
                price_str = re.sub(r'[^\d]', '', match.group(1))
                if price_str: details["price"] = float(price_str)

        # External ID
        ext_id = url.split('-')[-1].split('.')[0]
        details["external_id"] = f"figaro_{ext_id}"

        # Look for attributes in the page
        # Le Figaro often has a 'caracteristiques' section
        chars = soup.find_all(['li', 'div'], class_=re.compile(r'attribute|feature|char'))
        for char in chars:
            text = char.get_text().lower()
            if 'm²' in text:
                match = re.search(r'(\d+[\d\s,]*)\s*m²', text)
                if match:
                    details["area"] = float(match.group(1).replace(',', '.').replace(' ', ''))
            elif 'pièce' in text:
                match = re.search(r'(\d+)\s*pièce', text)
                if match:
                    details["rooms"] = int(match.group(1))

        # Photo URLs
        og_img = soup.find('meta', attrs={"property": "og:image"})
        if og_img:
            details["photo_urls"] = [og_img.get("content")]

        return details
