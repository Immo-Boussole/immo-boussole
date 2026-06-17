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


def full_refresh_job():
    """
    Combined job:
    1. Runs the normal scraping job (find new listings in search results)
    2. Runs the individual status refresh (verify if existing listings are still online)
    """
    print("Démarrage du rafraîchissement complet (Scraping + Statuts)...")
    
    # Run the automated searches
    scraping_job()
    
    # Run the individual status checks
    from app.services import refresh_all_listings_status
    db = SessionLocal()
    try:
        asyncio.run(refresh_all_listings_status(db))
    except Exception as e:
        print(f"Erreur durant le rafraîchissement des statuts : {e}")
    finally:
        db.close()
        print("Rafraîchissement complet terminé.")


from apscheduler.triggers.interval import IntervalTrigger
from app.db_maintenance import identify_problems, repair_listings_batch_task, EMPTY_DESCRIPTION, GENERIC_TITLE_FIGARO
from app.models import SearchQuery, Source, ReadySearch, GlobalSettings


def db_check_job():
    print("[Scheduler] Démarrage de la vérification auto de la DB...")
    db = SessionLocal()
    try:
        identify_problems(db)
    finally:
        db.close()


def db_repair_job():
    print("[Scheduler] Démarrage de la réparation auto de la DB...")
    from app.db_maintenance import repair_all_sequential_task
    try:
        # Run repairs sequentially in the background
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(repair_all_sequential_task())
        loop.close()
    except Exception as e:
        print(f"[Scheduler] Erreur durant la réparation auto : {e}")


def _parse_interval(interval_str):
    if not interval_str: return 1440
    s = interval_str.lower().strip()
    if "30 min" in s: return 30
    if "1h" in s: return 60
    if "6h" in s: return 360
    if "12h" in s: return 720
    if "24h" in s: return 1440
    return 1440


def sync_db_maintenance_jobs(scheduler):
    db = SessionLocal()
    try:
        settings = db.query(GlobalSettings).first()
        if not settings:
            return

        # 1. Check Job
        job_id = "db_check_job"
        if settings.db_check_automate:
            minutes = _parse_interval(settings.db_check_interval)
            scheduler.add_job(
                db_check_job,
                trigger=IntervalTrigger(minutes=minutes),
                id=job_id,
                replace_existing=True,
                name="Vérification DB automatique"
            )
            print(f"[Scheduler] Job {job_id} configuré (toutes les {minutes} min)")
        else:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                print(f"[Scheduler] Job {job_id} supprimé")

        # 2. Repair Job
        job_id = "db_repair_job"
        if settings.db_repair_automate:
            minutes = _parse_interval(settings.db_repair_interval)
            scheduler.add_job(
                db_repair_job,
                trigger=IntervalTrigger(minutes=minutes),
                id=job_id,
                replace_existing=True,
                name="Réparation DB automatique"
            )
            print(f"[Scheduler] Job {job_id} configuré (toutes les {minutes} min)")
        else:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
                print(f"[Scheduler] Job {job_id} supprimé")
    finally:
        db.close()


def start_scheduler():
    """
    Registers cron jobs and interval jobs.
    """
    scheduler = BackgroundScheduler()

    # Every 30 minutes, 06:00 – 22:30
    from app.translations import get_text
    scheduler.add_job(
        scraping_job,
        trigger=CronTrigger(hour="6-22", minute="0,30"),
        id="scraping_job_30min",
        name=f"Scraping auto — {get_text(None, 'auto_searches.auto_refresh_value')}",
        replace_existing=True,
    )

    # Sync DB maintenance jobs
    sync_db_maintenance_jobs(scheduler)

    scheduler.start()
    return scheduler
