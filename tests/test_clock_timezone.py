from datetime import datetime
from types import SimpleNamespace

import app.clock as clock


class _FakeDateTime:
    @classmethod
    def now(cls, tz):
        assert str(tz) == "Europe/Berlin"
        return datetime(2026, 8, 31, 1, 13, tzinfo=tz)


def test_app_today_uses_berlin_business_date(monkeypatch):
    monkeypatch.setattr(clock, "settings", SimpleNamespace(local_date_override="", app_env="test"))
    monkeypatch.setattr(clock, "datetime", _FakeDateTime)

    assert clock.app_today().isoformat() == "2026-08-31"
