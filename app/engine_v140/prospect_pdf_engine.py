"""Local Price Checks 1.4.0 PDF engine.

The original benchmarked source is stored in ordered source parts during the
migration into the Web-MVP repository.  They are concatenated verbatim at
import time so the public API remains identical to the 1.4.0 engine.
"""
from pathlib import Path

_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("_prospect_pdf_engine_*.part"))
if len(_parts) != 4:
    raise RuntimeError(f"v1.4 PDF engine incomplete: expected 4 source parts, got {len(_parts)}")
_source = "".join(p.read_text(encoding="utf-8") for p in _parts)
exec(compile(_source, str(_here / "prospect_pdf_engine_v140.py"), "exec"), globals(), globals())
