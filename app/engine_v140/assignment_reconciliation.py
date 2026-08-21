from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
import unicodedata

import pymupdf

from .collectors import CollectedOffer, cat, compute_unit_price, size, upr, upr_unit
from .product_cleaning import clean_product_name, product_name_issue


_PAGE_RE = re.compile(r"\bPDF\s+Seite\s+(\d+)\b", re.I)
_MONEY_RE = re.compile(r"(?<!\d)(\d{1,3}[.,]\d{2})(?!\d)")
_BAD_NAME_FRAGMENTS = (
    "er ein genuss",
    "deutschland ohne deko",
    "teilnehmenden märkten",
    "teilnehmenden maerkten",
    "tiefgefroren versch sorten",
    "ohne deko",
)


@dataclass(frozen=True)
class AssignmentMetrics:
    checked: int = 0
    correct: int = 0
    corrected: int = 0
    rejected: int = 0
    recovered: int = 0

    @property
    def accuracy(self) -> float:
        return round(self.correct / self.checked * 100.0, 1) if self.checked else 100.0


def _fold(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", (value or "").lower())
        if not unicodedata.combining(char)
    )


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]{3,}", _fold(value))
        if token not in {"und", "oder", "mit", "versch", "sorten", "original", "classic", "aktion"}
    }


def _same_product(a: str, b: str) -> bool:
    left = _tokens(a)
    right = _tokens(b)
    if not left or not right:
        return False
    overlap = left & right
    return len(overlap) >= min(2, len(left), len(right)) and len(overlap) / max(1, min(len(left), len(right))) >= 0.6


def _page_number(row) -> int | None:
    match = _PAGE_RE.search(getattr(row, "source_text", "") or "")
    if not match:
        return None
    return int(match.group(1))


def _normalized_unit(unit: str | None) -> str | None:
    value = (unit or "").lower().strip().rstrip(".")
    aliases = {
        "liter": "l",
        "milliliter": "ml",
        "kilogramm": "kg",
        "gramm": "g",
        "st": "stück",
        "stk": "stück",
    }
    return aliases.get(value, value or None)


def expected_price_from_unit(
    quantity: float | None,
    unit: str | None,
    unit_price: float | None,
    unit_price_unit: str | None,
) -> float | None:
    """Return a two-decimal selling price implied by package and base unit price.

    This is a validation signal, not a replacement for visible prospect prices.
    It is intentionally limited to compatible mass/volume units.
    """
    if quantity is None or unit_price is None or quantity <= 0 or unit_price <= 0:
        return None
    u = _normalized_unit(unit)
    base = _normalized_unit(unit_price_unit)
    factor = None
    if u == base and u in {"kg", "l"}:
        factor = float(quantity)
    elif u == "g" and base == "kg":
        factor = float(quantity) / 1000.0
    elif u == "ml" and base == "l":
        factor = float(quantity) / 1000.0
    if factor is None:
        return None
    value = factor * float(unit_price)
    if not 0.05 <= value <= 500:
        return None
    return round(value + 1e-9, 2)


def _price_close(a: float | None, b: float | None, *, cents: float = 0.031) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= max(cents, min(float(a), float(b)) * 0.0075)


def _suspicious_name(name: str) -> bool:
    cleaned = clean_product_name(name or "").strip()
    folded = re.sub(r"[^a-z0-9]+", " ", _fold(cleaned)).strip()
    if not cleaned or product_name_issue(cleaned):
        return True
    if any(fragment in folded for fragment in _BAD_NAME_FRAGMENTS):
        return True
    words = re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", cleaned)
    return len(words) < 1 or len(cleaned) < 4


def _page_money_values(page) -> list[float]:
    values = []
    for raw in _MONEY_RE.findall(page.get_text("text", sort=True) or ""):
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        if 0.05 <= value <= 500:
            values.append(value)
    return values


def _append_marker(row, marker: str) -> None:
    text = (getattr(row, "source_text", "") or "").strip()
    if marker not in text:
        row.source_text = f"{text}\n{marker}".strip()[:4000]


def _set_assignment_metrics(rows: list, metrics: AssignmentMetrics) -> None:
    for row in rows:
        row.product_price_assignment_checked = metrics.checked
        row.product_price_assignment_correct = metrics.correct
        row.product_price_assignment_corrected = metrics.corrected
        row.product_price_assignment_rejected = metrics.rejected
        row.product_price_assignment_recovered = metrics.recovered
        row.product_price_assignment_accuracy = metrics.accuracy


def _candidate_context(product, raw_blocks) -> str:
    # Keep details in the same visual column. A small vertical corridor is
    # enough to capture package/base-price text without pulling in neighbours.
    x0 = product.rect.x0 - 22
    x1 = product.rect.x1 + 90
    y0 = product.rect.y0 - 12
    y1 = product.rect.y1 + 125
    selected = []
    for block in raw_blocks:
        cx = (block.rect.x0 + block.rect.x1) / 2
        cy = (block.rect.y0 + block.rect.y1) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            selected.append(block)
    selected.sort(key=lambda item: (item.rect.y0, item.rect.x0))
    parts = []
    for text in [product.text, *(item.text for item in selected)]:
        value = (text or "").strip()
        if value and value not in parts:
            parts.append(value)
    return "\n".join(parts)


def _clone_lidl_offer(source, template, *, name: str, price: float, regular: float | None, app_price: float | None,
                      context: str, quantity: float | None, unit: str | None, unit_price: float | None,
                      unit_price_unit: str | None, page_no: int, image_path: str | None) -> CollectedOffer:
    row = CollectedOffer(
        source_key=source.key,
        store_name=source.store_name,
        retailer=source.retailer,
        product_name=name[:180],
        category=cat(name),
        price=price,
        regular_price=regular,
        app_price=app_price,
        unit_price=unit_price,
        unit_price_unit=unit_price_unit,
        quantity=quantity,
        unit=unit,
        valid_from=getattr(template, "valid_from", None),
        valid_to=getattr(template, "valid_to", None),
        source_text=f"PDF Seite {page_no}: LidlPdfText:LOCAL_ONLY {context}"[:4000],
        source_url=getattr(template, "source_url", None) or getattr(source, "url", ""),
        local_store_offer=True,
        confidence=.995,
    )
    row.lidl_availability = "LOCAL_ONLY"
    if image_path:
        row.image_path = image_path
        row.audit_image_path = image_path
        row.image_alt = name
    return row


def _reconcile_lidl(source, pdf_path: Path, rows: list) -> tuple[list, AssignmentMetrics]:
    from . import lidl_pdf as lp

    document = pymupdf.open(pdf_path)
    by_page: dict[int, list] = {}
    for row in rows:
        page = _page_number(row)
        if page:
            by_page.setdefault(page, []).append(row)

    checked = correct = corrected = rejected = recovered = 0
    output = list(rows)

    for page_no, page_rows in by_page.items():
        if not (1 <= page_no <= len(document)):
            continue
        page = document[page_no - 1]
        raw_blocks = [
            lp._Block(pymupdf.Rect(*block[:4]), block[4].strip())
            for block in page.get_text("blocks", sort=True)
            if block[4].strip() and block[1] < page.rect.height * 0.95
        ]
        anchors = lp._price_anchors(page, raw_blocks)
        page_values = [anchor.price for anchor in anchors]

        released_prices: list[float] = []
        for row in page_rows:
            expected = expected_price_from_unit(
                getattr(row, "quantity", None),
                getattr(row, "unit", None),
                getattr(row, "unit_price", None),
                getattr(row, "unit_price_unit", None),
            )
            if expected is None:
                continue
            checked += 1
            current = float(getattr(row, "price", 0) or 0)
            if _price_close(current, expected):
                correct += 1
                continue

            matching = [anchor for anchor in anchors if _price_close(anchor.price, expected)]
            if matching:
                old = current
                anchor = min(matching, key=lambda item: abs(item.price - expected))
                row.price = float(anchor.price)
                if anchor.regular_price and anchor.regular_price > row.price:
                    row.regular_price = float(anchor.regular_price)
                if anchor.app_price and anchor.app_price < row.price:
                    row.app_price = float(anchor.app_price)
                    _append_marker(row, f"SPECIAL_PRICE kind=lidl_plus label=Lidl Plus price={anchor.app_price:.2f}")
                _append_marker(row, f"ASSIGNMENT_RECONCILED original={old:.2f} corrected={row.price:.2f} via=unit_price")
                released_prices.append(old)
                correct += 1
                corrected += 1
            else:
                # Strong economic evidence but no matching visible selling
                # price is a dangerous assignment. Keep it out of public import.
                row.assignment_quality_rejected = True
                _append_marker(row, f"ASSIGNMENT_SUSPECT current={current:.2f} expected={expected:.2f}")
                rejected += 1

        # A displaced neighbour can leave a real article without a row at all
        # (page 14: Iglo while Duplo owned the 4.99 anchor). Revisit unused title
        # candidates, but recover only when package x unit-price independently
        # predicts an exact visible selling-price anchor.
        products = lp._product_candidates(page, raw_blocks)
        current_names = [getattr(row, "product_name", "") for row in page_rows if not getattr(row, "assignment_quality_rejected", False)]
        template = page_rows[0] if page_rows else (rows[0] if rows else None)
        if template is None:
            continue
        for product in products:
            name = lp._product_name(product.title_text or product.text)
            if not name or _suspicious_name(name) or any(_same_product(name, existing) for existing in current_names):
                continue
            context = _candidate_context(product, raw_blocks)
            quantity, unit = size(context)
            unit_price = upr(context)
            unit_price_unit = upr_unit(context)
            expected = expected_price_from_unit(quantity, unit, unit_price, unit_price_unit)
            if expected is None:
                continue
            candidates = [anchor for anchor in anchors if _price_close(anchor.price, expected)]
            if not candidates:
                continue
            anchor = min(candidates, key=lambda item: lp._layout_distance(product.rect, item.rect))
            if lp._layout_distance(product.rect, anchor.rect) > 210:
                continue
            # Recovery is allowed when the anchor was released by a corrected
            # neighbour or when no current row already claims this product.
            if released_prices and not any(_price_close(anchor.price, value) for value in released_prices):
                claimed = any(_price_close(getattr(row, "price", None), anchor.price) for row in page_rows)
                if claimed:
                    continue
            crop_path = None
            crop_parent = next(
                (
                    Path(getattr(row, "audit_image_path")).parent
                    for row in page_rows
                    if getattr(row, "audit_image_path", None)
                ),
                None,
            )
            if crop_parent is not None:
                generated = lp._crop_offer(
                    page,
                    product.rect | anchor.rect,
                    crop_parent,
                    f"{pdf_path}:{page_no}:{name}:{anchor.price}:recovered",
                )
                crop_path = str(generated) if generated else None
            new_row = _clone_lidl_offer(
                source,
                template,
                name=name,
                price=float(anchor.price),
                regular=float(anchor.regular_price) if anchor.regular_price else None,
                app_price=float(anchor.app_price) if anchor.app_price else None,
                context=f"{context}\n{anchor.text}",
                quantity=quantity,
                unit=unit,
                unit_price=unit_price,
                unit_price_unit=unit_price_unit,
                page_no=page_no,
                image_path=crop_path,
            )
            if new_row.app_price and new_row.app_price < new_row.price:
                _append_marker(new_row, f"SPECIAL_PRICE kind=lidl_plus label=Lidl Plus price={new_row.app_price:.2f}")
            _append_marker(new_row, "ASSIGNMENT_RECOVERED via=unit_price_anchor")
            output.append(new_row)
            page_rows.append(new_row)
            current_names.append(name)
            checked += 1
            correct += 1
            recovered += 1

    document.close()
    output = [row for row in output if not getattr(row, "assignment_quality_rejected", False)]
    metrics = AssignmentMetrics(checked, correct, corrected, rejected, recovered)
    _set_assignment_metrics(output, metrics)
    return output, metrics


def _edeka_cell(anchor, anchors, width: int, height: int) -> tuple[int, int, int, int]:
    """Create a card cell around one red EDEKA price tag.

    Midpoints to nearby price tags are used as hard separators, preventing OCR
    text from crossing into a neighbouring offer card.
    """
    ax0, ay0, ax1, ay1 = anchor.bbox
    cx = (ax0 + ax1) / 2
    cy = (ay0 + ay1) / 2
    left, right = 0.0, float(width)
    top, bottom = 0.0, float(height)

    horizontal = []
    vertical = []
    for other in anchors:
        if other is anchor:
            continue
        ox0, oy0, ox1, oy1 = other.bbox
        ocx = (ox0 + ox1) / 2
        ocy = (oy0 + oy1) / 2
        if abs(ocy - cy) <= 190:
            horizontal.append((ocx, ocy))
        if abs(ocx - cx) <= 230:
            vertical.append((ocx, ocy))
    for ocx, _ in horizontal:
        midpoint = (cx + ocx) / 2
        if ocx < cx:
            left = max(left, midpoint)
        else:
            right = min(right, midpoint)
    for _, ocy in vertical:
        midpoint = (cy + ocy) / 2
        if ocy < cy:
            top = max(top, midpoint)
        else:
            bottom = min(bottom, midpoint)

    # Offer information normally sits above/around the red tag. Cap giant cells
    # to avoid headers and adjacent editorial content on sparse pages.
    max_w = min(float(width), 520.0)
    max_h = min(float(height), 620.0)
    if right - left > max_w:
        left = max(0.0, cx - max_w * 0.58)
        right = min(float(width), cx + max_w * 0.42)
    if bottom - top > max_h:
        top = max(0.0, cy - max_h * 0.82)
        bottom = min(float(height), cy + max_h * 0.18)
    top = max(0.0, min(top, ay0 - 70))
    bottom = min(float(height), max(bottom, ay1 + 45))
    return int(left), int(top), int(right), int(bottom)


def _edeka_page_is_bad(page_rows: list) -> bool:
    if not page_rows:
        return False
    suspicious = sum(
        1 for row in page_rows
        if _suspicious_name(getattr(row, "product_name", "")) or getattr(row, "crop_quality_rejected", False)
    )
    return suspicious >= 2 and suspicious / len(page_rows) >= 0.28


def _save_card_crop(image, bbox: tuple[int, int, int, int], target_dir: Path | None, identity: str) -> str | None:
    if target_dir is None:
        return None
    try:
        import hashlib
        target_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(identity.encode("utf-8", errors="ignore")).hexdigest()[:20]
        path = target_dir / f"edeka-card-{digest}.jpg"
        image.crop(bbox).convert("RGB").save(path, format="JPEG", quality=92, optimize=True)
        return str(path)
    except (OSError, ValueError):
        return None


def _resegment_edeka_page(source, pdf_path: Path, page_no: int, page_rows: list) -> list:
    from . import edeka_pdf as ep

    document = pymupdf.open(pdf_path)
    try:
        page = document[page_no - 1]
        image = ep._render_page(page)
        words = ep._ocr_words(image)
        anchors = [ep._anchor_from_box(image, bbox) for bbox in ep._red_components(image)]
        anchors = [anchor for anchor in anchors if anchor is not None]
        if not anchors:
            return []

        template = page_rows[0]
        target_dir = next(
            (
                Path(getattr(row, "audit_image_path")).parent
                for row in page_rows
                if getattr(row, "audit_image_path", None)
            ),
            None,
        )
        rebuilt = []
        seen: set[tuple[str, float]] = set()
        for anchor in anchors:
            cell = _edeka_cell(anchor, anchors, image.width, image.height)
            x0, y0, x1, y1 = cell
            lines = ep._line_groups(words, x0=x0, y0=y0, x1=x1, y1=y1)
            name = ep._product_name(lines, anchor.bbox[1])
            dense_lines: list[str] = []
            if not name or _suspicious_name(name):
                dense_lines = ep._dense_ocr_lines(image, cell, psm=6)
                dense_name = ep._dense_product_name(dense_lines)
                if dense_name and not _suspicious_name(dense_name):
                    name = dense_name
            if not name or _suspicious_name(name):
                continue
            text_lines = [line["text"] for line in lines]
            combined = ep._normalize_context("\n".join([*text_lines, *dense_lines]))
            quantity, unit = ep._quantity(combined)
            unit_price, unit_price_unit = ep._unit_price(combined)
            key = (clean_product_name(name).lower(), round(float(anchor.price), 2))
            if key in seen:
                continue
            seen.add(key)
            image_path = _save_card_crop(
                image,
                cell,
                target_dir,
                f"{pdf_path}:{page_no}:{name}:{anchor.price}",
            )
            row = CollectedOffer(
                source_key=source.key,
                store_name=source.store_name,
                retailer=source.retailer,
                product_name=clean_product_name(name)[:180],
                category=cat(name),
                price=float(anchor.price),
                regular_price=float(anchor.reference_price) if anchor.reference_price else None,
                unit_price=unit_price,
                unit_price_unit=unit_price_unit,
                quantity=quantity,
                unit=unit,
                valid_from=getattr(template, "valid_from", None),
                valid_to=getattr(template, "valid_to", None),
                source_text=(
                    f"PDF Seite {page_no}: EDEKA OCR CARD_CELL bbox={cell} "
                    f"price_bbox={anchor.bbox} {combined}"
                )[:4000],
                source_url=getattr(template, "source_url", None) or getattr(source, "url", ""),
                local_store_offer=True,
                confidence=.995,
            )
            row.card_bbox = cell
            row.assignment_cell_verified = True
            if image_path:
                row.image_path = image_path
                row.audit_image_path = image_path
                row.image_alt = row.product_name
            rebuilt.append(row)
        return rebuilt
    except Exception:
        return []
    finally:
        document.close()


def _reconcile_edeka(source, pdf_path: Path, rows: list) -> tuple[list, AssignmentMetrics]:
    by_page: dict[int, list] = {}
    for row in rows:
        page = _page_number(row)
        if page:
            by_page.setdefault(page, []).append(row)

    output = list(rows)
    checked = correct = corrected = rejected = recovered = 0
    for page_no, page_rows in by_page.items():
        # Economic validation applies on all pages and catches neighbour-price
        # swaps even when the OCR title itself is fine.
        for row in page_rows:
            expected = expected_price_from_unit(
                getattr(row, "quantity", None),
                getattr(row, "unit", None),
                getattr(row, "unit_price", None),
                getattr(row, "unit_price_unit", None),
            )
            if expected is None:
                continue
            checked += 1
            if _price_close(getattr(row, "price", None), expected):
                correct += 1
            else:
                row.assignment_quality_rejected = True
                rejected += 1

        if not _edeka_page_is_bad(page_rows):
            continue
        rebuilt = _resegment_edeka_page(source, pdf_path, page_no, page_rows)
        good_existing = sum(not _suspicious_name(getattr(row, "product_name", "")) for row in page_rows)
        good_rebuilt = sum(not _suspicious_name(getattr(row, "product_name", "")) for row in rebuilt)
        # Replace a broken OCR page only with a materially stronger card-cell
        # result. This prevents a fallback attempt from regressing healthy pages.
        if good_rebuilt >= 3 and good_rebuilt > good_existing:
            output = [row for row in output if _page_number(row) != page_no]
            output.extend(rebuilt)
            recovered += len(rebuilt)
            checked += len(rebuilt)
            correct += len(rebuilt)

    output = [row for row in output if not getattr(row, "assignment_quality_rejected", False)]
    metrics = AssignmentMetrics(checked, correct, corrected, rejected, recovered)
    _set_assignment_metrics(output, metrics)
    return output, metrics


def reconcile_pdf_assignments(source, pdf_path: Path, rows: list) -> tuple[list, AssignmentMetrics]:
    retailer = str(getattr(source, "retailer", "") or "").strip().lower()
    if retailer == "lidl":
        return _reconcile_lidl(source, Path(pdf_path), list(rows or []))
    if retailer == "edeka":
        return _reconcile_edeka(source, Path(pdf_path), list(rows or []))
    metrics = AssignmentMetrics()
    _set_assignment_metrics(list(rows or []), metrics)
    return list(rows or []), metrics
