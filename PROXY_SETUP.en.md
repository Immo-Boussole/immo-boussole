# 🏠 Guide: Deploying a Home Residential Proxy (Synology NAS / Docker + Cloudflared)

This guide explains how to deploy a secure residential proxy at home (on a **Synology NAS**, Raspberry Pi, or home server) and expose it encrypted through a **Cloudflare Tunnel**, bypassing strict anti-bot detection (DataDome on LeBonCoin, etc.) commonly triggered on cloud VPS providers (OVH, Hetzner, AWS...).

---

## 💡 How it works

Websites like **LeBonCoin** aggressively block datacenter IP ranges. Routing scraper traffic through your home internet connection allows you to benefit from the natural high reputation of residential IP addresses.

Cloudflare blocks traditional HTTPS proxy requests (`CONNECT`) on standard web tunnels. To overcome this, we use **GOST (Go Simple Tunnel)** to wrap the proxy stream inside an authenticated, encrypted **WebSocket (WSS)** connection.

```mermaid
graph LR
    subgraph Cloud VPS (Immo-Boussole)
        App[Browserless / Playwright] -->|Local HTTP Proxy| GostClient[gost-client :1080]
    end
    subgraph Cloudflare
        GostClient -->|Encrypted WSS Tunnel| CF[Cloudflare Tunnel]
    end
    subgraph Home Network (Synology NAS)
        CF -->|Local WebSocket| GostServer[gost-server :8080]
        GostServer -->|Residential Scraping| LBC[LeBonCoin / Internet]
    end
```

---

## 🚀 Step 1: Create a Free Cloudflare Tunnel

1. Open your [Cloudflare Zero Trust](https://one.dash.cloudflare.com/) dashboard.
2. Go to **Networks** > **Tunnels** > **Add a tunnel**.
3. Select **Cloudflared** and name your tunnel (e.g., `immo-proxy-home`).
4. Copy your **Tunnel Token**.
5. Under **Public Hostnames**, add a route:
   * **Subdomain:** `proxy` (or your preferred subdomain, e.g., `proxy.your-domain.com`)
   * **Domain:** your Cloudflare-managed domain
   * **Type:** `HTTP`
   * **URL:** `gost-server:8080`

---

## 📦 Step 2: Deploy at Home (Single `docker-compose.yml`)

On your **Synology NAS** (via *Container Manager* > *Project* > *Create*), or on any local Docker host, create a folder named `immo-proxy` containing this `docker-compose.yml`:

```yaml
version: "3.8"

services:

  # ── Gost Proxy Server (WebSocket Encapsulation + Auth) ──────────────────────
  gost-server:
    image: gogost/gost:latest
    container_name: immo-gost-server
    restart: always
    command: ["-L", "http+ws://admin:my_secure_password@:8080"]
    networks:
      - proxy-net

  # ── Cloudflared Tunnel (Secure ingress without open ports) ──────────────────
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

Create a `.env` file alongside `docker-compose.yml`:
```bash
# Cloudflare Tunnel Token from Step 1
TUNNEL_TOKEN=eyJhIjoi...your_cloudflare_token...
```

> [!TIP]
> Remember to replace `admin:my_secure_password` in the Gost command with your own credentials.

Start the project:
```bash
docker compose up -d
```

---

## ⚙️ Step 3: Immo-Boussole Configuration (VPS)

### 1. Configure Tunnel URL on VPS

In Immo-Boussole's `.env` file on your VPS (`/opt/immo-boussole/dev/.env` or `/opt/immo-boussole/prod/.env`):

```bash
# WebSocket connection to your Cloudflare tunnel subdomain
GOST_UPSTREAM_URL="wss://admin:my_secure_password@proxy.your-domain.com"
```

Restart your containers:
```bash
sudo docker compose up -d
```

### 2. Configure Proxy Chain in the Immo-Boussole Web UI

1. Log in to Immo-Boussole as an admin.
2. Go to **Maintenance & Système** > **Routage & Chaînes de Proxys**.
3. Select **LeBonCoin** (or **Default**).
4. Set up the chain:
   * Step 1: `direct` *(always attempts VPS first)*
   * Step 2: `http://gost-client:1080` *(relays to your home proxy)*
5. Click **Enregistrer les chaînes de proxy**.

---

## 🛡️ Dynamic Routing Behavior

* **Step 1 (Direct)**: Immo-Boussole always tries scraping directly from the VPS first.
* **Step 2 (Auto Fallback)**: If a DataDome block (status 403 / captcha) is encountered, Immo-Boussole automatically falls back to your home proxy.
* **Step 3 (Persistent Route Promotion)**: If the direct route fails 3 consecutive times, your home proxy is promoted as the new default starting route for subsequent scraper jobs.
