from __future__ import annotations

from io import BytesIO
import json
import re
from typing import Any
from urllib.parse import urlparse

from PIL import Image
from pypdf import PdfReader

from .collectors import CollectedOffer, cat, clean_product_name, product_name_issue, size

_NAME_KEYS = (
    "productName", "product_name", "name", "title", "headline", "description",
    "articleName", "article_name", "label", "displayName", "productTitle", "shortDescription",
)
_PRICE_KEYS = (
    "offerPrice", "offer_price", "promotionalPrice", "promotionPrice", "salePrice",
    "price", "currentPrice", "finalPrice", "salesPrice", "discountPrice", "priceText", "salesPriceText",
)
_REGULAR_PRICE_KEYS = (
    "regularPrice", "regular_price", "oldPrice", "listPrice", "originalPrice", "wasPrice",
    "recommendedRetailPrice", "recommended_retail_price", "rrp", "uvp", "referencePrice", "comparisonPrice",
)
_PACKAGE_KEYS = ("packageSize", "package_size", "packSize", "content", "quantityText", "unitText")
_PAGE_KEYS = ("pageNumber", "pageNo", "page_no", "page", "pageIndex", "page_index")
_TOTAL_KEYS = ("totalPages", "pageCount", "pagesCount", "numberOfPages", "totalPageCount")
_PAGE_COLLECTION_KEYS = {
    "pages", "leafletpages", "publicationpages", "catalogpages", "brochurepages",
    "flyerpages", "documentpages", "pageitems", "pagecontents", "sheets", "spreads",
}
_GLOBAL_PRODUCT_COLLECTIONS = {"products", "productlist", "productitems", "articles", "articlelist", "items", "catalogueproducts"}
_PRODUCT_ID_KEYS = (
    "productId", "product_id", "articleId", "article_id", "sku", "skuId", "sku_id",
    "gtin", "ean", "productCode", "articleNumber", "itemId", "item_id", "id",
)
_PRODUCT_REF_KEYS = (
    "productId", "product_id", "articleId", "article_id", "sku", "skuId", "sku_id",
    "gtin", "ean", "productCode", "articleNumber", "itemId", "item_id",
    "productRef", "product_ref", "articleRef", "article_ref", "targetId", "target_id", "id",
)
_CONTEXT_WORDS = ("product", "produkt", "article", "artikel", "offer", "angebot", "hotspot", "promotion", "annotation")
_URL_KEYS = ("url", "href", "canonicalUrl", "canonicalURL", "productUrl", "productURL", "deeplink", "deepLink")


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
        value = _scalar(obj.get(key))
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
    text = str(value).strip().lower()
    if not text or len(text) > 160:
        return None
    return text


def _identifiers_from(obj: dict, keys: tuple[str, ...]) -> set[str]:
    result: set[str] = set()
    for key in keys:
        if key in obj:
            ident = _identifier(obj.get(key))
            if ident:
                result.add(ident)
    return result


def _url_identifiers(obj: dict) -> set[str]:
    result: set[str] = set()
    for key in _URL_KEYS:
        value = _scalar(obj.get(key))
        if not isinstance(value, str):
            continue
        for pattern in (r"(?:^|[/_-])p(?:-|/)?(\d{6,})(?:\D|$)", r"flyx_content=p-(\d{6,})", r"product(?:id)?[=/:-](\d{6,})"):
            for match in re.findall(pattern, value, re.I):
                result.add(match.lower())
    return result


def _path_collection_name(path: str) -> str:
    tail = path.rsplit(".", 1)[-1] if path else ""
    tail = re.sub(r"\[\d+\]$", "", tail)
    return tail.lower()


def _walk(value: Any, *, path: str = "", inherited_page: int | None = None):
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
                if key.lower() in _PAGE_COLLECTION_KEYS and isinstance(value, list) and 4 <= len(value) <= 500:
                    candidates.append(len(value))
    return max(candidates) if candidates else None


def manifest_reference_pages(payloads: list[dict]) -> dict[str, int]:
    found: dict[str, set[int]] = {}
    for payload in payloads:
        for obj, path, page_no in _walk(payload.get("data"), inherited_page=None):
            if page_no is None:
                continue
            context = path.lower() + " " + " ".join(str(k).lower() for k in obj.keys())
            if not any(word in context for word in _CONTEXT_WORDS):
                continue
            identifiers = _identifiers_from(obj, _PRODUCT_REF_KEYS) | _url_identifiers(obj)
            for ident in identifiers:
                found.setdefault(ident, set()).add(page_no)
    return {ident: next(iter(pages)) for ident, pages in found.items() if len(pages) == 1}


def _is_global_catalog_path(path: str) -> bool:
    parts = re.sub(r"\[\d+\]", "", path.lower()).split(".")
    return any(part in _GLOBAL_PRODUCT_COLLECTIONS for part in parts)


def _online_only(obj: dict) -> bool:
    for key in ("onlineOnly", "online_only", "isOnlineOnly", "webOnly", "shopOnly"):
        if obj.get(key) is True:
            return True
    for key in ("channel", "salesChannel", "availability", "offerType", "badge", "label"):
        value = _scalar(obj.get(key))
        if isinstance(value, str) and any(token in value.lower() for token in ("online only", "nur online", "online-only", "onlineshop")):
            return True
    for key in _URL_KEYS:
        value = _scalar(obj.get(key))
        if not isinstance(value, str):
            continue
        try:
            parsed = urlparse(value)
        except Exception:
            continue
        if parsed.netloc.lower().endswith("lidl.de") and re.search(r"/p/[^/]+/p\d+", parsed.path, re.I):
            return True
    return False


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
    for key in _PRICE_KEYS:
        if key in obj:
            price = _money(obj.get(key))
            if price is not None:
                break
    if price is None:
        return None

    regular = None
    for key in _REGULAR_PRICE_KEYS:
        if key in obj:
            regular = _money(obj.get(key))
            if regular is not None:
                break
    explicit_page = _number_from(obj, _PAGE_KEYS)
    return cleaned, price, regular, explicit_page, page_hint, brand, _online_only(obj)


def _near_duplicate_name(a: str, b: str) -> bool:
    def norm(value: str) -> str:
        value = re.sub(r"[^a-z0-9äöüß]+", " ", value.lower()).strip()
        return re.sub(r"\s+", " ", value)
    x, y = norm(a), norm(b)
    if x == y:
        return True
    shorter, longer = sorted((x, y), key=len)
    return len(shorter) >= 8 and longer.startswith(shorter + " ") and len(longer) - len(shorter) <= 24


def manifest_offers(payloads: list[dict], source, *, valid_from: str, valid_to: str) -> list[CollectedOffer]:
    out: list[CollectedOffer] = []
    seen: set[tuple] = set()
    accepted: list[tuple[int, float, str]] = []
    reference_pages = manifest_reference_pages(payloads)
    for payload in payloads:
        data = payload.get("data")
        payload_page = payload.get("page_hint")
        seed_page = None if _has_page_collection(data) else payload_page
        for obj, path, inherited_page in _walk(data, inherited_page=seed_page):
            candidate = _candidate_offer(obj, path, inherited_page)
            if not candidate:
                continue
            name, price, regular, explicit_page, fallback_page, _brand, online_only = candidate
            ids = _identifiers_from(obj, _PRODUCT_ID_KEYS) | _url_identifiers(obj)
            ref_pages = {reference_pages[i] for i in ids if i in reference_pages}
            reference_page = next(iter(ref_pages)) if len(ref_pages) == 1 else None
            # A request-time page hint must never make a global product catalogue
            # look page-scoped. Global products need an explicit page or a real
            # hotspot/reference join.
            safe_fallback = None if _is_global_catalog_path(path) else fallback_page
            page_no = explicit_page or reference_page or safe_fallback
            if page_no is None:
                continue

            q, unit = size(name)
            key = (name.lower(), price, page_no, q, unit)
            if key in seen:
                continue
            if any(p == page_no and abs(pr - price) < 0.001 and _near_duplicate_name(existing_name, name) for p, pr, existing_name in accepted):
                continue
            seen.add(key)
            accepted.append((page_no, price, name))
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
                local_store_offer=not online_only,
                confidence=.98,
            ))
    return out


def embedded_json_states(page) -> list[dict]:
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
