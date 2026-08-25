from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Direct execution sets sys.path[0] to /app/scripts, not the repository root.
# Add the script's own parent deterministically so the documented container
# command works without a manually supplied PYTHONPATH.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.category_classifier import reclassify_products
from app.db import SessionLocal


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclassify products with the deterministic Lokero taxonomy.")
    parser.add_argument("--apply", action="store_true", help="Persist unlocked category changes")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        summary = reclassify_products(db, apply=args.apply)
        for entry in summary.entries:
            if entry.status in {"changed", "locked", "unknown"}:
                print(
                    f"id={entry.product_id} name={entry.product_name!r} "
                    f"old={entry.old_category or '-'} new={entry.new_category} "
                    f"status={entry.status} reason={entry.reason}"
                )
        mode = "APPLIED" if args.apply else "DRY RUN"
        print(
            f"{mode}: inspected={summary.inspected} changed={summary.changed} "
            f"unchanged={summary.unchanged} locked={summary.locked} unknown={summary.unknown}"
        )
        if not args.apply:
            print("No data changed. Re-run with --apply after reviewing this plan.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
