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

## 🔄 Migration from DEV to PROD

To replicate new features, settings, or listings from your development (DEV) environment to your production (PROD) environment, follow these best practices:

1. **Backup DEV**: In your DEV instance, go to "Administration" and generate a backup including all elements you wish to migrate.
2. **Protect PROD**: Although you can check "System Configuration (.env)" when restoring on PROD, the system is designed to be smart and granular.
   - **It will NEVER overwrite** your domain variables, passwords, database URLs, secrets, or PROD environment configuration (like `APP_DOMAIN`, `APP_URL`, `DATABASE_URL`, `SECRET_KEY`, etc.).
   - It will only merge non-sensitive new settings.
3. **Granular Selection**: If you only want to import listings, simply uncheck "System Configuration", "Users", and "Settings & Zones" during the restore.

### Large Files (Bypassing Cloudflare's 100MB limit via SSH)

If your ZIP file exceeds Cloudflare's upload limit (often 100MB) or if you experience network authentication issues, you can perform a direct file copy over SSH.

1. **Extract the archive on the server**:
   ```bash
   sudo apt-get install unzip -y
   mkdir -p /tmp/backup_extracted
   unzip /tmp/backup.zip -d /tmp/backup_extracted
   ```
2. **Stop the container** (critical to avoid database corruption):
   ```bash
   sudo docker stop immo-boussole-production-app
   ```
3. **Copy files manually using `docker cp`**:
   The ZIP contains `immo_boussole.db` and the `static/media/` folder. Direct copying ensures your PROD `.env` file is never overwritten.
   ```bash
   sudo docker cp /tmp/backup_extracted/immo_boussole.db immo-boussole-production-app:/app/data/immo_boussole.db
   sudo docker cp /tmp/backup_extracted/static/media/. immo-boussole-production-app:/app/static/media/
   ```
4. **Start the container and restore permissions (Critical)**:
   Because the copy was done via `sudo`, the files now belong to the `root` system user. You must give it back ownership to the application user (`boussole`), **and then restart the container** so SQLite recognizes the new write permissions (otherwise you will get an "Internal Server Error" / readonly database):
   ```bash
   sudo docker start immo-boussole-production-app
   sudo docker exec -u root immo-boussole-production-app chown -R boussole:boussole /app/data /app/static/media
   sudo docker restart immo-boussole-production-app
   ```
5. **Clean up temporary files**:
   ```bash
   sudo rm -rf /tmp/backup.zip /tmp/backup_extracted
   ```

## ⚙️ Technical Details (API)
The REST endpoints now accept parameters to choose components:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/backup` | `GET` | Generates the ZIP (parameters: `include_env`, `include_settings`, `include_users`, `include_listings`, `include_media`). |
| `/api/admin/restore` | `POST` | Accepts a `multipart/form-data` upload (key: `file` + `restore_*` booleans). Protects `INFRA` keys in `.env` during restoration. |
