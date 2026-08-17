from __future__ import annotations

import secrets
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .admin_learning import apply_product_correction, audit
from .admin_quality import build_quality_report
from .clock import app_today
from .config import settings
from .db import get_db
from .freshness import market_freshness
from .models import (
    AdminAuditLog,
    AdminSetting,
    CollectionRun,
    MasterProduct,
    MediaAsset,
    Offer,
    ProductAdminData,
    ProductAlias,
    ProductBarcode,
    ProductCategory,
    Store,
)

BASE = Path(__file__).resolve().parent
MEDIA_DIR = settings.data_dir / "admin_media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=BASE / "templates")
security = HTTPBasic(auto_error=False)
router = APIRouter()


def _admin(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    if not settings.admin_password:
        raise HTTPException(status_code=503, detail="Adminbereich ist nicht konfiguriert. ADMIN_PASSWORD setzen.")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value or "kategorie"


def _dashboard(db: Session):
    today = app_today()
    products = db.query(MasterProduct).count()
    stores = db.query(Store).count()
    active_stores = db.query(Store).filter(Store.active.is_(True)).count()
    current_offers = db.query(Offer).filter(Offer.valid_from <= today, Offer.valid_to >= today).count()
    corrected = db.query(ProductAdminData).filter(ProductAdminData.name_locked.is_(True)).count()
    aliases = db.query(ProductAlias).count()
    media = db.query(MediaAsset).filter(MediaAsset.active.is_(True)).count()
    runs = db.query(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(10).all()
    return {
        "products": products,
        "stores": stores,
        "active_stores": active_stores,
        "current_offers": current_offers,
        "corrected": corrected,
        "aliases": aliases,
        "media": media,
        "runs": runs,
        "freshness": market_freshness(db),
    }


@router.get("/admin")
def admin_dashboard(request: Request, tab: str = "dashboard", q: str = "", db: Session = Depends(get_db), actor: str = Depends(_admin)):
    categories = db.query(ProductCategory).order_by(ProductCategory.sort_order, ProductCategory.name).all()
    context = {
        "request": request,
        "tab": tab,
        "q": q,
        "actor": actor,
        "dashboard": _dashboard(db),
        "categories": categories,
        "settings_runtime": settings,
    }
    if tab == "products":
        query = db.query(MasterProduct)
        if q.strip():
            query = query.filter(MasterProduct.name.ilike(f"%{q.strip()}%"))
        products = query.order_by(MasterProduct.name).limit(250).all()
        metas = {x.master_product_id: x for x in db.query(ProductAdminData).filter(ProductAdminData.master_product_id.in_([p.id for p in products])).all()} if products else {}
        barcodes = {}
        for row in db.query(ProductBarcode).filter(ProductBarcode.master_product_id.in_([p.id for p in products])).all() if products else []:
            barcodes.setdefault(row.master_product_id, []).append(row.barcode)
        context.update({"products": products, "metas": metas, "barcodes": barcodes})
    elif tab == "stores":
        context["stores_list"] = db.query(Store).order_by(Store.retailer, Store.city, Store.name).all()
    elif tab == "quality":
        context["quality"] = build_quality_report(db)
    elif tab == "media":
        context["media_assets"] = db.query(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(300).all()
        context["stores_list"] = db.query(Store).order_by(Store.name).all()
        context["products"] = db.query(MasterProduct).order_by(MasterProduct.name).limit(500).all()
        context["retailers"] = [r[0] for r in db.query(Store.retailer).distinct().order_by(Store.retailer).all()]
    elif tab == "settings":
        context["admin_settings"] = db.query(AdminSetting).order_by(AdminSetting.key).all()
    elif tab == "audit":
        context["audit_rows"] = db.query(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(250).all()
    return templates.TemplateResponse("admin.html", context)


@router.post("/admin/products/{product_id}")
def update_product(product_id: int, name: str = Form(...), brand: str = Form(""), package_size: str = Form(""), category_id: str = Form(""), notes: str = Form(""), db: Session = Depends(get_db), actor: str = Depends(_admin)):
    product = db.get(MasterProduct, product_id)
    if not product:
        raise HTTPException(404, "Artikel nicht gefunden")
    cat_id = int(category_id) if category_id.strip().isdigit() else None
    apply_product_correction(db, product, name=name, brand=brand, package_size=package_size, category_id=cat_id, notes=notes)
    db.commit()
    return RedirectResponse(f"/admin?tab=products&q={product.name}", status_code=303)


@router.post("/admin/stores/{store_id}/toggle")
def admin_toggle_store(store_id: int, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Markt nicht gefunden")
    store.active = not store.active
    audit(db, "store_activated" if store.active else "store_deactivated", "store", store.id, store.name, actor)
    db.commit()
    return RedirectResponse("/admin?tab=stores", status_code=303)


@router.post("/admin/stores/{store_id}")
def update_store(store_id: int, name: str = Form(...), address: str = Form(...), postal_code: str = Form(...), city: str = Form(...), source_url: str = Form(""), external_id: str = Form(""), db: Session = Depends(get_db), actor: str = Depends(_admin)):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(404, "Markt nicht gefunden")
    store.name = name.strip()
    store.address = address.strip()
    store.postal_code = postal_code.strip()
    store.city = city.strip()
    store.source_url = source_url.strip() or None
    store.external_id = external_id.strip() or None
    audit(db, "store_updated", "store", store.id, store.name, actor)
    db.commit()
    return RedirectResponse("/admin?tab=stores", status_code=303)


@router.post("/admin/categories")
def create_category(name: str = Form(...), sort_order: int = Form(100), db: Session = Depends(get_db), actor: str = Depends(_admin)):
    cleaned = name.strip()
    if cleaned and not db.query(ProductCategory).filter(func.lower(ProductCategory.name) == cleaned.lower()).first():
        slug = _slug(cleaned)
        base = slug
        n = 2
        while db.query(ProductCategory).filter(ProductCategory.slug == slug).first():
            slug = f"{base}-{n}"; n += 1
        row = ProductCategory(name=cleaned, slug=slug, sort_order=sort_order)
        db.add(row); db.flush()
        audit(db, "category_created", "category", row.id, cleaned, actor)
        db.commit()
    return RedirectResponse("/admin?tab=categories", status_code=303)


@router.post("/admin/categories/{category_id}")
def update_category(category_id: int, name: str = Form(...), sort_order: int = Form(100), active: str = Form("0"), db: Session = Depends(get_db), actor: str = Depends(_admin)):
    row = db.get(ProductCategory, category_id)
    if not row:
        raise HTTPException(404, "Kategorie nicht gefunden")
    row.name = name.strip(); row.sort_order = sort_order; row.active = active == "1"
    audit(db, "category_updated", "category", row.id, row.name, actor)
    db.commit()
    return RedirectResponse("/admin?tab=categories", status_code=303)


@router.post("/admin/media")
async def upload_media(kind: str = Form(...), product_id: str = Form(""), store_id: str = Form(""), retailer: str = Form(""), alt_text: str = Form(""), source_url: str = Form(""), primary: str = Form("0"), file: UploadFile | None = File(None), db: Session = Depends(get_db), actor: str = Depends(_admin)):
    if kind not in {"product", "store", "retailer_logo"}:
        raise HTTPException(400, "Ungültiger Medientyp")
    local_path = None
    mime = None
    if file and file.filename:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise HTTPException(400, "Nur JPG, PNG, WEBP oder GIF erlaubt")
        data = await file.read()
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(400, "Datei ist größer als 8 MB")
        filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}{suffix}"
        (MEDIA_DIR / filename).write_bytes(data)
        local_path = filename
        mime = file.content_type
    pid = int(product_id) if product_id.strip().isdigit() else None
    sid = int(store_id) if store_id.strip().isdigit() else None
    is_primary = primary == "1"
    if is_primary:
        q = db.query(MediaAsset).filter(MediaAsset.kind == kind)
        if pid: q = q.filter(MediaAsset.master_product_id == pid)
        if sid: q = q.filter(MediaAsset.store_id == sid)
        if retailer.strip(): q = q.filter(MediaAsset.retailer == retailer.strip())
        for existing in q.all(): existing.is_primary = False
    row = MediaAsset(kind=kind, master_product_id=pid, store_id=sid, retailer=retailer.strip() or None, file_path=local_path, source_url=source_url.strip() or None, alt_text=alt_text.strip() or None, mime_type=mime, is_primary=is_primary, active=True)
    db.add(row); db.flush(); audit(db, "media_added", "media", row.id, f"kind={kind}", actor); db.commit()
    return RedirectResponse("/admin?tab=media", status_code=303)


@router.post("/admin/media/{media_id}/toggle")
def toggle_media(media_id: int, db: Session = Depends(get_db), actor: str = Depends(_admin)):
    row = db.get(MediaAsset, media_id)
    if not row: raise HTTPException(404, "Medium nicht gefunden")
    row.active = not row.active
    audit(db, "media_toggled", "media", row.id, f"active={row.active}", actor); db.commit()
    return RedirectResponse("/admin?tab=media", status_code=303)


@router.get("/admin-media/{filename}")
def admin_media_file(filename: str, actor: str = Depends(_admin)):
    safe = Path(filename).name
    target = MEDIA_DIR / safe
    if not target.exists(): raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(target)


@router.post("/admin/settings")
def save_setting(key: str = Form(...), value: str = Form(""), description: str = Form(""), db: Session = Depends(get_db), actor: str = Depends(_admin)):
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "", key.strip())[:120]
    if not cleaned: raise HTTPException(400, "Ungültiger Schlüssel")
    row = db.get(AdminSetting, cleaned)
    if not row:
        row = AdminSetting(key=cleaned); db.add(row)
    row.value = value; row.description = description.strip() or None; row.updated_at = datetime.utcnow()
    audit(db, "setting_saved", "setting", cleaned, value[:200], actor); db.commit()
    return RedirectResponse("/admin?tab=settings", status_code=303)
