import asyncio
from app.database import SessionLocal
from app.models import SearchQuery, Source
from app.services import scrape_and_diff

async def main():
    db = SessionLocal()
    url = "https://www.leboncoin.fr/recherche?category=9&locations=Tain-l%27Hermitage_26600__45.07028_4.83761_5000_5000&price=200000-500000&square=100-500&rooms=4-max&real_estate_type=1&outside_access=garden&global_condition=3,2,1,4"
    
    query = db.query(SearchQuery).filter(SearchQuery.url == url).first()
    if not query:
        query = SearchQuery(url=url, source=Source.LEBONCOIN, name="Maisons Tain l'Hermitage & Alentours")
        db.add(query)
        db.commit()
        db.refresh(query)
        print("Nouvelle recherche ajoutée en base de données avec succès.")
    else:
        print("Cette recherche existe déjà.")
        
    print("Démarrage du scraping manuel depuis LeBonCoin...")
    try:
        await scrape_and_diff(query, db)
    except Exception as e:
        print(f"Erreur durant l'extraction : {e}")
    finally:
        db.close()
        print("Fin du processus.")

if __name__ == "__main__":
    asyncio.run(main())
