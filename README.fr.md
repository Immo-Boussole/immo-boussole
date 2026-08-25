# 🧭 Immo-Boussole

[![Build and Push Docker Image](https://github.com/Immo-Boussole/immo-boussole/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Immo-Boussole/immo-boussole/actions/workflows/docker-publish.yml)
[![Docker Hub](https://img.shields.io/badge/docker-hub-blue.svg?logo=docker&logoColor=white)](https://hub.docker.com/repository/docker/wikijm/immo-boussole/general)
[![Image Docker](https://img.shields.io/badge/image-wikijm%2Fimmo-boussole%3A02bec0caeabbc82c597c1439940f4a13bee12f13-0db7ed?logo=docker&logoColor=white)](https://hub.docker.com/r/wikijm/immo-boussole)
[![Documentation Wiki](https://img.shields.io/badge/docs-GitHub%20Wiki-blue?logo=github)](https://github.com/Immo-Boussole/immo-boussole/wiki)

> 🧭 **Organisation Immo-Boussole** : [Application Web](https://github.com/Immo-Boussole/immo-boussole) • [Extension Web](https://github.com/Immo-Boussole/immo-boussole-extension) • [Orchestrateur](https://github.com/Immo-Boussole/immo-boussole-orchestrator) • [Wiki Central](https://github.com/Immo-Boussole/immo-boussole/wiki)

---

## 🌐 Langues

- 🇬🇧 [English (Default)](README.md)
- 🇫🇷 [Français](README.fr.md)

---

**Immo-Boussole** est une application web collaborative moderne conçue pour centraliser, cataloguer, évaluer et suivre les offres immobilières sur plus de 10 plateformes (LeBonCoin, SeLoger, BienIci, LogicImmo, Le Figaro, etc.) de façon fluide et structurée.

---

## 📸 Aperçu de l'interface

| Tableau de bord | Liste des annonces | Fiche détaillée |
|---|---|---|
| ![Tableau de Bord](static/media/demo/exemple_tableaudebord.png) | ![Tableau des Annonces](static/media/demo/exemple_tableaudesannonces.png) | ![Détail Annonce](static/media/demo/exemple_annonce.png) |

---

## 🚀 Fonctionnalités Clés

* **Scraping Multi-Plateformes Intelligent** : Extraction automatisée des prix, surfaces, DPE, taxes foncières, charges, géolocalisations et photos haute résolution sur plus de 11 plateformes :
  * *LeBonCoin, SeLoger, Le Figaro Immobilier, LogicImmo, BienIci, IAD France, Immobilier Notaires, Vinci Immobilier, Immobilier France, Provimo, Hektor (Ma-Boîte-Immo, Immo-Rêve).*
* **Recherches Automatiques Planifiées** : Planificateur d'arrière-plan exécuté toutes les heures de 6h à 22h30 pour scraper vos recherches configurées ("Prêt à Rechercher").
* **Forcer la Recherche Immédiate** : Déclenchez un cycle de scraping complet à la demande sans attendre l'heure planifiée.
* **Stockage Local des Médias** : Photos téléchargées et servies en local pour garantir l'absence de liens cassés.
* **Avis Collaboratifs & Notes** : Notes individuelles multi-utilisateurs, critères d'évaluation, avantages et inconvénients pour chaque bien.
* **Synthèse IA "Bien Idéal"** : Profil dynamique calculé à partir des meilleures annonces pour révéler vos critères clés et points de vigilance.
* **Vue Carte Interactive** : Visualisation cartographique géographique des annonces actives, importées et nouvellement trouvées.
* **Assistant IA & Protocole MCP** : Assistant conversationnel intégré (Ollama) et serveur Model Context Protocol (MCP) pour vos outils LLM externes (Claude Desktop).
* **Intégrations Google** : Synchronisation des visites avec Google Calendar et des contacts d'agences avec Google Contacts.
* **Sauvegarde & Restauration** : Module administrateur pour exporter et réimporter l'intégralité de la base de données et des photos en un clic (archive ZIP).

## 📱 Vues de l'Application & Modules Fonctionnels

Immo-Boussole intègre 20 vues spécialisées réparties en 6 domaines fonctionnels :

### 1. 🏠 Catalogue Immobilier & Évaluation des Biens
| Route | Nom de la Vue | Description |
|---|---|---|
| `/` | **Tableau de bord** | Synthèse globale avec indicateurs KPI, flux des nouvelles annonces, suivi des baisses de prix et filtres de statut |
| `/listings/table` | **Tableau des annonces** | Grille haute densité triable avec filtres multicritères, personnalisation des colonnes et actions groupées |
| `/listing/{id}` | **Fiche détaillée** | Dossier complet avec galerie haute résolution, jauges DPE/GES, calculs financiers, fiche agence, références cadastrales avec lien officiel DVF (explore.data.gouv.fr), widget Géorisques, pièces jointes, avis collaboratifs et prise de rendez-vous |
| `/a-voir` | **À voir** | Boîte de réception dédiée au tri des annonces importées non encore qualifiées |
| `/a-visiter` | **À visiter** | Présélection des biens prioritaires retenus pour des visites physiques |

### 2. 👥 Collaboration, Contacts & Agenda
| Route | Nom de la Vue | Description |
|---|---|---|
| `/contacts` | **Gestionnaire de contacts** | Annuaire des agences, négociateurs, notaires et vendeurs avec synchronisation Google Contacts |
| `/visites` | **Gestionnaire de visites** | Planification des visites, comptes-rendus post-visite, photos de visite, suivi des offres et synchro Google Calendar |

### 3. 🗺️ Intelligence Géospatiale & Trajets
| Route | Nom de la Vue | Description |
|---|---|---|
| `/carte` | **Carte interactive** | Carte plein écran Leaflet avec regroupement en clusters, heatmaps, statuts colorés et calques de commodités |
| `/zones` | **Gestion des zones** | Éditeur cartographique de polygones et rayons pour définir vos zones recherchées ou secteurs interdits |
| `/distance-temps` | **Distance & Temps** | Matrice d'estimation des temps de trajet (voiture, transports, vélo) vers vos lieux du quotidien |
| `/points-interet` | **Points d'intérêt** | Scanner de proximité (OpenStreetMap Overpass API) mesurant les distances aux gares, écoles et commerces |

### 4. 🤖 IA & Sourcing Automatisé
| Route | Nom de la Vue | Description |
|---|---|---|
| `/profile/ideal` | **Profil Idéal IA** | Modélisation IA de vos critères clés et calcul d'un score d'adéquation (0-100%) sur chaque annonce |
| `/chat` | **Assistant IA** | Assistant conversationnel (Ollama) pour interroger, comparer et résumer le catalogue en langage naturel |
| `/searches/ready` | **Recherches Prêtes** | Bibliothèque d'URL de recherche multi-portails avec déclenchement immédiat à la demande |
| `/searches/auto` | **Recherches Automatiques** | Moteur de scraping planifié toutes les heures (6h-22h30) avec gestion des proxies et journaux |

### 5. 🔍 Qualité des Données & Maintenance
| Route | Nom de la Vue | Description |
|---|---|---|
| `/duplicates/hunt` | **Chasse aux duplicats** | Hachage visuel perceptuel (dHash/pHash) et corrélation floue pour détecter et fusionner les annonces en doublon |
| `/listings/repair` | **Réparations** | Boîte à outils de maintenance : correction du géocodage GPS, réparation d'images et actualisation des anciennes annonces |

### 6. ⚙️ Gestion Utilisateurs, Administration & Paramètres
| Route | Nom de la Vue | Description |
|---|---|---|
| `/admin/users` | **Gestion Utilisateurs** | Gestion des accès, attribution des rôles (Admin/User) et révocation des clés d'API |
| `/admin/maintenance` | **Administration & Maintenance** | Moniteur de proxies, sauvegarde/restauration intégrale en 1 clic (archive ZIP) et gestion des caches |
| `/profile` | **Mon Profil & Sécurité** | Gestion du compte, jetons de connexion Google OAuth (Calendar & Contacts) et clés d'API personnelles |

---

## 📚 Documentation Complète & Guides (GitHub Wiki)

Tous les guides techniques de déploiement, d'administration et de configuration sont réunis sur notre **[Wiki GitHub](https://github.com/Immo-Boussole/immo-boussole/wiki)** :

| Guide / Thème | Description | Lien |
|---|---|---|
| 🧭 **Architecture & Écosystème** | Vue d'ensemble du système (App Principale, Extension Web et Orchestrateur) | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Architecture-Overview-FR) |
| 📱 **Vues & Modules Fonctionnels** | Guide détaillé des 20 vues, pages et fonctionnalités de l'application | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Views-and-Features-FR) |
| 🐳 **Déploiement Docker & Cloudflare** | Mise en production avec Docker Compose, Portainer et les tunnels Cloudflare Zero Trust | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Installation-Docker-FR) |
| 🎛️ **Orchestrateur de Flotte** | Déployer et piloter plusieurs instances sur Docker local et distant | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Orchestrator-Setup-FR) |
| 🧩 **Extension Web (Navigateurs)** | Scraping en 1 clic sur LeBonCoin & Figaro depuis Firefox, Chrome et Edge | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/WebExtension-Setup-FR) |
| 🛡️ **Proxy Résidentiel & Anti-Bot** | Déployer un proxy résidentiel (NAS Synology / Raspberry Pi) pour contourner les blocages DataDome / 403 | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Proxy-Setup-FR) |
| 🤖 **Assistant IA & Serveur MCP** | Connecter Ollama et exposer vos annonces à Claude Desktop via MCP | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/MCP-Setup-FR) |
| 💾 **Sauvegarde & Restauration** | Procédures de backup et restore de la base SQLite et des médias | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Backup-Restore-FR) |
| 🔑 **Configuration Google OAuth2** | Configurer la synchronisation Google Calendar et Google Contacts | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Google-OAuth-Setup-FR) |
| 📐 **Standards de Documentation** | Règles de rédaction, traductions et consignes pour les agents IA | [Consulter le guide](https://github.com/Immo-Boussole/immo-boussole/wiki/Documentation-Standards-FR) |

---

## ⚡ Démarrage Rapide

### 1. Avec Docker (Recommandé)

Immo-Boussole est entièrement conteneurisé et intègre le moteur de scraping sans tête **Browserless**.

#### Utiliser l'image officielle (Docker Hub)
```bash
docker compose -f docker-compose.hub.yml up -d
```

#### Construire depuis les sources
```bash
docker compose up -d --build immo-boussole
```

L'application est immédiatement accessible sur **[http://localhost:8000](http://localhost:8000)**.  
*Les données (base de données et photos) sont conservées en sécurité dans des volumes nommés Docker.*

---

### 2. Développement Local avec Python

#### Prérequis
* Python 3.10+
* Une instance [Browserless](https://www.browserless.io/) ou Chrome en local

```bash
# 1. Cloner le dépôt
git clone https://github.com/Immo-Boussole/immo-boussole.git
cd immo-boussole

# 2. Créer l'environnement virtuel
python -m venv venv
.\venv\Scripts\activate  # Sous Windows (ou source venv/bin/activate sous Linux/macOS)

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env

# 5. Démarrer le serveur
python -m uvicorn app.main:app --reload
```

---

## ⚙️ Configuration de l'environnement

Principales variables configurables dans `.env` :

| Variable | Valeur par défaut | Description |
|---|---|---|
| `SECRET_KEY` | *(requis)* | Clé secrète de signature des sessions et jetons. |
| `DATABASE_URL` | `sqlite:///./immo_boussole.db` | Chaîne de connexion SQLite. |
| `BROWSERLESS_URL` | `ws://localhost:3000` | Endpoint WebSocket du navigateur headless. |
| `BROWSERLESS_TOKEN` | *(vide)* | Jeton d'authentification optionnel pour Browserless. |
| `SCRAPING_SCHEDULE` | `"Toutes les heures, de 6h à 22h30"` | Texte descriptif du planning affiché dans l'UI. |
| `GEORISQUES_API_KEY` | *(optionnel)* | Clé API pour les risques naturels et technologiques français. |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Endpoint pour l'assistant IA Ollama. |
| `OLLAMA_MODEL` | `llama3` | Modèle utilisé pour le chat et l'analyse. |

---

## 🔌 Documentation de l'API & Swagger

Immo-Boussole intègre une API REST complète propulsée par **FastAPI** :

* **Interface interactive Swagger UI** : [http://localhost:8000/docs](http://localhost:8000/docs)
* **Documentation ReDoc** : [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🧪 Tests

Une suite de tests automatisés couvre les endpoints API, le scraping, la base de données et les intégrations :

```bash
# Lancer tous les tests
python tests/run_tests.py

# Mode CI (rapide)
python tests/run_tests.py --ci
```

---

## 🏗️ Stack Technique

* **Backend** : FastAPI (Python 3.12), SQLAlchemy ORM, SQLite, APScheduler, Pydantic v2
* **Scraping & Automatisation** : Playwright, Browserless, BeautifulSoup4, HTTPX
* **Frontend** : HTML5, Vanilla CSS (Design Sombre / Glassmorphism), Templates Jinja2
* **Intégrations** : Google Calendar API, Google People API, MCP (Model Context Protocol), API Géorisques, OpenStreetMap / Nominatim

---

## 📄 Licence

Ce projet est sous licence open-source. Voir le dépôt pour les détails.
