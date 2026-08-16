from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


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
        f"sqlite:///{BASE_DIR / 'data' / 'local_price_checks.sqlite3'}",
    )
    default_radius_km: int = int(os.getenv("DEFAULT_RADIUS_KM", "15"))
    local_date_override: str = os.getenv("LOCAL_DATE_OVERRIDE", "").strip()
    scheduler_enabled: bool = _bool_env("SCHEDULER_ENABLED", False)
    collection_hour: int = int(os.getenv("COLLECTION_HOUR", "5"))
    collection_minute: int = int(os.getenv("COLLECTION_MINUTE", "30"))
    collector_browser_enabled: bool = _bool_env("COLLECTOR_BROWSER_ENABLED", False)
    collector_timeout_seconds: int = int(os.getenv("COLLECTOR_TIMEOUT_SECONDS", "30"))
    stale_after_hours: int = int(os.getenv("STALE_AFTER_HOURS", "36"))
    driving_cost_per_km: float = float(os.getenv("DRIVING_COST_PER_KM", "0.30"))
    route_distance_factor: float = float(os.getenv("ROUTE_DISTANCE_FACTOR", "1.25"))


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
