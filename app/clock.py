from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import settings


BUSINESS_TIMEZONE = ZoneInfo("Europe/Berlin")


def app_today() -> date:
    """Return Spareno's business date in German local time.

    Production hosts commonly run on UTC. Using ``date.today()`` there makes
    the app stay on yesterday's offer week between German midnight and the UTC
    date rollover. All offer validity/week decisions therefore use
    Europe/Berlin explicitly.
    """
    if settings.local_date_override:
        try:
            return date.fromisoformat(settings.local_date_override)
        except ValueError:
            if settings.app_env not in {"development", "local"}:
                raise RuntimeError("LOCAL_DATE_OVERRIDE must be YYYY-MM-DD")
    return datetime.now(BUSINESS_TIMEZONE).date()
