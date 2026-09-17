from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import _admin
from .beta_market_scope import is_beta_retailer
from .db import get_db
from .market_admin_delete import preview_false_store_delete, delete_false_store
from .models import Store
from .physical_market_identity import (
    alias_groups,
    canonical_store_map,
    is_weak_discovery_store,
    normalized_address,
    official_retailer_id,
)

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()

_ALIAS_OFFICIAL_ID = "official_id"
_ALIAS_ADDRESS = "address"
_ALIAS_WEAK_MAP = "weak_map_proximity"
_ALIAS_AMBIGUOUS = "ambiguous"
_CONFIRMED_ALIAS_KINDS = {_ALIAS_OFFICIAL_ID, _ALIAS_ADDRESS}


def _alias_kind(canonical: Store, alias: Store) -> str:
    """Classify why an alias belongs to a canonical physical market.

    Equal retailer IDs and exact normalized addresses are confirmed identity
    evidence. Only a weak OSM/Map row that joined through the conservative
    proximity rule is a possible false-market candidate. Unknown shapes remain
    fail-closed and are never eligible for hard delete from this page.
    """
    alias_official_id = official_retailer_id(alias)
    if (
        alias_official_id
        and alias_official_id == official_retailer_id(canonical)
    ):
        return _ALIAS_OFFICIAL_ID
    if normalized_address(alias) == normalized_address(canonical):
        return _ALIAS_ADDRESS
    if is_weak_discovery_store(alias):
        return _ALIAS_WEAK_MAP
    return _ALIAS_AMBIGUOUS


def _alias_reason(kind: str) -> str:
    return {
        _ALIAS_OFFICIAL_ID: "gleiche offizielle Händler-ID",
        _ALIAS_ADDRESS: "gleiche konfliktfreie normalisierte Adresse",
        _ALIAS_WEAK_MAP: "eindeutiger naher OSM/Map-Alias zu starker Händleridentität",
        _ALIAS_AMBIGUOUS: "Alias-Zuordnung ohne löschbare schwache Map-Evidenz",
    }[kind]


def _market_identity_view_model(db: Session) -> dict:
    stores = db.query(Store).order_by(
        Store.retailer,
        Store.postal_code,
        Store.city,
        Store.name,
    ).all()
    groups = alias_groups(stores)
    mapping = canonical_store_map(stores)
    previews = {store.id: preview_false_store_delete(db, store) for store in stores}

    confirmed_aliases: list[dict] = []
    possible_false_markets: list[dict] = []
    for group in groups:
        for alias in group.aliases:
            kind = _alias_kind(group.canonical, alias)
            row = {
                "canonical": group.canonical,
                "alias": alias,
                "kind": kind,
                "reason": _alias_reason(kind),
                "preview": previews[alias.id],
                "delete_allowed": (
                    kind == _ALIAS_WEAK_MAP and previews[alias.id].allowed
                ),
            }
            if kind in _CONFIRMED_ALIAS_KINDS:
                confirmed_aliases.append(row)
            else:
                possible_false_markets.append(row)

    members_by_canonical_id: dict[int, list[Store]] = {}
    canonical_by_id: dict[int, Store] = {}
    for store in stores:
        canonical = mapping[store.id]
        canonical_by_id[canonical.id] = canonical
        members_by_canonical_id.setdefault(canonical.id, []).append(store)

    market_rows: list[dict] = []
    for canonical_id, members in members_by_canonical_id.items():
        canonical = canonical_by_id[canonical_id]
        public = any(
            bool(member.active and member.benchmark_verified)
            for member in members
        )
        verified = any(bool(member.benchmark_verified) for member in members)
        active = any(bool(member.active) for member in members)
        if public:
            status = "public"
        elif verified:
            status = "verified_inactive"
        elif active:
            status = "active_unverified"
        else:
            status = "pre_public"
        market_rows.append({
            "store": canonical,
            "members": tuple(members),
            "alias_count": len(members) - 1,
            "public": public,
            "verified": verified,
            "active": active,
            "status": status,
            "beta_scope": is_beta_retailer(canonical.retailer),
        })

    market_rows.sort(key=lambda row: (
        row["store"].retailer or "",
        row["store"].postal_code or "",
        row["store"].city or "",
        row["store"].name or "",
    ))
    return {
        "confirmed_aliases": confirmed_aliases,
        "possible_false_markets": possible_false_markets,
        "market_rows": market_rows,
    }


def _weak_map_alias_target(stores: list[Store], store_id: int) -> tuple[Store, Store] | None:
    """Return canonical/alias only for a proximity-bound weak Map alias."""
    for group in alias_groups(stores):
        for alias in group.aliases:
            if alias.id != store_id:
                continue
            if _alias_kind(group.canonical, alias) == _ALIAS_WEAK_MAP:
                return group.canonical, alias
            return None
    return None


@router.get("/admin/market-identities")
def market_identity_admin(
    request: Request,
    result: str = "",
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    view = _market_identity_view_model(db)
    return templates.TemplateResponse(
        "admin_market_identities.html",
        {
            "request": request,
            "actor": actor,
            "admin_section": "market_identities",
            **view,
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
    if confirm != "LOESCHEN":
        raise HTTPException(400, "Zum endgültigen Löschen exakt LOESCHEN eingeben")

    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Markt nicht gefunden")

    stores = db.query(Store).all()
    target = _weak_map_alias_target(stores, store_id)
    if target is None:
        raise HTTPException(
            409,
            "Nur eindeutig zugeordnete schwache OSM/Map-Aliase dürfen hier "
            "als Fehlmarkt dauerhaft gelöscht werden. Bestätigte Händler-ID- "
            "oder Adress-Aliase bleiben erhalten.",
        )

    canonical, alias = target
    label = (
        f"{alias.retailer} | {alias.name} | {alias.address} | "
        f"canonical_store:{canonical.id}"
    )
    preview = delete_false_store(db, alias)
    if not preview.allowed:
        raise HTTPException(
            400,
            "Markt kann nicht hart gelöscht werden: " + "; ".join(preview.blockers),
        )
    audit(db, "false_store_deleted", "store", store_id, label, actor)
    db.commit()
    return RedirectResponse(
        f"/admin/market-identities?result=store:{store_id}:deleted",
        status_code=303,
    )
