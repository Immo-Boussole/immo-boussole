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
FORCE=false

for arg in "$@"; do
    if [ "$arg" = "--force" ] || [ "$arg" = "-f" ]; then
        FORCE=true
    fi
done

# Navigate to the project directory
if ! cd "$PROJECT_DIR"; then
    echo "$(date) - ERROR: Unable to access directory $PROJECT_DIR"
    exit 1
fi

# Ensure git trusts this directory to avoid dubious ownership errors
git config --global --add safe.directory "$PROJECT_DIR" 2>/dev/null || true

# Fetch information from the remote server without modifying local files
git fetch

# Compare the local commit with the remote commit of the tracked branch
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u} 2>/dev/null || git rev-parse HEAD)

if [ "$LOCAL" != "$REMOTE" ] || [ "$FORCE" = "true" ]; then
    echo "$(date) - Updating $PROJECT_DIR (force=$FORCE)..."
    
    # 1. Update the code (reset local branch to match the remote tracking branch exactly)
    git reset --hard @{u} 2>/dev/null || git reset --hard HEAD
    
    # 2. Extract pinned APP_VERSION tag from DOCKER_IMAGE.txt if present
    if [ -f "DOCKER_IMAGE.txt" ]; then
        IMAGE_REF=$(grep -v '^#' DOCKER_IMAGE.txt | grep -v '^[[:space:]]*$' | head -n 1)
        if [ -n "$IMAGE_REF" ]; then
            PINNED_TAG="${IMAGE_REF##*:}"
            if [ -n "$PINNED_TAG" ]; then
                export APP_VERSION="$PINNED_TAG"
                echo "$(date) - Image pinning active: APP_VERSION=$APP_VERSION"
            fi
        fi
    fi

    # 3. Pull pre-built images (if applicable) and rebuild/restart the containers
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
    
    # 4. Cleanup old dangling images
    echo "$(date) - Pruning old Docker images..."
    docker image prune -f

    echo "$(date) - Update successfully completed."
else
    # Uncomment the following line to display a message even when there is nothing to do
    # echo "$(date) - The code is already up to date."
    exit 0
fi
