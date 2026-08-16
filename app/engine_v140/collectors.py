"""Full Local Price Checks 1.4.0 structured web collector.

The benchmarked source is kept in ordered source parts during the migration to
the mobile Web-MVP repository. The parts are concatenated and executed inside
this module so its original relative imports and public API stay unchanged.
"""
from pathlib import Path

_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("_collectors_*.part"))
if len(_parts) != 4:
    raise RuntimeError(f"v1.4 web collector incomplete: expected 4 source parts, got {len(_parts)}")
_source = "".join(p.read_text(encoding="utf-8") for p in _parts)
exec(compile(_source, str(_here / "collectors_v140.py"), "exec"), globals(), globals())
