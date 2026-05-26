# Guide d'Utilisation : Service MCP & Assistant IA

Vous avez maintenant deux façons d'interagir avec vos données immobilières via l'IA :
1. **Assistant IA intégré** : Une interface de chat directement dans l'application Immo-Boussole qui communique avec Ollama.
2. **Service MCP (Model Context Protocol)** : Un serveur standardisé qui permet à des outils externes (comme Claude Desktop) d'accéder à vos données.

---

## 1. Assistant IA Intégré (Ollama)

Cette fonctionnalité vous permet de discuter directement avec vos annonces depuis le navigateur.

### Configuration
L'application est configurée pour chercher Ollama sur `http://host.docker.internal:11434` (l'adresse standard d'Ollama sur la machine hôte depuis un container Docker Windows).

1. **Lancez Ollama** sur votre machine.
2. **Téléchargez le modèle** (par défaut `llama3`) :
   ```bash
   ollama run llama3
   ```
3. **Accédez à l'Assistant** : Un nouveau lien "**Assistant IA**" est disponible dans la barre latérale de l'application.

### Fonctionnalités
L'assistant peut :
- **Rechercher des biens** : *"Trouve-moi des appartements à moins de 300k€ à Lyon"*
- **Analyser des détails** : *"Que penses-tu de l'annonce #42 ? Est-elle proche d'une gare ?"*
- **Donner des stats** : *"Quel est le prix moyen au m² dans ma base ?"*

---

## 2. Service MCP (Pour Claude Desktop)

Le service MCP permet à Claude Desktop d'utiliser Immo-Boussole comme une source de connaissances.

### Configuration dans Claude Desktop
Ajoutez cette configuration à votre fichier `claude_desktop_config.json` (souvent dans `%APPDATA%\Claude\claude_desktop_config.json`) :

```json
{
  "mcpServers": {
    "immo-boussole": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "immo-boussole-mcp",
        "python",
        "-m",
        "app.mcp_server"
      ]
    }
  }
}
```

*Note : Assurez-vous que le container `immo-boussole-mcp` est bien démarré.*

### Outils exposés
- `search_listings` : Recherche multicritères.
- `get_listing_details` : Détails techniques, avis et DPE.
- `get_stats` : Vue d'ensemble du catalogue.

---

## 3. Déploiement

Pour appliquer ces changements, relancez vos containers :

```bash
docker-compose up -d --build
```

L'application exposera désormais :
- Le port **8000** : Interface Web (et Assistant IA).
- Port **8001** : Service MCP (transport SSE si besoin).
