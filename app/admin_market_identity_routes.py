from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import _admin
from .db import get_db
from .market_admin_delete import delete_false_store, preview_false_store_delete
from .models import Store
from .physical_market_identity import alias_groups, canonical_store_map

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/market-identities")
def market_identity_admin(
    request: Request,
    result: str = "",
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    rows = db.query(Store).order_by(Store.retailer, Store.postal_code, Store.city, Store.name).all()
    groups = alias_groups(rows)
    mapping = canonical_store_map(rows)
    hidden_ids = {alias.id for group in groups for alias in group.aliases}
    standalone = [row for row in rows if row.id not in hidden_ids and mapping[row.id].id == row.id]
    previews = {
        row.id: preview_false_store_delete(db, row)
        for row in rows
    }
    return templates.TemplateResponse(
        "admin_market_identities.html",
        {
            "request": request,
            "actor": actor,
            "admin_section": "stores",
            "groups": groups,
            "standalone": standalone,
            "previews": previews,
            "result": result,
        },
    )


@router.post("/admin/market-identities/{store_id}/delete")
def delete_false_market(
    store_id: int,
    confirm: str = Form(...),
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    if confirm != "DELETE":
        raise HTTPException(400, "Löschbestätigung fehlt")
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Markt nicht gefunden")

    name = store.name
    preview = delete_false_store(db, store)
    if not preview.allowed:
        raise HTTPException(
            400,
            "Markt kann nicht hart gelöscht werden: " + "; ".join(preview.blockers),
        )
    audit(db, "false_store_deleted", "store", store_id, name, actor)
    db.commit()
    return RedirectResponse(
        f"/admin/market-identities?result=store:{store_id}:deleted",
        status_code=303,
    )
