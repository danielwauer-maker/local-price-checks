from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db_transfer import MigrationSafetyError, verify_migration


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Lokero SQLite-to-PostgreSQL migration")
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--postgres-url", required=True)
    args = parser.parse_args()
    try:
        report = verify_migration(args.sqlite_path, args.postgres_url)
    except MigrationSafetyError as exc:
        parser.exit(2, f"SAFETY ERROR: {exc}\n")
    print(report.render())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
