import httpx
import json
import logging
import os
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.models import AIProfile
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

async def call_llm(messages: List[Dict[str, Any]], profile: Optional[AIProfile]) -> Dict[str, Any]:
    """Appel à l'API de chat en fonction du profil."""
    tools = [
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

    # Default to Ollama if no profile
    provider = profile.provider if profile else "openai-compatible"
    endpoint = profile.endpoint.rstrip("/") if profile else settings.OLLAMA_URL.rstrip("/")
    model = profile.model_name if profile else settings.OLLAMA_MODEL
    api_key = profile.api_key if profile else ""

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            if provider in ["chatgpt", "openai-compatible", "mistral"]:
                # OpenAI Format
                if not endpoint.endswith("/chat/completions"):
                    endpoint = f"{endpoint}/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "stream": False
                }
                resp = await client.post(endpoint, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return {"message": data["choices"][0]["message"]}

            elif provider == "claude":
                # Anthropic Format
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                
                # Extract system prompt
                system_prompt = ""
                anthropic_messages = []
                for m in messages:
                    if m["role"] == "system":
                        system_prompt = m["content"]
                    elif m["role"] in ["user", "assistant"]:
                        anthropic_messages.append(m)
                    elif m["role"] == "tool":
                        anthropic_messages.append({
                            "role": "user", 
                            "content": [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": m["content"]}]
                        })

                # Convert tools
                anthropic_tools = []
                for t in tools:
                    anthropic_tools.append({
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "input_schema": t["function"]["parameters"]
                    })

                payload = {
                    "model": model,
                    "messages": anthropic_messages,
                    "system": system_prompt,
                    "max_tokens": 4000,
                    "tools": anthropic_tools
                }
                
                resp = await client.post(endpoint, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                
                # Convert response back to generic format
                result_message = {"role": "assistant", "content": ""}
                tool_calls = []
                for content_block in data.get("content", []):
                    if content_block["type"] == "text":
                        result_message["content"] += content_block["text"]
                    elif content_block["type"] == "tool_use":
                        tool_calls.append({
                            "id": content_block["id"],
                            "type": "function",
                            "function": {
                                "name": "get_listing_details" if content_block["name"] == "get_listing_details" else content_block["name"], # mapping issue prevention
                                "arguments": json.dumps(content_block["input"])
                            }
                        })
                
                if tool_calls:
                    result_message["tool_calls"] = tool_calls
                return {"message": result_message}
                
            elif provider == "google":
                # Gemini format
                url = f"{endpoint}?key={api_key}"
                if not "generateContent" in endpoint:
                    base = endpoint.rstrip("/")
                    if base.endswith("/models"):
                        base = base[:-7]
                    url = f"{base}/models/{model}:generateContent?key={api_key}"
                
                gemini_contents = []
                system_prompt = ""
                for m in messages:
                    if m["role"] == "system":
                        system_prompt = m["content"]
                    elif m["role"] == "user":
                        gemini_contents.append({"role": "user", "parts": [{"text": m["content"]}]})
                    elif m["role"] == "assistant":
                        parts = []
                        if "tool_calls" in m:
                            for tc in m["tool_calls"]:
                                call_item = {
                                    "functionCall": {
                                        "name": tc["function"]["name"],
                                        "args": json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                                    }
                                }
                                if tc.get("id") and tc["id"] != "default":
                                    call_item["functionCall"]["id"] = tc["id"]
                                parts.append(call_item)
                        else:
                            parts.append({"text": m["content"]})
                        
                        # Preserve thought_signature if present
                        ts = m.get("thought_signature") or m.get("thoughtSignature")
                        if ts:
                            parts.append({
                                "thought_signature": ts
                            })
                        
                        gemini_contents.append({"role": "model", "parts": parts})
                    elif m["role"] == "tool":
                        response_part = {
                            "functionResponse": {
                                "name": m.get("name", "tool"),
                                "response": {"result": m["content"]}
                            }
                        }
                        if m.get("tool_call_id") and m["tool_call_id"] != "default":
                            response_part["functionResponse"]["id"] = m["tool_call_id"]
                        gemini_contents.append({
                            "role": "user", 
                            "parts": [response_part]
                        })

                # Tools
                gemini_tools = [{"functionDeclarations": []}]
                for t in tools:
                    gemini_tools[0]["functionDeclarations"].append({
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "parameters": t["function"]["parameters"]
                    })

                payload = {
                    "contents": gemini_contents,
                    "tools": gemini_tools,
                    "systemInstruction": {"parts": [{"text": system_prompt}]}
                }
                
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                
                parts = data["candidates"][0]["content"].get("parts", [])
                fc_parts = [p["functionCall"] for p in parts if "functionCall" in p]
                ts_parts = [p.get("thought_signature") or p.get("thoughtSignature") for p in parts if "thought_signature" in p or "thoughtSignature" in p]
                text_content = "".join([p["text"] for p in parts if "text" in p])
                
                if fc_parts:
                    tool_calls = []
                    for i, fc in enumerate(fc_parts):
                        fc_id = fc.get("id") or f"call_{i+1}"
                        tool_calls.append({
                            "id": fc_id,
                            "type": "function",
                            "function": {
                                "name": fc["name"],
                                "arguments": json.dumps(fc["args"]) if not isinstance(fc["args"], str) else fc["args"]
                            }
                        })
                    msg = {
                        "role": "assistant",
                        "content": text_content,
                        "tool_calls": tool_calls
                    }
                    if ts_parts:
                        msg["thought_signature"] = ts_parts[0]
                    return {"message": msg}
                else:
                    msg = {
                        "role": "assistant",
                        "content": text_content
                    }
                    if ts_parts:
                        msg["thought_signature"] = ts_parts[0]
                    return {"message": msg}

        except Exception as e:
            error_str = str(e)
            import re
            error_str = re.sub(r"key=[^&'\s]+", "key=********", error_str)
            
            # Log detailed response body if available
            response_body = ""
            if hasattr(e, "response") and e.response is not None:
                try:
                    response_body = e.response.text
                    logger.error(f"LLM API Detail: {response_body}")
                except Exception:
                    pass
            
            logger.error(f"LLM API error: {error_str}")
            return {"message": {"role": "assistant", "content": f"Erreur avec le fournisseur d'IA : {error_str}" + (f" | Détails : {response_body}" if response_body else "") }}

async def run_assistant_step(user_input: str, history: List[Dict[str, Any]] = [], user_id: int = None, db: Session = None) -> Tuple[str, List[Dict[str, Any]]]:
    """Exécute une itération de l'assistant (gestion tool calling incluse)."""
    
    profile = None
    if user_id and db:
        profile = db.query(AIProfile).filter(AIProfile.user_id == user_id, AIProfile.is_default == True).first()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    if user_input:
        messages.append({"role": "user", "content": user_input})
    
    resp = await call_llm(messages, profile)
    msg = resp.get("message", {})
    
    if msg.get("tool_calls"):
        messages.append(msg)
        for tool_call in msg["tool_calls"]:
            func_name = tool_call["function"]["name"]
            args_str = tool_call["function"]["arguments"]
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
            
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
                "name": func_name,
                "content": str(result),
                "tool_call_id": tool_call.get("id", "default") # Ollama id format varies
            })
        
        # Second call to get final text
        final_resp = await call_llm(messages, profile)
        final_msg = final_resp.get("message", {})
        return final_msg.get("content", ""), messages + [final_msg]
        
    return msg.get("content", ""), messages + [msg]
