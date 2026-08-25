"""Fail-fast backup/restore helpers used by the PostgreSQL migration runbook."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
from pathlib import Path


def _new_output(path: str) -> Path:
    output = Path(path).expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing backup: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def backup_sqlite(source_value: str, output_value: str) -> None:
    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"SQLite source not found: {source}")
    output = _new_output(output_value)
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        target_connection = sqlite3.connect(output)
        source_connection.backup(target_connection)
        result = target_connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"Backup integrity_check failed: {result}")
    except Exception:
        if target_connection is not None:
            target_connection.close()
        output.unlink(missing_ok=True)
        raise
    finally:
        if source_connection is not None:
            source_connection.close()
        if target_connection is not None:
            target_connection.close()
    print(f"SQLite backup created and verified: {output}")


def _require_tool(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"Required PostgreSQL tool is not on PATH: {name}")
    return executable


def pg_dump(url: str, output_value: str) -> None:
    output = _new_output(output_value)
    try:
        subprocess.run([_require_tool("pg_dump"), "--dbname", url, "--format=custom", "--file", str(output)], check=True)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    print(f"PostgreSQL custom-format backup created: {output}")


def pg_restore(url: str, input_value: str) -> None:
    source = Path(input_value).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"PostgreSQL backup not found: {source}")
    subprocess.run(
        [_require_tool("pg_restore"), "--dbname", url, "--exit-on-error", "--single-transaction", str(source)],
        check=True,
    )
    print(f"PostgreSQL restore completed: {source}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lokero database backup/restore helpers")
    commands = parser.add_subparsers(dest="command", required=True)
    sqlite_command = commands.add_parser("sqlite")
    sqlite_command.add_argument("--source", required=True)
    sqlite_command.add_argument("--output", required=True)
    dump_command = commands.add_parser("pg-dump")
    dump_command.add_argument("--postgres-url", required=True)
    dump_command.add_argument("--output", required=True)
    restore_command = commands.add_parser("pg-restore")
    restore_command.add_argument("--postgres-url", required=True)
    restore_command.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        if args.command == "sqlite":
            backup_sqlite(args.source, args.output)
        elif args.command == "pg-dump":
            pg_dump(args.postgres_url, args.output)
        else:
            pg_restore(args.postgres_url, args.input)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
