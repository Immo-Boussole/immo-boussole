import re
from app.scrapers.base import BaseScraper
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

class VinciScraper(BaseScraper):

    async def get_listings(self, search_url: str) -> List[Dict]:
        """
        Extract listings from Vinci Immobilier.
        """
        snapshot = await self.extract_page_content(search_url)
        if not snapshot:
            return []

        html_content = snapshot.get("html", "")
        listings = []

        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            items = soup.find_all(['div', 'article'], class_=re.compile(r'programme|card'))
            for item in items:
                try:
                    link = item.find('a', href=True)
                    if not link: continue
                    url = link['href']
                    if not url.startswith('http'):
                        url = "https://www.vinci-immobilier.com" + url
                    
                    title = item.find(['h2', 'h3']).text.strip() if item.find(['h2', 'h3']) else "Programme Vinci"
                    
                    price_elem = item.find(text=re.compile(r'À partir de\s*\d+[\s\d]*€'))
                    price = 0.0
                    if price_elem:
                        price_str = re.sub(r'[^\d]', '', price_elem)
                        if price_str: price = float(price_str)
                    
                    ext_id = url.split('/')[-1].split('.')[0]

                    listings.append({
                        "external_id": f"vinci_{ext_id}",
                        "title": title,
                        "url": url,
                        "price": price,
                        "location": "France",
                    })
                except Exception as e:
                    continue
        
        return listings

    async def get_listing_details(self, url: str) -> Dict:
        """
        Scrape details for a Vinci Immobilier listing.
        """
        snapshot = await self.extract_page_content(url)
        if not snapshot:
            return {}

        html_content = snapshot.get("html", "")
        if not html_content:
            return {}

        details = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        details["url"] = url
        details["title"] = soup.find('title').text.strip() if soup.find('title') else "Programme Vinci"
        
        desc = soup.find('div', class_=re.compile(r'description|bloc-texte'))
        details["description_text"] = desc.get_text().strip() if desc else ""

        # Attributes
        text = soup.get_text().lower()
        if 'm²' in text:
            match = re.search(r'(\d+[\d\s,]*)\s*m²', text)
            if match:
                details["area"] = float(match.group(1).replace(',', '.').replace(' ', ''))
        
        ext_id = url.split('/')[-1].split('.')[0]
        details["external_id"] = f"vinci_{ext_id}"

        # Photo
        og_img = soup.find('meta', attrs={"property": "og:image"})
        if og_img:
            details["photo_urls"] = [og_img.get("content")]

        return details
