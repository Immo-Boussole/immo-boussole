import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./immo_boussole.db"

    # App
    APP_ENV: str = "production"
    APP_DOMAIN: str = "localhost"
    APP_URL: str = "http://localhost:8000"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-at-all-costs"  # MUST be overridden in .env for production
    HTTPS_ONLY: bool = False  # Set to True in production to enforce secure cookies

    # Scraping scheduler
    SCRAPING_INTERVAL_HOURS: int = 12
    SCRAPING_SCHEDULE: str = "Toutes les 30 min, de 6h à 22h30"  # Human-readable label shown in the UI

    # Browserless URL (headless Chrome via CDP)
    BROWSERLESS_URL: str = "ws://localhost:3000"

    # Optional Browserless authentication token
    BROWSERLESS_TOKEN: str = ""

    # Proxy chains configured as a JSON string
    # Format: '{"leboncoin": ["direct", "http://gost-client:1080"], "default": ["direct"]}'
    SCRAPING_PROXIES: str = '{"default": ["direct"]}'

    # Browserless connection timeout (seconds)
    BROWSERLESS_CONNECT_TIMEOUT: int = 30

    # Versioning (overridden during build)
    APP_VERSION: str = "1.1.1-dev"

    # Géorisques API
    GEORISQUES_API_BASEURL: str = "https://www.georisques.gouv.fr/api/"
    GEORISQUES_API_KEY: str = ""

    # Notifications (Apprise)
    # Global fallback URL used when a user has no personal apprise_url configured.
    # Supports any Apprise-compatible URL: tgram://, discord://, ntfy://, mailto://, etc.
    # Leave empty to disable global notifications.
    APPRISE_URL: str = ""

    # LLM / Ollama
    OLLAMA_URL: str = "http://host.docker.internal:11434"
    OLLAMA_MODEL: str = "llama3"

    # Header Enforcement (Cloudflare Tunnel / Reverse Proxy security)
    # Format: comma-separated list of "Header-Name" (presence only) or "Header-Name:Expected-Value" (exact match)
    # Example: "CF-Ray,X-Origin-Verify:my-super-secret-token"
    # Disabled when empty or whitespace.
    REQUIRED_HEADERS: str = ""
    REQUIRED_HEADERS_EXEMPT_LOCALHOST: bool = True

    @property
    def parsed_required_headers(self) -> dict:
        """Parse REQUIRED_HEADERS into a dictionary {header_name_lowercase: expected_value_or_none}."""
        if not self.REQUIRED_HEADERS or not self.REQUIRED_HEADERS.strip():
            return {}
        result = {}
        for item in self.REQUIRED_HEADERS.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" in item:
                key, val = item.split(":", 1)
                result[key.strip().lower()] = val.strip()
            else:
                result[item.lower()] = None
        return result

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
