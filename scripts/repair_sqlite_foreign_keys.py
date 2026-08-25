from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REPAIRABLE_OFFER_FOREIGN_KEYS = {
    ("offer_occurrences", "offers", "offer_id", "id"),
    ("offer_price_references", "offers", "offer_id", "id"),
    ("offer_provenance", "offers", "offer_id", "id"),
}
DELETE_BATCH_SIZE = 500


def _foreign_key_details(connection: sqlite3.Connection, table: str, foreign_key_id: int) -> tuple[str, str, str]:
    quoted_table = table.replace('"', '""')
    rows = connection.execute(f'PRAGMA foreign_key_list("{quoted_table}")').fetchall()
    matching = [row for row in rows if row[0] == foreign_key_id]
    if len(matching) != 1:
        return ("<unknown>", "<unknown>", "<unknown>")
    row = matching[0]
    return (str(row[2]), str(row[3]), str(row[4]))


def _foreign_key_issues(connection: sqlite3.Connection) -> list[tuple[str, int, str, int, str, str]]:
    issues = []
    for table, rowid, parent, foreign_key_id in connection.execute("PRAGMA foreign_key_check").fetchall():
        actual_parent, child_column, parent_column = _foreign_key_details(connection, table, foreign_key_id)
        if actual_parent != parent:
            child_column = parent_column = "<unknown>"
        issues.append((table, int(rowid), parent, int(foreign_key_id), child_column, parent_column))
    return issues


def _print_checks(
    connection: sqlite3.Connection,
    label: str,
) -> tuple[list[str], list[tuple[str, int, str, int, str, str]]]:
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()]
    issues = _foreign_key_issues(connection)
    print(f"{label} integrity_check: {', '.join(integrity)}")
    print(f"{label} foreign_key_check: {len(issues)} issue(s)")
    grouped = Counter((table, parent, child_column, parent_column) for table, _, parent, _, child_column, parent_column in issues)
    for (table, parent, child_column, parent_column), count in sorted(grouped.items()):
        print(f"- {table}.{child_column} -> {parent}.{parent_column}: {count}")
    return integrity, issues


def _backup_database(connection: sqlite3.Connection, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        raise FileExistsError(f"Backup already exists: {backup_path}")
    backup_connection = sqlite3.connect(backup_path)
    try:
        connection.backup(backup_connection)
    finally:
        backup_connection.close()


def _delete_rowids(connection: sqlite3.Connection, table: str, rowids: list[int]) -> int:
    deleted = 0
    for offset in range(0, len(rowids), DELETE_BATCH_SIZE):
        batch = rowids[offset : offset + DELETE_BATCH_SIZE]
        placeholders = ", ".join("?" for _ in batch)
        if table == "offer_provenance":
            connection.execute(
                f"DELETE FROM prospect_offer_reviews WHERE offer_provenance_id IN "
                f"(SELECT id FROM offer_provenance WHERE rowid IN ({placeholders}))",
                batch,
            )
        cursor = connection.execute(f'DELETE FROM "{table}" WHERE rowid IN ({placeholders})', batch)
        deleted += cursor.rowcount
    return deleted


def repair_sqlite_foreign_keys(
    sqlite_path: str | Path,
    *,
    apply: bool = False,
    backup_path: str | Path | None = None,
) -> int:
    path = Path(sqlite_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        integrity, issues = _print_checks(connection, "Before")
        if integrity != ["ok"]:
            print("ABORT: integrity_check did not return 'ok'; no data changed.")
            return 2
        unexpected = [
            issue
            for issue in issues
            if (issue[0], issue[2], issue[4], issue[5]) not in REPAIRABLE_OFFER_FOREIGN_KEYS
        ]
        if unexpected:
            print(f"ABORT: {len(unexpected)} unexpected foreign-key issue(s); no data changed.")
            return 2
        if not issues:
            print("Nothing to repair.")
            return 0
        if not apply:
            print("Dry run only. Re-run with --apply to remove only the listed orphan child rows.")
            return 0

        destination = (
            Path(backup_path).expanduser().resolve()
            if backup_path
            else path.with_name(f"{path.name}.backup-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
        )
        if destination == path:
            raise ValueError("Backup path must differ from the SQLite database path")
        _backup_database(connection, destination)
        print(f"Backup: {destination}")

        by_table: dict[str, list[int]] = {}
        for table, rowid, _, _, _, _ in issues:
            by_table.setdefault(table, []).append(rowid)
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table in ("offer_occurrences", "offer_price_references", "offer_provenance"):
                rowids = by_table.get(table, [])
                if rowids:
                    print(f"Deleted {table}: {_delete_rowids(connection, table, rowids)}")
            final_integrity, remaining = _print_checks(connection, "After")
            if final_integrity != ["ok"] or remaining:
                raise RuntimeError("post-repair integrity checks failed; rolling back")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return 0
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely inspect and repair known orphan Offer child rows in SQLite.")
    parser.add_argument("sqlite_path", help="Path to the SQLite database")
    parser.add_argument("--apply", action="store_true", help="Create a backup and delete the known orphan child rows")
    parser.add_argument("--backup-path", help="Explicit backup destination; defaults to a timestamped sibling file")
    args = parser.parse_args()
    return repair_sqlite_foreign_keys(args.sqlite_path, apply=args.apply, backup_path=args.backup_path)


if __name__ == "__main__":
    raise SystemExit(main())
