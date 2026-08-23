from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import engine


@pytest.mark.skipif(engine.dialect.name != "sqlite", reason="SQLite-only hardening")
def test_sqlite_connections_have_concurrency_pragmas():
    with engine.connect() as connection:
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        synchronous = connection.execute(text("PRAGMA synchronous")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()

    assert busy_timeout >= 30000
    # Foreign-key enforcement is deliberately not enabled by the concurrency
    # hook. Enabling it changes schema/migration behavior and must be introduced
    # as a separate, explicit database-migration change once all referenced
    # tables are guaranteed to exist during setup and teardown.
    assert foreign_keys == 0
    # NORMAL is 1 in SQLite. The assertion intentionally permits FULL (2) if a
    # platform/database policy has strengthened durability after connection.
    assert synchronous in {1, 2}
    # File-backed production databases should use WAL. In-memory SQLite cannot
    # switch to WAL and reports "memory", which keeps isolated unit tests valid.
    assert str(journal_mode).lower() in {"wal", "memory"}
