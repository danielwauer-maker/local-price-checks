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
