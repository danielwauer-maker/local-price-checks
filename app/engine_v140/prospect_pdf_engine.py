"""Local Price Checks 1.4.0 PDF engine.

The benchmarked parser source is kept in ordered source parts during the
migration into the Web-MVP repository. They are concatenated at import time so
the public API remains compatible with the 1.4.0 engine.
"""
from pathlib import Path
import re

_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("_prospect_pdf_engine_*.part"))
if len(_parts) != 4:
    raise RuntimeError(f"v1.4 PDF engine incomplete: expected 4 source parts, got {len(_parts)}")
_source = "".join(p.read_text(encoding="utf-8") for p in _parts)
exec(compile(_source, str(_here / "prospect_pdf_engine_v140.py"), "exec"), globals(), globals())

# Harden the migrated low-level helper: the original 1.4.0 card-level parser
# already rejected deposit values through surrounding layout logic. The Web-MVP
# also calls this helper independently, so remove explicit Pfand amounts before
# choosing a sale price.
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


# Public/detail images should show one complete offer card, not the broad
# neighbourhood crop that is useful only for parser debugging. Product/price
# assignment is reconciled first so media is generated for the corrected card.
_parse_pdf_file_v140 = parse_pdf_file


def parse_pdf_file(source, pdf_path):
    parsed = _parse_pdf_file_v140(source, pdf_path)
    try:
        from .assignment_runtime import reconcile_pdf_assignments

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
