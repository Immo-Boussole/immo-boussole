import asyncio
import os
from undetected_chromedriver import Chrome, ChromeOptions

async def extract_with_uc(url: str):
    print("Lancement de Selenium avec UC...")
    # On évite le mode headless au 1er lancement pour s'assurer que Chrome démarre
    options = ChromeOptions()
    driver = Chrome(options=options, headless=False, use_subprocess=False)
    
    try:
        print(f"Navigation vers {url}")
        driver.get(url)
        # Fallback pour s'assurer que le js passe
        await asyncio.sleep(8)
        content = driver.page_source
        
        with open("uc_debug.html", "w", encoding="utf-8") as f:
            f.write(content)
            
        print(f"Code source enregistré ({len(content)} char)")
    finally:
        driver.quit()

if __name__ == "__main__":
    url = "https://www.leboncoin.fr/recherche?category=9&locations=Tain-l%27Hermitage_26600__45.07028_4.83761_5000_5000&price=200000-500000&square=100-500&rooms=4-max&real_estate_type=1&outside_access=garden&global_condition=3,2,1,4"
    asyncio.run(extract_with_uc(url))
