# 💾 Backup & Restore

To ensure the safety of your data, **Immo-Boussole** includes a built-in backup and restore system accessible only to administrators.

## 🛡️ Access Control
The backup and restore functionality is strictly restricted to users with the **ADMIN** role. It can be found at the bottom of the **User Management** page (`/admin/users`).

## 📦 What is backed up?
The system generates a single `.zip` file containing everything needed to move or restore the application:
1. **Database** (`immo_boussole.db`): All listings, users, reviews, queries, and history.
2. **Media** (`static/media/`): All downloaded photos of the properties.
3. **Configuration** (`.env`): Your secret keys, API tokens, and environment settings.

## 🚀 How to use

### 1. Creating a Backup
- Navigate to **User Management** in the sidebar.
- Scroll down to the **Backup & Restore** section.
- Click on **Download backup**.
- A ZIP file named `immo_boussole_backup_YYYYMMDD_HHMMSS.zip` will be generated and downloaded to your computer.

### 2. Restoring a Backup
> [!CAUTION]
> Restoring a backup will **completely overwrite** your current database, photos, and configuration. This action is irreversible.

- Navigate to **User Management**.
- In the **Backup & Restore** section, click on **Restore backup**.
- Select the `.zip` file you previously downloaded.
- Confirm the warning prompt.
- Wait for the "Success" message.
- **Recommended**: Restart the application (or Docker container) to ensure all configuration changes are fully loaded.

## ⚙️ Technical Details (API)
If you wish to automate backups via scripts, you can use the following REST endpoints (requires admin session):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/backup` | `GET` | Generates and returns the ZIP backup file. |
| `/api/admin/restore` | `POST` | Accepts a multipart/form-data file upload (key: `file`). |

---
*Note: If you are using Docker, remember that your volumes are persistent. Backups are mainly useful for migrating to another server or for extra safety before a major manual change.*
