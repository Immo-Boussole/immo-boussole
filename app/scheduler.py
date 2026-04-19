from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.database import SessionLocal
from app.models import SearchQuery, Source, ReadySearch
from app.services import scrape_and_diff
import asyncio


def scraping_job():
    """
    Main scraping job: synchronises ReadySearches into SearchQueries, then
    runs scrape_and_diff for every active query.

    Each ReadySearch is passed explicitly to scrape_and_diff so that newly
    discovered listings inherit the platform and criteria columns displayed
    in the auto_searches view (/searches/auto).

    Scheduled to run every hour from 06:00 to 22:30 (local time).
    """
    print("Démarrage de la tâche de scraping (Scheduler)...")
    db = SessionLocal()

    # ── 1. Sync ReadySearches → SearchQueries ──────────────────────────────
    # Build a map: url -> ReadySearch for later lookup
    ready_searches = db.query(ReadySearch).all()
    ready_search_by_url: dict[str, ReadySearch] = {}

    for rs in ready_searches:
        if rs.platform and not rs.platform.endswith("(ajout manuel)") and rs.platform != "manuel":
            ready_search_by_url[rs.url] = rs
            existing = db.query(SearchQuery).filter(SearchQuery.url == rs.url).first()
            if not existing:
                try:
                    src = Source(rs.platform)
                    new_q = SearchQuery(
                        url=rs.url,
                        source=src,
                        name=f"Auto: {rs.criteria or rs.platform}",
                        active=1,
                    )
                    db.add(new_q)
                    db.commit()
                except ValueError:
                    pass

    # ── 2. Run scrapers for all active queries ─────────────────────────────
    queries = db.query(SearchQuery).filter(SearchQuery.active == 1).all()

    async def run_scrapers():
        for query in queries:
            print(f"Recherche et scraping en cours pour : {query.name} ({query.source})")
            # Pass the originating ReadySearch when available so new listings
            # get source_ready_search_id + source_criteria set correctly.
            ready_search = ready_search_by_url.get(query.url)
            await scrape_and_diff(query, db, ready_search=ready_search)

    try:
        asyncio.run(run_scrapers())
    except Exception as e:
        print(f"Erreur durant l'exécution des tâches de scraping : {e}")
    finally:
        db.close()
        print("Tâche de scraping terminée.")


def start_scheduler():
    """
    Registers two APScheduler cron jobs so scraping runs every hour
    between 06:00 and 22:30 (local server time):

      - Job 1: minute=0, hour=6-22  → fires at 06:00, 07:00, …, 22:00
      - Job 2: minute=30, hour=22   → fires at 22:30
    """
    scheduler = BackgroundScheduler()

    # Hourly on the hour, 06:00 – 22:00
    scheduler.add_job(
        scraping_job,
        trigger=CronTrigger(hour="6-22", minute="0"),
        id="scraping_job_hourly",
        name="Scraping auto — toutes les heures (06h-22h)",
        replace_existing=True,
    )

    # Extra run at 22:30
    scheduler.add_job(
        scraping_job,
        trigger=CronTrigger(hour="22", minute="30"),
        id="scraping_job_2230",
        name="Scraping auto — 22h30",
        replace_existing=True,
    )

    scheduler.start()
    return scheduler
