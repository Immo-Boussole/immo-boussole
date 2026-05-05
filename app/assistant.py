import httpx
import json
import logging
import os
from typing import List, Dict, Any, Tuple
from app.config import settings
from app.mcp_server import tool_search_listings, tool_get_listing_details, tool_get_stats

logger = logging.getLogger("assistant")

SYSTEM_PROMPT = """Tu es l'assistant intelligent d'Immo-Boussole. Ton rôle est d'aider l'utilisateur à naviguer dans sa base de données immobilière.
Tu peux rechercher des biens, analyser des statistiques ou donner des détails sur une annonce spécifique.

Directives:
- Sois professionnel, concis et efficace.
- Utilise les outils à ta disposition pour fournir des informations exactes.
- Si tu affiches une liste de biens, présente-les clairement (Markdown).
- Ne fais pas de suppositions, utilise les données de la base.
- Si un outil retourne une URL comme '/listing/123', présente-la comme un lien cliquable si possible.
- Réponds toujours en français.
"""

async def call_ollama(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Appel à l'API de chat d'Ollama avec support des outils."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "search_listings",
                        "description": "Rechercher des annonces immobilières dans la base",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "min_price": {"type": "number", "description": "Prix minimum"},
                                "max_price": {"type": "number", "description": "Prix maximum"},
                                "city": {"type": "string", "description": "Ville"},
                                "min_area": {"type": "number", "description": "Surface min"},
                                "limit": {"type": "integer", "description": "Nombre de résultats (max 10)"}
                            }
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_listing_details",
                        "description": "Obtenir les détails complets d'un bien par son ID",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "listing_id": {"type": "integer", "description": "ID de l'annonce"}
                            },
                            "required": ["listing_id"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_stats",
                        "description": "Voir les statistiques globales du marché local",
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                }
            ]
        }
        
        try:
            response = await client.post(f"{settings.OLLAMA_URL}/api/chat", json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return {"message": {"content": f"Désolé, je rencontre une difficulté technique avec Ollama ({str(e)}). Assure-toi qu'Ollama est bien lancé sur `{settings.OLLAMA_URL}` avec le modèle `{settings.OLLAMA_MODEL}`."}}

async def run_assistant_step(user_input: str, history: List[Dict[str, Any]] = []) -> Tuple[str, List[Dict[str, Any]]]:
    """Exécute une itération de l'assistant (gestion tool calling incluse)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    if user_input:
        messages.append({"role": "user", "content": user_input})
    
    resp = await call_ollama(messages)
    msg = resp.get("message", {})
    
    if msg.get("tool_calls"):
        messages.append(msg)
        for tool_call in msg["tool_calls"]:
            func_name = tool_call["function"]["name"]
            args = tool_call["function"]["arguments"]
            
            logger.info(f"Assistant tool call: {func_name} with {args}")
            
            try:
                if func_name == "search_listings":
                    result = tool_search_listings(**args)
                elif func_name == "get_listing_details":
                    result = tool_get_listing_details(**args)
                elif func_name == "get_stats":
                    result = tool_get_stats()
                else:
                    result = "Outil inconnu"
            except Exception as e:
                result = f"Erreur outil: {str(e)}"
            
            messages.append({
                "role": "tool",
                "content": result,
                "tool_call_id": tool_call.get("id", "default") # Ollama id format varies
            })
        
        # Second call to get final text
        final_resp = await call_ollama(messages)
        final_msg = final_resp.get("message", {})
        return final_msg.get("content", ""), messages + [final_msg]
        
    return msg.get("content", ""), messages + [msg]
