import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./immo_boussole.db"

    # App
    DEBUG: bool = True
    APP_PASSWORD: str = "password"  # Default password, should be changed in .env
    SECRET_KEY: str = "change-me-at-all-costs"  # Used for session cookies

    # Scraping scheduler
    SCRAPING_INTERVAL_HOURS: int = 12

    # Optional ScrapingBee API key (legacy / fallback)
    SCRAPINGBEE_API_KEY: str = ""

    # Browserless URL (for headless scraping)
    BROWSERLESS_URL: str = "ws://127.0.0.1:3000"

    # Deprecated: PinchTab URL
    PINCHTAB_URL: str = "http://127.0.0.1:9867"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
