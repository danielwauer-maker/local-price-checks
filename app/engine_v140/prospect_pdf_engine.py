"""Local Price Checks 1.4.0 PDF engine.

The benchmarked parser source is kept in ordered source parts during the
migration into the Web-MVP repository. They are concatenated at import time so
the public API remains compatible with the 1.4.0 engine.
"""
from dataclasses import replace
from pathlib import Path
import re

_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("_prospect_pdf_engine_*.part"))
if len(_parts) != 4:
    raise RuntimeError(f"v1.4 PDF engine incomplete: expected 4 source parts, got {len(_parts)}")
_source = "".join(p.read_text(encoding="utf-8") for p in _parts)
exec(compile(_source, str(_here / "prospect_pdf_engine_v140.py"), "exec"), globals(), globals())

_extract_current_price_v140 = _extract_current_price

def _extract_current_price(text: str, retailer: str):
    cleaned = text or ""
    cleaned = re.sub(
        r"(?i)(?:zzgl\.?\s*)?(?:\d{1,3}[.,]\d{2})\s*(?:€\s*)?Pfand\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)\bPfand\s*(?:von\s*)?(?:\d{1,3}[.,]\d{2})\s*(?:€)?",
        " ",
        cleaned,
    )
    return _extract_current_price_v140(cleaned, retailer)


_parse_pdf_file_v140 = parse_pdf_file


def parse_pdf_file(source, pdf_path):
    parsed = _parse_pdf_file_v140(source, pdf_path)

    for row in getattr(parsed, "rows", []):
        try:
            app_price = float(getattr(row, "app_price", 0) or 0)
            offer_price = float(getattr(row, "price", 0) or 0)
        except (TypeError, ValueError):
            continue
        if app_price > 0 and offer_price > app_price:
            marker = f"SPECIAL_PRICE kind=lidl_plus label=Lidl Plus price={app_price:.2f}"
            source_text = (getattr(row, "source_text", "") or "").strip()
            if marker not in source_text:
                room = max(0, 3999 - len(marker))
                row.source_text = f"{source_text[:room]}\n{marker}".strip()

    try:
        from .assignment_dispatch import reconcile_pdf_assignments

        reconciled, assignment = reconcile_pdf_assignments(
            source,
            Path(pdf_path),
            getattr(parsed, "rows", []),
        )
        parsed.rows[:] = reconciled
        if hasattr(parsed, "notes"):
            parsed.notes.append(
                "product_price_assignment_"
                f"checked={assignment.checked} "
                f"correct={assignment.correct} "
                f"corrected={assignment.corrected} "
                f"rejected={assignment.rejected} "
                f"recovered={assignment.recovered} "
                f"accuracy={assignment.accuracy:.1f}"
            )
        if assignment.rejected:
            warning = (
                f"product_price_assignment_unresolved={assignment.rejected} "
                f"product_price_assignment_accuracy={assignment.accuracy:.1f}"
            )
            existing = (getattr(parsed, "technical_warning", None) or "").strip()
            parsed = replace(
                parsed,
                technical_warning=" | ".join(part for part in (existing, warning) if part),
            )
    except Exception as exc:
        if hasattr(parsed, "notes"):
            parsed.notes.append(f"assignment_reconciliation_warning={type(exc).__name__}: {exc}")

    try:
        from .crop_refinement import refine_pdf_offer_crops

        refined = refine_pdf_offer_crops(getattr(parsed, "rows", []))
        if refined and hasattr(parsed, "notes"):
            parsed.notes.append(f"refined_product_crops={refined}")
    except Exception as exc:
        if hasattr(parsed, "notes"):
            parsed.notes.append(f"crop_refinement_warning={type(exc).__name__}: {exc}")
    return parsed
