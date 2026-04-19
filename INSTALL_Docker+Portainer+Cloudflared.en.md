# 🧭 Installation via Portainer and Exposure with Cloudflared

This guide explains how to deploy **Immo-Boussole** on a server using **Portainer** (via Docker Compose Stacks) and how to securely expose it on the Internet using **Cloudflared** (Cloudflare Tunnels), taking advantage of the security options in Cloudflare's Free Tier.

## 📋 Prerequisites

1. A server with **Docker** and **Portainer** (or Portainer CE) installed.
2. A domain name managed by **Cloudflare** (your DNS servers must point to Cloudflare).
3. An active Cloudflare account (the free plan is sufficient).

---

## 🔒 Step 1: Creating a Cloudflare Tunnel (Zero Trust)

The most secure method to expose your application without opening ports on your router or firewall (NAT) is to use a Cloudflare tunnel. Your server will establish an outbound connection to Cloudflare, thus hiding its public IP address.

1. Log in to your Cloudflare dashboard and go to **Zero Trust** (left menu).
2. Go to **Networks** > **Connectors** and click **Create a tunnel**.
3. Choose **Cloudflared** as the connector and give your tunnel a name (e.g., `immo-boussole-tunnel`).
4. On the installation screen, choose your environment (Docker) and **copy the token** provided in the command (the string after `--token`). You will need this for the Portainer deployment.
5. Click **Next**.
6. In the **Public Hostname** tab, configure the public access URL:
   - **Subdomain**: `immo` (or whatever you prefer, e.g., `search`)
   - **Domain**: `your-domain.com` (select your domain from the list)
   - **Service**:
     - Type: `HTTP`
     - URL: `immo-boussole:8000` (this is the name of the Docker service we will create and its internal port)
7. Click **Complete setup**.

---

## 🐳 Step 2: Deployment on Portainer

We will deploy Immo-Boussole, FlareSolverr (for scraping), and the Cloudflared connector in the same stack. The containers will be able to communicate with each other via the internal Docker network.

1. Log in to your **Portainer** interface.
2. Select your environment (usually `local`) and go to **Stacks**.
3. Select the **Repository** method.
   > [!TIP]
   > This method is recommended because Portainer handles Git cloning internally, avoiding `git not found` errors on NAS systems (like Synology).

4. **Repository configuration**:
   - **Repository URL**: `https://github.com/Immo-Boussole/immo-boussole.git` (or your **own fork** URL)
   - **Repository Reference**: `refs/heads/main`
   - **Compose file path**: 
     - `docker-compose.hub.cloudflared.yml` (Recommended: Pulls pre-built image from [Docker Hub](https://hub.docker.com/repository/docker/wikijm/immo-boussole/general))
     - `docker-compose.cloudflared.yml` (Manual build: Compiles the application from source code)

   > [!IMPORTANT]
   > The Docker image is automatically updated on Docker Hub after each code change via GitHub Actions. Using the Hub version ensures a faster deployment and avoids compilation on your server.

7. **Environment variables** (at the bottom of the page):
   - **Required changes**: Add a variable named `TUNNEL_TOKEN` and paste your Zero Trust token.
   - **Initial setup**: On the first run, the application will redirect you to `/setup-admin` to create your administrator account.

8. Click **Deploy the stack**. Wait a few minutes while Portainer downloads the images, builds the application, and starts the containers.

Once the stack is deployed, the `cloudflared` container will establish the secure connection to Cloudflare. Your application will then be accessible anywhere at the URL configured in Step 1 (e.g., `https://immo.your-domain.com`), all secured via HTTPS managed by Cloudflare!

---

## 🛡️ Step 3: Security Configurations (Cloudflare Free Tier)

Even though access to Immo-Boussole is internally protected by an account system (ADMIN/USER), it is crucial to add layers of security at the Cloudflare level to prevent potential brute force attacks or exploit vulnerabilities, especially since the application is online.

In the classic Cloudflare dashboard (Website > Your domain):

### 1. Enable Basic WAF (Web Application Firewall) mode
- Go to **Security** > **Settings**.
- Set the **Security Level** to **Medium** or **High** (helps block malicious bots).
- Ensure **Browser Integrity Check** is enabled.
- In **Security** > **Bots**, enable **Bot Fight Mode**.

### 2. Restrict Geographic Access (WAF Custom Rules)
If you and your collaborators only connect from France (for example), blocking the rest of the world is a very effective defense.
- Go to **Security** > **WAF** > **Custom rules** tab.
- Click **Create rule**.
- Name the rule: `Block requests outside FR`
- In the **Expression builder**:
  - **Field**: `Country`
  - **Operator**: `does not equal`
  - **Value**: `France`
- In the **Action** section, select **Block**.
- Click **Save**.

---

## 🦸‍♂️ Zero Trust Access (Highly Recommended Maximum Option)

For impenetrable security, you can place the application behind a Cloudflare Access captive portal (free for up to 50 users). The Immo-Boussole application will **only be viewable by explicitly authorized people**, after authenticating via a one-time code (OTP) sent by email, or via Google/GitHub/Microsoft.

1. Go back to the Cloudflare **Zero Trust** dashboard.
2. Go to **Access** > **Applications** and click **Add an application**.
3. Choose **Self-hosted**.
4. Configure the application:
   - **Application name**: `Immo-Boussole Portal`
   - **Session Duration**: `24 hours` (or more)
   - **Subdomain** and **Domain**: `immo.your-domain.com` (must be the exact URL of the tunnel created in Step 1)
5. Click **Next**.
6. Create a **Policy** (authorization rule):
   - **Policy name**: `Collaborators Access`
   - **Action**: `Allow`
   - In the **Include** block, choose `Emails` (or `Emails ending in` for an entire domain) and enter your personal email address and those of your collaborators (remember to validate with Enter).
7. Click **Next** then **Add application**.

**Result:** 
From now on, whenever anyone visits `https://immo.your-domain.com`, Cloudflare will display a Zero Trust-branded login page before the network request even reaches your server. Only authorized email addresses will receive a PIN code to enter and access the application.

---

🎉 *Congratulations! Your Immo-Boussole instance is now deployed in a resilient manner, totally invisible on the public Internet (no open ports), secured by HTTPS, conveniently managed from Portainer, and protected by a strict "Zero Trust" policy.*
