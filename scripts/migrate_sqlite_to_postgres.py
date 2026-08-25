from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db_transfer import MigrationSafetyError, migrate_sqlite_to_postgres


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely copy a Lokero SQLite database to PostgreSQL")
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--postgres-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-nonempty", action="store_true", help="Explicitly permit inserts into a reviewed non-empty target; existing rows are never overwritten")
    args = parser.parse_args()
    try:
        summary = migrate_sqlite_to_postgres(
            args.sqlite_path,
            args.postgres_url,
            dry_run=args.dry_run,
            allow_nonempty=args.allow_nonempty,
        )
    except MigrationSafetyError as exc:
        parser.exit(2, f"SAFETY ERROR: {exc}\n")
    print(summary.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
