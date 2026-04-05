# 🧭 Immo-Boussole

*Note : Ce projet cible à l'origine les plateformes immobilières françaises pour la recherche de biens. / Note: At its core, this project targets French platforms for property search.*

[English version available here](README.md)

**Immo-Boussole** est une application web collaborative conçue pour centraliser, cataloguer et évaluer les offres immobilières (LeBonCoin, SeLoger) de manière structurée.

![Tableau de Bord](static/media/demo/exemple_tableaudebord.png)
![Tableau des Annonces](static/media/demo/exemple_tableaudesannonces.png)
![Détail Annonce](static/media/demo/exemple_annonce.png)


## 🚀 Fonctionnalités Clés

- **Scraping Intelligent** : Extraction automatique des détails (prix, surface, DPE, taxes, charges, photos) depuis plus de 10 plateformes :
  - LeBonCoin, SeLoger, Le Figaro Immobilier, LogicImmo, BienIci, IAD France, Immobilier Notaires, Vinci Immobilier, Immobilier France.
- **Gestion Locale des Médias** : Les photos sont téléchargées et servies localement pour éviter les liens morts.
- **Avis Collaboratifs** : Système de notation et de commentaires séparés.
- **Fiche Bien Idéal** : Génération d'un profil dynamique basé sur les annonces les mieux notées (moyennes de prix, surface, points positifs/négatifs récurrents).
- **Interface Premium** : Design sombre moderne, cartes descriptives, carrousels de photos et bouton de suppression avec confirmation sécurisée (slide).

---

## ✨ Démonstration des fonctionnalités

L'application est conçue pour optimiser la recherche collaborative. Voici un aperçu des fonctionnalités principales :

### 📥 1. Importation d'Annonces Haute Qualité
Importez des annonces actives de **LeBonCoin** et **SeLoger**. Le scraper récupère automatiquement les titres, descriptions, prix, surfaces et photos haute résolution.

![Tableau de Bord avec Annonces](static/media/demo/demo_dashboard.png)
*État initial du tableau de bord après l'importation de 4 annonces.*

### 📸 2. Galerie Photo Interactive
La page de détail comprend un carrousel réactif et une galerie "lightbox" premium pour une vue immersive des biens.

![Démo Galerie Photo](static/media/demo/demo_gallery.png)

*Démonstration interactive du carrousel et de la galerie.*

### 👥 3. Système d'Avis Collaboratif
L'application permet à plusieurs examinateurs (ex: **Jean DUPONT** et **Marie MARTIN**) de donner des avis indépendants, des notes et des remarques sur chaque bien.

![Démo Avis Collaboratifs](static/media/demo/demo_reviews.png)

*Ajout d'avis collaboratifs et attribution de notes.*

### 🌟 4. Profil Dynamique "Bien Idéal"
L'application synthétise automatiquement tous les avis bien notés pour créer le profil de votre "Bien Idéal", soulignant les points positifs et négatifs récurrents.

![Profil Bien Idéal](static/media/demo/demo_ideal_profile.png)

*Synthèse dynamique des avis en un profil de 'Correspondance Parfaite'.*

### 🛡️ 5. Suppression Sécurisée par "Glisser pour Supprimer"
Pour éviter les suppressions accidentelles, l'interface utilise une interaction premium de glissement pour confirmer.

![Démo Suppression](static/media/demo/demo_deletion.webp)

*Démonstration de la fonctionnalité sécurisée de glissement pour supprimer.*

### 🔔 6. Alerte de Nouvelle Version
Une bannière s'affiche automatiquement en bas de l'écran d'accueil lorsqu'une nouvelle version du code source est disponible sur GitHub. Ce mécanisme compare discrètement le hash du commit local avec celui de la branche principale afin de toujours vous informer des dernières fonctionnalités et mises à jour.

![Démo Alerte de Version](static/media/demo/demo_alert_banner.png)

*Aperçu de la bannière indiquant une mise à jour disponible.*

## 🛠️ Installation & Lancement

### Prérequis
- Python 3.10+
- [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) lancé localement (port 8191 par défaut) pour le scraping.

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

Le projet est entièrement containerisé, incluant automatiquement le moteur de scraping **FlareSolverr**.

1. **Lancer l'ensemble des services** :
   ```bash
   docker compose up -d --build immo-boussole
   ```
   Cette commande construit (ou reconstruit) l'image à partir du code source local et lance deux conteneurs : `immo-boussole` (l'application) et `flaresolverr` (le bypass Cloudflare).

   > [!TIP]
   > Pour mettre à jour l'application après une modification de code, relancez simplement cette même commande :
   > `docker compose up -d --build immo-boussole`
   > L'image sera mise à jour avec vos changements, mais **vos données (base de données et photos) resteront intactes** grâce aux volumes persistants.

2. **Accès** : L'interface est disponible sur [http://localhost:8000](http://localhost:8000).

3. **Gestion des Captchas (Optionnel)** :
   Si vous rencontrez des blocages par captcha lors du scraping, vous pouvez activer le solver [2Captcha](https://2captcha.com/) :
   - Dans votre fichier `.env`, réglez `CAPTCHA_SOLVER=2captcha`.
   - Renseignez votre clé API dans `TWO_CAPTCHA_API_KEY=votre_cle_ici`.
   - Redémarrez les conteneurs : `docker compose up -d`.

4. **Persistance** : La base de données et les médias sont stockés dans des volumes nommés (`immo-boussole-db` et `immo-boussole-media`).

### 🌐 Déploiement Avancé (Portainer & Cloudflared)

Pour une mise en production sécurisée sur un serveur distant, vous pouvez utiliser **Portainer** pour gérer vos conteneurs et **Cloudflared** (Tunnels Cloudflare Zero Trust) pour exposer l'application sur Internet de manière sécurisée sans ouvrir de ports.

👉 **Consultez le guide détaillé : [Installation via Docker, Portainer et Cloudflared](INSTALL_Docker+Portainer+Cloudflared.fr.md)**

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
  - **Restriction** : Aucun accès au panneau d'administration.

---

## 📖 Guide d'Utilisation

1. **Ajouter un bien** : Cliquez sur "+ Ajouter une annonce" et collez l'URL LeBonCoin ou SeLoger.
2. **Évaluer** : Cliquez sur une carte pour voir les détails, puis remplissez votre section.
3. **Supprimer** : Sur le tableau de bord, cliquez sur la corbeille d'une carte et faites glisser le curseur pour confirmer.
4. **Profil Idéal** : Consultez la synthèse globale via le menu latéral pour voir quel type de bien vous correspond le mieux.

## 🔌 Documentation de l'API (REST)

L'application expose une API REST complète construite avec **FastAPI**. Tous les endpoints nécessitent une authentification (session active) et retournent un code HTTP 401 en cas d'accès non autorisé.

### Annonces (Listings)
- `GET /api/listings` : Récupère la liste des annonces (filtres de recherche optionnels : `status`, `source`, `limit`).
- `GET /api/listings/{listing_id}` : Récupère les détails complets d'une annonce spécifique.
- `POST /api/listings/submit-url` : Ajoute une nouvelle annonce via une URL (lance automatiquement le scraping). Accepte `url` et `skip_scraping` (booléen) en JSON.
- `POST /api/listings/{listing_id}/rescrape` : Relance le scraping manuel pour mettre à jour une annonce existante.
- `PUT /api/listings/{listing_id}` : Met à jour manuellement les attributs d'une annonce (titre, prix, surface, DPE, etc.).
- `DELETE /api/listings/{listing_id}` : Supprime une annonce et ses avis associés.
- `POST /api/listings/{listing_id}/photos` : Importe de nouvelles photos à partir d'une liste d'URLs.
- `POST /api/listings/{listing_id}/photos/upload` : Télécharge directement des photos (Multipart Form).

### Administration (Admin uniquement)
- `GET /admin/users` : Interface de gestion des utilisateurs.
- `POST /api/admin/users` : Crée un nouveau compte utilisateur (Corps JSON : `username`, `password`, `role`).
- `DELETE /api/admin/users/{user_id}` : Supprime un compte utilisateur (empêche l'auto-suppression).

### Avis (Reviews)
- `GET /api/listings/{listing_id}/reviews` : Liste tous les avis laissés sur une annonce.
- `POST /api/listings/{listing_id}/reviews` : Ajoute ou met à jour un avis collaboratif (notes, positifs, négatifs).
- `PUT /api/reviews/{review_id}` : Modifie un avis spécifique existant.
- `DELETE /api/reviews/{review_id}` : Supprime un avis existant.

### Profil Idéal
- `GET /api/profile/ideal` : Retourne la synthèse dynamique du bien idéal, calculée à partir des annonces les mieux notées.

### Recherches Enregistrées (Queries)
- `GET /api/queries` : Retourne la liste des recherches automatiques planifiées.
- `POST /api/queries` : Ajoute une nouvelle recherche à planifier (URL, nom, source).

L'API est également entièrement documentée et testable via l'interface Swagger intégrée, accessible sur [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (ou `/redoc`) lorsque l'application est lancée.

## 🏗️ Structure du Projet

- `app/` : Logique backend (scrapers, modèles, services API).
- `templates/` : Pages HTML (Jinja2).
- `static/` : Assets CSS et médias téléchargés (photos des annonces).
- `tests/` : Scripts de tests unitaires et d'intégration.
- `debug/` : Outils de débogage et logs de scraping temporaires.
- `Dockerfile` & `docker-compose.yml` : Configuration Docker.
- `immo_boussole.db` : Base de données SQLite (gérée automatiquement).

## 🏗️ Stack Technique
- **Backend** : FastAPI (Python)
- **Database** : SQLite + SQLAlchemy (Migrations automatiques incluses)
- **Scraping** : FlareSolverr / BeautifulSoup4 / HTTPX
- **Scrapers additionnels** : Figaro et LogicImmo adaptés depuis le projet [French-eState-Scrapper](https://github.com/Web3-Serializer/French-eState-Scrapper)
- **Frontend** : HTML5 / Vanilla CSS / Jinja2
- **Scheduler** : APScheduler (pour les recherches automatiques)


## 🚀 Prochaines évolutions

- ✅ Protéger l'accès à tout le site par un mécanisme d'authentification.
- ✅ Créer un système de création de compte d'administrateur au premier démarrage.
- ✅ Créer une interface d'administration.
- ✅ Créer un système de création de compte utilisateur (au moins un compte utilisateur par défaut, l'administrateur ne devrait pas pouvoir importer d'annonces).
- ⬜ Créer un système de création de compte conseiller immobilier (possibilité de regarder les annonces importées dans l'application, et les retours faits par les utilisateurs, ainsi que la la fiche de bien idéal).
- ⬜ Ajouter un système de favoris pour les annonces.
- ⬜ Ajouter un système de favoris pour les recherches.
- ✅ Rendre l'application multilangue (Français et Anglais).
- ⬜ Ajouter un système de notifications (email, push, etc.).
- ⬜ Remettre en place le mécanisme de détection de doublons (alerte si un bien similaire est déjà présent).
