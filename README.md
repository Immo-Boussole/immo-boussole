# 🧭 Immo-Boussole

[![Build and Push Docker Image](https://github.com/Immo-Boussole/immo-boussole/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Immo-Boussole/immo-boussole/actions/workflows/docker-publish.yml)
[![Docker Hub](https://img.shields.io/badge/docker-hub-blue.svg?logo=docker&logoColor=white)](https://hub.docker.com/repository/docker/wikijm/immo-boussole/general)

*Note: At its core, this project targets French platforms for property search. / Note : Ce projet cible à l'origine les plateformes immobilières françaises pour la recherche de biens.*

[Version française disponible ici](README.fr.md)

**Immo-Boussole** is a collaborative web application designed to centralize, catalog, and evaluate real estate listings (LeBonCoin, SeLoger) in a structured manner.

![Dashboard](static/media/demo/exemple_tableaudebord.png)
![Listings Table](static/media/demo/exemple_tableaudesannonces.png)
![Listing Detail](static/media/demo/exemple_annonce.png)

## 🚀 Key Features

- **Smart Scraping**: Automatic extraction of details (price, area, DPE, taxes, charges, photos) from over 10 platforms:
  - LeBonCoin, SeLoger, Le Figaro Immobilier, LogicImmo, BienIci, IAD France, Immobilier Notaires, Vinci Immobilier, Immobilier France.
- **Local Media Management**: Photos are downloaded and served locally to avoid dead links.
- **Collaborative Reviews**: Separate rating and comment system.
- **Ideal Property Profile**: Generation of a dynamic profile based on top-rated listings (average price, area, recurring pros/cons).
- **Premium Interface**: Modern dark design, descriptive cards, photo carousels, and a secure delete button with confirmation (slide).

---

## ✨ Features Demonstration

The application is designed to optimize collaborative searching. Here is an overview of the main features:

### 📥 1. High-Quality Listings Import
Import active listings from **LeBonCoin** and **SeLoger**. The scraper automatically retrieves titles, descriptions, prices, areas, and high-resolution photos.

![Dashboard with Listings](static/media/demo/demo_dashboard.png)
*Initial state of the dashboard after importing 4 listings.*

### 📸 2. Interactive Photo Gallery
The detail page includes a responsive carousel and a premium "lightbox" gallery for an immersive view of the properties.

![Photo Gallery Demo](static/media/demo/demo_gallery.png)

*Interactive demonstration of the carousel and gallery.*

### 👥 3. Collaborative Review System
The application allows multiple reviewers (e.g., **Jean DUPONT** and **Marie MARTIN**) to provide independent reviews, ratings, and notes on each property.

![Collaborative Reviews Demo](static/media/demo/demo_reviews.png)

*Adding collaborative reviews and assigning ratings.*

### 🌟 4. "Ideal Property" Dynamic Profile
The application automatically synthesizes all highly-rated reviews to create your "Ideal Property" profile, highlighting recurring positive and negative points.

![Ideal Property Profile](static/media/demo/demo_ideal_profile.png)

*Dynamic synthesis of reviews into a 'Perfect Match' profile.*

### 🛡️ 5. Secure "Slide to Delete"
To prevent accidental deletions, the interface uses a premium slide-to-confirm interaction.

![Deletion Demo](static/media/demo/demo_deletion.webp)

*Demonstration of the secure slide-to-delete feature.*

### 🔔 6. New Version Alert
A banner automatically appears at the bottom of the home screen when a new version of the source code is available on GitHub. This mechanism discreetly compares the local commit hash with that of the main branch to keep you informed of the latest features and updates.

![Version Alert Demo](static/media/demo/demo_alert_banner.png)

*Preview of the banner indicating an available update.*

## 🛠️ Installation & Launch

### Prerequisites
- Python 3.10+
- [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) running locally (port 8191 by default) for scraping.

### Local Installation
1. **Clone the project**
2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate  # Windows
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure the environment**:
   ```bash
   cp .env.example .env
   ```
5. **Start the server**:
   ```bash
   python -m uvicorn app.main:app --reload
   ```
   The application is accessible at [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## 🐳 Running with Docker

The project is fully containerized, automatically including the **FlareSolverr** scraping engine. A pre-built image is available on [Docker Hub](https://hub.docker.com/repository/docker/wikijm/immo-boussole/general) and is automatically updated after each code modification via [GitHub Actions](.github/workflows/docker-publish.yml).

1. **Launch all services**:
   You can either build the image locally or use the pre-built image from Docker Hub:

   - **From source (local build)**:
     ```bash
     docker compose up -d --build immo-boussole
     ```
   - **From Docker Hub (pre-built)**:
     ```bash
     docker compose -f docker-compose.hub.yml up -d
     ```

   The local build command builds (or rebuilds) the image from the local source code and launches two containers: `immo-boussole` (the app) and `flaresolverr` (Cloudflare bypass).

   > [!TIP]
   > To update the application after a code change (when building locally), simply re-run:
   > `docker compose up -d --build immo-boussole`
   > The image will be updated with your changes, but **your data (database and photos) will remain intact** thanks to persistent volumes.

2. **Access**: The interface is available at [http://localhost:8000](http://localhost:8000).

3. **Captcha Management (Optional)**:
   If you encounter captcha blocks during scraping, you can enable the [2Captcha](https://2captcha.com/) solver:
   - In your `.env` file, set `CAPTCHA_SOLVER=2captcha`.
   - Enter your API key in `TWO_CAPTCHA_API_KEY=your_key_here`.
   - Restart the containers: `docker compose up -d`.

4. **Persistence**: The database and media are stored in named volumes (`immo-boussole-db` and `immo-boussole-media`).

### 🌐 Advanced Deployment (Portainer & Cloudflared)

For secure production deployment on a remote server, you can use **Portainer** to manage your containers and **Cloudflared** (Cloudflare Zero Trust Tunnels) to securely expose the application to the Internet without opening ports.

👉 **See the detailed guide: [Installation via Docker, Portainer, and Cloudflared](INSTALL_Docker+Portainer+Cloudflared.en.md)**

---

## 🔒 Security & Authentication

Access to the application is protected by a multi-user authentication system with roles.

- **Initial Setup**: On the first run, the application redirects to `/setup-admin` to create the primary administrator account.
- **Session**: Sessions are secured using a `SECRET_KEY` (automatically generated or defined in `.env`).
- **Access Control**: Any unauthenticated access attempt redirects to the login page.

---

## 👥 User Roles & Permissions

The system distinguishes between two primary roles:

- **ADMIN**:
  - Access to the **User Management** interface (`/admin/users`).
  - Ability to create and delete user accounts.
  - **Restriction**: Cannot import or scrape new listings (to maintain focus on management).
- **USER**:
  - Full access to property searching and evaluation.
  - Ability to import listings via URLs or manual entry.
  - **Restriction**: No access to the administration panel.

---

## 📖 User Guide

1. **Add a property**: Click on "+ Add Listing" and paste the LeBonCoin or SeLoger URL.
2. **Review**: Click on a card to view details, then fill out your section.
3. **Delete**: On the dashboard, click the trash can icon on a card and slide to confirm.
4. **Ideal Profile**: Check the global synthesis via the sidebar to see what type of property fits you best.

## 🔌 API Documentation (REST)

The application exposes a comprehensive REST API built with **FastAPI**. All endpoints require authentication (active session) and return an HTTP 401 code in case of unauthorized access.

### Listings
- `GET /api/listings`: Retrieves the list of listings (optional search filters: `status`, `source`, `limit`).
- `GET /api/listings/{listing_id}`: Retrieves full details of a specific listing.
- `POST /api/listings/submit-url`: Adds a new listing via a URL (automatically starts scraping). Accepts `url` and `skip_scraping` (boolean) in JSON.
- `POST /api/listings/{listing_id}/rescrape`: Manually triggers a scrape to update an existing listing.
- `PUT /api/listings/{listing_id}`: Manually updates the attributes of a listing (title, price, area, DPE, etc.).
- `DELETE /api/listings/{listing_id}`: Deletes a listing and its associated reviews.
- `POST /api/listings/{listing_id}/photos`: Imports new photos from a list of URLs.
- `POST /api/listings/{listing_id}/photos/upload`: Directly uploads photos (Multipart Form).

### Administration (Admin only)
- `GET /admin/users`: Interface for managing users.
- `POST /api/admin/users`: Creates a new user account (JSON body: `username`, `password`, `role`).
- `DELETE /api/admin/users/{user_id}`: Deletes a user account (prevents self-deletion).

### Reviews
- `GET /api/listings/{listing_id}/reviews`: Lists all reviews left on a listing.
- `POST /api/listings/{listing_id}/reviews`: Adds or updates a collaborative review (ratings, pros, cons).
- `PUT /api/reviews/{review_id}`: Modifies an existing specific review.
- `DELETE /api/reviews/{review_id}`: Deletes an existing review.

### Ideal Profile
- `GET /api/profile/ideal`: Returns the dynamic synthesis of the ideal property, calculated from the highest-rated listings.

### Saved Searches (Queries)
- `GET /api/queries`: Returns the list of scheduled automatic searches.
- `POST /api/queries`: Adds a new search to be scheduled (URL, name, source).

The API is also fully documented and testable via the integrated Swagger interface, accessible at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (or `/redoc`) when the application is running.

## 🏗️ Project Structure

- `app/`: Backend logic (scrapers, models, API services).
- `templates/`: HTML pages (Jinja2).
- `static/`: CSS assets and downloaded media (listing photos).
- `tests/`: Unit and integration test scripts.
- `debug/`: Debugging tools and temporary scraping logs.
- `Dockerfile` & `docker-compose.yml`: Docker configuration.
- `immo_boussole.db`: SQLite database (managed automatically).

## 🏗️ Technical Stack
- **Backend**: FastAPI (Python)
- **Database**: SQLite + SQLAlchemy (Automatic migrations included)
- **Scraping**: FlareSolverr / BeautifulSoup4 / HTTPX
- **Additional Scrapers**: Figaro and LogicImmo adapted from the [French-eState-Scrapper](https://github.com/Web3-Serializer/French-eState-Scrapper) project
- **Frontend**: HTML5 / Vanilla CSS / Jinja2
- **Scheduler**: APScheduler (for automatic searches)


## 🚀 Upcoming Features

- ✅ Protect access to the entire site with an authentication mechanism.
- ✅ Create an admin account setup system on first run.
- ✅ Create an administration interface.
- ✅ Create a user account system (at least one default user account, the admin should not be able to import listings).
- ⬜ Create a real estate agent account system (ability to view imported listings in the app, user feedback, and the ideal property profile).
- ⬜ Add a favorite system for listings.
- ⬜ Add a favorite system for searches.
- ✅ Make the application multilingual (French and English).
- ⬜ Add a notification system (email, push, etc.).
- ⬜ Re-implement the duplicate detection mechanism (alert if a similar property is already present).
