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

### 3. Data Persistence & I18N
- **Database**: [SQLite](https://www.sqlite.org/index.html) managed via **SQLAlchemy**.
- **I18N**: JSON-based localization files (`locales/en.json`, `locales/fr.json`).
- **Media**: Local storage for downloaded photos and static assets.

## 🐳 Docker Services
Defined in `docker-compose.yml`:
| Service | Image | Role |
|---------|-------|------|
| `immo-boussole-app` | `python:3.12-slim` | Main FastAPI app, scheduler, and API. |
| `browserless` | `browserless/chrome:latest` | Remote headless Chrome for scraping. |

## ⚙️ Environment Configuration
Key variables required in `.env`:
- `DATABASE_URL`: Path to the SQLite DB file (def: `sqlite:////app/data/immo_boussole.db`).
- `BROWSERLESS_URL`: WebSocket URL for the browser (def: `ws://browserless:3000`).
- `SCRAPING_INTERVAL_HOURS`: Background task frequency (def: `12`).
- `DEBUG`: Boolean for development mode.

## 📦 Core Dependencies
- `APScheduler`: Handles background tasks for periodic scraping.
- `httpx`: Async HTTP client for light requests and API calls.
- `python-multipart`: Enables file uploads and form parsing.
- `aiofiles`: Asynchronous file operations (essential for media handling).
