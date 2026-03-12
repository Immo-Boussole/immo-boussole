import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./immo_boussole.db"

    # App
    DEBUG: bool = True

    # Scraping scheduler
    SCRAPING_INTERVAL_HOURS: int = 12

    # Optional ScrapingBee API key (legacy / fallback)
    SCRAPINGBEE_API_KEY: str = None

    # PinchTab headless browser URL
    # Default: localhost for dev, host.docker.internal for Docker
    PINCHTAB_URL: str = "http://127.0.0.1:9867"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
