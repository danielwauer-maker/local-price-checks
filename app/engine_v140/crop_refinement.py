from __future__ import annotations

import re
import unicodedata
from hashlib import sha256
from pathlib import Path

from PIL import Image


_BBOX_RE = re.compile(
    r"bbox=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)\s+price_bbox=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)",
    re.I,
)
_IDENTITY_STOPWORDS = {
    "versch", "verschiedene", "sorten", "oder", "und", "mit", "der", "die", "das",
    "je", "packung", "stück", "stk", "aktion", "angebot", "original", "classic",
}


def _save_refined(source: Path, box: tuple[int, int, int, int], suffix: str) -> Path | None:
    try:
        image = Image.open(source).convert("RGB")
        x0, y0, x1, y1 = box
        x0 = max(0, min(image.width - 1, x0))
        y0 = max(0, min(image.height - 1, y0))
        x1 = max(x0 + 1, min(image.width, x1))
        y1 = max(y0 + 1, min(image.height, y1))
        if x1 - x0 < 80 or y1 - y0 < 80:
            return None
        target = source.with_name(f"{source.stem}-{suffix}{source.suffix}")
        image.crop((x0, y0, x1, y1)).save(target, format="JPEG", quality=91, optimize=True)
        return target
    except (OSError, ValueError):
        return None


def _fold(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.lower())
        if not unicodedata.combining(char)
    )


def _identity_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", _fold(value or ""))
        if token not in _IDENTITY_STOPWORDS and not token.isdigit()
    }


def _crop_contains_product(path: Path, product_name: str) -> bool | None:
    """Verify a fallback crop contains enough product identity text.

    Returns ``None`` when OCR is unavailable so image validation never makes a
    collector fail just because an optional verifier is missing.
    """
    expected = _identity_tokens(product_name)
    if not expected:
        return None
    try:
        import pytesseract
        with Image.open(path) as image:
            text = pytesseract.image_to_string(
                image.convert("RGB"),
                lang="deu",
                config="--psm 11",
                timeout=8,
            )
    except Exception:
        return None
    observed = _identity_tokens(text)
    overlap = expected & observed
    required = 1 if len(expected) <= 2 else 2
    coverage = len(overlap) / max(1, len(expected))
    return len(overlap) >= required and coverage >= (0.34 if len(expected) >= 3 else 0.5)


def _edeka_refined_box(image: Image.Image, source_text: str) -> tuple[int, int, int, int]:
    match = _BBOX_RE.search(source_text or "")
    if not match:
        return (
            int(image.width * 0.08),
            int(image.height * 0.18),
            int(image.width * 0.92),
            int(image.height * 0.88),
        )

    bx0, by0, bx1, by1, px0, py0, px1, py1 = map(int, match.groups())
    original_w = max(1, bx1 - bx0)
    original_h = max(1, by1 - by0)
    sx = image.width / original_w
    sy = image.height / original_h

    # The price tag is a reliable card anchor. Keep the product/title space
    # above and alongside it, but stop well before the neighbouring card bands
    # which the original whole-column crop included.
    relative_price_cx = ((px0 + px1) / 2 - bx0) * sx
    relative_price_top = (py0 - by0) * sy
    relative_price_bottom = (py1 - by0) * sy
    half_width = min(image.width * 0.46, 235 * sx)
    x0 = int(relative_price_cx - half_width)
    x1 = int(relative_price_cx + half_width)
    y0 = int(relative_price_top - 315 * sy)
    y1 = int(relative_price_bottom + 78 * sy)
    return x0, y0, x1, y1


def _lidl_refined_box(image: Image.Image) -> tuple[int, int, int, int]:
    # Lidl's parser centres the old fallback on the matched product/price union,
    # then enlarges it substantially. Reduce only the outer neighbourhood while
    # preserving enough padding for the complete product card and its details.
    width = int(image.width * 0.72)
    height = int(image.height * 0.72)
    x0 = (image.width - width) // 2
    y0 = (image.height - height) // 2
    return x0, y0, x0 + width, y0 + height


def _reject_wrong_crop(row) -> None:
    # Keep the immutable PDF/provenance as the audit truth but tell media
    # persistence to retire an older wrong prospect crop for this product.
    row.crop_quality_rejected = True
    row.audit_image_path = None
    row.image_path = None


def refine_pdf_offer_crops(rows) -> int:
    """Produce tighter Lidl/EDEKA card crops and suppress identity mismatches.

    REWE and other retailers are deliberately untouched. For EDEKA in
    particular, OCR association can occasionally bind the right text/price to
    a broad crop containing another card. Such a crop is now rejected rather
    than shown to users as a misleading product image.
    """
    changed = 0
    for row in rows or []:
        retailer = str(getattr(row, "retailer", "") or "").strip().lower()
        if retailer not in {"lidl", "edeka"}:
            continue
        raw_path = getattr(row, "audit_image_path", None) or getattr(row, "image_path", None)
        if not raw_path:
            continue
        source = Path(raw_path)
        if not source.is_file():
            continue

        # EDEKA is OCR-driven and therefore gets an additional identity check
        # on the original broad crop. If the named article is not present at all
        # (e.g. only a neighbouring "Burger" card is visible for "Golden Toast
        # Burger"), a tighter crop cannot repair the association safely.
        if retailer == "edeka":
            identity_ok = _crop_contains_product(source, getattr(row, "product_name", "") or "")
            if identity_ok is False:
                _reject_wrong_crop(row)
                changed += 1
                continue

        try:
            with Image.open(source) as image:
                image.load()
                box = (
                    _edeka_refined_box(image, getattr(row, "source_text", "") or "")
                    if retailer == "edeka"
                    else _lidl_refined_box(image)
                )
        except OSError:
            continue
        identity = sha256(
            f"{retailer}|{getattr(row, 'product_name', '')}|{getattr(row, 'price', '')}|{box}".encode("utf-8")
        ).hexdigest()[:10]
        refined = _save_refined(source, box, f"card-{identity}")
        if refined is None:
            continue

        # A second EDEKA check protects against tightening away the article even
        # when it existed somewhere in the broad audit crop.
        if retailer == "edeka":
            refined_ok = _crop_contains_product(refined, getattr(row, "product_name", "") or "")
            if refined_ok is False:
                try:
                    refined.unlink(missing_ok=True)
                except OSError:
                    pass
                _reject_wrong_crop(row)
                changed += 1
                continue

        row.crop_quality_rejected = False
        row.audit_image_path = str(refined)
        row.image_path = str(refined)
        row.image_media_source = "prospect_crop"
        changed += 1
    return changed
