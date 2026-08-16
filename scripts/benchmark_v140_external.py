from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import re

import pymupdf as fitz

from app.engine_v140 import prospect_pdf_engine as e
from app.engine_v140.source_registry import RetailSource


@dataclass(frozen=True)
class Case:
    name: str
    retailer: str
    store_name: str
    source_key: str
    source_url: str
    path: Path
    expected_correct: int
    expected_total: int


def _source(case: Case) -> RetailSource:
    return RetailSource(case.source_key, case.retailer, case.store_name, case.source_url, "x", "x")


def _page_excluded(retailer: str, page_text: str, dominant_start):
    low = page_text.lower()
    pvf, _pvt = e._row_validity(page_text, page_text)
    if pvf and dominant_start:
        try:
            rv = datetime.strptime(pvf, "%d.%m.%Y").date()
            if rv < dominant_start - timedelta(days=1):
                return True
        except Exception:
            pass
    if retailer == "Netto Marken-Discount" and low.count("nur online") >= 2 and "online-kracher" in low:
        return True
    return False


def _plausible(row) -> bool:
    name = row.product_name.strip()
    low = name.lower()
    if len(name) < 3 or low in {"ki", "uvp", "ab", "je"}:
        return False
    if re.match(r"^\d+(?:[.,]\d+)?\s+(?:uvp|statt)", low):
        return False
    if re.search(r"\b(?:gültig\s+(?:am|ab|von)|kw\s*33|pfand)\b", low):
        return False
    if any(low.endswith(" " + x) for x in ("mit", "oder", "aus", "von", "für", "und")):
        return False
    if not (0.01 < row.price < 5000):
        return False

    expected = None
    if row.quantity and row.unit_price and row.unit_price_unit:
        if row.unit == "g" and row.unit_price_unit == "kg":
            expected = row.quantity * row.unit_price / 1000
        elif row.unit == "kg" and row.unit_price_unit == "kg":
            expected = row.quantity * row.unit_price
        elif row.unit == "ml" and row.unit_price_unit == "l":
            expected = row.quantity * row.unit_price / 1000
        elif row.unit == "l" and row.unit_price_unit == "l":
            expected = row.quantity * row.unit_price
    if expected and abs(row.price - expected) / max(row.price, .01) > .15:
        raw = (row.source_text or "").lower()
        # Tier/bundle prices legitimately differ from a single-item unit price.
        if not any(k in raw for k in ("einzelpreis", "ab 2 flaschen", "ab 4 flaschen", "ab 6 flaschen", "beim kauf von", "pro flasche", " für ")):
            return False
    return True


def benchmark_case(case: Case):
    source = _source(case)
    parsed = e.parse_pdf_file(source, case.path)
    doc = fitz.open(case.path)
    full_text = e._document_text(doc)
    groups = matched = good = 0
    for page_no, page in enumerate(doc, 1):
        text = page.get_text("text") or ""
        if _page_excluded(case.retailer, text, parsed.valid_from):
            continue
        valid_from, valid_to = e._row_validity(text, full_text)
        rows, anchor_count, matched_count = e._anchor_first_page_rows(
            page, source, case.retailer, page_no, valid_from, valid_to, case.source_url
        )
        groups += anchor_count
        matched += matched_count
        good += sum(_plausible(row) for row in rows)
    return parsed, groups, matched, good


def main():
    ap = argparse.ArgumentParser(description="Run the exact Local Price Checks 1.4.0 external PDF benchmark.")
    ap.add_argument("--rewe", type=Path, required=True)
    ap.add_argument("--netto", type=Path, required=True)
    ap.add_argument("--aldi", type=Path, required=True)
    ap.add_argument("--strict", action="store_true", help="Fail unless historic per-retailer gates are met or exceeded.")
    args = ap.parse_args()

    cases = [
        Case(
            "REWE", "REWE", "REWE:XL Hundertmark", "rewe_dierdorf",
            "https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
            args.rewe, 227, 227,
        ),
        Case(
            "Netto", "Netto Marken-Discount", "Netto Dierdorf", "netto_dierdorf",
            "https://www.netto-online.de/filialen/dierdorf/koenigsberger-str-24/6822",
            args.netto, 359, 361,
        ),
        Case(
            "ALDI", "ALDI SÜD", "ALDI SÜD Dierdorf", "aldi_dierdorf",
            "https://www.aldi-sued.de/angebote",
            args.aldi, 170, 174,
        ),
    ]

    total_groups = total_matched = total_good = 0
    failed = False
    for case in cases:
        if not case.path.exists():
            raise SystemExit(f"Referenzdatei fehlt: {case.path}")
        parsed, groups, matched, good = benchmark_case(case)
        total_groups += groups
        total_matched += matched
        total_good += good
        print(f"{case.name}: groups={groups} matched={matched} validated={good} parsed_rows={len(parsed.rows)}")
        print(f"  release gate: {case.expected_correct}/{case.expected_total}")
        if args.strict and (groups < case.expected_total or good < case.expected_correct):
            failed = True

    recall = total_matched / total_groups * 100 if total_groups else 0
    quality = total_good / total_groups * 100 if total_groups else 0
    print(f"TOTAL {total_groups} groups, {total_matched} matched, {total_good} validated")
    print(f"recall={recall:.4f}% validated={quality:.4f}%")
    print("historic baseline: 762 groups / 756 validated = 99.2126%")

    if args.strict and (failed or total_groups < 762 or total_good < 756):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
