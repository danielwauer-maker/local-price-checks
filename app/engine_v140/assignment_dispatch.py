from __future__ import annotations

from pathlib import Path

from .assignment_reconciliation import AssignmentMetrics, expected_price_from_unit, _price_close, _reconcile_lidl
from .assignment_runtime import _reconcile_edeka


def _safe_lidl(source, pdf_path: Path, rows: list) -> tuple[list, AssignmentMetrics]:
    """Run economic reconciliation without confusing a conditional base price.

    Some Lidl cards print a unit price for the Lidl-Plus value rather than the
    generally available offer. Such a row is internally consistent with
    ``app_price`` and must not be 'corrected' to the conditional value.
    """
    temporarily_suppressed: dict[int, tuple[float | None, str | None]] = {}
    for row in rows:
        expected = expected_price_from_unit(
            getattr(row, "quantity", None),
            getattr(row, "unit", None),
            getattr(row, "unit_price", None),
            getattr(row, "unit_price_unit", None),
        )
        app_price = getattr(row, "app_price", None)
        normal_price = getattr(row, "price", None)
        if (
            expected is not None
            and app_price is not None
            and _price_close(expected, app_price)
            and not _price_close(expected, normal_price)
        ):
            temporarily_suppressed[id(row)] = (
                getattr(row, "unit_price", None),
                getattr(row, "unit_price_unit", None),
            )
            row.unit_price = None
            row.unit_price_unit = None

    reconciled, metrics = _reconcile_lidl(source, pdf_path, rows)
    for row in reconciled:
        original = temporarily_suppressed.get(id(row))
        if original is not None:
            row.unit_price, row.unit_price_unit = original
    return reconciled, metrics


def reconcile_pdf_assignments(source, pdf_path: Path, rows: list) -> tuple[list, AssignmentMetrics]:
    retailer = str(getattr(source, "retailer", "") or "").strip().lower()
    clean = list(rows or [])
    if retailer == "lidl":
        return _safe_lidl(source, Path(pdf_path), clean)
    if retailer == "edeka":
        return _reconcile_edeka(source, Path(pdf_path), clean)
    metrics = AssignmentMetrics()
    return clean, metrics
