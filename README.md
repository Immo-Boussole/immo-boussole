# 🧭 Immo-Boussole

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
   # Renseigner votre SCRAPINGBEE_API_KEY (optionnel) ou ajuster FLARESOLVERR_URL
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

### 🌐 Déploiement Avancé (Portainer & Cloudflare)

Pour une mise en production sécurisée sur un serveur distant, vous pouvez utiliser **Portainer** pour gérer vos conteneurs et **Cloudflared** (Tunnels Cloudflare Zero Trust) pour exposer l'application sur Internet de manière sécurisée sans ouvrir de ports.

👉 **Consultez le guide détaillé : [Installation via Docker, Portainer et Cloudflared](INSTALL_Docker+Portainer+Cloudflared.md)**

---

## 🔒 Sécurité & Authentification

L'accès à l'ensemble du site est protégé par un mécanisme d'authentification par mot de passe partagé.

- **Configuration** : Définissez votre mot de passe dans le fichier `.env` via la variable `APP_PASSWORD`.
- **Session** : Les sessions sont sécurisées via une `SECRET_KEY` (générée automatiquement lors de l'installation ou à définir dans `.env`).
- **Fonctionnement** : Toute tentative d'accès non authentifiée redirige vers la page de connexion. Un bouton "Déconnexion" est disponible dans le menu latéral pour fermer la session.

---

## 📖 Guide d'Utilisation

1. **Ajouter un bien** : Cliquez sur "+ Ajouter une annonce" et collez l'URL LeBonCoin ou SeLoger.
2. **Évaluer** : Cliquez sur une carte pour voir les détails, puis remplissez votre section.
3. **Supprimer** : Sur le tableau de bord, cliquez sur la corbeille d'une carte et faites glisser le curseur pour confirmer.
4. **Profil Idéal** : Consultez la synthèse globale via le menu latéral pour voir quel type de bien vous correspond le mieux.

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
- ⬜ Créer un mécanisme d'alerte en cas de nouvelle version disponible (basée sur un hash du code source hébergé sur GitHub).
- ⬜ Créer une interface d'administration.
- ⬜ Créer un système de création de compte utilisateur (au moins un compte utilisateur par défaut, l'administrateur ne devrait pas pouvoir importer d'annonces).
- ⬜ Ajouter un système de favoris pour les annonces.
- ⬜ Ajouter un système de favoris pour les recherches.
- ⬜ Rendre l'application multilangue (Français et Anglais).
- ⬜ Ajouter un système de notifications (email, push, etc.).
- ⬜ Remettre en place le mécanisme de détection de doublons (alerte si un bien similaire est déjà présent).