# 🧭 Installation via Portainer et exposition avec Cloudflared

Ce guide explique comment déployer **Immo-Boussole** sur un serveur en utilisant **Portainer** (via des Stacks Docker Compose) et comment l'exposer de manière sécurisée sur Internet grâce à **Cloudflared** (Tunnels Cloudflare), en profitant des options de sécurité du niveau gratuit (Free Tier) de Cloudflare.

## 📋 Prérequis

1. Un serveur avec **Docker** et **Portainer** (ou Portainer CE) installés.
2. Un nom de domaine géré par **Cloudflare** (vos serveurs DNS doivent pointer vers Cloudflare).
3. Un compte Cloudflare actif (le plan gratuit est suffisant).

---

## 🔒 Étape 1 : Création du Tunnel Cloudflare (Zéro Trust)

La méthode la plus sécurisée pour exposer votre application sans ouvrir de ports sur votre routeur ou pare-feu (NAT) est d'utiliser un tunnel Cloudflare. Votre serveur établira une connexion sortante vers Cloudflare, masquant ainsi son adresse IP publique.

1. Connectez-vous à votre tableau de bord Cloudflare et accédez à **Zero Trust** (menu de gauche).
2. Allez dans **Networks** > **Connectors** et cliquez sur **Create a tunnel**.
3. Choisissez **Cloudflared** comme connecteur et donnez un nom à votre tunnel (ex: `immo-boussole-tunnel`).
4. Sur l'écran d'installation, choisissez votre environnement (Docker) et **copiez le token** fourni dans la commande (la chaîne de caractères après `--token`). Vous en aurez besoin pour le déploiement sur Portainer.
5. Cliquez sur **Next**.
6. Dans l'onglet **Public Hostname**, configurez l'URL d'accès public :
   - **Subdomain** : `immo` (ou ce que vous souhaitez, par exemple `recherche`)
   - **Domain** : `votre-domaine.com` (sélectionnez votre domaine dans la liste)
   - **Service** :
     - Type : `HTTP`
     - URL : `immo-boussole:8000` (c'est le nom du service Docker que nous allons créer et son port interne)
7. Cliquez sur **Complete setup**.

---

## 🐳 Étape 2 : Déploiement sur Portainer

Nous allons déployer Immo-Boussole, FlareSolverr (pour le scraping) et le connecteur Cloudflared dans la même stack. Les conteneurs pourront communiquer entre eux via le réseau interne Docker.

1. Connectez-vous à votre interface **Portainer**.
2. Sélectionnez votre environnement (généralement `local`) et allez dans **Stacks**.
3. Sélectionnez la méthode **Repository**.
   > [!TIP]
   > Cette méthode est recommandée car Portainer gère lui-même le clonage de Git, évitant ainsi les erreurs `git not found` sur les NAS (comme Synology).

4. **Configuration du dépôt** :
   - **Repository URL** : `https://github.com/Immo-Boussole/immo-boussole.git` (ou l'URL de **votre propre fork**)
   - **Repository Reference** : `refs/heads/main`
   - **Compose file path** : 
     - `docker-compose.hub.cloudflared.yml` (Recommandé : Récupère l'image pré-construite sur [Docker Hub](https://hub.docker.com/repository/docker/wikijm/immo-boussole/general))
     - `docker-compose.cloudflared.yml` (Construction manuelle : Compile l'application à partir du code source)

   > [!IMPORTANT]
   > L'image Docker est mise à jour automatiquement sur Docker Hub après chaque modification du code via GitHub Actions. Utiliser la version Hub garantit un déploiement plus rapide et évite la phase de compilation sur votre serveur.

7. **Variables d'environnement** (en bas de page) :
   - **Modifications requises** : Ajoutez une variable nommée `TUNNEL_TOKEN` et collez votre token Zero Trust.
   - **Configuration initiale** : Au premier démarrage, l'application vous redirigera vers `/setup-admin` pour créer votre compte administrateur. 

8. Cliquez sur **Deploy the stack**. Patientez quelques minutes pendant que Portainer télécharge les images, construit l'application et lance les conteneurs.

Une fois la stack déployée, le conteneur `cloudflared` établira la connexion sécurisée vers Cloudflare. Votre application sera alors accessible partout sur l'URL configurée à l'étape 1 (ex: `https://immo.votre-domaine.com`), le tout sécurisé en HTTPS managé par Cloudflare !

---

## 🛡️ Étape 3 : Configurations de Sécurité (Cloudflare Free Tier)

Même si l'accès à Immo-Boussole est protégé en interne par un système de comptes (ADMIN/USER), il est crucial d'ajouter des couches de sécurité au niveau de Cloudflare pour éviter d'éventuelles attaques par force brute ou l'exploitation de failles, d'autant plus que l'application est en ligne.

Dans le tableau de bord Cloudflare classique (Website > Votre domaine) :

### 1. Activer le mode WAF (Web Application Firewall) basique
- Allez dans **Security** > **Settings**.
- Réglez le **Security Level** sur **Medium** ou **High** (aide à bloquer les bots malveillants).
- Assurez-vous que **Browser Integrity Check** est activé.
- Dans **Security** > **Bots**, activez le mode **Bot Fight Mode**.

### 2. Restreindre l'accès géographique (WAF Custom Rules)
Si vous et vos collaborateurs ne vous connectez que depuis la France (par exemple), bloquer le reste du monde est une défense très efficace.
- Allez dans **Security** > **WAF** > Onglet **Custom rules**.
- Cliquez sur **Create rule**.
- Nommez la règle : `Bloquer requêtes hors FR`
- Dans l'éditeur d'expression (Expression builder) :
  - **Field**: `Country`
  - **Operator**: `does not equal`
  - **Value**: `France`
- Dans la section **Action**, sélectionnez **Block**.
- Enregistrez (Save).

---

## 🦸‍♂️ Accès Zéro Trust (Option Maximale Recommandée)

Pour une sécurité impénétrable, vous pouvez placer l'application derrière un portail captif Cloudflare Access (gratuit jusqu'à 50 utilisateurs). L'application Immo-Boussole ne sera consultable **que par les personnes explicitement autorisées**, après s'être authentifiées via un code à usage unique (OTP) envoyé par email, ou via Google/GitHub/Microsoft.

1. Retournez dans le tableau de bord **Zero Trust** de Cloudflare.
2. Allez dans **Access** > **Applications** et cliquez sur **Add an application**.
3. Choisissez **Self-hosted**.
4. Configurez l'application :
   - **Application name** : `Portail Immo-Boussole`
   - **Session Duration** : `24 hours` (ou plus)
   - **Subdomain** et **Domain** : `immo.votre-domaine.com` (doit être l'URL exacte du tunnel créé à l'étape 1)
5. Cliquez sur **Next**.
6. Créez une **Policy** (règle d'autorisation) :
   - **Policy name** : `Accès Collaborateurs`
   - **Action** : `Allow`
   - Dans le bloc **Include**, choisissez `Emails` (ou `Emails ending in` pour un domaine entier) et entrez votre adresse email personnelle et celle de vos collaborateurs (pensez à valider avec Entrée).
7. Cliquez sur **Next** puis sur **Add application**.

**Résultat :** 
Désormais, lorsque quiconque visitera `https://immo.votre-domaine.com`, Cloudflare affichera une mire de connexion estampillée Zero Trust avant même que la requête réseau n'atteigne votre serveur. Seules les adresses email autorisées recevront un code PIN pour entrer et découvrir l'application.

---

🎉 *Félicitations ! Votre instance Immo-Boussole est maintenant déployée de manière résiliente, totalement invisible sur l'Internet public (aucun port ouvert), sécurisée par HTTPS, gérée commodément depuis Portainer et protégée par une politique strict de type "Zero Trust".*
