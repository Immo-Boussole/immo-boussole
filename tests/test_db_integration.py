import asyncio
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import SearchQuery, Source
from app.services import scrape_and_diff

async def test_full_scrape():
    # 1. Obtenir une session DB
    db: Session = SessionLocal()
    
    # 2. Créer ou trouver une requête de test
    test_query = db.query(SearchQuery).filter(SearchQuery.url == "https://www.leboncoin.fr/recherche?category=9&text=paris").first()
    if not test_query:
        print("Création de la requête de test...")
        test_query = SearchQuery(
            url="https://www.leboncoin.fr/recherche?category=9&text=paris",
            source=Source.LEBONCOIN
        )
        db.add(test_query)
        db.commit()
    
    print(f"Lancement du test de scraping pour ID: {test_query.id}")
    
    # 3. Lancer le service
    await scrape_and_diff(query=test_query, db=db)
    
    # 4. Fermer la session
    db.close()
    print("Test terminé.")

if __name__ == "__main__":
    asyncio.run(test_full_scrape())
