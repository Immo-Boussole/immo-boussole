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

<<<<<<< HEAD
    # Browserless URL (headless Chrome via CDP)
    BROWSERLESS_URL: str = "ws://localhost:3000"
=======
    # Browserless URL (for headless scraping)
    BROWSERLESS_URL: str = "ws://127.0.0.1:3000"
>>>>>>> 16b15c06962da86941aae50b5f0adf15a6b01549

    # Optional Browserless authentication token
    BROWSERLESS_TOKEN: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
