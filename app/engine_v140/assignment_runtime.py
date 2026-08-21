from __future__ import annotations

from pathlib import Path

import pymupdf

from .assignment_reconciliation import (
    AssignmentMetrics,
    _page_number,
    _set_assignment_metrics,
    expected_price_from_unit,
    _price_close,
    _reconcile_lidl,
)
from .collectors import CollectedOffer, cat
from .edeka_name_quality import choose_consensus_name, strict_name_ok
from .product_cleaning import clean_product_name


def _cell(anchor, anchors, width: int, height: int) -> tuple[int, int, int, int]:
    ax0, ay0, ax1, ay1 = anchor.bbox
    cx = (ax0 + ax1) / 2
    cy = (ay0 + ay1) / 2
    left, right = 0.0, float(width)
    top, bottom = 0.0, float(height)

    for other in anchors:
        if other is anchor:
            continue
        ox0, oy0, ox1, oy1 = other.bbox
        ocx = (ox0 + ox1) / 2
        ocy = (oy0 + oy1) / 2
        if abs(ocy - cy) <= 190:
            midpoint = (cx + ocx) / 2
            if ocx < cx:
                left = max(left, midpoint)
            else:
                right = min(right, midpoint)
        if abs(ocx - cx) <= 230:
            midpoint = (cy + ocy) / 2
            if ocy < cy:
                top = max(top, midpoint)
            else:
                bottom = min(bottom, midpoint)

    max_w = min(float(width), 500.0)
    max_h = min(float(height), 580.0)
    if right - left > max_w:
        left = max(0.0, cx - max_w * 0.58)
        right = min(float(width), cx + max_w * 0.42)
    if bottom - top > max_h:
        top = max(0.0, cy - max_h * 0.84)
        bottom = min(float(height), cy + max_h * 0.16)
    top = max(0.0, min(top, ay0 - 55))
    bottom = min(float(height), max(bottom, ay1 + 30))
    return int(left), int(top), int(right), int(bottom)


def _bad_page(rows: list) -> bool:
    if not rows:
        return False
    suspicious = sum(
        1 for row in rows
        if not strict_name_ok(getattr(row, "product_name", ""))
        or bool(getattr(row, "crop_quality_rejected", False))
    )
    return suspicious >= 1 and suspicious / len(rows) >= 0.12


def _crop_target(page_rows: list) -> Path | None:
    for row in page_rows:
        raw = getattr(row, "audit_image_path", None) or getattr(row, "image_path", None)
        if raw:
            return Path(raw).parent
    return None


def _save_crop(image, bbox, target_dir: Path | None, identity: str) -> str | None:
    if target_dir is None:
        return None
    try:
        import hashlib
        target_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(identity.encode("utf-8", errors="ignore")).hexdigest()[:20]
        target = target_dir / f"edeka-card-{digest}.jpg"
        image.crop(bbox).convert("RGB").save(target, format="JPEG", quality=92, optimize=True)
        return str(target)
    except (OSError, ValueError):
        return None


def _ocr_name_candidates(ep, image, card, lines, anchor_top: int) -> tuple[list[str], list[str]]:
    candidates: list[str] = []
    context: list[str] = []
    structured = ep._product_name(lines, anchor_top)
    if structured:
        candidates.append(structured)
    for psm in (6, 11, 12):
        dense_lines = ep._dense_ocr_lines(image, card, psm=psm)
        context.extend(dense_lines)
        dense_name = ep._dense_product_name(dense_lines)
        if dense_name:
            candidates.append(dense_name)
    return candidates, context


def _rebuild_page(source, pdf_path: Path, page_no: int, page_rows: list) -> list:
    from . import edeka_pdf as ep

    document = pymupdf.open(pdf_path)
    try:
        page = document[page_no - 1]
        image = ep._prepared_page(page)
        words = ep._ocr_words(image, 35.0)
        anchors = [ep._anchor_from_box(image, bbox) for bbox in ep._red_components(image)]
        anchors = [anchor for anchor in anchors if anchor is not None]
        if not anchors:
            return []

        template = page_rows[0]
        target_dir = _crop_target(page_rows)
        rebuilt = []
        seen: set[tuple[str, float]] = set()
        for anchor in anchors:
            card = _cell(anchor, anchors, image.width, image.height)
            x0, y0, x1, y1 = card
            lines = ep._line_groups(words, x0=x0, y0=y0, x1=x1, y1=y1)
            candidates, dense_context = _ocr_name_candidates(ep, image, card, lines, anchor.bbox[1])
            name = choose_consensus_name(candidates)
            if not name:
                continue

            context_lines = [line["text"] for line in lines]
            combined = ep._normalize_context("\n".join([*context_lines, *dense_context]))
            quantity, unit = ep._quantity(combined)
            unit_price, unit_price_unit = ep._unit_price(combined)
            expected = expected_price_from_unit(quantity, unit, unit_price, unit_price_unit)
            if expected is not None and not _price_close(expected, anchor.price):
                continue

            key = (clean_product_name(name).lower(), round(float(anchor.price), 2))
            if key in seen:
                continue
            seen.add(key)
            crop = _save_crop(image, card, target_dir, f"{pdf_path}:{page_no}:{name}:{anchor.price}")
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
                    f"PDF Seite {page_no}: EDEKA OCR CARD_CELL_STRICT bbox={card} "
                    f"price_bbox={anchor.bbox} OCR_CONSENSUS name={name} {combined}"
                )[:4000],
                source_url=getattr(template, "source_url", None) or getattr(source, "url", ""),
                local_store_offer=True,
                confidence=.998,
            )
            row.card_bbox = card
            row.assignment_cell_verified = True
            row.edeka_name_consensus_verified = True
            if crop:
                row.image_path = crop
                row.audit_image_path = crop
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
        for row in page_rows:
            # Names that are visibly OCR fragments are never allowed into the
            # public offer list, even when their price happens to be plausible.
            if not strict_name_ok(getattr(row, "product_name", "")):
                row.assignment_quality_rejected = True
                rejected += 1
                continue
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

        if not _bad_page(page_rows):
            continue
        rebuilt = _rebuild_page(source, pdf_path, page_no, page_rows)
        good_existing = sum(
            strict_name_ok(getattr(row, "product_name", ""))
            and not getattr(row, "assignment_quality_rejected", False)
            for row in page_rows
        )
        good_rebuilt = len(rebuilt)
        # A strict rebuild may intentionally return fewer offers. Precision is
        # more important here than retaining OCR garbage, so replace the page
        # whenever it yields at least two consensus-verified cards and is not
        # catastrophically sparse relative to the original page.
        if good_rebuilt >= 2 and good_rebuilt >= max(2, good_existing // 2):
            output = [row for row in output if _page_number(row) != page_no]
            output.extend(rebuilt)
            recovered += len(rebuilt)
            checked += len(rebuilt)
            correct += len(rebuilt)

    output = [row for row in output if not getattr(row, "assignment_quality_rejected", False)]
    metrics = AssignmentMetrics(checked, correct, corrected, rejected, recovered)
    _set_assignment_metrics(output, metrics)
    for row in output:
        if str(getattr(row, "retailer", "")).upper() == "EDEKA":
            row.edeka_strict_names_rejected = rejected
    return output, metrics


def reconcile_pdf_assignments(source, pdf_path: Path, rows: list) -> tuple[list, AssignmentMetrics]:
    retailer = str(getattr(source, "retailer", "") or "").strip().lower()
    if retailer == "lidl":
        return _reconcile_lidl(source, Path(pdf_path), list(rows or []))
    if retailer == "edeka":
        return _reconcile_edeka(source, Path(pdf_path), list(rows or []))
    metrics = AssignmentMetrics()
    clean = list(rows or [])
    _set_assignment_metrics(clean, metrics)
    return clean, metrics
