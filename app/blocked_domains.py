import csv
from pathlib import Path
from typing import Tuple, Optional, Dict
from urllib.parse import urlparse

_BLOCKED_DOMAINS_CSV_PATH = Path(__file__).parent / "data" / "blocked_domains.csv"
_blocked_domains_cache: Optional[Dict[str, str]] = None


def load_blocked_domains(force_reload: bool = False) -> Dict[str, str]:
    """
    Loads blocked domains from CSV file.
    Returns a dictionary mapping lowercased domain names to their descriptions.
    """
    global _blocked_domains_cache
    if _blocked_domains_cache is not None and not force_reload:
        return _blocked_domains_cache

    domains: Dict[str, str] = {}
    if _BLOCKED_DOMAINS_CSV_PATH.is_file():
        try:
            with open(_BLOCKED_DOMAINS_CSV_PATH, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    domain = (row.get("domain") or "").strip().lower()
                    description = (row.get("description") or "").strip()
                    if domain:
                        domains[domain] = description
        except Exception as e:
            print(f"[BlockedDomains] Error reading CSV {_BLOCKED_DOMAINS_CSV_PATH}: {e}")

    _blocked_domains_cache = domains
    return domains


def is_domain_blocked(url: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Checks if a given URL belongs to a blocked domain.
    Matching logic:
    - Hostname matches exact domain (e.g., 'pretto.fr')
    - Hostname ends with '.<domain>' (e.g., 'www.pretto.fr', 'sub.pretto.fr')

    Returns:
        (is_blocked, matched_domain, description)
    """
    if not url:
        return False, None, None

    url_str = url.strip()
    if not url_str.startswith(("http://", "https://")):
        url_str = "http://" + url_str

    try:
        parsed = urlparse(url_str)
        netloc = (parsed.netloc or "").split(":")[0].lower()
    except Exception:
        return False, None, None

    if not netloc:
        return False, None, None

    blocked_map = load_blocked_domains()
    for domain, description in blocked_map.items():
        if netloc == domain or netloc.endswith("." + domain):
            return True, domain, description

    return False, None, None
