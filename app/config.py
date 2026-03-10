import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./immo_boussole.db"
    DEBUG: bool = True
    # Configuration du scraping
    SCRAPING_INTERVAL_HOURS: int = 12
    SCRAPINGBEE_API_KEY: str = None

    class Config:
        env_file = ".env"

settings = Settings()
