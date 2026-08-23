# Autonomie & Déploiements — Immo-Boussole

## Règle d'autonomie

Pour ce projet, **tous les automatismes sont autorisés sans demander de confirmation préalable**, à l'exception du déploiement en Production.

### Ce qui est exécuté en pleine autonomie (sans confirmation) :
- Exécution de commandes terminal (tests, linters, builds, git, etc.)
- Création, modification et suppression de fichiers dans le projet
- Exécution et validation des tests locaux (pytest)
- Création de commits (au format Conventional Commits)
- Push sur le repository distant (git push origin main)
- Déploiement / mise à jour automatique sur l'environnement de **Développement / Staging** (dev)
- Vérifications post-déploiement et tests automatisés

### Règle stricte pour la Production :
- **NE JAMAIS déployer en Production de manière autonome**.
- Une fois que :
  1. Les tests locaux (pytest) sont **OK**
  2. Les GitHub Actions / CI sont **OK**
  3. Les commits sont poussés et déployés avec succès sur l'environnement **Dev**
- **Proposer explicitement à l'utilisateur de procéder au déploiement en Production** (par exemple en fournissant la commande SSH prête à l'emploi ou en demandant sa validation).
