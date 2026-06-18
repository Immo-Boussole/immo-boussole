#!/bin/bash

# ==============================================================================
# Automatic Update Script (Auto-Update) for Immo-Boussole
# ==============================================================================
# This script checks if new commits are available on the remote repository.
# If there are updates, it pulls the code and restarts the Docker containers.
# Ideal for being executed by a Cron job (e.g., every hour).
#
# Usage:
# ./auto_update.sh /path/to/project [compose-file.yml]
#
# Examples:
# ./auto_update.sh /opt/immo-boussole/dev docker-compose.cloudflared.yml
# ./auto_update.sh /opt/immo-boussole/prod
# ==============================================================================

# Default variables
PROJECT_DIR="${1:-/opt/immo-boussole/dev}"
COMPOSE_FILE="${2:-docker-compose.yml}"

# Navigate to the project directory
if ! cd "$PROJECT_DIR"; then
    echo "$(date) - ERROR: Unable to access directory $PROJECT_DIR"
    exit 1
fi

# Fetch information from the remote server without modifying local files
git fetch

# Compare the local commit with the remote commit of the tracked branch
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u})

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date) - New code detected in $PROJECT_DIR. Updating..."
    
    # 1. Update the code
    git pull
    
    # 2. Pull pre-built images (if applicable) and rebuild/restart the containers
    if [ -f "$COMPOSE_FILE" ]; then
        docker compose -f "$COMPOSE_FILE" pull
        docker compose -f "$COMPOSE_FILE" up -d --build
    elif [ -f "docker-compose.cloudflared.yml" ]; then
        # Smart fallback
        docker compose -f docker-compose.cloudflared.yml pull
        docker compose -f docker-compose.cloudflared.yml up -d --build
    else
        docker compose pull
        docker compose up -d --build
    fi
    
    echo "$(date) - Update successfully completed."
else
    # Uncomment the following line to display a message even when there is nothing to do
    # echo "$(date) - The code is already up to date."
    exit 0
fi
