from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Konfiguracja aplikacji oparta na pydantic-settings.
    Automatycznie wczytuje zmienne środowiskowe i plik .env.
    """
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

    api_v1_prefix: str = "/api/v1"
    photon_search_url: str = "https://photon.komoot.io/api/"
    photon_reverse_url: str = "https://photon.komoot.io/reverse"
    http_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
