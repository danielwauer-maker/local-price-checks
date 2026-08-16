from __future__ import annotations

from datetime import date

from .config import settings


def app_today() -> date:
    if settings.local_date_override:
        try:
            return date.fromisoformat(settings.local_date_override)
        except ValueError:
            if settings.app_env not in {"development", "local"}:
                raise RuntimeError("LOCAL_DATE_OVERRIDE must be YYYY-MM-DD")
    return date.today()
