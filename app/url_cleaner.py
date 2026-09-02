import re
import urllib.parse
from typing import List, Optional

# Known tracking / analytics query parameters to remove
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_EXACT_PARAMS = {
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "msclkid",
    "zanpid",
    "xtor",
    "xtref",
    "xts",
    "ref_src",
    "ref_url",
    "igshid",
    "mc_cid",
    "mc_eid",
    "_ga",
    "_gl",
}

# Regex to match http/https URLs in arbitrary text
URL_REGEX = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)

# Characters that should be stripped from the edges of an extracted URL
LEADING_PUNCTUATION = "([{\'\"«<"
TRAILING_PUNCTUATION = ".,;:!?\"\'»>`*~"


def _clean_punctuation(raw_url: str) -> str:
    """
    Strips trailing and leading punctuation/quotes/brackets from an extracted URL,
    taking into account balanced parentheses/brackets.
    """
    url = raw_url.strip()

    # Strip leading punctuation/brackets
    url = url.lstrip(LEADING_PUNCTUATION)

    # Strip simple trailing punctuation
    url = url.rstrip(TRAILING_PUNCTUATION)

    # Handle unbalanced closing parentheses or brackets (e.g. from "(https://example.com)")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    while url.endswith("]") and url.count("]") > url.count("["):
        url = url[:-1]
    while url.endswith("}") and url.count("}") > url.count("{"):
        url = url[:-1]

    # Clean any residual trailing punctuation after bracket removal
    url = url.rstrip(TRAILING_PUNCTUATION)
    return url.strip()


def clean_tracking_params(url: str) -> str:
    """
    Removes known marketing tracking and analytics query parameters from a URL
    (e.g., utm_source, fbclid, gclid, etc.) while preserving legitimate query params.
    """
    if not url:
        return url

    try:
        parsed = urllib.parse.urlparse(url)
        if not parsed.query:
            return url

        # Parse query params (preserving order)
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered_pairs = []

        for key, val in query_pairs:
            key_lower = key.lower()
            # Check if parameter starts with any tracking prefix or matches exact known tracker
            if any(key_lower.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES):
                continue
            if key_lower in TRACKING_EXACT_PARAMS:
                continue
            filtered_pairs.append((key, val))

        new_query = urllib.parse.urlencode(filtered_pairs)
        cleaned = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        return cleaned
    except Exception:
        return url


def clean_url(raw_url: str) -> str:
    """
    Cleans an individual URL by stripping surrounding punctuation and tracking parameters.
    """
    cleaned = _clean_punctuation(raw_url)
    cleaned = clean_tracking_params(cleaned)
    return cleaned.strip()


def extract_urls_from_text(text: str) -> List[str]:
    """
    Extracts all distinct valid URLs from arbitrary text, cleaning surrounding
    punctuation and tracking query parameters.
    """
    if not text or not isinstance(text, str):
        return []

    matches = URL_REGEX.findall(text)
    extracted: List[str] = []
    seen = set()

    for m in matches:
        cleaned = clean_url(m)
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            if cleaned not in seen:
                seen.add(cleaned)
                extracted.append(cleaned)

    return extracted


def extract_single_url_from_text(text: str) -> str:
    """
    Extracts a single URL from user-provided text.
    - If 1 URL is found: returns the cleaned URL.
    - If no URL is found: raises ValueError("Aucune URL valide (http:// ou https://) trouvée dans le texte.").
    - If multiple URLs are found: raises ValueError("Plusieurs URLs détectées. Veuillez n'en fournir qu'une seule ou utiliser l'ajout multiple.").
    """
    if not text or not isinstance(text, str) or not text.strip():
        raise ValueError("L'URL ne peut pas être vide.")

    urls = extract_urls_from_text(text)

    if not urls:
        raise ValueError("Aucune URL valide (doit commencer par http:// ou https://) n'a été trouvée.")

    if len(urls) > 1:
        raise ValueError(
            "Plusieurs URLs ont été détectées dans votre texte. "
            "Veuillez n'en fournir qu'une seule ou utiliser le mode d'ajout multiple (batch)."
        )

    return urls[0]
