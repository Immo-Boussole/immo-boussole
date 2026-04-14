from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings
import asyncio
from app.database import SessionLocal
from app.models import SearchQuery, Source, ReadySearch
from app.services import scrape_and_diff

def scraping_job():
    print("Démarrage de la tâche de scraping (Scheduler)...")
    db = SessionLocal()
    
    # Sync ReadySearches to SearchQueries
    ready_searches = db.query(ReadySearch).all()
    for rs in ready_searches:
        if rs.platform and not rs.platform.endswith("(ajout manuel)") and rs.platform != "manuel":
            existing = db.query(SearchQuery).filter(SearchQuery.url == rs.url).first()
            if not existing:
                try:
                    src = Source(rs.platform)
                    new_q = SearchQuery(url=rs.url, source=src, name=f"Auto: {rs.criteria or rs.platform}", active=1)
                    db.add(new_q)
                    db.commit()
                except ValueError:
                    pass

    queries = db.query(SearchQuery).filter(SearchQuery.active == 1).all()
    
    # Run async scrapers within the synchronous APScheduler job environment
    async def run_scrapers():
        for query in queries:
            print(f"Recherche et scraping en cours pour : {query.name} ({query.source})")
            await scrape_and_diff(query, db)
            
    try:    
        asyncio.run(run_scrapers())
    except Exception as e:
        print(f"Erreur durant l'exécution des tâches de scraping : {e}")
    finally:
        db.close()
        print("Tâche de scraping terminée.")

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Execute job every configured interval (in hours)
    scheduler.add_job(
        scraping_job,
        trigger=IntervalTrigger(hours=settings.SCRAPING_INTERVAL_HOURS),
        id="main_scraping_job",
        name="Scraping des annonces immobilières",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
