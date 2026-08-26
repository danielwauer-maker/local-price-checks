from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL, make_url

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'data' / 'local_price_checks.sqlite3'}"


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = int(os.getenv("APP_PORT", "8000"))
    data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    database_url: str = os.getenv(
        "DATABASE_URL",
        DEFAULT_DATABASE_URL,
    )
    auto_create_schema: bool = _bool_env(
        "AUTO_CREATE_SCHEMA",
        os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).startswith("sqlite"),
    )
    default_radius_km: int = int(os.getenv("DEFAULT_RADIUS_KM", "15"))
    local_date_override: str = os.getenv("LOCAL_DATE_OVERRIDE", "").strip()
    scheduler_enabled: bool = _bool_env("SCHEDULER_ENABLED", False)
    manual_collection_enabled: bool = _bool_env("MANUAL_COLLECTION_ENABLED", False)
    collection_hour: int = int(os.getenv("COLLECTION_HOUR", "5"))
    collection_minute: int = int(os.getenv("COLLECTION_MINUTE", "30"))
    collector_browser_enabled: bool = _bool_env("COLLECTOR_BROWSER_ENABLED", False)
    collector_timeout_seconds: int = int(os.getenv("COLLECTOR_TIMEOUT_SECONDS", "30"))
    stale_after_hours: int = int(os.getenv("STALE_AFTER_HOURS", "36"))
    driving_cost_per_km: float = float(os.getenv("DRIVING_COST_PER_KM", "0.15"))
    route_distance_factor: float = float(os.getenv("ROUTE_DISTANCE_FACTOR", "1.25"))
    store_coordinate_tolerance_m: float = float(os.getenv("STORE_COORDINATE_TOLERANCE_M", "250"))
    store_quality_min_valid_offers: int = int(os.getenv("STORE_QUALITY_MIN_VALID_OFFERS", "10"))
    store_quality_min_price_coverage_pct: float = float(os.getenv("STORE_QUALITY_MIN_PRICE_COVERAGE_PCT", "80"))
    store_quality_max_duplicate_rate_pct: float = float(os.getenv("STORE_QUALITY_MAX_DUPLICATE_RATE_PCT", "10"))
    store_quality_max_invalid_rate_pct: float = float(os.getenv("STORE_QUALITY_MAX_INVALID_RATE_PCT", "20"))
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin").strip()
    admin_password: str = os.getenv("ADMIN_PASSWORD", "").strip()
    supabase_url: str = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    supabase_publishable_key: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)


def database_url(value: str | None = None) -> URL:
    """Parse and validate the configured SQLAlchemy database URL.

    Keeping this in one place gives the application, Alembic and maintenance
    tools identical handling without ever logging credentials.
    """

    url = make_url(value or settings.database_url)
    if url.get_backend_name() not in {"sqlite", "postgresql"}:
        raise ValueError("DATABASE_URL must use SQLite or PostgreSQL")
    if url.get_backend_name() == "postgresql" and url.drivername != "postgresql+psycopg":
        raise ValueError("PostgreSQL DATABASE_URL must use postgresql+psycopg://")
    return url
