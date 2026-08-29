from __future__ import annotations

from sqlalchemy.orm import Session

from .models import AdminSetting

FEATURE_PREFIX = "feature."

DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "markets": True,
    "offers": True,
    "favorites": True,
    "shopping_list": True,
    "region_availability": True,
    "optimization": False,
    "savings": False,
    "normal_price_badges": False,
    "price_alerts": False,
    "product_alternatives": False,
    "reviewer_mode": True,
}


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def get_feature_flags(db: Session) -> dict[str, bool]:
    rows = (
        db.query(AdminSetting)
        .filter(AdminSetting.key.like(f"{FEATURE_PREFIX}%"))
        .all()
    )
    overrides = {row.key[len(FEATURE_PREFIX):]: row.value for row in rows}
    return {
        key: _as_bool(overrides.get(key), default)
        for key, default in DEFAULT_FEATURE_FLAGS.items()
    }


def feature_enabled(db: Session, name: str) -> bool:
    defaults = DEFAULT_FEATURE_FLAGS
    if name not in defaults:
        return False
    row = db.get(AdminSetting, f"{FEATURE_PREFIX}{name}")
    return _as_bool(row.value if row else None, defaults[name])


def set_feature_flag(db: Session, name: str, enabled: bool) -> AdminSetting:
    if name not in DEFAULT_FEATURE_FLAGS:
        raise KeyError(name)
    key = f"{FEATURE_PREFIX}{name}"
    row = db.get(AdminSetting, key)
    if not row:
        row = AdminSetting(key=key)
        db.add(row)
    row.value = "1" if enabled else "0"
    row.description = f"Spareno feature flag: {name}"
    return row
