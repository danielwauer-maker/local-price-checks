from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app import sqlite_alembic
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


def _leave_realistic_stale_shm(path: Path) -> bytes:
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("SELECT COUNT(*) FROM master_products").fetchone()
        assert connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
        shm_path = Path(f"{path}-shm")
        assert shm_path.is_file()
        contents = shm_path.read_bytes()
        assert contents
    finally:
        connection.close()
    Path(f"{path}-shm").write_bytes(contents)
    wal_path = Path(f"{path}-wal")
    assert not wal_path.exists() or wal_path.stat().st_size == 0
    return contents


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


def test_dry_run_aborts_when_non_checkpointed_wal_exists(tmp_path: Path):
    database = tmp_path / "historical.sqlite3"
    _historical_baseline(database)
    wal = Path(f"{database}-wal")
    wal.write_bytes(b"pending WAL data")
    before = database.read_bytes()

    with pytest.raises(MigrationSafetyError, match="Active/non-checkpointed WAL"):
        prepare_existing_sqlite_for_alembic(database)

    assert database.read_bytes() == before
    assert _revision(database) is None


def test_dry_run_aborts_with_active_wal_connection(tmp_path: Path):
    database = tmp_path / "historical.sqlite3"
    _historical_baseline(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "INSERT INTO master_products (id, brand, name, package_size, normalized_key) "
            "VALUES (8, 'Test', 'Aktiver WAL Write', NULL, 'aktiver-wal-write')"
        )
        connection.commit()
        assert Path(f"{database}-wal").stat().st_size > 0

        with pytest.raises(MigrationSafetyError, match="Active/non-checkpointed WAL"):
            prepare_existing_sqlite_for_alembic(database)
    finally:
        connection.close()

    assert _revision(database) is None


def test_stale_nonzero_shm_without_open_user_allows_dry_run(tmp_path: Path):
    database = tmp_path / "historical.sqlite3"
    _historical_baseline(database)
    shm = Path(f"{database}-shm")
    contents = _leave_realistic_stale_shm(database)
    before = database.read_bytes()

    result = prepare_existing_sqlite_for_alembic(database)

    assert not result.applied
    assert result.action == "stamp-baseline-and-upgrade"
    assert database.read_bytes() == before
    assert shm.read_bytes() == contents


def test_stale_nonzero_shm_without_open_user_allows_apply_and_is_not_deleted(tmp_path: Path):
    database = tmp_path / "historical.sqlite3"
    backup = tmp_path / "historical.before-alembic.sqlite3"
    _historical_baseline(database)
    shm = Path(f"{database}-shm")
    contents = _leave_realistic_stale_shm(database)

    result = prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert result.applied
    assert _revision(database) == TARGET_REVISION
    assert shm.read_bytes() == contents
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT name FROM master_products WHERE id=7").fetchone() == (
            "Historisches Produkt",
        )
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)


def test_apply_preserves_source_owner_and_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = tmp_path / "historical.sqlite3"
    backup = tmp_path / "historical.before-alembic.sqlite3"
    _historical_baseline(database)
    source_stat = database.stat()
    chown_calls: list[tuple[Path, int, int]] = []

    monkeypatch.setattr(
        sqlite_alembic.os,
        "chown",
        lambda path, uid, gid: chown_calls.append((Path(path), uid, gid)),
        raising=False,
    )

    prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert len(chown_calls) == 1
    _, uid, gid = chown_calls[0]
    assert (uid, gid) == (source_stat.st_uid, source_stat.st_gid)


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


def test_apply_preserves_categories_admin_links_and_provides_restorable_backup(tmp_path: Path):
    database = tmp_path / "production-like.sqlite3"
    backup = tmp_path / "production-like.before-alembic.sqlite3"
    restored = tmp_path / "production-like.restored.sqlite3"
    _historical_baseline(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "INSERT INTO product_categories (id, name, slug, active, sort_order) "
            "VALUES (42, 'Historische Kategorie', 'historisch', 1, 7)"
        )
        connection.execute(
            "INSERT INTO product_admin_data "
            "(id, master_product_id, category_id, name_locked, category_locked, notes, updated_at) "
            "VALUES (43, 7, 42, 1, 1, 'bestehende Zuordnung', '2026-08-25 00:00:00')"
        )
        connection.commit()
        assert connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
    connection.close()

    dry_run = prepare_existing_sqlite_for_alembic(database)
    assert not dry_run.applied
    assert not backup.exists()

    prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT name, slug FROM product_categories WHERE id=42").fetchone() == (
            "Historische Kategorie",
            "historisch",
        )
        assert connection.execute(
            "SELECT master_product_id, category_id, category_locked FROM product_admin_data WHERE id=43"
        ).fetchone() == (7, 42, 1)
        assert connection.execute("SELECT COUNT(*) FROM master_products").fetchone() == (1,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    shutil.copy2(backup, restored)
    assert _revision(restored) is None
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT name FROM product_categories WHERE id=42").fetchone() == (
            "Historische Kategorie",
        )
        assert connection.execute(
            "SELECT master_product_id, category_id FROM product_admin_data WHERE id=43"
        ).fetchone() == (7, 42)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


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


def test_source_write_during_staging_aborts_before_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = tmp_path / "racing-writer.sqlite3"
    backup = tmp_path / "racing-writer.backup.sqlite3"
    _historical_baseline(database)
    original_run_alembic = sqlite_alembic._run_alembic

    def run_alembic_then_simulate_writer(path: Path, *arguments: str) -> None:
        original_run_alembic(path, *arguments)
        if arguments == ("upgrade", TARGET_REVISION):
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE master_products SET name='Extern geaendert' WHERE id=7")
                connection.commit()

    monkeypatch.setattr(sqlite_alembic, "_run_alembic", run_alembic_then_simulate_writer)

    with pytest.raises(MigrationSafetyError, match="changed during preparation"):
        prepare_existing_sqlite_for_alembic(database, apply=True, backup_path=backup)

    assert _revision(database) is None
    assert _revision(backup) is None
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT name FROM master_products WHERE id=7").fetchone() == (
            "Extern geaendert",
        )


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
