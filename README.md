# 🧭 Immo-Boussole

[![Build and Push Docker Image](https://github.com/Immo-Boussole/immo-boussole/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Immo-Boussole/immo-boussole/actions/workflows/docker-publish.yml)
[![Docker Hub](https://img.shields.io/badge/docker-hub-blue.svg?logo=docker&logoColor=white)](https://hub.docker.com/repository/docker/wikijm/immo-boussole/general)
[![Docker Image](https://img.shields.io/badge/image-wikijm%2Fimmo-boussole%3A20312430b7bed763f3a1bb651f1959a6fda60e6b-0db7ed?logo=docker&logoColor=white)](https://hub.docker.com/r/wikijm/immo-boussole)
[![Wiki Documentation](https://img.shields.io/badge/docs-GitHub%20Wiki-blue?logo=github)](https://github.com/Immo-Boussole/immo-boussole/wiki)

> *Note: At its core, this project targets French real estate platforms. / Note : Ce projet cible principalement les plateformes immobilières françaises.*  
> 🇫🇷 **[Version française disponible ici (README.fr.md)](README.fr.md)**

**Immo-Boussole** is a modern, collaborative web application designed to centralize, catalog, evaluate, and track real estate listings across 10+ platforms (LeBonCoin, SeLoger, BienIci, LogicImmo, Le Figaro, etc.) in a structured and intuitive manner.

---

## 📸 Screenshots

| Dashboard | Listings Overview | Listing Detail |
|---|---|---|
| ![Dashboard](static/media/demo/exemple_tableaudebord.png) | ![Listings Table](static/media/demo/exemple_tableaudesannonces.png) | ![Listing Detail](static/media/demo/exemple_annonce.png) |

---

## 🚀 Key Features

* **Smart Multi-Platform Scraping**: Automated extraction of price, area, DPE energy ratings, property taxes, HOA fees, geolocations, and full-resolution photos from over 10 platforms:
  * *LeBonCoin, SeLoger, Le Figaro Immobilier, LogicImmo, BienIci, IAD France, Immobilier Notaires, Vinci Immobilier, Immobilier France, Provimo.*
* **Automated Scheduled Scraping**: Background scheduler running hourly from 6:00 to 22:30 to automatically scrape configured searches ("Ready to Search").
* **Instant Force Search**: Trigger a complete background scraping cycle on demand without waiting for the schedule.
* **Local Media & Offline Storage**: Photos are downloaded and served locally to ensure zero dead links.
* **Collaborative Reviews & Notes**: Multi-user independent ratings, notes, pros/cons, and criteria evaluations for each property.
* **"Ideal Property" AI Synthesis**: Dynamic profile automatically synthesized from top-rated listings to identify recurring matches and red flags.
* **Interactive Map View**: Visual geographic mapping of active, imported, and newly discovered listings.
* **AI Assistant & MCP Protocol**: Built-in conversational AI assistant (Ollama) and Model Context Protocol (MCP) server for external LLM tools (Claude Desktop).
* **Google Integrations**: Synchronize property visits with Google Calendar and real estate agency contacts with Google Contacts.
* **Backup & Restore**: Built-in admin module to export and import the entire database and media library in a single ZIP file.

---

## 📚 Complete Documentation & Guides (GitHub Wiki)

All technical deployment and configuration guides are centralized on our **[GitHub Wiki](https://github.com/Immo-Boussole/immo-boussole/wiki)**:

| Guide / Topic | Description | Link |
|---|---|---|
| 🐳 **Docker & Cloudflare Deployment** | Production setup with Docker Compose, Portainer, and Cloudflare Zero Trust Tunnels | [Read Guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Installation-Docker-EN) |
| 🛡️ **Residential Proxy & Anti-Bot** | Deploy a residential proxy (Synology NAS / Raspberry Pi) to bypass DataDome / 403 blocks | [Read Guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Proxy-Setup-EN) |
| 🤖 **AI Assistant & MCP Service** | Connect Ollama and expose your listings to Claude Desktop via MCP | [Read Guide](https://github.com/Immo-Boussole/immo-boussole/wiki/MCP-Setup-EN) |
| 💾 **Backup & Restore** | Backup and restore SQLite databases, media files, and configurations | [Read Guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Backup-Restore-EN) |
| 🔑 **Google OAuth2 Setup** | Configure Google Calendar & Google Contacts synchronization | [Read Guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Google-OAuth-Setup-EN) |

---

## ⚡ Quick Start

### 1. Using Docker (Recommended)

Immo-Boussole is containerized and includes the **Browserless** headless browser engine.

#### Using Pre-built Image (Docker Hub)
```bash
docker compose -f docker-compose.hub.yml up -d
```

#### Building from Source
```bash
docker compose up -d --build immo-boussole
```

The application is immediately accessible at **[http://localhost:8000](http://localhost:8000)**.  
*Persistent data (database and photos) is safely preserved in Docker named volumes.*

---

### 2. Local Python Development

#### Prerequisites
* Python 3.10+
* A running [Browserless](https://www.browserless.io/) or Chrome instance

```bash
# 1. Clone the repository
git clone https://github.com/Immo-Boussole/immo-boussole.git
cd immo-boussole

# 2. Setup virtual environment
python -m venv venv
.\venv\Scripts\activate  # On Windows (or source venv/bin/activate on Linux/macOS)

# 3. Install dependencies
pip install -r requirements.txt

# 4. Environment setup
cp .env.example .env

# 5. Run development server
python -m uvicorn app.main:app --reload
```

---

## ⚙️ Environment Configuration

Common configuration variables in `.env`:

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Session and token signing key. |
| `DATABASE_URL` | `sqlite:///./immo_boussole.db` | SQLite database connection string. |
| `BROWSERLESS_URL` | `ws://localhost:3000` | WebSocket endpoint for the headless browser scraper. |
| `BROWSERLESS_TOKEN` | *(empty)* | Optional authentication token for Browserless. |
| `SCRAPING_SCHEDULE` | `"Toutes les heures, de 6h à 22h30"` | Human-readable schedule displayed in the UI. |
| `GEORISQUES_API_KEY` | *(optional)* | API key for French natural/technological risk data. |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Endpoint for the Ollama AI assistant. |
| `OLLAMA_MODEL` | `llama3` | Model used for chat and listing analysis. |

---

## 🔌 API & Swagger Documentation

Immo-Boussole includes a complete REST API powered by **FastAPI**:

* **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🧪 Testing

The repository provides a test suite for API endpoints, scraping logic, database operations, and integrations:

```bash
# Run all tests
python tests/run_tests.py

# Run in CI mode
python tests/run_tests.py --ci
```

---

## 🏗️ Tech Stack

* **Backend**: FastAPI (Python 3.12), SQLAlchemy ORM, SQLite, APScheduler, Pydantic v2
* **Scraping & Automation**: Playwright, Browserless, BeautifulSoup4, HTTPX
* **Frontend**: HTML5, Vanilla CSS (Modern Dark Mode / Glassmorphism), Jinja2 templates
* **Integrations**: Google Calendar API, Google People API, MCP (Model Context Protocol), Géorisques API, OpenStreetMap / Nominatim

---

## 📄 License

This project is open-source. See the repository for details.

