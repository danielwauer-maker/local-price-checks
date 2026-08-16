from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from collections import Counter

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
    return RetailSource(
        case.source_key,
        case.retailer,
        case.store_name,
        case.source_url,
        "store_page",
        "store_specific",
    )


def _plausibility(row):
    if row.quantity and row.unit_price and row.unit_price_unit:
        exp = None
        if row.unit == "g" and row.unit_price_unit == "kg":
            exp = row.quantity * row.unit_price / 1000
        elif row.unit == "kg" and row.unit_price_unit == "kg":
            exp = row.quantity * row.unit_price
        elif row.unit == "ml" and row.unit_price_unit == "l":
            exp = row.quantity * row.unit_price / 1000
        elif row.unit == "l" and row.unit_price_unit == "l":
            exp = row.quantity * row.unit_price
        if exp is not None and row.price:
            return abs(row.price - exp) / max(row.price, .05)
    return .08


def benchmark_case(case: Case):
    result = e.parse_pdf_file(_source(case), case.path)
    rows = result.rows
    bad = []
    for row in rows:
        quality = e.evaluate_offer(row)
        if not quality.accepted or _plausibility(row) > .22:
            bad.append(row)
    correct = len(rows) - len(bad)
    return result, correct, bad


def main():
    ap = argparse.ArgumentParser(description="Run the Local Price Checks 1.4.0 external PDF benchmark.")
    ap.add_argument("--rewe", type=Path, required=True)
    ap.add_argument("--netto", type=Path, required=True)
    ap.add_argument("--aldi", type=Path, required=True)
    ap.add_argument("--strict", action="store_true", help="Fail unless the historic 756/762 baseline is met or exceeded.")
    args = ap.parse_args()

    cases = [
        Case(
            "REWE Dierdorf", "REWE", "REWE:XL Hundertmark", "rewe_dierdorf",
            "https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
            args.rewe, 227, 227,
        ),
        Case(
            "Netto", "Netto Marken-Discount", "Netto Dierdorf", "netto_dierdorf",
            "https://www.netto-online.de/filialen/dierdorf/koenigsberger-str-24/6822",
            args.netto, 359, 361,
        ),
        Case(
            "ALDI SÜD", "ALDI SÜD", "ALDI SÜD Dierdorf", "aldi_dierdorf",
            "https://www.aldi-sued.de/angebote",
            args.aldi, 170, 174,
        ),
    ]

    total_rows = total_correct = 0
    expected_correct = sum(c.expected_correct for c in cases)
    expected_total = sum(c.expected_total for c in cases)

    for case in cases:
        if not case.path.exists():
            raise SystemExit(f"Referenzdatei fehlt: {case.path}")
        result, correct, bad = benchmark_case(case)
        total_rows += len(result.rows)
        total_correct += correct
        print(f"{case.name}: {correct}/{len(result.rows)} rows; historic gate {case.expected_correct}/{case.expected_total}")
        if result.notes:
            for note in result.notes:
                print(f"  - {note}")
        if bad:
            print(f"  questionable rows: {len(bad)}")
            for row in bad[:10]:
                print(f"    {row.product_name!r} -> {row.price}")

    quality = (total_correct / total_rows * 100) if total_rows else 0
    print(f"TOTAL parsed quality: {total_correct}/{total_rows} = {quality:.2f}%")
    print(f"Historic release baseline: {expected_correct}/{expected_total} = {expected_correct/expected_total*100:.2f}%")

    if args.strict:
        # The migration gate is intentionally tied to the established release
        # counts, not just a percentage over a smaller parser result set.
        if total_rows < expected_total or total_correct < expected_correct:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
