from __future__ import annotations

import json

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
