from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path

from PIL import Image


_BBOX_RE = re.compile(
    r"bbox=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)\s+price_bbox=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)",
    re.I,
)


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


def _edeka_refined_box(image: Image.Image, source_text: str) -> tuple[int, int, int, int]:
    match = _BBOX_RE.search(source_text or "")
    if not match:
        # Fallback: price sits in the lower part of the existing EDEKA crop.
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

    # The price tag is a reliable card anchor. Keep substantially more space
    # above it for the product image/title, but much less than the old 480px
    # column crop which routinely included neighbouring cards.
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
    # Lidl's parser already centres the crop on the matched product/price union,
    # but historically enlarged it by ~2.1x/2.2x. A centred 72% crop retains
    # the complete matched card while removing most neighbouring products.
    width = int(image.width * 0.72)
    height = int(image.height * 0.72)
    x0 = (image.width - width) // 2
    y0 = (image.height - height) // 2
    return x0, y0, x0 + width, y0 + height


def refine_pdf_offer_crops(rows) -> int:
    """Replace broad Lidl/EDEKA audit crops with tighter card-level crops.

    The original PDFs remain immutable and available for audit. The refined
    crop is what product media persistence sees, so public/detail views no
    longer need to show neighbouring cards whenever a clean retailer image is
    unavailable.
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
        try:
            with Image.open(source) as image:
                image.load()
                if retailer == "edeka":
                    box = _edeka_refined_box(image, getattr(row, "source_text", "") or "")
                else:
                    box = _lidl_refined_box(image)
        except OSError:
            continue
        identity = sha256(
            f"{retailer}|{getattr(row, 'product_name', '')}|{getattr(row, 'price', '')}|{box}".encode("utf-8")
        ).hexdigest()[:10]
        refined = _save_refined(source, box, f"card-{identity}")
        if refined is None:
            continue
        row.audit_image_path = str(refined)
        row.image_path = str(refined)
        row.image_media_source = "prospect_crop"
        changed += 1
    return changed
