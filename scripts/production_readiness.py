from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.db import SessionLocal
from app.production_readiness import build_multi_market_readiness


def main() -> int:
    db = SessionLocal()
    try:
        report = build_multi_market_readiness(db)
    finally:
        db.close()

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
