# 💾 Backup & Restore

To ensure data security and ease migrations (e.g., from dev to prod), **Immo-Boussole** includes a built-in granular backup and restore system accessible only to administrators.

## 🛡️ Access Control
The backup and restore functionality is strictly restricted to users with the **ADMIN** role. It can be found at the bottom of the **Administration** page (`/admin/maintenance`).

## 📦 Granular Backup
When creating a backup, you can individually select the components to include:
- **System Configuration** (`.env`): Your secret keys, API tokens, and environment parameters.
- **Settings & Zones**: Your saved searches, keywords, and forbidden zones.
- **Users**: Accounts, roles, and passwords.
- **Listings & Reviews**: Real estate listing data, statuses, and comments.
- **Media Files** (`static/media/`): All downloaded photos.

The system generates a `.zip` file containing the selected elements (with a database stripped of non-selected data).

## 🚀 Usage

### 1. Create a Backup
- Go to **Administration** in the sidebar.
- Scroll down to the **Backup & Restore** section.
- Check the desired components and click on **Create a backup**.
- A ZIP file named `immo_boussole_backup_YYYYMMDD_HHMMSS.zip` will be generated.

### 2. Restore a Backup
> [!CAUTION]
> Restoring a backup will **overwrite** the selected components in your current database, photos, and configuration.

- Go to **Administration**.
- In the **Backup & Restore** section, click **Restore a backup**.
- Select the previously downloaded `.zip` file.
- Check **only the items you want to restore** (useful for migrating only listings from dev to prod, for example).
- Confirm the warning.
- **Recommended**: Restart the application (or Docker container) to ensure `.env` configuration changes take effect perfectly.

## ⚙️ Technical Details (API)
The REST endpoints now accept parameters to choose components:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/backup` | `GET` | Generates the ZIP (parameters: `include_env`, `include_settings`, `include_users`, `include_listings`, `include_media`). |
| `/api/admin/restore` | `POST` | Accepts a `multipart/form-data` upload (key: `file` + `restore_*` booleans). |
