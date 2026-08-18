from __future__ import annotations

from io import BytesIO
import json
import re
from typing import Any

from PIL import Image
from pypdf import PdfReader

from .collectors import CollectedOffer, cat, clean_product_name, product_name_issue, size

_NAME_KEYS = (
    "productName", "product_name", "name", "title", "headline", "description",
    "articleName", "article_name", "label",
)
_PRICE_KEYS = (
    "offerPrice", "offer_price", "promotionalPrice", "promotionPrice", "salePrice",
    "price", "currentPrice", "finalPrice", "salesPrice",
)
_REGULAR_PRICE_KEYS = (
    "regularPrice", "regular_price", "oldPrice", "listPrice", "originalPrice", "wasPrice",
)
_PACKAGE_KEYS = ("packageSize", "package_size", "packSize", "content", "quantityText", "unitText")
_PAGE_KEYS = ("pageNumber", "pageNo", "page_no", "page", "pageIndex", "page_index")
_TOTAL_KEYS = ("totalPages", "pageCount", "pagesCount", "numberOfPages", "totalPageCount")
_PAGE_COLLECTION_KEYS = {
    "pages", "leafletpages", "publicationpages", "catalogpages", "brochurepages",
    "flyerpages", "documentpages", "pageitems", "pagecontents", "sheets", "spreads",
}
_PRODUCT_ID_KEYS = (
    "productId", "product_id", "articleId", "article_id", "sku", "skuId", "sku_id",
    "gtin", "ean", "productCode", "articleNumber", "itemId", "item_id",
)
_PRODUCT_REF_KEYS = (
    "productId", "product_id", "articleId", "article_id", "sku", "skuId", "sku_id",
    "gtin", "ean", "productCode", "articleNumber", "itemId", "item_id",
    "productRef", "product_ref", "articleRef", "article_ref", "targetId", "target_id",
)
_CONTEXT_WORDS = ("product", "produkt", "article", "artikel", "offer", "angebot", "hotspot", "promotion", "annotation")


def _scalar(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "amount", "price", "gross", "displayValue", "formattedValue"):
            if key in value:
                return _scalar(value[key])
        return None
    if isinstance(value, list):
        return _scalar(value[0]) if value else None
    return value


def _money(value: Any) -> float | None:
    value = _scalar(value)
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace("€", "").replace("EUR", "").replace(" ", "")
        if not text:
            return None
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        m = re.search(r"\d{1,4}(?:\.\d{1,2})?", text)
        if not m:
            return None
        number = float(m.group(0))
    else:
        return None
    return round(number, 2) if 0.01 <= number <= 10000 else None


def _text_from(obj: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = obj.get(key)
        value = _scalar(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _number_from(obj: dict, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = _scalar(obj.get(key))
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if key in {"pageIndex", "page_index"} and number >= 0:
            number += 1
        if 1 <= number <= 500:
            return number
    return None


def _identifier(value: Any) -> str | None:
    value = _scalar(value)
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text or len(text) > 160:
        return None
    return text.lower()


def _identifiers_from(obj: dict, keys: tuple[str, ...]) -> set[str]:
    result: set[str] = set()
    for key in keys:
        if key not in obj:
            continue
        ident = _identifier(obj.get(key))
        if ident:
            result.add(ident)
    return result


def _path_collection_name(path: str) -> str:
    tail = path.rsplit(".", 1)[-1] if path else ""
    tail = re.sub(r"\[\d+\]$", "", tail)
    return tail.lower()


def _walk(value: Any, *, path: str = "", inherited_page: int | None = None):
    """Walk manifest data while preserving the real logical page context."""
    if isinstance(value, dict):
        page = _number_from(value, _PAGE_KEYS) or inherited_page
        yield value, path, page
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _walk(child, path=child_path, inherited_page=page)
    elif isinstance(value, list):
        page_collection = _path_collection_name(path) in _PAGE_COLLECTION_KEYS
        for idx, child in enumerate(value):
            child_page = idx + 1 if page_collection else inherited_page
            yield from _walk(child, path=f"{path}[{idx}]", inherited_page=child_page)


def _has_page_collection(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in _PAGE_COLLECTION_KEYS and isinstance(child, list) and child:
                return True
            if _has_page_collection(child):
                return True
    elif isinstance(value, list):
        return any(_has_page_collection(child) for child in value[:50])
    return False


def manifest_page_count(payloads: list[dict]) -> int | None:
    candidates: list[int] = []
    for payload in payloads:
        data = payload.get("data")
        for obj, _path, _page in _walk(data):
            total = _number_from(obj, _TOTAL_KEYS)
            if total:
                candidates.append(total)
            for key, value in obj.items():
                if key.lower() in _PAGE_COLLECTION_KEYS and isinstance(value, list):
                    if 4 <= len(value) <= 500:
                        candidates.append(len(value))
    return max(candidates) if candidates else None


def manifest_reference_pages(payloads: list[dict]) -> dict[str, int]:
    """Map Lidl product/article identifiers found inside page-scoped hotspot trees.

    Lidl currently ships a global product catalogue (name/price/productId) separately
    from page/hotspot metadata. Product catalogue rows have no pageNumber themselves.
    The hotspot tree, however, repeats the product/article identifier below the real
    logical page. This two-pass map lets us join both payload families without falling
    back to the request-time page hint.
    """
    found: dict[str, set[int]] = {}
    for payload in payloads:
        data = payload.get("data")
        for obj, path, page_no in _walk(data, inherited_page=None):
            if page_no is None:
                continue
            context = path.lower() + " " + " ".join(str(k).lower() for k in obj.keys())
            if not any(word in context for word in _CONTEXT_WORDS):
                continue
            for ident in _identifiers_from(obj, _PRODUCT_REF_KEYS):
                found.setdefault(ident, set()).add(page_no)
    # A product normally appears on one leaflet page. Keep only unambiguous mappings;
    # ambiguous references are safer left unresolved than assigned to the wrong page.
    return {ident: next(iter(pages)) for ident, pages in found.items() if len(pages) == 1}


def _candidate_offer(obj: dict, path: str, page_hint: int | None):
    context = path.lower() + " " + " ".join(str(k).lower() for k in obj.keys())
    if not any(word in context for word in _CONTEXT_WORDS):
        return None
    name = _text_from(obj, _NAME_KEYS)
    if not name:
        return None
    brand = _text_from(obj, ("brand", "brandName", "manufacturer", "vendor"))
    package = _text_from(obj, _PACKAGE_KEYS)
    combined = " ".join(part for part in (brand, name, package) if part)
    cleaned = clean_product_name(combined)
    if not cleaned or product_name_issue(cleaned) or len(cleaned) < 3:
        return None

    price = None
    price_key = None
    for key in _PRICE_KEYS:
        if key in obj:
            price = _money(obj.get(key))
            if price is not None:
                price_key = key
                break
    if price is None:
        return None

    regular = None
    for key in _REGULAR_PRICE_KEYS:
        if key in obj:
            regular = _money(obj.get(key))
            if regular is not None:
                break
    page_no = _number_from(obj, _PAGE_KEYS) or page_hint
    return cleaned, price, regular, page_no, price_key


def manifest_offers(payloads: list[dict], source, *, valid_from: str, valid_to: str) -> list[CollectedOffer]:
    out: list[CollectedOffer] = []
    seen: set[tuple] = set()
    reference_pages = manifest_reference_pages(payloads)
    for payload in payloads:
        data = payload.get("data")
        payload_page = payload.get("page_hint")
        seed_page = None if _has_page_collection(data) else payload_page
        for obj, path, inherited_page in _walk(data, inherited_page=seed_page):
            candidate = _candidate_offer(obj, path, inherited_page)
            if not candidate:
                continue
            name, price, regular, page_no, _price_key = candidate
            if page_no is None:
                ids = _identifiers_from(obj, _PRODUCT_ID_KEYS)
                pages = {reference_pages[i] for i in ids if i in reference_pages}
                if len(pages) == 1:
                    page_no = next(iter(pages))
            if page_no is None:
                continue
            q, unit = size(name)
            key = (name.lower(), price, page_no, q, unit)
            if key in seen:
                continue
            seen.add(key)
            raw = json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))[:2600]
            out.append(CollectedOffer(
                source.key,
                source.store_name,
                source.retailer,
                name[:180],
                cat(name),
                price,
                regular_price=regular,
                quantity=q,
                unit=unit,
                valid_from=valid_from,
                valid_to=valid_to,
                source_text=f"PDF Seite {page_no}: Manifest {raw}",
                source_url=source.url,
                confidence=.98,
            ))
    return out


def embedded_json_states(page) -> list[dict]:
    """Read JSON application state already present in the live viewer DOM."""
    states: list[dict] = []
    try:
        scripts = page.locator('script[type="application/json"], script#__NEXT_DATA__')
        for idx in range(min(scripts.count(), 40)):
            raw = scripts.nth(idx).text_content() or ""
            if not raw or len(raw) > 5_000_000:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            states.append({"url": "dom-state", "data": data, "page_hint": None})
    except Exception:
        pass
    return states


def _surface_screenshots(page, expected: int) -> list[bytes]:
    """Prefer actual large canvas/image leaflet surfaces over whole-page screenshots."""
    candidates: list[tuple[float, float, float, bytes]] = []
    try:
        locator = page.locator("canvas, img")
        for idx in range(min(locator.count(), 80)):
            node = locator.nth(idx)
            try:
                if not node.is_visible():
                    continue
                box = node.bounding_box()
                if not box or box["width"] < 280 or box["height"] < 360:
                    continue
                ratio = box["height"] / max(1.0, box["width"])
                if not 0.8 <= ratio <= 2.2:
                    continue
                payload = node.screenshot(animations="disabled")
                candidates.append((box["x"], box["width"] * box["height"], box["height"], payload))
            except Exception:
                continue
    except Exception:
        candidates = []
    candidates.sort(key=lambda item: (-item[1], item[0]))
    chosen = candidates[:expected]
    if len(chosen) == expected:
        chosen.sort(key=lambda item: item[0])
        return [item[3] for item in chosen]
    return []


def logical_page_images(page, current_page: int | None, total_pages: int | None) -> list[tuple[int, bytes]]:
    """Return one image per logical leaflet page, splitting two-page spreads when necessary."""
    current = current_page or 1
    expected = 1
    if total_pages and current > 1 and current < total_pages:
        expected = 2

    direct = _surface_screenshots(page, expected)
    if direct:
        return [(current + idx, payload) for idx, payload in enumerate(direct) if not total_pages or current + idx <= total_pages]

    payload = page.screenshot(full_page=False, animations="disabled")
    image = Image.open(BytesIO(payload)).convert("RGB")
    top = min(90, image.height // 10)
    bottom = max(top + 100, image.height - min(70, image.height // 12))
    image = image.crop((0, top, image.width, bottom))
    if expected == 1:
        buf = BytesIO(); image.save(buf, format="PNG")
        return [(current, buf.getvalue())]

    midpoint = image.width // 2
    result: list[tuple[int, bytes]] = []
    for idx, crop in enumerate((image.crop((0, 0, midpoint, image.height)), image.crop((midpoint, 0, image.width, image.height)))):
        page_no = current + idx
        if total_pages and page_no > total_pages:
            continue
        buf = BytesIO(); crop.save(buf, format="PNG")
        result.append((page_no, buf.getvalue()))
    return result


def add_image_pdf_page(writer, payload: bytes) -> None:
    image = Image.open(BytesIO(payload)).convert("RGB")
    buf = BytesIO()
    image.save(buf, format="PDF", resolution=150.0)
    reader = PdfReader(BytesIO(buf.getvalue()))
    if reader.pages:
        writer.add_page(reader.pages[0])
