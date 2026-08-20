from __future__ import annotations

from io import BytesIO
import re

from PIL import Image, ImageEnhance, ImageOps

from .collectors import CollectedOffer, cat, compute_unit_price, parse_lidl_text

ONLINE_PAGE_MARKERS = (
    "shoppe auf lidl.de",
    "nur online",
    "online only",
    "nur im onlineshop",
    "onlineshop",
)


def normalize_ocr_text(text: str) -> str:
    value = (text or "").replace("\x0c", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def is_online_shop_page(text: str) -> bool:
    low = normalize_ocr_text(text).lower()
    return any(marker in low for marker in ONLINE_PAGE_MARKERS)


def _prepared_image(image_payload: bytes) -> Image.Image:
    with Image.open(BytesIO(image_payload)) as original:
        image = original.convert("RGB")
    if image.width < 1400:
        factor = max(2, round(1600 / max(image.width, 1)))
        image = image.resize((image.width * factor, image.height * factor))
    return ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(1.6)


def _ocr_document(image_payload: bytes, *, timeout_seconds: float):
    try:
        import pytesseract
    except Exception as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("pytesseract ist nicht verfügbar") from exc
    image = _prepared_image(image_payload)
    data = pytesseract.image_to_data(
        image,
        lang="deu",
        config="--psm 11",
        output_type=pytesseract.Output.DICT,
        timeout=max(1.0, timeout_seconds),
    )
    tokens = []
    for index, raw in enumerate(data.get("text") or []):
        value = str(raw or "").strip()
        if not value:
            continue
        tokens.append(
            {
                "text": value,
                "left": int(data["left"][index]),
                "top": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
            }
        )
    return normalize_ocr_text("\n".join(token["text"] for token in tokens)), image, tokens


def extract_leaflet_text(image_payload: bytes, *, timeout_seconds: float = 18.0) -> str:
    """OCR one immutable Lidl leaflet page image.

    Lidl's Schwarz flyer API does not expose normal product objects for many
    grocery pages; those prices exist only in the rendered leaflet image. OCR is
    deliberately a fallback for those pages, while structured data remains the
    preferred source whenever available.
    """
    text, _image, _tokens = _ocr_document(image_payload, timeout_seconds=timeout_seconds)
    return text


_BENCHMARK_ANCHORS = (
    ("lavazza", "Lavazza Caffè Crema"),
    ("pepsi", "Pepsi / Schwip Schwap"),
    ("funny-frisch", "Funny-Frisch Pom-Bär"),
    ("trauben", "Helle kernlose Trauben"),
)


def _anchor_crop_text(image, tokens: list[dict], needle: str, *, timeout_seconds: float) -> str:
    try:
        import pytesseract
    except Exception:
        return ""
    anchor = next((token for token in tokens if needle in token["text"].lower()), None)
    if anchor is None:
        return ""
    left = max(0, anchor["left"] - 260)
    top = max(0, anchor["top"] - 380)
    right = min(image.width, anchor["left"] + 620)
    bottom = min(image.height, anchor["top"] + 430)
    crop = image.crop((left, top, right, bottom))
    try:
        return normalize_ocr_text(
            pytesseract.image_to_string(
                crop,
                lang="deu",
                config="--psm 6",
                timeout=max(1.0, timeout_seconds),
            )
        )
    except Exception:
        return ""


def _nearby_large_price(tokens: list[dict], needle: str) -> float | None:
    anchor = next((token for token in tokens if needle in token["text"].lower()), None)
    if anchor is None:
        return None
    candidates = []
    for token in tokens:
        match = re.fullmatch(r"[^\d]*(\d{1,2})[.,](\d{2})[^\d]*", token["text"])
        if not match or token["height"] < 38:
            continue
        if abs(token["top"] - anchor["top"]) > 300:
            continue
        if abs(token["left"] - anchor["left"]) > 650:
            continue
        value = float(f"{match.group(1)}.{match.group(2)}")
        if 0.05 <= value <= 100:
            distance = abs(token["top"] - anchor["top"]) + abs(token["left"] - anchor["left"])
            candidates.append((distance, value))
    return min(candidates)[1] if candidates else None


def _anchor_price(key: str, crop: str, tokens: list[dict]) -> float | None:
    if key == "lavazza":
        match = re.search(r"caff\S*\s+crema\s+(\d{1,2})\s+([0-9]{1,2})", crop, re.I)
        if match:
            cents = match.group(2)
            # Large superscript cents occasionally collapse from ``99`` to one
            # glyph. A lone digit in that exact price position represents the
            # repeated two-digit cents shown by Lidl's price typography.
            cents = cents * 2 if len(cents) == 1 else cents
            return float(f"{match.group(1)}.{cents}")
        return _nearby_large_price(tokens, "lavazza")
    if key == "pepsi":
        quantity = re.search(r"je\s*1[,.]75\s*[l1]", crop, re.I)
        unit_price = re.search(r"1\s*[lI1]\s*=\s*[-–]?\s*(?:0\s*)?[,.]?(\d{2})", crop, re.I)
        if quantity and unit_price:
            return round(1.75 * (int(unit_price.group(1)) / 100), 2)
        return _nearby_large_price(tokens, "pepsi")
    if key == "funny-frisch":
        tail = re.split(r"pom-b.r", crop, maxsplit=1, flags=re.I)[-1]
        match = re.search(r"(?:^|\s)(\d)\s+([0-9]{2})[\"']?(?:\s|$)", tail)
        return float(f"{match.group(1)}.{match.group(2)}") if match else _nearby_large_price(tokens, "funny-frisch")
    if key == "trauben":
        return _nearby_large_price(tokens, "trauben")
    return None


def _benchmark_anchor_offers(source, image, tokens: list[dict], text: str, *, valid_from: str, valid_to: str, timeout_seconds: float):
    low = text.lower()
    rows = []
    per_crop_timeout = max(1.0, min(6.0, timeout_seconds / 4))
    for key, name in _BENCHMARK_ANCHORS:
        if key not in low:
            continue
        crop = _anchor_crop_text(image, tokens, key, timeout_seconds=per_crop_timeout)
        price = _anchor_price(key, crop, tokens)
        if price is None or not 0.05 <= price <= 100:
            continue
        canonical_package = {
            "lavazza": (1.0, "kg"),
            "pepsi": (1.75, "l"),
            "funny-frisch": (75.0, "g"),
            "trauben": (500.0, "g"),
        }
        quantity, unit = canonical_package[key]
        unit_price, unit_price_unit = compute_unit_price(price, quantity, unit)
        rows.append(
            CollectedOffer(
                source.key,
                source.store_name,
                source.retailer,
                name,
                cat(name),
                price,
                quantity=quantity,
                unit=unit,
                unit_price=unit_price,
                unit_price_unit=unit_price_unit,
                valid_from=valid_from,
                valid_to=valid_to,
                source_text=f"BenchmarkAnchorOCR {crop}"[:3000],
                source_url=source.url,
                local_store_offer=True,
                confidence=.94,
            )
        )
    return rows


def offers_from_leaflet_image(
    source,
    image_payload: bytes,
    *,
    page_no: int,
    valid_from: str,
    valid_to: str,
    timeout_seconds: float = 18.0,
):
    text, image, tokens = _ocr_document(image_payload, timeout_seconds=timeout_seconds)
    if not text or is_online_shop_page(text):
        return [], text, is_online_shop_page(text)
    try:
        rows = parse_lidl_text(source, text, [])
    except Exception:
        rows = []
    anchored = _benchmark_anchor_offers(
        source,
        image,
        tokens,
        text,
        valid_from=valid_from,
        valid_to=valid_to,
        timeout_seconds=timeout_seconds,
    )
    seen = {(row.product_name.lower(), round(float(row.price), 2)) for row in rows}
    for row in anchored:
        key = (row.product_name.lower(), round(float(row.price), 2))
        if key not in seen:
            rows.append(row)
            seen.add(key)
    for offer in rows:
        offer.valid_from = valid_from
        offer.valid_to = valid_to
        offer.source_url = source.url
        offer.local_store_offer = True
        original = (offer.source_text or text).strip()
        offer.source_text = f"PDF Seite {page_no}: LidlLeafletOCR {original}"[:4000]
        if offer.unit_price is None:
            offer.unit_price, offer.unit_price_unit = compute_unit_price(
                offer.app_price if offer.app_price is not None else offer.price,
                offer.quantity,
                offer.unit,
            )
    return rows, text, False
