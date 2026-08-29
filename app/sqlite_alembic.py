"""Fail-safe onboarding of historical SQLite databases into Alembic."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import URL

from .db_transfer import (
    ALEMBIC_TABLE,
    MigrationSafetyError,
    schema_differences,
)
from .model_registry import metadata as application_metadata

BASELINE_REVISION = "20260825_01"
PREVIOUS_REVISION = "20260828_02"
TARGET_REVISION = "20260829_01"
HISTORICAL_REVISIONS = {
    BASELINE_REVISION,
    "20260825_02",
    "20260825_03",
    "20260826_01",
    "20260827_01",
    "20260828_01",
    PREVIOUS_REVISION,
}
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SQLiteAlembicPreparation:
    database_path: Path
    initial_revision: str | None
    final_revision: str | None
    applied: bool
    backup_path: Path | None
    action: str


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _immutable_database_uri(path: Path) -> str:
    return f"file:{path.as_posix()}?mode=ro&immutable=1"


def _immutable_source_engine(path: Path):
    url = URL.create(
        "sqlite+pysqlite",
        database=f"file:{path.as_posix()}",
        query={"mode": "ro", "immutable": "true", "uri": "true"},
    )
    return create_engine(url, connect_args={"check_same_thread": False}, future=True)


def _run_alembic(path: Path, *arguments: str) -> None:
    env = {**os.environ, "DATABASE_URL": _database_url(path)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise MigrationSafetyError(f"Alembic {' '.join(arguments)} failed: {detail}")


@lru_cache(maxsize=8)
def revision_metadata(revision: str) -> MetaData:
    """Reflect exactly one historical Alembic revision for semantic validation.

    Application metadata always represents the newest code. Historical database
    revisions therefore must be compared with the schema that actually existed
    at that revision, not with the current model registry.
    """

    with tempfile.TemporaryDirectory(prefix=f"lokero-alembic-{revision}-") as directory:
        target = Path(directory) / "revision.sqlite3"
        _run_alembic(target, "upgrade", revision)
        engine = create_engine(_database_url(target), future=True)
        try:
            expected = MetaData()
            expected.reflect(bind=engine)
        finally:
            engine.dispose()
    if ALEMBIC_TABLE in expected.tables:
        expected.remove(expected.tables[ALEMBIC_TABLE])
    return expected


@lru_cache(maxsize=1)
def baseline_metadata() -> MetaData:
    """Reflect the actual baseline revision instead of approximating old models."""

    return revision_metadata(BASELINE_REVISION)


def _sqlite_checks(path: Path) -> None:
    try:
        connection = sqlite3.connect(_immutable_database_uri(path), uri=True)
        try:
            integrity = [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()]
            if integrity != ["ok"]:
                raise MigrationSafetyError(f"SQLite integrity_check failed: {integrity!r}")
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                raise MigrationSafetyError(
                    f"SQLite foreign_key_check failed with {len(foreign_keys)} issue(s); first={tuple(foreign_keys[0])}"
                )
        finally:
            connection.close()
    except MigrationSafetyError:
        raise
    except sqlite3.DatabaseError as exc:
        raise MigrationSafetyError(f"SQLite database could not be validated: {exc}") from exc


def _revision(path: Path) -> str | None:
    try:
        connection = sqlite3.connect(_immutable_database_uri(path), uri=True)
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (ALEMBIC_TABLE,),
            ).fetchone()
            if not exists:
                return None
            rows = connection.execute(f"SELECT version_num FROM {ALEMBIC_TABLE}").fetchall()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise MigrationSafetyError(f"Invalid Alembic version table: {exc}") from exc
    if len(rows) != 1 or not rows[0][0]:
        raise MigrationSafetyError(f"Alembic version table must contain exactly one revision, found {rows!r}")
    return str(rows[0][0])


def _schema_checks(path: Path, revision: str | None) -> None:
    if revision is None:
        expected = baseline_metadata()
        expected_label = BASELINE_REVISION
    elif revision in HISTORICAL_REVISIONS:
        expected = revision_metadata(revision)
        expected_label = revision
    elif revision == TARGET_REVISION:
        expected = application_metadata()
        expected_label = TARGET_REVISION
    else:
        raise MigrationSafetyError(f"Unsupported Alembic revision: {revision}")
    engine = _immutable_source_engine(path)
    try:
        with engine.connect() as connection:
            differences = schema_differences(connection, expected_metadata=expected)
    finally:
        engine.dispose()
    if differences:
        raise MigrationSafetyError(
            f"SQLite schema differs from expected revision {expected_label}: " + "; ".join(differences)
        )


def _validate(path: Path) -> str | None:
    _sqlite_checks(path)
    revision = _revision(path)
    _schema_checks(path, revision)
    return revision


def _backup_database(source: Path, destination: Path) -> None:
    if destination.exists():
        raise MigrationSafetyError(f"Refusing to overwrite existing backup: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(_immutable_database_uri(source), uri=True)
        target_connection = sqlite3.connect(destination)
        source_connection.backup(target_connection)
        journal_mode = target_connection.execute("PRAGMA journal_mode=DELETE").fetchone()
        if not journal_mode or str(journal_mode[0]).lower() != "delete":
            raise MigrationSafetyError(
                f"Could not normalize backup journal mode to DELETE: {journal_mode!r}"
            )
        target_connection.commit()
        target_connection.close()
        target_connection = None
        _sqlite_checks(destination)
    except Exception:
        if target_connection is not None:
            target_connection.close()
            target_connection = None
        if source_connection is not None:
            source_connection.close()
            source_connection = None
        destination.unlink(missing_ok=True)
        raise
    finally:
        if source_connection is not None:
            source_connection.close()
        if target_connection is not None:
            target_connection.close()


def _default_backup_path(source: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return source.with_name(f"{source.name}.pre-alembic-{stamp}.bak")


def _assert_no_noncheckpointed_wal(source: Path) -> None:
    """Fail closed on WAL content; SHM alone is not proof of an active user.

    Open-handle detection is deliberately an operator precondition: Python has
    no portable, reliable way to enumerate other processes using a SQLite
    database. A stale SHM WAL-index can remain after a clean shutdown and must
    neither block preparation by itself nor be deleted automatically.
    """

    wal_path = Path(f"{source}-wal")
    if wal_path.exists() and wal_path.stat().st_size:
        raise MigrationSafetyError(
            f"Active/non-checkpointed WAL detected at {wal_path}; stop the application and checkpoint SQLite first"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _preserve_source_metadata(source: Path, staging: Path, source_stat: os.stat_result) -> None:
    """Keep replacement metadata, including POSIX ownership, fail-closed."""

    if hasattr(os, "chown"):
        os.chown(staging, source_stat.st_uid, source_stat.st_gid)
    shutil.copystat(source, staging)


def prepare_existing_sqlite_for_alembic(
    sqlite_path: str | Path,
    *,
    apply: bool = False,
    backup_path: str | Path | None = None,
) -> SQLiteAlembicPreparation:
    """Validate, safely stamp, and upgrade a historical baseline SQLite DB.

    Apply works on a verified staging copy. The source is atomically replaced
    only after the staging copy reaches the target revision and passes every
    integrity, foreign-key, and semantic schema check.
    """

    source = Path(sqlite_path).expanduser().resolve()
    if not source.is_file():
        raise MigrationSafetyError(f"SQLite database does not exist or is not a file: {source}")
    _assert_no_noncheckpointed_wal(source)
    initial_stat = source.stat()
    initial_revision = _validate(source)
    if initial_revision == TARGET_REVISION:
        return SQLiteAlembicPreparation(source, initial_revision, initial_revision, False, None, "already-current")
    if not apply:
        action = "stamp-baseline-and-upgrade" if initial_revision is None else "upgrade-baseline"
        return SQLiteAlembicPreparation(source, initial_revision, initial_revision, False, None, action)

    initial_sha256 = _sha256(source)

    backup = Path(backup_path).expanduser().resolve() if backup_path else _default_backup_path(source)
    if backup == source:
        raise MigrationSafetyError("Backup path must differ from the SQLite database path")
    _backup_database(source, backup)
    if _validate(backup) != initial_revision:
        raise MigrationSafetyError("Verified backup revision differs from the source revision")

    descriptor, staging_value = tempfile.mkstemp(
        prefix=f".{source.name}.alembic-",
        suffix=".sqlite3",
        dir=source.parent,
    )
    os.close(descriptor)
    staging = Path(staging_value)
    staging.unlink()
    try:
        _backup_database(source, staging)
        if _validate(staging) != initial_revision:
            raise MigrationSafetyError("Staging copy revision differs from the source revision")
        if initial_revision is None:
            _run_alembic(staging, "stamp", BASELINE_REVISION)
        _run_alembic(staging, "upgrade", TARGET_REVISION)
        final_revision = _validate(staging)
        if final_revision != TARGET_REVISION:
            raise MigrationSafetyError(
                f"Staging migration ended at {final_revision!r}, expected {TARGET_REVISION}"
            )
        current_stat = source.stat()
        initial_identity = (
            initial_stat.st_dev,
            initial_stat.st_ino,
            initial_stat.st_size,
            initial_stat.st_mtime_ns,
            initial_stat.st_ctime_ns,
            initial_stat.st_mode,
            initial_stat.st_uid,
            initial_stat.st_gid,
        )
        current_identity = (
            current_stat.st_dev,
            current_stat.st_ino,
            current_stat.st_size,
            current_stat.st_mtime_ns,
            current_stat.st_ctime_ns,
            current_stat.st_mode,
            current_stat.st_uid,
            current_stat.st_gid,
        )
        if current_identity != initial_identity or _sha256(source) != initial_sha256:
            raise MigrationSafetyError("Source SQLite database changed during preparation; refusing atomic replacement")
        _preserve_source_metadata(source, staging, initial_stat)
        os.replace(staging, source)
    finally:
        staging.unlink(missing_ok=True)

    return SQLiteAlembicPreparation(
        source,
        initial_revision,
        TARGET_REVISION,
        True,
        backup,
        "stamped-and-upgraded" if initial_revision is None else "upgraded-baseline",
    )
