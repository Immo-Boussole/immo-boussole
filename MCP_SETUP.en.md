# User Guide: MCP Service & AI Assistant

You now have two ways to interact with your real estate data via AI:
1. **Integrated AI Assistant**: A chat interface directly within the Immo-Boussole application that communicates with Ollama.
2. **MCP Service (Model Context Protocol)**: A standardized server that allows external tools (like Claude Desktop) to access your data.

---

## 1. Integrated AI Assistant (Ollama)

This feature allows you to chat directly with your listings from your browser.

### Configuration
The application is configured to look for Ollama at `http://host.docker.internal:11434` (the standard address for Ollama on the host machine from a Windows Docker container).

1. **Start Ollama** on your machine.
2. **Download the model** (defaults to `llama3`):
   ```bash
   ollama run llama3
   ```
3. **Access the Assistant**: A new "**AI Assistant**" link is available in the application sidebar.

### Features
The assistant can:
- **Search for properties**: *"Find me apartments under €300k in Lyon"*
- **Analyze details**: *"What do you think of listing #42? Is it close to a train station?"*
- **Provide stats**: *"What is the average price per sqm in my database?"*

---

## 2. MCP Service (For Claude Desktop)

The MCP service allows Claude Desktop to use Immo-Boussole as a knowledge source.

### Configuration in Claude Desktop
Add this configuration to your `claude_desktop_config.json` file (usually located at `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

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

*Note: Ensure the `immo-boussole-mcp` container is running.*

### Exposed Tools
- `search_listings`: Multi-criteria search.
- `get_listing_details`: Technical details, reviews, and DPE.
- `get_stats`: Overall catalog overview.

---

## 3. Deployment

To apply these changes, restart your containers:

```bash
docker-compose up -d --build
```

The application will now expose:
- Port **8000**: Web Interface (and AI Assistant).
- Port **8001**: MCP Service (SSE transport if needed).
