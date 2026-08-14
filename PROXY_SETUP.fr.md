# 🏠 Guide : Déploiement d'un Proxy Résidentiel à Domicile (Synology NAS / Docker + Cloudflared)

Ce guide détaille comment créer un proxy résidentiel sécurisé chez vous (sur un **NAS Synology**, un Raspberry Pi ou un serveur domestique) et l'exposer de manière chiffrée via un **Cloudflare Tunnel**, afin de contourner les blocages anti-bots stricts (DataDome sur LeBonCoin, etc.) subis par les serveurs VPS (OVH, Hetzner, AWS...).

---

## 💡 Principe de fonctionnement

Les sites comme **LeBonCoin** bloquent systématiquement les adresses IP de datacenters. En faisant transiter les requêtes de scraping par votre connexion internet personnelle, vous bénéficiez de la réputation naturelle de votre adresse IP résidentielle.

Cloudflare bloque les requêtes proxy HTTPS classiques (`CONNECT`) sur les tunnels web standards. Pour contourner cela, nous utilisons **GOST (Go Simple Tunnel)** qui encapsule le flux proxy dans une connexion **WebSocket chiffrée (WSS)** avec authentification.

```mermaid
graph LR
    subgraph VPS OVH (Immo-Boussole)
        App[Browserless / Playwright] -->|Proxy HTTP local| GostClient[gost-client :1080]
    end
    subgraph Cloudflare
        GostClient -->|Tunnel WSS chiffré| CF[Cloudflare Tunnel]
    end
    subgraph Domicile (Synology NAS)
        CF -->|WebSocket local| GostServer[gost-server :8080]
        GostServer -->|Scraping résidentiel| LBC[LeBonCoin / Internet]
    end
```

---

## 🚀 Étape 1 : Créer le Tunnel Cloudflare (Gratuit)

1. Rendez-vous sur votre tableau de bord [Cloudflare Zero Trust](https://one.dash.cloudflare.com/).
2. Allez dans **Networks** > **Tunnels** > **Add a tunnel**.
3. Choisissez **Cloudflared** et donnez un nom à votre tunnel (ex: `immo-proxy-home`).
4. Récupérez le **Token du Tunnel** (la longue chaîne de caractères fournie lors de l'étape de configuration).
5. Dans l'onglet **Public Hostnames**, ajoutez une route :
   * **Subdomain :** `proxy` (ou le sous-domaine de votre choix, ex: `proxy.mon-domaine.fr`)
   * **Domain :** votre domaine Cloudflare
   * **Type :** `HTTP`
   * **URL :** `gost-server:8080` (nom du service docker ci-dessous)

---

## 📦 Étape 2 : Déployer le Proxy à Domicile (Un seul `docker-compose.yml`)

Sur votre **NAS Synology** (via *Container Manager* > *Projets* > *Créer*), ou sur tout serveur Linux local, créez un dossier `immo-proxy` avec ce fichier `docker-compose.yml` :

```yaml
version: "3.8"

services:

  # ── Serveur Proxy Gost (Encapsulation WebSocket avec Auth) ──────────────────
  gost-server:
    image: gogost/gost:latest
    container_name: immo-gost-server
    restart: always
    command: ["-L", "http+ws://admin:mon_mot_de_passe_secret@:8080"]
    networks:
      - proxy-net

  # ── Tunnel Cloudflared (Exposition sécurisée sans ouvrir de ports) ──────────
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: immo-proxy-tunnel
    restart: always
    command: ["tunnel", "--no-autoupdate", "run", "--token", "${TUNNEL_TOKEN}"]
    networks:
      - proxy-net
    depends_on:
      - gost-server

networks:
  proxy-net:
    name: immo-proxy-net
```

Créez le fichier `.env` à côté du `docker-compose.yml` :
```bash
# Token Cloudflare Tunnel récupéré à l'étape 1
TUNNEL_TOKEN=eyJhIjoi...votre_token_cloudflare...
```

> [!TIP]
> Pensez à remplacer `admin:mon_mot_de_passe_secret` dans la commande Gost par vos propres identifiants.

Lancez le projet :
```bash
docker compose up -d
```

---

## ⚙️ Étape 3 : Configuration côté Immo-Boussole (VPS)

### 1. Renseigner l'URL du tunnel sur le VPS

Dans le fichier `.env` d'Immo-Boussole sur votre VPS (`/opt/immo-boussole/dev/.env` ou `/opt/immo-boussole/prod/.env`) :

```bash
# Connexion WebSocket vers votre sous-domaine Cloudflare
GOST_UPSTREAM_URL="wss://admin:mon_mot_de_passe_secret@proxy.mon-domaine.fr"
```

Redémarrez les conteneurs :
```bash
sudo docker compose up -d
```

### 2. Configurer la chaîne dans l'interface Immo-Boussole

1. Ouvrez Immo-Boussole et connectez-vous en tant qu'administrateur.
2. Allez dans **Maintenance & Système** > section **Routage & Chaînes de Proxys**.
3. Sélectionnez **LeBonCoin** (ou **Par défaut**).
4. Définissez la chaîne :
   * Étape 1 : `direct` *(essaie toujours le VPS en premier)*
   * Étape 2 : `http://gost-client:1080` *(relais vers votre proxy à domicile)*
5. Cliquez sur **Enregistrer les chaînes de proxy**.

---

## 🛡️ Fonctionnement du Routage Dynamique

* **Étape 1 (Direct)** : Immo-Boussole tente d'abord de scraper directement depuis le VPS.
* **Étape 2 (Bascule automatique)** : Si un blocage DataDome (statut 403 / captcha) est détecté, Immo-Boussole bascule immédiatement sur votre proxy à domicile sans interrompre la tâche.
* **Étape 3 (Bascule persistante)** : Si la route directe échoue 3 fois de suite, le proxy à domicile est promu comme route par défaut pour les lancements suivants afin de préserver les performances.
