from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_routes import _admin
from .config import settings
from .db import get_db
from .data_operations import build_data_operations

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/datenstatus")
def admin_data_status(request: Request, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    operations = build_data_operations(db, stale_after_hours=settings.stale_after_hours)
    return templates.TemplateResponse("admin_data_status.html", {
        "request": request,
        "actor": actor,
        "admin_section": "data_status",
        **operations,
        "scheduler_enabled": settings.scheduler_enabled,
        "stale_after_hours": settings.stale_after_hours,
    })
