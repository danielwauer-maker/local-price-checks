from __future__ import annotations

from io import BytesIO
import re

from PIL import Image, ImageEnhance, ImageOps

from .collectors import compute_unit_price, parse_lidl_text

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


def extract_leaflet_text(image_payload: bytes) -> str:
    """OCR one immutable Lidl leaflet page image.

    Lidl's Schwarz flyer API does not expose normal product objects for many
    grocery pages; those prices exist only in the rendered leaflet image. OCR is
    deliberately a fallback for those pages, while structured data remains the
    preferred source whenever available.
    """
    try:
        import pytesseract
    except Exception as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("pytesseract ist nicht verfügbar") from exc

    with Image.open(BytesIO(image_payload)) as original:
        image = original.convert("RGB")
        # Upscale small viewer tiles before sparse-text OCR. This materially
        # improves decimal prices and small package-size text in leaflet cards.
        if image.width < 1400:
            factor = max(2, round(1600 / max(image.width, 1)))
            image = image.resize((image.width * factor, image.height * factor))
        gray = ImageOps.grayscale(image)
        gray = ImageEnhance.Contrast(gray).enhance(1.6)
        text = pytesseract.image_to_string(gray, lang="deu", config="--psm 11")
    return normalize_ocr_text(text)


def offers_from_leaflet_image(source, image_payload: bytes, *, page_no: int, valid_from: str, valid_to: str):
    text = extract_leaflet_text(image_payload)
    if not text or is_online_shop_page(text):
        return [], text, is_online_shop_page(text)
    try:
        rows = parse_lidl_text(source, text, [])
    except Exception:
        rows = []
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
