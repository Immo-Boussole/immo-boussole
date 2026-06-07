#!/bin/bash

# ==============================================================================
# Script de mise à jour automatique (Auto-Update) pour Immo-Boussole
# ==============================================================================
# Ce script vérifie si de nouveaux commits sont disponibles sur le dépôt distant.
# S'il y a des nouveautés, il télécharge le code et relance les conteneurs Docker.
# Idéal pour être exécuté par une tâche Cron (ex: toutes les heures).
#
# Utilisation :
# ./auto_update.sh /chemin/vers/le/projet [fichier-compose.yml]
#
# Exemples :
# ./auto_update.sh /opt/immo-boussole/dev docker-compose.cloudflared.yml
# ./auto_update.sh /opt/immo-boussole/prod
# ==============================================================================

# Variables par défaut
PROJECT_DIR="${1:-/opt/immo-boussole/dev}"
COMPOSE_FILE="${2:-docker-compose.yml}"

# Se placer dans le dossier du projet
if ! cd "$PROJECT_DIR"; then
    echo "$(date) - ERREUR: Impossible d'accéder au dossier $PROJECT_DIR"
    exit 1
fi

# Récupérer les informations du serveur distant sans modifier les fichiers locaux
git fetch

# Comparer le commit local avec le commit distant de la branche suivie
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u})

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date) - Nouveau code détecté dans $PROJECT_DIR. Mise à jour en cours..."
    
    # 1. Mettre à jour le code
    git pull
    
    # 2. Reconstruire et relancer les conteneurs
    if [ -f "$COMPOSE_FILE" ]; then
        docker compose -f "$COMPOSE_FILE" up -d --build
    elif [ -f "docker-compose.cloudflared.yml" ]; then
        # Fallback intelligent
        docker compose -f docker-compose.cloudflared.yml up -d --build
    else
        docker compose up -d --build
    fi
    
    echo "$(date) - Mise à jour terminée avec succès."
else
    # Décommenter la ligne suivante pour afficher un message même quand il n'y a rien à faire
    # echo "$(date) - Le code est déjà à jour."
    exit 0
fi
