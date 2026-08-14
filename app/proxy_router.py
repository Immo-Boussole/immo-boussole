import json
from typing import List, Dict, Optional
from app.config import settings


class ProxyRouter:

    def __init__(self):
        # Tracks consecutive block/captcha errors for "direct" route per platform
        self.consecutive_blocks: Dict[str, int] = {}
        # Stores the current default proxy index per platform
        self.default_proxy_index: Dict[str, int] = {}
        # Parse chains from settings
        self.proxy_chains: Dict[str, List[str]] = self._parse_proxy_chains()

    def _parse_proxy_chains(self, custom_json: Optional[str] = None) -> Dict[str, List[str]]:
        chains = {"default": ["direct"]}
        raw = custom_json

        # If not passed explicitly, attempt to load from database first
        if raw is None:
            try:
                from app.database import SessionLocal
                from app.models import GlobalSettings
                db = SessionLocal()
                try:
                    gs = db.query(GlobalSettings).first()
                    if gs and gs.scraping_proxies_json:
                        raw = gs.scraping_proxies_json
                finally:
                    db.close()
            except Exception:
                pass

        # Fallback to settings.SCRAPING_PROXIES (.env)
        if not raw and settings.SCRAPING_PROXIES:
            raw = settings.SCRAPING_PROXIES

        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        if isinstance(v, list):
                            # Ensure each item is a string
                            chains[k] = [str(x) for x in v]
                elif isinstance(parsed, list):
                    chains["default"] = [str(x) for x in parsed]
            except Exception as e:
                print(f"[ProxyRouter] Erreur parsing SCRAPING_PROXIES: {e}")
        return chains

    def reload_chains(self, custom_json: Optional[str] = None):
        """Reloads the proxy chains dynamically."""
        self.proxy_chains = self._parse_proxy_chains(custom_json)
        print(f"[ProxyRouter] Chaînes de proxy rechargées : {self.proxy_chains}")

    def get_proxy_chain(self, platform: str) -> List[str]:
        """Returns the configured proxy chain for a given platform, falling back to default."""
        return self.proxy_chains.get(platform, self.proxy_chains.get("default", ["direct"]))

    def get_current_proxy(self, platform: str, attempt_index: Optional[int] = None) -> str:
        """
        Gets the proxy string to use.
        If attempt_index is provided, returns that specific step of the chain.
        Otherwise, returns the current default proxy (which dynamically defaults to index 0).
        """
        chain = self.get_proxy_chain(platform)
        if not chain:
            return "direct"

        if attempt_index is not None:
            return chain[attempt_index % len(chain)]

        idx = self.default_proxy_index.get(platform, 0)
        return chain[idx % len(chain)]

    def report_success(self, platform: str, proxy: str):
        """Called when a request succeeds, resetting consecutive block count for the direct route."""
        if proxy == "direct":
            self.consecutive_blocks[platform] = 0

    def report_block(self, platform: str, proxy: str):
        """
        Called when a request is blocked.
        If the block happened on 'direct', increments consecutive failure count.
        After 3 consecutive blocks, automatically promotes index 1 (the home proxy) to default.
        """
        chain = self.get_proxy_chain(platform)
        if not chain:
            return

        if proxy == "direct":
            self.consecutive_blocks[platform] = self.consecutive_blocks.get(platform, 0) + 1
            print(f"[ProxyRouter] Blocage direct détecté pour {platform} (blocages consécutifs : {self.consecutive_blocks[platform]})")
            
            if self.consecutive_blocks[platform] >= 3 and len(chain) > 1:
                # Promote to index 1 (first external proxy) if current default is still index 0
                if self.default_proxy_index.get(platform, 0) == 0:
                    self.default_proxy_index[platform] = 1
                    print(f"[ProxyRouter] Blocage direct persistant pour {platform}. Bascule de la route par défaut vers : {chain[1]}")


# Global singleton instance
proxy_router = ProxyRouter()
