# 💾 Sauvegarde & Restauration

Pour garantir la sécurité de vos données, **Immo-Boussole** inclut un système intégré de sauvegarde et de restauration accessible uniquement aux administrateurs.

## 🛡️ Contrôle d'accès
La fonctionnalité de sauvegarde et de restauration est strictement réservée aux utilisateurs ayant le rôle **ADMIN**. Elle se trouve au bas de la page **Gestion Utilisateurs** (`/admin/users`).

## 📦 Que contient la sauvegarde ?
Le système génère un fichier `.zip` unique contenant tout le nécessaire pour déplacer ou restaurer l'application :
1. **Base de données** (`immo_boussole.db`) : Toutes les annonces, utilisateurs, avis, recherches et historique.
2. **Médias** (`static/media/`) : Toutes les photos téléchargées des biens.
3. **Configuration** (`.env`) : Vos clés secrètes, jetons API et paramètres d'environnement.

## 🚀 Utilisation

### 1. Créer une sauvegarde
- Allez dans **Gestion Utilisateurs** dans la barre latérale.
- Faites défiler jusqu'à la section **Sauvegarde & Restauration**.
- Cliquez sur **Télécharger une sauvegarde**.
- Un fichier ZIP nommé `immo_boussole_backup_AAAAMMJJ_HHMMSS.zip` sera généré et téléchargé sur votre ordinateur.

### 2. Restaurer une sauvegarde
> [!CAUTION]
> La restauration d'une sauvegarde **écrasera complètement** votre base de données, vos photos et votre configuration actuelles. Cette action est irréversible.

- Allez dans **Gestion Utilisateurs**.
- Dans la section **Sauvegarde & Restauration**, cliquez sur **Restaurer une sauvegarde**.
- Sélectionnez le fichier `.zip` précédemment téléchargé.
- Confirmez l'avertissement.
- Attendez le message de succès.
- **Recommandé** : Redémarrez l'application (ou le conteneur Docker) pour vous assurer que tous les changements de configuration sont parfaitement pris en compte.

## ⚙️ Détails techniques (API)
Si vous souhaitez automatiser les sauvegardes via des scripts, vous pouvez utiliser les points de terminaison REST suivants (nécessite une session admin) :

| Point de terminaison | Méthode | Description |
|----------------------|---------|-------------|
| `/api/admin/backup` | `GET` | Génère et renvoie le fichier ZIP de sauvegarde. |
| `/api/admin/restore` | `POST` | Accepte un envoi de fichier multipart/form-data (clé : `file`). |

---
*Note : Si vous utilisez Docker, rappelez-vous que vos volumes sont persistants. Les sauvegardes sont principalement utiles pour migrer vers un autre serveur ou pour une sécurité supplémentaire avant une modification manuelle majeure.*
