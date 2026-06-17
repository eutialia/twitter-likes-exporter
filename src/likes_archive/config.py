from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Required ---
    database_url: str
    media_root: Path
    x_user_id: str
    x_bearer_token: str
    x_cookies: str
    x_csrf_token: str

    # --- Optional: media ---
    media_base_url: str = "/media"
    media_download_workers: int = 16

    # --- Optional: scraper ---
    scrape_delay_min: float = 1.0
    scrape_delay_max: float = 15.0
    scrape_delay_peak_ratio: float = 0.15
    scrape_force_full_refetch: bool = False

    # --- Optional: web ---
    tweets_per_page: int = 50

    # --- Optional: notifications ---
    webhook_url: str | None = None

    # --- Optional: server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # pydantic-settings populates every field from environment variables at runtime,
    # so the no-argument construction is correct even though the type checker can't see it.
    return Settings()  # ty: ignore[missing-argument]
