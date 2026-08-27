# Nettoyage Local Automatique en Fin d'Action — Immo-Boussole

## Règle de Nettoyage Systématique

À la fin de chaque tâche ou ensemble d'actions modifiant le projet ou exécutant des tests/builds locaux, l'agent IA doit procéder à un nettoyage local de la racine du workspace.

### Éléments à nettoyer / vérifier

1. **Bases de données de test résiduelles** (`test_*.db`) :
   - Tout fichier `test_*.db` résiduel en racine du projet (les tests doivent utiliser `tempfile.TemporaryDirectory(ignore_cleanup_errors=True)`).
2. **Fichiers de conflit de synchronisation cloud** (`*[conflicted]*`) :
   - Tout fichier comportant `[conflicted]` dans son nom (artefacts générés par la synchronisation Dropbox, OneDrive ou Google Drive).
3. **Fichiers journal SQLite orphelins** (`*.db-shm`, `*.db-wal`, `*.db-journal`) :
   - Fichiers SHM/WAL/journal orphelins non associés à la base active locale `immo_boussole.db`.
4. **Caches d'exécution** :
   - Dossiers `__pycache__` présents directement en racine du projet (s'il en existe).
   - Fichiers et dossiers `.pytest_cache/` résiduels post-tests si jugé nécessaire.

### Procédure de nettoyage

Exécuter la vérification/nettoyage avec PowerShell :

```powershell
Get-ChildItem -Path . -Filter "test_*.db" | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path . -Filter "*conflicted*" | Remove-Item -Force -ErrorAction SilentlyContinue
```
