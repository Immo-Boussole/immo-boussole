# Autonomie & Déploiements — Immo-Boussole

## Règle d'autonomie

Pour ce projet, **tous les automatismes sont autorisés sans demander de confirmation préalable**, à l'exception du déploiement en Production.

### Commandes de mise à jour des environnements

- **Développement (Dev)** :

  ```bash
  ssh immo-dev "sudo bash /opt/immo-boussole/dev/scripts/auto_update.sh /opt/immo-boussole/dev/ docker-compose.cloudflared.yml" --force
  ```

- **Production (Prod)** :

  ```bash
  ssh immo-dev "sudo bash /opt/immo-boussole/prod/scripts/auto_update.sh /opt/immo-boussole/prod/ docker-compose.cloudflared.yml" --force
  ```

### Ce qui est exécuté en pleine autonomie (sans confirmation)

- Exécution de commandes terminal (tests, linters, builds, git, etc.)
- Création, modification et suppression de fichiers dans le projet
- Exécution et validation des tests locaux (pytest)
- Création de commits (au format Conventional Commits)
- Push sur le repository distant (git push origin main)
- Déploiement / mise à jour sur l'environnement de **Développement / Staging** (dev)
- Vérifications post-déploiement et tests automatisés

### Règle stricte pour la Production et workflow après modification de code

- À chaque modification de code / commit / push :
  1. **Proposer d'exécuter la commande de mise à jour Dev** :

     ```bash
     ssh immo-dev "sudo bash /opt/immo-boussole/dev/scripts/auto_update.sh /opt/immo-boussole/dev/ docker-compose.cloudflared.yml" --force
     ```

  2. Une fois que :
     - Les tests locaux (pytest) sont **OK**
     - Les GitHub Actions / CI sont **OK**
     - Le déploiement sur **Dev** est validé
  3. **Proposer explicitement à l'utilisateur d'exécuter la commande de mise à jour en Production** :

     ```bash
     ssh immo-dev "sudo bash /opt/immo-boussole/prod/scripts/auto_update.sh /opt/immo-boussole/prod/ docker-compose.cloudflared.yml" --force
     ```

- **NE JAMAIS déployer en Production de manière autonome sans l'accord explicite de l'utilisateur.**

