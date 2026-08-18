from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .lidl_flipbook import (
    _advance_and_wait,
    _dismiss_cookies,
    _extract_current_page,
    _extract_total_pages,
    _page_fingerprint,
)
from .lidl_live import lidl_store_page_for, resolve_lidl_leaflet
from .source_registry import source_for_store_record

_RELEVANT_KEYS = {
    "pages", "page", "pageNumber", "pageNo", "pageIndex", "spreads", "sheets",
    "products", "product", "productId", "productName", "title", "name",
    "offers", "offer", "hotspots", "hotspot", "annotations", "annotation",
    "price", "offerPrice", "salePrice", "regularPrice", "oldPrice", "uvp", "rrp",
    "gtin", "ean", "sku", "articleId", "itemId", "label", "badge", "channel",
    "availability", "onlineOnly", "webOnly", "canonicalUrl", "url", "href",
}


def _safe_url(value: str) -> str:
    """Keep scheme/host/path but strip query and fragment tokens."""
    try:
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return value[:500]


def _scalar_preview(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:300]
    return None


def _walk_structure(value, *, path: str = "$", out: list[dict] | None = None, depth: int = 0):
    if out is None:
        out = []
    if depth > 10 or len(out) >= 1200:
        return out
    if isinstance(value, dict):
        keys = list(value.keys())
        interesting = [str(k) for k in keys if str(k) in _RELEVANT_KEYS or any(token in str(k).lower() for token in ("product", "offer", "price", "page", "hotspot", "annot", "article", "item"))]
        if interesting:
            samples = {}
            for key in interesting[:30]:
                if key in value:
                    preview = _scalar_preview(value.get(key))
                    if preview is not None:
                        samples[key] = preview
            out.append({
                "path": path,
                "kind": "object",
                "keys": [str(k) for k in keys[:80]],
                "interesting_keys": interesting[:50],
                "samples": samples,
            })
        for key, child in list(value.items())[:250]:
            _walk_structure(child, path=f"{path}.{key}", out=out, depth=depth + 1)
    elif isinstance(value, list):
        if value:
            out.append({"path": path, "kind": "array", "length": len(value)})
        for idx, child in enumerate(value[:12]):
            _walk_structure(child, path=f"{path}[{idx}]", out=out, depth=depth + 1)
    return out


def _payload_record(url: str, data, page_hint: int | None) -> dict:
    raw = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    return {
        "url": _safe_url(url),
        "page_hint": page_hint,
        "size_bytes": len(raw.encode("utf-8", errors="ignore")),
        "sha256": hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest(),
        "top_level_type": type(data).__name__,
        "top_level_keys": list(data.keys())[:100] if isinstance(data, dict) else [],
        "structure": _walk_structure(data),
    }


def capture_lidl_manifest_debug(store, *, data_dir: Path, max_states: int = 40) -> Path:
    """Capture a privacy-minimised structural snapshot of Lidl viewer JSON.

    This diagnostic intentionally does not import offers and does not change QA
    data. It is only meant to reveal the real production payload structure so
    the parser can be fixed deterministically.
    """
    source = source_for_store_record(store)
    store_page = lidl_store_page_for(store.name)
    leaflet = resolve_lidl_leaflet(source.url, date.today(), store_page_url=store_page)
    target_dir = data_dir / "diagnostics" / "lidl"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"lidl_manifest_debug_store_{store.id}_latest.json"

    captured: list[dict] = []
    payload_hashes: set[str] = set()
    capture_hint = {"page": 1}
    viewer_states = 0
    navigation_methods: set[str] = set()
    viewer_total = None
    final_url = leaflet.url
    error = None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                locale="de-DE",
                timezone_id="Europe/Berlin",
                viewport={"width": 1440, "height": 1100},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36",
                extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.7"},
            )
            page = context.new_page()

            def capture_response(response):
                try:
                    ctype = (response.headers.get("content-type") or "").lower()
                    url_low = response.url.lower()
                    relevant_url = any(token in url_low for token in (
                        "flyer", "leaflet", "prospekt", "brochure", "catalog", "page",
                        "offer", "product", "article", "hotspot", "publication", "spread",
                        "manifest", "annotation",
                    ))
                    if "json" not in ctype and not relevant_url:
                        return
                    data = response.json()
                    raw = json.dumps(data, ensure_ascii=False, default=str)
                    low = raw.lower()
                    if not any(token in low for token in (
                        "price", "preis", "offer", "angebot", "product", "produkt",
                        "article", "artikel", "gtin", "ean", "hotspot", "page",
                        "manifest", "annotation",
                    )):
                        return
                    digest = hashlib.sha256((response.url + "\n" + raw).encode("utf-8", errors="ignore")).hexdigest()
                    if digest in payload_hashes or len(captured) >= 80:
                        return
                    payload_hashes.add(digest)
                    captured.append(_payload_record(response.url, data, capture_hint.get("page")))
                except Exception:
                    pass

            page.on("response", capture_response)
            page.goto(leaflet.url, wait_until="domcontentloaded", timeout=45000)
            _dismiss_cookies(page)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                page.wait_for_timeout(2500)
            _dismiss_cookies(page)

            fingerprints: set[str] = set()
            for logical_state in range(1, max_states + 1):
                body = page.locator("body").inner_text(timeout=5000) or ""
                final_url = page.url or leaflet.url
                current_page = _extract_current_page(body) or capture_hint.get("page") or logical_state
                capture_hint["page"] = current_page
                viewer_total = viewer_total or _extract_total_pages(body)
                fingerprint = _page_fingerprint(page, body)
                if fingerprint in fingerprints:
                    break
                fingerprints.add(fingerprint)
                viewer_states += 1
                capture_hint["page"] = 2 if current_page <= 1 else current_page + 2
                changed, method = _advance_and_wait(page, fingerprint, current_page)
                if method:
                    navigation_methods.add(method)
                if not changed:
                    break
            context.close()
            browser.close()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    document = {
        "created_utc": datetime.utcnow().isoformat() + "Z",
        "store": {"id": store.id, "name": store.name, "retailer": store.retailer, "external_id": store.external_id},
        "leaflet": {
            "url": _safe_url(leaflet.url),
            "valid_from": leaflet.valid_from.isoformat(),
            "valid_to": leaflet.valid_to.isoformat(),
            "store_context_confirmed": leaflet.store_context_confirmed,
        },
        "viewer": {
            "final_url": _safe_url(final_url),
            "states": viewer_states,
            "total": viewer_total,
            "navigation": sorted(navigation_methods),
        },
        "payload_count": len(captured),
        "payloads": captured,
        "error": error,
        "note": "Querystrings/fragments are stripped; only structural payload diagnostics and bounded scalar samples are stored.",
    }
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return target
