"""
Stackfluence configuration.
All secrets/tunables come from environment variables.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # --- App ---
    app_name: str = "Stackfluence"
    debug: bool = False
    base_url: str = "https://stackfluence.com"

    # --- Secrets ---
    click_id_secret: str = "CHANGE-ME-IN-PRODUCTION"  # HMAC signing key
    click_id_expiry_seconds: int = 86400 * 30  # 30 days

    # --- Database ---
    database_url: str = "postgresql+asyncpg://stackfluence:stackfluence@localhost:5432/stackfluence"

    # --- Redis (rate limiting + caching) ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Bot detection thresholds ---
    bot_risk_block_threshold: float = 0.9  # hard block
    bot_risk_flag_threshold: float = 0.5   # mark non-billable
    rate_limit_per_ip_per_minute: int = 30
    rate_limit_per_link_per_minute: int = 120

    # --- Shopify ---
    shopify_api_version: str = "2024-01"

    # --- Supabase ---
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # --- Billing defaults ---
    default_dedupe_window_seconds: int = 1800  # 30 min
    default_min_engagement_seconds: int = 10
    default_min_pageviews: int = 2

    model_config = {"env_prefix": "SF_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
