from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app.db_transfer import MigrationSafetyError
from app.sqlite_alembic import BASELINE_REVISION, TARGET_REVISION, prepare_existing_sqlite_for_alembic


def _upgrade(path: Path, revision: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path.as_posix()}"}
    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", revision], check=True, env=env)


def _historical_baseline(path: Path) -> None:
    _upgrade(path, BASELINE_REVISION)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE alembic_version")
        connection.execute(
            "INSERT INTO master_products (id, brand, name, package_size, normalized_key) "
            "VALUES (7, 'Test', 'Historisches Produkt', NULL, 'historisches-produkt')"
        )
        connection.commit()


def _revision(path: Path) -> str | None:
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if not exists:
            return None
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return str(row[0]) if row else None


def test_historical_baseline_dry_run_passes_without_changes(tmp_path: Path):
    database = tmp_path / "historical.sqlite3"
    _historical_baseline(database)
    before = database.read_bytes()

    result = prepare_existing_sqlite_for_alembic(database)

    assert not result.applied
    assert result.initial_revision is None
    assert result.action == "stamp-baseline-and-upgrade"
    assert database.read_bytes() == before
    assert _revision(database) is None


def test_historical_baseline_apply_backs_up_stamps_and_upgrades(tmp_path: Path):
    database = tmp_path / "historical.sqlite3"
    backup = tmp_path / "historical.before-alembic.sqlite3"
    _historical_baseline(database)

    result = prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert result.applied
    assert result.backup_path == backup
    assert backup.is_file()
    assert _revision(backup) is None
    assert _revision(database) == TARGET_REVISION
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(product_categories)")}
        assert "parent_id" in columns
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT name FROM master_products WHERE id=7").fetchone() == ("Historisches Produkt",)


def test_schema_drift_refuses_apply_without_stamp_or_data_change(tmp_path: Path):
    database = tmp_path / "drift.sqlite3"
    backup = tmp_path / "must-not-exist.sqlite3"
    _historical_baseline(database)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE master_products ADD COLUMN unexpected TEXT")
        connection.commit()
    before = database.read_bytes()

    with pytest.raises(MigrationSafetyError, match="schema differs"):
        prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert database.read_bytes() == before
    assert _revision(database) is None
    assert not backup.exists()


def test_corrupt_database_aborts_before_backup(tmp_path: Path):
    database = tmp_path / "corrupt.sqlite3"
    backup = tmp_path / "must-not-exist.sqlite3"
    database.write_bytes(b"this is not a sqlite database")

    with pytest.raises(MigrationSafetyError, match="could not be validated"):
        prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert not backup.exists()


def test_unknown_foreign_key_problem_aborts_before_backup(tmp_path: Path):
    database = tmp_path / "foreign-key.sqlite3"
    backup = tmp_path / "must-not-exist.sqlite3"
    _historical_baseline(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO product_admin_data "
            "(id, master_product_id, category_id, name_locked, category_locked, notes, updated_at) "
            "VALUES (9, 7, 999999, 0, 0, NULL, '2026-08-25 00:00:00')"
        )
        connection.commit()

    with pytest.raises(MigrationSafetyError, match="foreign_key_check failed"):
        prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert _revision(database) is None
    assert not backup.exists()


def test_versioned_baseline_upgrades_without_restamping(tmp_path: Path):
    database = tmp_path / "versioned-baseline.sqlite3"
    backup = tmp_path / "versioned-baseline.backup.sqlite3"
    _upgrade(database, BASELINE_REVISION)

    result = prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert result.initial_revision == BASELINE_REVISION
    assert result.action == "upgraded-baseline"
    assert _revision(database) == TARGET_REVISION
    assert _revision(backup) == BASELINE_REVISION


def test_current_database_is_idempotent_even_with_apply(tmp_path: Path):
    database = tmp_path / "current.sqlite3"
    backup = tmp_path / "must-not-exist.sqlite3"
    _upgrade(database, TARGET_REVISION)
    before = database.read_bytes()

    result = prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert not result.applied
    assert result.action == "already-current"
    assert result.final_revision == TARGET_REVISION
    assert database.read_bytes() == before
    assert not backup.exists()
