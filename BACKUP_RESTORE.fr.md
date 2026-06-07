# 💾 Sauvegarde & Restauration

Pour garantir la sécurité de vos données et faciliter les migrations (ex: de dev vers prod), **Immo-Boussole** inclut un système intégré de sauvegarde et de restauration granulaire accessible uniquement aux administrateurs.

## 🛡️ Contrôle d'accès
La fonctionnalité de sauvegarde et de restauration est strictement réservée aux utilisateurs ayant le rôle **ADMIN**. Elle se trouve au bas de la page **Administration** (`/admin/maintenance`).

## 📦 Sauvegarde Granulaire
Lors de la création d'une sauvegarde, vous pouvez sélectionner individuellement les composants à inclure :
- **Configuration système** (`.env`) : Vos clés secrètes, jetons API et paramètres d'environnement.
- **Paramètres & Zones** : Vos recherches enregistrées, mots-clés, et zones interdites.
- **Utilisateurs** : Les comptes, rôles et mots de passe.
- **Annonces & Avis** : Les données des annonces immobilières, leurs statuts, et les commentaires.
- **Fichiers Médias** (`static/media/`) : Toutes les photos téléchargées.

Le système génère un fichier `.zip` contenant les éléments sélectionnés (avec une base de données expurgée des données non sélectionnées).

## 🚀 Utilisation

### 1. Créer une sauvegarde
- Allez dans **Administration** dans la barre latérale.
- Faites défiler jusqu'à la section **Sauvegarde & Restauration**.
- Cochez les composants désirés et cliquez sur **Créer une sauvegarde**.
- Un fichier ZIP nommé `immo_boussole_backup_AAAAMMJJ_HHMMSS.zip` sera généré.

### 2. Restaurer une sauvegarde
> [!CAUTION]
> La restauration d'une sauvegarde **écrasera** les composants sélectionnés dans votre base de données, vos photos et votre configuration actuelles.

- Allez dans **Administration**.
- Dans la section **Sauvegarde & Restauration**, cliquez sur **Restaurer une sauvegarde**.
- Sélectionnez le fichier `.zip` précédemment téléchargé.
- Cochez **uniquement les éléments que vous souhaitez restaurer** (pratique pour migrer uniquement les annonces de dev à prod, par exemple).
- Confirmez l'avertissement.
- **Recommandé** : Redémarrez l'application (ou le conteneur Docker) pour vous assurer que les changements de configuration `.env` sont parfaitement pris en compte.

## 🔄 Migration de DEV vers PROD

Pour répliquer les nouveautés, réglages ou annonces de votre environnement de développement (DEV) vers votre environnement de production (PROD), suivez ces meilleures pratiques :

1. **Sauvegardez la DEV** : Dans votre instance DEV, allez dans "Administration" et générez une sauvegarde en incluant tous les éléments que vous souhaitez migrer.
2. **Protégez la PROD** : Bien que vous puissiez cocher "Configuration système (.env)" lors de la restauration sur la PROD, le système est conçu pour être intelligent et granulaire. 
   - **Il n'écrasera JAMAIS** vos variables de domaine, mots de passe, URL de base de données, secrets ou configuration de l'environnement de PROD (comme `APP_DOMAIN`, `APP_URL`, `DATABASE_URL`, `SECRET_KEY`, etc.).
   - Il se contentera de fusionner les nouveaux réglages non-sensibles.
3. **Sélection Granulaire** : Si vous souhaitez uniquement importer les annonces, décochez simplement "Configuration système", "Utilisateurs", et "Paramètres & Zones" lors de la restauration.

## ⚙️ Détails techniques (API)
Les points de terminaison REST acceptent désormais des paramètres pour choisir les composants :

| Point de terminaison | Méthode | Description |
|----------------------|---------|-------------|
| `/api/admin/backup` | `GET` | Génère le ZIP (paramètres : `include_env`, `include_settings`, `include_users`, `include_listings`, `include_media`). |
| `/api/admin/restore` | `POST` | Accepte un envoi `multipart/form-data` (clé : `file` + booléens `restore_*`). Protège les clés `INFRA` du `.env` lors de la restauration. |
