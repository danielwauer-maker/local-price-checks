from __future__ import annotations

import json
import re
from typing import Any

from . import lidl_manifest as legacy
from .collectors import CollectedOffer, cat, clean_product_name, compute_unit_price, parse_lidl_text, product_name_issue, size

_ONLINE_MARKERS = (
    "shoppe auf lidl.de",
    "nur online",
    "online only",
    "nur im onlineshop",
    "onlineshop",
)


def _money_from(obj: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in obj:
            value = legacy._money(obj.get(key))
            if value is not None:
                return value
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(v) for v in value if v is not None)
    if isinstance(value, dict):
        return "\n".join(_text(v) for v in value.values() if isinstance(v, (str, int, float)))
    return str(value)


def _page_text(page: dict) -> str:
    parts = [
        _text(page.get("altText")),
        _text(page.get("keyWords")),
    ]
    for link in page.get("links") or []:
        if isinstance(link, dict):
            parts.extend((_text(link.get("title")), _text(link.get("label"))))
    return "\n".join(p for p in parts if p).strip()


def _page_online_only(page: dict) -> bool:
    low = _page_text(page).lower()
    return any(marker in low for marker in _ONLINE_MARKERS)


def _product_online_only(product: dict, page: dict) -> bool:
    if _page_online_only(page):
        return True
    if legacy._online_only(product):
        return True
    raw = json.dumps(product, ensure_ascii=False, default=str).lower()
    return any(marker in raw for marker in _ONLINE_MARKERS)


def _catalog_by_product_id(flyer: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    products = flyer.get("products") or {}
    values = products.values() if isinstance(products, dict) else products if isinstance(products, list) else []
    for product in values:
        if not isinstance(product, dict):
            continue
        ident = legacy._identifier(product.get("productId"))
        if ident:
            result[ident] = product
    return result


def _iter_schwarz_flyers(payloads: list[dict]):
    for payload in payloads:
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        flyer = data.get("flyer")
        if isinstance(flyer, dict) and isinstance(flyer.get("pages"), list):
            yield flyer


def _build_offer(source, *, name: str, price: float, regular: float | None, page_no: int, raw_obj: Any, valid_from: str, valid_to: str, local: bool, source_kind: str) -> CollectedOffer | None:
    cleaned = clean_product_name(name)
    if not cleaned or product_name_issue(cleaned) or len(cleaned) < 3:
        return None
    q, unit = size(cleaned)
    raw = json.dumps(raw_obj, ensure_ascii=False, default=str, separators=(",", ":"))[:3000]
    offer = CollectedOffer(
        source.key,
        source.store_name,
        source.retailer,
        cleaned[:180],
        cat(cleaned),
        price,
        regular_price=regular,
        quantity=q,
        unit=unit,
        valid_from=valid_from,
        valid_to=valid_to,
        source_text=f"PDF Seite {page_no}: {source_kind} {raw}",
        source_url=source.url,
        local_store_offer=local,
        confidence=.99 if local else .95,
    )
    if offer.unit_price is None:
        offer.unit_price, offer.unit_price_unit = compute_unit_price(price, q, unit)
    return offer


def _offers_from_product_links(flyer: dict, source, valid_from: str, valid_to: str) -> list[CollectedOffer]:
    catalog = _catalog_by_product_id(flyer)
    out: list[CollectedOffer] = []
    seen: set[tuple] = set()
    pages = flyer.get("pages") or []
    for idx, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        page_no = idx + 1
        for link in page.get("links") or []:
            if not isinstance(link, dict):
                continue
            details = link.get("productDetails")
            if not isinstance(details, dict):
                continue
            ident = legacy._identifier(details.get("productId"))
            if not ident:
                continue
            product = catalog.get(ident)
            if not product:
                continue
            price = _money_from(product, legacy._PRICE_KEYS)
            if price is None:
                continue
            regular = _money_from(product, legacy._REGULAR_PRICE_KEYS)
            title = str(product.get("title") or details.get("title") or "").strip()
            brand = str(product.get("brand") or "").strip()
            package = str(product.get("packageSize") or product.get("content") or "").strip()
            name = " ".join(p for p in (brand, title, package) if p)
            online = _product_online_only(product, page)
            offer = _build_offer(
                source,
                name=name,
                price=price,
                regular=regular,
                page_no=page_no,
                raw_obj={"link": link, "product": product},
                valid_from=valid_from,
                valid_to=valid_to,
                local=not online,
                source_kind="SchwarzFlyerLink+Catalog",
            )
            if not offer:
                continue
            key = (offer.product_name.lower(), round(float(offer.price), 2), page_no, offer.local_store_offer)
            if key not in seen:
                seen.add(key)
                out.append(offer)
    return out


def _offers_from_page_text(flyer: dict, source, valid_from: str, valid_to: str) -> list[CollectedOffer]:
    """Use Schwarz flyer accessibility text for grocery pages without productDetails.

    Lidl's food pages in the production payload expose recipe/theme links but no
    productDetails objects. Their page altText/keyWords still belong to one
    concrete leaflet page, so the proven Lidl text parser can be reused without
    losing provenance.
    """
    out: list[CollectedOffer] = []
    pages = flyer.get("pages") or []
    for idx, page in enumerate(pages):
        if not isinstance(page, dict) or _page_online_only(page):
            continue
        page_no = idx + 1
        text = _page_text(page)
        if not text or len(text) < 20:
            continue
        try:
            rows = parse_lidl_text(source, text, [])
        except Exception:
            rows = []
        for offer in rows:
            offer.valid_from = valid_from
            offer.valid_to = valid_to
            offer.source_url = source.url
            original = (offer.source_text or "").strip()
            offer.source_text = f"PDF Seite {page_no}: SchwarzFlyerPageText {original}"[:4000]
            offer.local_store_offer = True
            if offer.unit_price is None:
                offer.unit_price, offer.unit_price_unit = compute_unit_price(
                    offer.app_price if offer.app_price is not None else offer.price,
                    offer.quantity,
                    offer.unit,
                )
            out.append(offer)
    return out


def schwarz_manifest_offers(payloads: list[dict], source, *, valid_from: str, valid_to: str) -> list[CollectedOffer]:
    """Production parser for Lidl's `endpoints.leaflets.schwarz/v4/flyer` payload."""
    out: list[CollectedOffer] = []
    seen: set[tuple] = set()
    found_schwarz = False
    for flyer in _iter_schwarz_flyers(payloads):
        found_schwarz = True
        rows = _offers_from_product_links(flyer, source, valid_from, valid_to)
        rows.extend(_offers_from_page_text(flyer, source, valid_from, valid_to))
        for offer in rows:
            m = re.search(r"PDF Seite (\d+)", offer.source_text or "")
            page_no = int(m.group(1)) if m else 0
            key = (
                offer.product_name.lower().strip(),
                round(float(offer.price), 2),
                offer.quantity,
                offer.unit,
                page_no,
                bool(offer.local_store_offer),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(offer)
    if found_schwarz:
        return out
    return _LEGACY_MANIFEST_OFFERS(payloads, source, valid_from=valid_from, valid_to=valid_to)


_LEGACY_MANIFEST_OFFERS = legacy.manifest_offers


def install() -> None:
    """Compatibility bridge used while the old generic manifest parser remains in place."""
    legacy.manifest_offers = schwarz_manifest_offers
