# 🧭 Immo-Boussole

[![Build and Push Docker Image](https://github.com/Immo-Boussole/immo-boussole/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Immo-Boussole/immo-boussole/actions/workflows/docker-publish.yml)
[![Docker Hub](https://img.shields.io/badge/docker-hub-blue.svg?logo=docker&logoColor=white)](https://hub.docker.com/repository/docker/wikijm/immo-boussole/general)
[![Image Docker](https://img.shields.io/badge/image-wikijm%2Fimmo-boussole%3A6146aab1e1e58f9dba8050a8a6fba0ee95aa3f14-0db7ed?logo=docker&logoColor=white)](https://hub.docker.com/r/wikijm/immo-boussole)

*Note : Ce projet cible à l'origine les plateformes immobilières françaises pour la recherche de biens. / Note: At its core, this project targets French platforms for property search.*

[English version available here](README.md)

**Immo-Boussole** est une application web collaborative conçue pour centraliser, cataloguer et évaluer les offres immobilières (LeBonCoin, SeLoger, et 8+ autres plateformes) de manière structurée.

![Tableau de Bord](static/media/demo/exemple_tableaudebord.png)
![Tableau des Annonces](static/media/demo/exemple_tableaudesannonces.png)
![Détail Annonce](static/media/demo/exemple_annonce.png)


## 🚀 Fonctionnalités Clés

- **Scraping Intelligent** : Extraction automatique des détails (prix, surface, DPE, taxes, charges, photos) depuis plus de 10 plateformes :
  - LeBonCoin, SeLoger, Le Figaro Immobilier, LogicImmo, BienIci, IAD France, Immobilier Notaires, Vinci Immobilier, Immobilier France.
- **Recherches Automatiques Planifiées** : Scraping automatique de toutes les entrées "Prêt à Rechercher", exécuté **toutes les heures de 6h à 22h30**. Les nouvelles annonces apparaissent dans la vue "Recherches Automatiques", pré-étiquetées avec leur plateforme source et leurs critères de recherche.
- **Forcer la Recherche** : Un bouton dans la vue "Recherches Automatiques" permet de déclencher instantanément un cycle complet de scraping, sans attendre la prochaine exécution planifiée.
- **Gestion Locale des Médias** : Les photos sont téléchargées et servies localement pour éviter les liens morts.
- **Avis Collaboratifs** : Système de notation et de commentaires séparés.
- **Fiche Bien Idéal** : Génération d'un profil dynamique basé sur les annonces les mieux notées (moyennes de prix, surface, points positifs/négatifs récurrents).
- **Carte Interactive** : Visualisation géographique de toutes les annonces actives et nouvelles.
- **Interface Premium** : Design sombre moderne, cartes descriptives, carrousels de photos et bouton de suppression avec confirmation sécurisée (slide).

---

## ✨ Démonstration des fonctionnalités

L'application est conçue pour optimiser la recherche collaborative. Voici un aperçu des fonctionnalités principales :

### 📥 1. Importation d'Annonces Haute Qualité
Importez des annonces actives de **LeBonCoin** et **SeLoger**. Le scraper récupère automatiquement les titres, descriptions, prix, surfaces et photos haute résolution.

![Tableau de Bord avec Annonces](static/media/demo/demo_dashboard.png)
*État initial du tableau de bord après l'importation de 4 annonces.*

### 🤖 2. Recherches Automatiques & Scraping Planifié
Configurez vos URLs de recherche dans la vue **"Prêt à Rechercher"** (plateforme + critères + URL). Le planificateur scrappe automatiquement toutes les recherches configurées chaque heure entre 6h et 22h30. Les nouvelles annonces apparaissent dans **"Recherches Automatiques"**, affichant la plateforme source et les critères comme deux premières colonnes. Un bouton **"Forcer la recherche"** permet de déclencher un cycle complet instantanément.

### 📸 3. Galerie Photo Interactive
La page de détail comprend un carrousel réactif et une galerie "lightbox" premium pour une vue immersive des biens.

![Démo Galerie Photo](static/media/demo/demo_gallery.png)

*Démonstration interactive du carrousel et de la galerie.*

### 👥 4. Système d'Avis Collaboratif
L'application permet à plusieurs examinateurs (ex: **Jean DUPONT** et **Marie MARTIN**) de donner des avis indépendants, des notes et des remarques sur chaque bien.

![Démo Avis Collaboratifs](static/media/demo/demo_reviews.png)

*Ajout d'avis collaboratifs et attribution de notes.*

### 🌟 5. Profil Dynamique "Bien Idéal"
L'application synthétise automatiquement tous les avis bien notés pour créer le profil de votre "Bien Idéal", soulignant les points positifs et négatifs récurrents.

![Profil Bien Idéal](static/media/demo/demo_ideal_profile.png)

*Synthèse dynamique des avis en un profil de 'Correspondance Parfaite'.*

### 🛡️ 6. Suppression Sécurisée par "Glisser pour Supprimer"
Pour éviter les suppressions accidentelles, l'interface utilise une interaction premium de glissement pour confirmer.

![Démo Suppression](static/media/demo/demo_deletion.webp)

*Démonstration de la fonctionnalité sécurisée de glissement pour supprimer.*

### 🔔 7. Alerte de Nouvelle Version
Une bannière s'affiche automatiquement en bas de l'écran d'accueil lorsqu'une nouvelle version du code source est disponible sur GitHub.

![Démo Alerte de Version](static/media/demo/demo_alert_banner.png)

*Aperçu de la bannière indiquant une mise à jour disponible.*

## 🛠️ Installation & Lancement

### Prérequis
- Python 3.10+
- Une instance [Browserless](https://www.browserless.io/) (ou Docker, qui l'intègre automatiquement) pour le scraping complet.

### Installation Locale
1. **Cloner le projet**
2. **Créer un environnement virtuel** :
   ```bash
   python -m venv venv
   .\venv\Scripts\activate  # Windows
   ```
3. **Installer les dépendances** :
   ```bash
   pip install -r requirements.txt
   ```
4. **Configurer l'environnement** :
   ```bash
   cp .env.example .env
   ```
5. **Lancer le serveur** :
   ```bash
   python -m uvicorn app.main:app --reload
   ```
   L'application est accessible sur [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## 🐳 Utilisation avec Docker

Le projet est entièrement containerisé, incluant automatiquement le moteur de scraping **Browserless**. Une image pré-construite est disponible sur [Docker Hub](https://hub.docker.com/repository/docker/wikijm/immo-boussole/general) et est mise à jour automatiquement après chaque modification du code via [GitHub Actions](.github/workflows/docker-publish.yml).

1. **Lancer l'ensemble des services** :
   Vous pouvez soit construire l'image localement, soit utiliser l'image pré-construite de Docker Hub :

   - **Depuis les sources (construction locale)** :
     ```bash
     docker compose up -d --build immo-boussole
     ```
   - **Depuis Docker Hub (image pré-construite)** :
     ```bash
     docker compose -f docker-compose.hub.yml up -d
     ```

   > [!TIP]
   > Pour mettre à jour l'application après une modification de code (en construction locale), relancez simplement :
   > `docker compose up -d --build immo-boussole`
   > L'image sera mise à jour avec vos changements, mais **vos données (base de données et photos) resteront intactes** grâce aux volumes persistants.

2. **Accès** : L'interface est disponible sur [http://localhost:8000](http://localhost:8000).

3. **Persistance** : La base de données et les médias sont stockés dans des volumes nommés (`immo-boussole-db` et `immo-boussole-media`).

### 🌐 Déploiement Avancé (Portainer & Cloudflared)

Pour une mise en production sécurisée sur un serveur distant, vous pouvez utiliser **Portainer** pour gérer vos conteneurs et **Cloudflared** (Tunnels Cloudflare Zero Trust) pour exposer l'application sur Internet de manière sécurisée sans ouvrir de ports.

👉 **Consultez le guide détaillé : [Installation via Docker, Portainer et Cloudflared](INSTALL_Docker+Portainer+Cloudflared.fr.md)**

---

## ⚙️ Configuration de l'environnement

Variables clés dans `.env` :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `SECRET_KEY` | *(requis)* | Clé de chiffrement des sessions. À changer en production. |
| `DATABASE_URL` | `sqlite:///./immo_boussole.db` | Chemin vers la base de données SQLite. |
| `BROWSERLESS_URL` | `ws://localhost:3000` | URL WebSocket du navigateur headless. |
| `BROWSERLESS_TOKEN` | *(vide)* | Token d'authentification optionnel pour Browserless. |
| `SCRAPING_SCHEDULE` | `"Toutes les heures, de 6h à 22h30"` | **Libellé lisible** du planning cron, affiché dans l'interface à côté du bouton "Forcer la recherche". |
| `GEORISQUES_API_KEY` | *(optionnel)* | Clé API pour le service de données de risques Géorisques. |
| `APP_VERSION` | `1.1.1-dev` | Version affichée dans le pied de page de la barre latérale. |

---

## 🔒 Sécurité & Authentification

L'accès à l'application est protégé par un système d'authentification multi-utilisateur avec des rôles.

- **Configuration Initiale** : Au premier démarrage, l'application redirige vers `/setup-admin` pour créer le compte administrateur principal.
- **Session** : Les sessions sont sécurisées via une `SECRET_KEY` (générée automatiquement ou à définir dans `.env`).
- **Contrôle d'Accès** : Toute tentative d'accès non authentifiée redirige vers la page de connexion.

---

## 👥 Rôles Utilisateurs & Permissions

Le système distingue deux rôles principaux :

- **ADMIN** :
  - Accès à l'interface de **Gestion des Utilisateurs** (`/admin/users`).
  - Capacité à créer et supprimer des comptes utilisateurs.
  - **Restriction** : Ne peut pas importer ou scraper de nouvelles annonces (afin de se concentrer sur la gestion).
- **USER** :
  - Accès complet à la recherche et à l'évaluation des biens.
  - Capacité à importer des annonces via URL ou saisie manuelle.
  - Accès au planificateur de recherches automatiques et au bouton "Forcer la recherche".
  - **Restriction** : Aucun accès au panneau d'administration.

---

## 📖 Guide d'Utilisation

1. **Ajouter un bien** : Cliquez sur "+ Ajouter une annonce" et collez l'URL LeBonCoin ou SeLoger.
2. **Configurer les recherches auto** : Allez dans **"Prêt à Rechercher"** et ajoutez une plateforme + critères + URL. Le planificateur la scrappe automatiquement toutes les heures (6h–22h30).
3. **Consulter les nouvelles annonces** : Ouvrez **"Recherches Automatiques"** pour voir, importer ou rejeter les biens nouvellement découverts. Utilisez **"Forcer la recherche"** pour déclencher un cycle immédiat.
4. **Évaluer** : Cliquez sur une carte pour voir les détails, puis remplissez votre section.
5. **Supprimer** : Sur le tableau de bord, cliquez sur la corbeille d'une carte et faites glisser le curseur pour confirmer.
6. **Profil Idéal** : Consultez la synthèse globale via le menu latéral pour voir quel type de bien vous correspond le mieux.

## 🔌 Documentation de l'API (REST)

L'application expose une API REST complète construite avec **FastAPI**. Tous les endpoints nécessitent une authentification (session active) et retournent un code HTTP 401 en cas d'accès non autorisé.

### Annonces (Listings)
- `GET /api/listings` : Liste des annonces (filtres optionnels : `status`, `source`, `limit`).
- `GET /api/listings/{listing_id}` : Détails complets d'une annonce.
- `POST /api/listings/submit-url` : Ajoute une annonce via URL (lance le scraping).
- `POST /api/listings/{listing_id}/rescrape` : Relance le scraping d'une annonce existante.
- `PUT /api/listings/{listing_id}` : Mise à jour manuelle des attributs d'une annonce.
- `DELETE /api/listings/{listing_id}` : Supprime une annonce et ses avis.
- `POST /api/listings/{listing_id}/import` : Importe une annonce (status → ACTIVE).
- `POST /api/listings/{listing_id}/reject` : Rejette une annonce (status → REJECTED).
- `POST /api/listings/{listing_id}/photos` : Importe des photos depuis des URLs.
- `POST /api/listings/{listing_id}/photos/upload` : Upload direct de photos (Multipart Form).

### Recherches Automatiques
- `POST /api/searches/force` : **Déclenche immédiatement un cycle complet de scraping** en arrière-plan.

### Recherches Prêtes (Ready Searches)
- `POST /api/searches/ready` : Ajoute une nouvelle recherche (plateforme, critères, URL).
- `PUT /api/searches/ready/{id}` : Met à jour une recherche existante.
- `DELETE /api/searches/ready/{id}` : Supprime une recherche.

### Administration (Admin uniquement)
- `GET /admin/users` : Interface de gestion des utilisateurs.
- `POST /api/admin/users` : Crée un nouveau compte utilisateur.
- `DELETE /api/admin/users/{user_id}` : Supprime un compte utilisateur.

### Avis (Reviews)
- `GET /api/listings/{listing_id}/reviews` : Liste tous les avis d'une annonce.
- `POST /api/listings/{listing_id}/reviews` : Ajoute ou met à jour un avis collaboratif.
- `PUT /api/reviews/{review_id}` : Modifie un avis existant.
- `DELETE /api/reviews/{review_id}` : Supprime un avis.

### Profil Idéal
- `GET /api/profile/ideal` : Retourne la synthèse dynamique du bien idéal.

L'API est entièrement documentée et testable via l'interface Swagger intégrée sur [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## 🏗️ Structure du Projet

- `app/` : Logique backend (scrapers, modèles, services API, planificateur).
  - `main.py` : Routes FastAPI et point d'entrée de l'application.
  - `models.py` : Modèles ORM SQLAlchemy (Listing, ReadySearch, SearchQuery, …).
  - `services.py` : Logique métier de scraping et création d'annonces.
  - `scheduler.py` : Jobs cron APScheduler (toutes les heures, 6h–22h30).
  - `database.py` : Moteur DB, fabrique de sessions et migrations automatiques.
- `templates/` : Pages HTML (Jinja2).
- `static/` : Assets CSS et médias téléchargés (photos des annonces).
- `locales/` : Fichiers JSON d'internationalisation (`fr.json`, `en.json`).
- `tests/` : Scripts de tests unitaires et d'intégration.
- `Dockerfile` & `docker-compose.yml` : Configuration Docker.
- `immo_boussole.db` : Base de données SQLite (gérée automatiquement).
- `.ai/` : Documentation spécialisée et contexte lié à l'IA.

## 🧪 Tests

Le projet inclut un framework de tests complet pour assurer la stabilité :

- **Lancer tous les tests** : `python tests/run_tests.py`
- **Mode CI (Rapide)** : `python tests/run_tests.py --ci`
- **CI Automatisée** : Gérée via GitHub Actions à chaque push ou déclenchement manuel.

Une documentation détaillée est disponible dans [.ai/TESTING.md](.ai/TESTING.md).

## 🏗️ Stack Technique
- **Backend** : FastAPI (Python 3.12)
- **Database** : SQLite + SQLAlchemy (Migrations automatiques incluses, sans Alembic)
- **Scraping** : Playwright + Browserless / BeautifulSoup4 / HTTPX
- **Scrapers additionnels** : Figaro et LogicImmo adaptés depuis le projet [French-eState-Scrapper](https://github.com/Web3-Serializer/French-eState-Scrapper)
- **Frontend** : HTML5 / Vanilla CSS / Jinja2
- **Planificateur** : APScheduler avec `CronTrigger` (toutes les heures, 6h–22h30)
- **Géo & Risques** : Nominatim (géocodage), OSRM (itinéraires), API Géorisques (données de risques)


## 🚀 Prochaines évolutions

- ✅ Protéger l'accès à tout le site par un mécanisme d'authentification.
- ✅ Créer un système de création de compte d'administrateur au premier démarrage.
- ✅ Créer une interface d'administration.
- ✅ Créer un système de création de compte utilisateur (l'administrateur ne peut pas importer d'annonces).
- ✅ Rendre l'application multilangue (Français et Anglais).
- ✅ Carte interactive des annonces.
- ✅ Recherches automatiques planifiées (toutes les heures, 6h–22h30) depuis les entrées "Prêt à Rechercher".
- ✅ Bouton "Forcer la recherche" pour déclencher un cycle immédiat.
- ✅ Colonnes Plateforme & Critères dans la vue "Recherches Automatiques".
- ⬜ Créer un système de création de compte conseiller immobilier.
- ⬜ Ajouter un système de favoris pour les annonces et les recherches.
- ⬜ Ajouter un système de notifications (email, push, etc.).
- ⬜ Remettre en place le mécanisme de détection de doublons.
