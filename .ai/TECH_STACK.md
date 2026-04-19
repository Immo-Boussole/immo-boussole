---
description: Technical architecture and stack overview
---

# Technical Stack: Immo-Boussole

## 🏗️ Architecture Overview
Immo-Boussole is a **Dockerized Python web application** that maintains a clean separation between its web server, scraping engine, and persistent storage.

### 1. Web Application Layer
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.12).
- **Web Server**: [Uvicorn](https://www.uvicorn.org/) (Async Workers).
- **Template Engine**: [Jinja2](https://jinja.palletsprojects.com/) with a custom design system based on `DESIGN.md`.
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/) for type safety and settings management.

### 2. Scraping Engine
- **Headless Browser**: [Playwright](https://playwright.dev/) connected via CDP (Chrome DevTools Protocol).
- **Backend Service**: [Browserless/Chrome](https://www.browserless.io/) (Dockerized).
- **Data Extraction**: [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + CSS Selectors.
- **Anti-Bot Resilience**: `playwright-stealth` integration.

### 3. Scheduler
- **Engine**: [APScheduler](https://apscheduler.readthedocs.io/) with `BackgroundScheduler`.
- **Trigger**: `CronTrigger` for time-based scheduling (replaces the legacy `IntervalTrigger`).
- **Schedule**: Two jobs — `hour='6-22', minute='0'` (17 hourly runs) + `hour='22', minute='30'` (22:30 run) — covering 6:00–22:30 local time.
- **On-Demand**: A `POST /api/searches/force` endpoint triggers `scraping_job()` immediately via FastAPI `BackgroundTasks`.

### 4. Data Persistence & I18N
- **Database**: [SQLite](https://www.sqlite.org/index.html) managed via **SQLAlchemy**.
- **Migrations**: Custom `run_migrations()` function in `database.py` — safe ADD COLUMN on startup, no Alembic required.
- **I18N**: JSON-based localization files (`locales/en.json`, `locales/fr.json`).
- **Media**: Local storage for downloaded photos and static assets.

### 5. Geo & Risk Data
- **Geocoding**: [Nominatim](https://nominatim.org/) (OpenStreetMap) via HTTPX.
- **Routing**: [OSRM](http://project-osrm.org/) for walking/bike/car travel times to SNCF stations.
- **Risk**: [Géorisques API](https://www.georisques.gouv.fr/) for French property risk reports.

## 🐳 Docker Services
Defined in `docker-compose.yml`:
| Service | Image | Role |
|---------|-------|------|
| `immo-boussole-app` | `python:3.12-slim` | Main FastAPI app, scheduler, and API. |
| `browserless` | `browserless/chrome:latest` | Remote headless Chrome for scraping. |

## ⚙️ Environment Configuration
Key variables required in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./immo_boussole.db` | Path to the SQLite DB file. |
| `BROWSERLESS_URL` | `ws://localhost:3000` | WebSocket URL for the headless browser. |
| `BROWSERLESS_TOKEN` | *(empty)* | Optional Browserless auth token. |
| `SCRAPING_SCHEDULE` | `"Toutes les heures, de 6h à 22h30"` | Human-readable cron label shown in the UI. |
| `SECRET_KEY` | *(required)* | Session encryption key. |
| `DEBUG` | `True` | Development mode flag. |
| `GEORISQUES_API_KEY` | *(optional)* | API key for the Géorisques risk data service. |

## 📦 Core Dependencies
- `APScheduler`: Handles background tasks for periodic scraping (CronTrigger).
- `httpx`: Async HTTP client for light requests and API calls.
- `python-multipart`: Enables file uploads and form parsing.
- `aiofiles`: Asynchronous file operations (essential for media handling).
- `pydantic-settings`: Environment variable parsing and validation.
- `playwright` + `playwright-stealth`: Headless browser automation with anti-bot evasion.
- `beautifulsoup4`: HTML parsing for scraped pages.
