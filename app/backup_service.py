from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .config import database_url, settings

BACKUP_FORMAT_VERSION = 1
RESTORE_CONFIRMATION = "WIEDERHERSTELLEN"
PENDING_RESTORE_FILENAME = ".pending-restore.json"
RESTORE_HISTORY_DIRNAME = "restore-history"


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupRecord:
    name: str
    path: str
    kind: str
    created_at: str
    size_bytes: int
    size_label: str
    sha256: str | None
    alembic_revision: str | None
    actor: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def configured_backup_dir() -> Path:
    return settings.backup_dir.expanduser().resolve()


def configured_sqlite_path() -> Path:
    url = database_url()
    if url.get_backend_name() != "sqlite":
        raise BackupError("Admin-Backups sind aktuell nur für SQLite aktiviert.")
    database = url.database
    if not database or database == ":memory:":
        raise BackupError("Die konfigurierte SQLite-Datenbank ist nicht dateibasiert.")
    path = Path(database).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path.resolve()


def _ensure_backup_dir(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _alembic_revision(path: Path) -> str | None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if not exists:
            return None
        row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
        return str(row[0]) if row and row[0] is not None else None
    finally:
        connection.close()


def _integrity_check(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError(f"SQLite integrity_check ist fehlgeschlagen: {result}")
    finally:
        connection.close()


def _metadata_path(backup_path: Path) -> Path:
    return backup_path.with_suffix(backup_path.suffix + ".json")


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError) as exc:
        raise BackupError(f"Metadaten konnten nicht gelesen werden: {path.name}") from exc
    if not isinstance(loaded, dict):
        raise BackupError(f"Ungültige Metadaten: {path.name}")
    return loaded


def _safe_backup_path(name: str, directory: Path) -> Path:
    if not name or Path(name).name != name or not name.endswith(".sqlite3"):
        raise BackupError("Ungültiger Backup-Dateiname.")
    root = _ensure_backup_dir(directory).resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise BackupError("Ungültiger Backup-Pfad.")
    if not target.is_file() or target.is_symlink():
        raise BackupError("Backup wurde nicht gefunden.")
    return target


def create_sqlite_backup(
    *,
    kind: str = "manual",
    actor: str | None = None,
    source_path: Path | None = None,
    backup_directory: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> BackupRecord:
    if kind not in {"manual", "pre-restore"}:
        raise BackupError("Unbekannter Backup-Typ.")

    source = (source_path or configured_sqlite_path()).expanduser().resolve()
    if not source.is_file():
        raise BackupError(f"SQLite-Datenbank nicht gefunden: {source}")

    directory = _ensure_backup_dir((backup_directory or configured_backup_dir()).expanduser().resolve())
    stamp = _now().strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"spareno-{kind}-{stamp}.sqlite3"
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")

    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(
            f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30
        )
        target_connection = sqlite3.connect(temporary, timeout=30)

        def _progress(status: int, remaining: int, total: int) -> None:
            if progress is not None:
                progress(max(total - remaining, 0), max(total, 0))

        source_connection.backup(
            target_connection,
            pages=4096,
            progress=_progress,
            sleep=0.02,
        )
        result = target_connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError(f"Backup integrity_check ist fehlgeschlagen: {result}")
        target_connection.commit()
        target_connection.close()
        target_connection = None

        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)

        checksum = _sha256(target)
        created_at = _iso_now()
        revision = _alembic_revision(target)
        size_bytes = target.stat().st_size
        metadata = {
            "format_version": BACKUP_FORMAT_VERSION,
            "type": "sqlite",
            "kind": kind,
            "created_at": created_at,
            "source_name": source.name,
            "size_bytes": size_bytes,
            "sha256": checksum,
            "alembic_revision": revision,
            "actor": actor,
        }
        _atomic_write_json(_metadata_path(target), metadata)
        return BackupRecord(
            name=target.name,
            path=str(target),
            kind=kind,
            created_at=created_at,
            size_bytes=size_bytes,
            size_label=_human_bytes(size_bytes),
            sha256=checksum,
            alembic_revision=revision,
            actor=actor,
        )
    except Exception:
        target.unlink(missing_ok=True)
        _metadata_path(target).unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if source_connection is not None:
            source_connection.close()
        if target_connection is not None:
            target_connection.close()


def list_backups(*, backup_directory: Path | None = None) -> list[BackupRecord]:
    directory = _ensure_backup_dir((backup_directory or configured_backup_dir()).expanduser().resolve())
    records: list[BackupRecord] = []
    for path in directory.glob("spareno-*.sqlite3"):
        if not path.is_file() or path.is_symlink():
            continue
        metadata: dict = {}
        sidecar = _metadata_path(path)
        if sidecar.is_file():
            try:
                metadata = _read_json(sidecar)
            except BackupError:
                metadata = {}
        stat = path.stat()
        created_at = str(metadata.get("created_at") or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat())
        records.append(
            BackupRecord(
                name=path.name,
                path=str(path),
                kind=str(metadata.get("kind") or "legacy"),
                created_at=created_at,
                size_bytes=stat.st_size,
                size_label=_human_bytes(stat.st_size),
                sha256=str(metadata.get("sha256")) if metadata.get("sha256") else None,
                alembic_revision=str(metadata.get("alembic_revision")) if metadata.get("alembic_revision") else None,
                actor=str(metadata.get("actor")) if metadata.get("actor") else None,
            )
        )
    records.sort(key=lambda row: row.created_at, reverse=True)
    return records


def backup_storage(*, backup_directory: Path | None = None) -> dict:
    directory = _ensure_backup_dir((backup_directory or configured_backup_dir()).expanduser().resolve())
    usage = shutil.disk_usage(directory)
    records = list_backups(backup_directory=directory)
    used_by_backups = sum(row.size_bytes for row in records)
    return {
        "path": str(directory),
        "count": len(records),
        "backup_bytes": used_by_backups,
        "backup_label": _human_bytes(used_by_backups),
        "total_bytes": usage.total,
        "total_label": _human_bytes(usage.total),
        "free_bytes": usage.free,
        "free_label": _human_bytes(usage.free),
    }


def _pending_restore_path(directory: Path) -> Path:
    return directory / PENDING_RESTORE_FILENAME


def _restore_history_dir(directory: Path) -> Path:
    return directory / RESTORE_HISTORY_DIRNAME


def _write_restore_history(directory: Path, payload: dict) -> None:
    history_dir = _restore_history_dir(directory)
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = _now().strftime("%Y%m%dT%H%M%S%fZ")
    _atomic_write_json(history_dir / f"restore-{stamp}.json", payload)


def list_restore_history(*, backup_directory: Path | None = None, limit: int = 20) -> list[dict]:
    directory = _ensure_backup_dir((backup_directory or configured_backup_dir()).expanduser().resolve())
    history_dir = _restore_history_dir(directory)
    if not history_dir.exists():
        return []
    rows: list[dict] = []
    for path in sorted(history_dir.glob("restore-*.json"), reverse=True):
        try:
            payload = _read_json(path)
        except BackupError:
            continue
        payload["history_file"] = path.name
        rows.append(payload)
        if len(rows) >= limit:
            break
    return rows


def prepare_restore(
    backup_name: str,
    *,
    actor: str | None = None,
    live_database_path: Path | None = None,
    backup_directory: Path | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    directory = _ensure_backup_dir((backup_directory or configured_backup_dir()).expanduser().resolve())
    pending = _pending_restore_path(directory)
    if pending.exists():
        raise BackupError("Es ist bereits eine Wiederherstellung vorgemerkt.")

    live = (live_database_path or configured_sqlite_path()).expanduser().resolve()
    if not live.is_file():
        raise BackupError("Die aktuelle SQLite-Datenbank wurde nicht gefunden.")
    selected = _safe_backup_path(backup_name, directory)

    if progress:
        progress("Backup wird geprüft", 5)
    _integrity_check(selected)

    metadata_path = _metadata_path(selected)
    metadata = _read_json(metadata_path) if metadata_path.is_file() else {}
    expected_checksum = str(metadata.get("sha256")) if metadata.get("sha256") else None
    actual_checksum = _sha256(selected)
    if expected_checksum and actual_checksum != expected_checksum:
        raise BackupError("Die SHA-256-Prüfsumme des Backups stimmt nicht mehr.")

    selected_revision = _alembic_revision(selected)
    live_revision = _alembic_revision(live)
    if selected_revision != live_revision:
        raise BackupError(
            "Die Schema-Version des Backups passt nicht zur aktuell laufenden Anwendung "
            f"(Backup: {selected_revision or 'keine'}, aktuell: {live_revision or 'keine'})."
        )

    if progress:
        progress("Sicherheitsbackup der aktuellen Datenbank wird erstellt", 15)

    safety = create_sqlite_backup(
        kind="pre-restore",
        actor=actor,
        source_path=live,
        backup_directory=directory,
        progress=(
            (lambda done, total: progress("Sicherheitsbackup wird erstellt", 15 + int((done / total) * 60)) if total else None)
            if progress
            else None
        ),
    )

    data_usage = shutil.disk_usage(live.parent)
    required_for_restore = selected.stat().st_size + 256 * 1024 * 1024
    if data_usage.free < required_for_restore:
        raise BackupError(
            "Zu wenig freier Speicher für die atomare Wiederherstellung. "
            f"Benötigt werden mindestens {_human_bytes(required_for_restore)}, frei sind {_human_bytes(data_usage.free)}."
        )

    if progress:
        progress("Wiederherstellung wird vorgemerkt", 85)
    payload = {
        "format_version": BACKUP_FORMAT_VERSION,
        "status": "pending",
        "requested_at": _iso_now(),
        "requested_by": actor,
        "backup_name": selected.name,
        "backup_sha256": actual_checksum,
        "backup_alembic_revision": selected_revision,
        "pre_restore_backup": safety.name,
    }
    _atomic_write_json(pending, payload)
    _write_restore_history(directory, {**payload, "event": "restore_requested"})
    if progress:
        progress("Container-Neustart wird vorbereitet", 95)
    return payload


def perform_pending_restore(
    *,
    live_database_path: Path | None = None,
    backup_directory: Path | None = None,
) -> dict | None:
    directory = _ensure_backup_dir((backup_directory or configured_backup_dir()).expanduser().resolve())
    pending = _pending_restore_path(directory)
    if not pending.is_file():
        return None

    payload = _read_json(pending)
    live = (live_database_path or configured_sqlite_path()).expanduser().resolve()
    live.parent.mkdir(parents=True, exist_ok=True)
    temporary = live.with_name(f".{live.name}.restore-{uuid4().hex}.tmp")
    replaced = False
    try:
        selected = _safe_backup_path(str(payload.get("backup_name") or ""), directory)
        expected_checksum = str(payload.get("backup_sha256") or "")
        actual_checksum = _sha256(selected)
        if not expected_checksum or actual_checksum != expected_checksum:
            raise BackupError("Pending-Restore-Prüfsumme stimmt nicht mit dem Backup überein.")
        _integrity_check(selected)

        if live.exists():
            selected_revision = _alembic_revision(selected)
            live_revision = _alembic_revision(live)
            if selected_revision != live_revision:
                raise BackupError(
                    "Pending Restore abgebrochen: Schema-Versionen unterscheiden sich."
                )

        shutil.copy2(selected, temporary)
        _integrity_check(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())

        os.replace(temporary, live)
        replaced = True
        for suffix in ("-wal", "-shm"):
            Path(f"{live}{suffix}").unlink(missing_ok=True)
        try:
            directory_fd = os.open(live.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass

        completed = {
            **payload,
            "status": "success",
            "event": "restore_completed",
            "completed_at": _iso_now(),
        }
        pending.unlink(missing_ok=True)
        _write_restore_history(directory, completed)
        return completed
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        failed = {
            **payload,
            "status": "failed_after_replace" if replaced else "failed",
            "event": "restore_failed",
            "failed_at": _iso_now(),
            "error": str(exc),
        }
        pending.unlink(missing_ok=True)
        try:
            _write_restore_history(directory, failed)
        except Exception:
            pass
        if replaced:
            return failed
        raise
