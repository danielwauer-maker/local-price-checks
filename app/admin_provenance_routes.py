from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_quality import build_prospect_provenance_report
from .admin_routes import _admin
from .db import get_db

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/quality/provenance")
def prospect_provenance_quality(
    request: Request,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    report = build_prospect_provenance_report(db)
    return templates.TemplateResponse(
        "admin_provenance.html",
        {"request": request, "actor": actor, "report": report},
    )


@router.get("/admin/quality/provenance.json")
def prospect_provenance_quality_json(
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    return build_prospect_provenance_report(db)
