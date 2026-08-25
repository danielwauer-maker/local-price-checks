from __future__ import annotations

import argparse

from app.db_transfer import MigrationSafetyError
from app.sqlite_alembic import prepare_existing_sqlite_for_alembic


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely onboard an existing baseline SQLite database into Alembic (default: dry run)."
    )
    parser.add_argument("--sqlite-path", required=True, help="Explicit path to the historical SQLite database")
    parser.add_argument("--apply", action="store_true", help="Back up, migrate a staging copy, and atomically replace")
    parser.add_argument("--backup-path", help="Explicit non-existing backup path; defaults to a timestamped sibling")
    args = parser.parse_args()
    try:
        result = prepare_existing_sqlite_for_alembic(
            args.sqlite_path,
            apply=args.apply,
            backup_path=args.backup_path,
        )
    except (MigrationSafetyError, OSError) as exc:
        parser.exit(1, f"ABORT: {exc}\n")

    mode = "APPLIED" if result.applied else "DRY RUN"
    print(f"{mode}: database={result.database_path}")
    print(f"initial_revision={result.initial_revision or 'unversioned'}")
    print(f"final_revision={result.final_revision or 'unversioned'}")
    print(f"action={result.action}")
    if result.backup_path:
        print(f"backup={result.backup_path}")
    if not result.applied and result.action != "already-current":
        print("No data changed. Re-run with --apply only while the application is stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
