from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .admin_routes import _admin
from .backup_service import (
    BackupError,
    RESTORE_CONFIRMATION,
    backup_storage,
    configured_backup_dir,
    create_sqlite_backup,
    list_backups,
    list_restore_history,
    prepare_restore,
)
from .config import database_url, settings

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()

_operation_lock = threading.Lock()
_state_lock = threading.Lock()
_operation_state: dict = {
    "status": "idle",
    "kind": None,
    "message": None,
    "progress": 0,
    "error": None,
    "backup_name": None,
}


def _set_state(**values) -> None:
    with _state_lock:
        _operation_state.update(values)


def _state() -> dict:
    with _state_lock:
        return dict(_operation_state)


def _reserve_operation(kind: str, backup_name: str | None = None) -> None:
    if not _operation_lock.acquire(blocking=False):
        raise HTTPException(409, "Es läuft bereits eine Backup- oder Restore-Operation.")
    _set_state(
        status="running",
        kind=kind,
        message="Operation wird vorbereitet",
        progress=1,
        error=None,
        backup_name=backup_name,
    )


def _run_manual_backup(actor: str) -> None:
    try:
        def progress(done: int, total: int) -> None:
            percent = int((done / total) * 85) if total else 0
            _set_state(
                status="running",
                kind="backup",
                message="Datenbank wird konsistent gesichert",
                progress=min(90, 5 + percent),
            )

        record = create_sqlite_backup(kind="manual", actor=actor, progress=progress)
        _set_state(
            status="success",
            kind="backup",
            message=f"Backup {record.name} wurde erstellt und geprüft.",
            progress=100,
            error=None,
            backup_name=record.name,
        )
    except Exception as exc:
        _set_state(
            status="failed",
            kind="backup",
            message="Backup konnte nicht erstellt werden.",
            progress=0,
            error=str(exc),
        )
    finally:
        _operation_lock.release()


def _run_restore(backup_name: str, actor: str) -> None:
    restart_required = False
    try:
        def progress(message: str, percent: int) -> None:
            _set_state(
                status="running",
                kind="restore",
                message=message,
                progress=max(0, min(99, percent)),
                backup_name=backup_name,
            )

        prepare_restore(
            backup_name,
            actor=actor,
            progress=progress,
        )
        restart_required = settings.backup_restore_restart
        _set_state(
            status="restart" if restart_required else "prepared",
            kind="restore",
            message=(
                "Sicherheitsbackup erstellt. Der App-Container wird jetzt neu gestartet und stellt das ausgewählte Backup offline wieder her."
                if restart_required
                else "Wiederherstellung vorgemerkt. Für die eigentliche Wiederherstellung muss der App-Prozess neu gestartet werden."
            ),
            progress=100,
            error=None,
            backup_name=backup_name,
        )
    except Exception as exc:
        _set_state(
            status="failed",
            kind="restore",
            message="Wiederherstellung wurde vor jeder Datenänderung abgebrochen.",
            progress=0,
            error=str(exc),
            backup_name=backup_name,
        )
    finally:
        _operation_lock.release()

    if restart_required:
        time.sleep(1.5)
        os.kill(os.getpid(), signal.SIGTERM)


def _page_context(request: Request, actor: str) -> dict:
    backend = database_url().get_backend_name()
    error = None
    backups = []
    storage = None
    restore_history = []
    try:
        storage = backup_storage()
        backups = list_backups()
        restore_history = list_restore_history(limit=10)
    except (BackupError, OSError) as exc:
        error = str(exc)

    return {
        "request": request,
        "actor": actor,
        "admin_section": "backups",
        "backend": backend,
        "supported": backend == "sqlite",
        "backup_dir": str(configured_backup_dir()),
        "storage": storage,
        "backups": backups,
        "restore_history": restore_history,
        "operation": _state(),
        "page_error": error,
        "restore_confirmation": RESTORE_CONFIRMATION,
        "auto_restart": settings.backup_restore_restart,
    }


@router.get("/admin/backups")
def admin_backups(request: Request, actor: str = Depends(_admin)):
    return templates.TemplateResponse("admin_backups.html", _page_context(request, actor))


@router.post("/admin/backups/create")
def admin_create_backup(
    background_tasks: BackgroundTasks,
    actor: str = Depends(_admin),
):
    if database_url().get_backend_name() != "sqlite":
        raise HTTPException(409, "Manuelle Admin-Backups sind aktuell nur für SQLite aktiviert.")
    _reserve_operation("backup")
    background_tasks.add_task(_run_manual_backup, actor)
    return RedirectResponse("/admin/backups", status_code=303)


@router.post("/admin/backups/restore")
def admin_restore_backup(
    background_tasks: BackgroundTasks,
    backup_name: str = Form(...),
    confirmation: str = Form(...),
    actor: str = Depends(_admin),
):
    if database_url().get_backend_name() != "sqlite":
        raise HTTPException(409, "Admin-Restore ist aktuell nur für SQLite aktiviert.")
    if confirmation.strip() != RESTORE_CONFIRMATION:
        raise HTTPException(
            400,
            f"Zur Bestätigung muss exakt {RESTORE_CONFIRMATION} eingegeben werden.",
        )
    _reserve_operation("restore", backup_name)
    background_tasks.add_task(_run_restore, backup_name, actor)
    return RedirectResponse("/admin/backups", status_code=303)
