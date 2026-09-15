from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.backup_service import (
    BackupError,
    create_sqlite_backup,
    list_backups,
    list_restore_history,
    perform_pending_restore,
    prepare_restore,
)


def _create_db(path: Path, *, revision: str = "rev-1", value: str = "value") -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version(version_num) VALUES (?)", (revision,))
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _sample_value(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("SELECT value FROM sample ORDER BY id LIMIT 1").fetchone()
        assert row is not None
        return str(row[0])
    finally:
        connection.close()


def test_create_sqlite_backup_is_verified_and_listed(tmp_path: Path):
    source = tmp_path / "source.sqlite3"
    backup_dir = tmp_path / "backups"
    _create_db(source, value="original")

    record = create_sqlite_backup(
        source_path=source,
        backup_directory=backup_dir,
        kind="manual",
        actor="tester",
    )

    backup_path = backup_dir / record.name
    assert backup_path.is_file()
    assert backup_path.with_suffix(".sqlite3.json").is_file()
    assert _sample_value(backup_path) == "original"
    assert record.sha256
    assert record.alembic_revision == "rev-1"

    records = list_backups(backup_directory=backup_dir)
    assert [row.name for row in records] == [record.name]
    assert records[0].actor == "tester"
    assert records[0].kind == "manual"


def test_restore_creates_pre_restore_backup_and_replaces_database_offline(tmp_path: Path):
    live = tmp_path / "live.sqlite3"
    restore_source = tmp_path / "restore-source.sqlite3"
    backup_dir = tmp_path / "backups"
    _create_db(live, revision="rev-1", value="current")
    _create_db(restore_source, revision="rev-1", value="restored")

    selected = create_sqlite_backup(
        source_path=restore_source,
        backup_directory=backup_dir,
        kind="manual",
        actor="tester",
    )

    pending = prepare_restore(
        selected.name,
        actor="tester",
        live_database_path=live,
        backup_directory=backup_dir,
    )
    assert pending["backup_name"] == selected.name
    assert pending["pre_restore_backup"].startswith("spareno-pre-restore-")

    # Simulate stale WAL/SHM files. They must disappear only after the offline swap.
    Path(f"{live}-wal").write_bytes(b"stale")
    Path(f"{live}-shm").write_bytes(b"stale")

    result = perform_pending_restore(
        live_database_path=live,
        backup_directory=backup_dir,
    )

    assert result is not None
    assert result["status"] == "success"
    assert _sample_value(live) == "restored"
    assert not Path(f"{live}-wal").exists()
    assert not Path(f"{live}-shm").exists()

    backups = list_backups(backup_directory=backup_dir)
    safety = [row for row in backups if row.kind == "pre-restore"]
    assert len(safety) == 1
    assert _sample_value(Path(safety[0].path)) == "current"

    history = list_restore_history(backup_directory=backup_dir)
    assert any(row.get("event") == "restore_requested" for row in history)
    assert any(row.get("event") == "restore_completed" for row in history)


def test_restore_rejects_schema_mismatch_before_live_data_changes(tmp_path: Path):
    live = tmp_path / "live.sqlite3"
    restore_source = tmp_path / "restore-source.sqlite3"
    backup_dir = tmp_path / "backups"
    _create_db(live, revision="rev-2", value="current")
    _create_db(restore_source, revision="rev-1", value="older-schema")

    selected = create_sqlite_backup(
        source_path=restore_source,
        backup_directory=backup_dir,
        kind="manual",
    )

    with pytest.raises(BackupError, match="Schema-Version"):
        prepare_restore(
            selected.name,
            live_database_path=live,
            backup_directory=backup_dir,
        )

    assert _sample_value(live) == "current"
    assert not (backup_dir / ".pending-restore.json").exists()
    assert not any(row.kind == "pre-restore" for row in list_backups(backup_directory=backup_dir))


def test_restore_rejects_path_traversal(tmp_path: Path):
    live = tmp_path / "live.sqlite3"
    backup_dir = tmp_path / "backups"
    _create_db(live)
    backup_dir.mkdir()

    with pytest.raises(BackupError, match="Dateiname"):
        prepare_restore(
            "../escape.sqlite3",
            live_database_path=live,
            backup_directory=backup_dir,
        )
