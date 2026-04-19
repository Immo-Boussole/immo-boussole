import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./immo_boussole.db"

    # App
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-at-all-costs"  # MUST be overridden in .env for production

    # Scraping scheduler
    SCRAPING_INTERVAL_HOURS: int = 12
    SCRAPING_SCHEDULE: str = "Toutes les heures, de 6h à 22h30"  # Human-readable label shown in the UI

    # Browserless URL (headless Chrome via CDP)
    BROWSERLESS_URL: str = "ws://localhost:3000"

    # Optional Browserless authentication token
    BROWSERLESS_TOKEN: str = ""

    # Versioning (overridden during build)
    APP_VERSION: str = "1.1.1-dev"

    # Géorisques API
    GEORISQUES_API_BASEURL: str = "https://www.georisques.gouv.fr/api/"
    GEORISQUES_API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
