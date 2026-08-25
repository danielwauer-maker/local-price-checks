"""Safe, reusable SQLite-to-PostgreSQL transfer and verification helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import Connection, Engine, MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import URL, make_url

from .model_registry import metadata as application_metadata

BATCH_SIZE = 1_000
ALEMBIC_TABLE = "alembic_version"


class MigrationSafetyError(RuntimeError):
    """Raised before any write when a migration safety condition is not met."""


@dataclass
class VerificationReport:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append((name, passed, detail))

    @property
    def passed(self) -> bool:
        return all(item[1] for item in self.checks)

    def render(self) -> str:
        lines = [f"{'PASS' if passed else 'FAIL'} {name}: {detail}" for name, passed, detail in self.checks]
        lines.append(f"RESULT: {'PASS' if self.passed else 'FAIL'} ({sum(p for _, p, _ in self.checks)}/{len(self.checks)} checks)")
        return "\n".join(lines)


@dataclass
class MigrationSummary:
    row_counts: dict[str, int]
    sequences_reset: dict[str, int]
    dry_run: bool

    def render(self) -> str:
        rows = sum(self.row_counts.values())
        mode = "DRY RUN" if self.dry_run else "MIGRATED"
        detail = ", ".join(f"{name}={count}" for name, count in sorted(self.row_counts.items()))
        return f"{mode}: {len(self.row_counts)} tables, {rows} rows\nRows: {detail}\nSequences reset: {len(self.sequences_reset)}"


def sqlite_url(path: str | Path) -> URL:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise MigrationSafetyError(f"SQLite source does not exist or is not a file: {source}")
    return URL.create(
        "sqlite+pysqlite",
        database=f"file:{source.as_posix()}",
        query={"mode": "ro", "uri": "true"},
    )


def postgres_url(value: str) -> URL:
    url = make_url(value)
    if url.drivername != "postgresql+psycopg":
        raise MigrationSafetyError("Target URL must use postgresql+psycopg://")
    return url


def source_engine(path: str | Path) -> Engine:
    return create_engine(sqlite_url(path), connect_args={"check_same_thread": False}, future=True)


def _ensure_source_integrity(connection: Connection) -> None:
    integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
    if integrity != "ok":
        raise MigrationSafetyError(f"SQLite integrity_check failed: {integrity}")
    foreign_key_problem = connection.execute(text("PRAGMA foreign_key_check")).first()
    if foreign_key_problem is not None:
        raise MigrationSafetyError(f"SQLite foreign_key_check failed: {tuple(foreign_key_problem)}")


def target_engine(url: str) -> Engine:
    return create_engine(postgres_url(url), future=True, pool_pre_ping=True)


def _application_table_names() -> list[str]:
    return [table.name for table in application_metadata().sorted_tables]


def _ensure_schema(source: Connection, target: Connection) -> None:
    expected = set(_application_table_names())
    source_tables = set(inspect(source).get_table_names())
    target_tables = set(inspect(target).get_table_names())
    missing_source = expected - source_tables
    missing_target = expected - target_tables
    unexpected_target = target_tables - expected - {ALEMBIC_TABLE}
    if missing_source:
        raise MigrationSafetyError(f"SQLite source is missing current application tables: {sorted(missing_source)}")
    if missing_target:
        raise MigrationSafetyError(
            "PostgreSQL target schema is incomplete; run 'alembic upgrade head' first. "
            f"Missing: {sorted(missing_target)}"
        )
    if unexpected_target:
        raise MigrationSafetyError(f"PostgreSQL target contains unexpected tables: {sorted(unexpected_target)}")


def _row_count(connection: Connection, table: Table) -> int:
    return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _target_counts(connection: Connection) -> dict[str, int]:
    return {table.name: _row_count(connection, table) for table in application_metadata().sorted_tables}


def _primary_keys_match(source: Connection, target: Connection, source_table: Table, target_table: Table) -> bool:
    source_columns = [source_table.c[column.name] for column in target_table.primary_key.columns]
    target_columns = list(target_table.primary_key.columns)
    source_keys = source.execute(select(*source_columns).order_by(*source_columns)).all()
    target_keys = target.execute(select(*target_columns).order_by(*target_columns)).all()
    return source_keys == target_keys


def assert_safe_target(connection: Connection, *, allow_nonempty: bool = False) -> dict[str, int]:
    counts = _target_counts(connection)
    nonempty = {name: count for name, count in counts.items() if count}
    if nonempty and not allow_nonempty:
        raise MigrationSafetyError(
            "PostgreSQL target contains application data; refusing to write. "
            "Use --allow-nonempty only after reviewing conflicts: " + repr(nonempty)
        )
    return counts


def _source_tables(connection: Connection) -> dict[str, Table]:
    reflected = MetaData()
    reflected.reflect(bind=connection, only=_application_table_names())
    return reflected.tables


def _chunks(rows: Iterable[dict[str, Any]], size: int = BATCH_SIZE) -> Iterable[list[dict[str, Any]]]:
    chunk: list[dict[str, Any]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _copy_table(source: Connection, target: Connection, source_table: Table, target_table: Table) -> int:
    column_names = [column.name for column in target_table.columns]
    statement = select(*(source_table.c[name] for name in column_names))
    count = 0
    mappings = source.execute(statement).mappings()
    for batch in _chunks((dict(row) for row in mappings)):
        target.execute(target_table.insert(), batch)
        count += len(batch)
    return count


def _reset_sequences(connection: Connection) -> dict[str, int]:
    reset: dict[str, int] = {}
    for table in application_metadata().sorted_tables:
        integer_pks = [column for column in table.primary_key.columns if column.type.python_type is int]
        if len(integer_pks) != 1:
            continue
        column = integer_pks[0]
        sequence = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table.name, "column_name": column.name},
        ).scalar_one()
        if sequence is None:
            continue
        maximum = connection.execute(select(func.max(column))).scalar_one()
        value = int(maximum) if maximum is not None else 1
        connection.execute(
            text("SELECT setval(CAST(:sequence_name AS regclass), :value, :is_called)"),
            {"sequence_name": sequence, "value": value, "is_called": maximum is not None},
        )
        reset[sequence] = value
    return reset


def migrate_sqlite_to_postgres(
    sqlite_path: str | Path,
    postgres_url_value: str,
    *,
    dry_run: bool = False,
    allow_nonempty: bool = False,
) -> MigrationSummary:
    source = source_engine(sqlite_path)
    target = target_engine(postgres_url_value)
    try:
        with source.connect() as source_connection, target.connect() as target_connection:
            _ensure_source_integrity(source_connection)
            _ensure_schema(source_connection, target_connection)
            assert_safe_target(target_connection, allow_nonempty=allow_nonempty)
            source_tables = _source_tables(source_connection)
            source_counts = {
                table.name: _row_count(source_connection, source_tables[table.name])
                for table in application_metadata().sorted_tables
            }
            if dry_run:
                return MigrationSummary(source_counts, {}, True)

        # One PostgreSQL transaction covers every table and every sequence.
        with source.connect() as source_connection, target.begin() as target_connection:
            _ensure_source_integrity(source_connection)
            _ensure_schema(source_connection, target_connection)
            assert_safe_target(target_connection, allow_nonempty=allow_nonempty)
            source_tables = _source_tables(source_connection)
            copied = {
                table.name: _copy_table(source_connection, target_connection, source_tables[table.name], table)
                for table in application_metadata().sorted_tables
            }
            sequences = _reset_sequences(target_connection)
        return MigrationSummary(copied, sequences, False)
    finally:
        source.dispose()
        target.dispose()


def _verify_foreign_keys(connection: Connection, report: VerificationReport) -> None:
    preparer = connection.dialect.identifier_preparer
    for table in application_metadata().sorted_tables:
        for constraint in table.foreign_key_constraints:
            pairs = list(constraint.elements)
            child_alias = "child"
            parent_alias = "parent"
            joins = " AND ".join(
                f"{parent_alias}.{preparer.quote(pair.column.name)} = {child_alias}.{preparer.quote(pair.parent.name)}"
                for pair in pairs
            )
            nonnull = " AND ".join(
                f"{child_alias}.{preparer.quote(pair.parent.name)} IS NOT NULL" for pair in pairs
            )
            parent_missing = f"{parent_alias}.{preparer.quote(pairs[0].column.name)} IS NULL"
            sql = (
                f"SELECT COUNT(*) FROM {preparer.quote(table.name)} AS {child_alias} "
                f"LEFT JOIN {preparer.quote(pairs[0].column.table.name)} AS {parent_alias} ON {joins} "
                f"WHERE {nonnull} AND {parent_missing}"
            )
            orphan_count = int(connection.execute(text(sql)).scalar_one())
            label = f"fk:{table.name}->{pairs[0].column.table.name}"
            report.add(label, orphan_count == 0, f"orphans={orphan_count}")


def _sequence_state(connection: Connection, table: Table, column_name: str) -> tuple[int | None, int | None]:
    sequence = connection.execute(
        text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
        {"table_name": table.name, "column_name": column_name},
    ).scalar_one()
    maximum = connection.execute(select(func.max(table.c[column_name]))).scalar_one()
    if not sequence:
        return maximum, None
    sequence_name = sequence.rsplit(".", 1)[-1]
    last_value = connection.execute(
        text("SELECT last_value FROM pg_sequences WHERE schemaname = current_schema() AND sequencename = :name"),
        {"name": sequence_name},
    ).scalar_one_or_none()
    return maximum, last_value


def verify_migration(sqlite_path: str | Path, postgres_url_value: str) -> VerificationReport:
    report = VerificationReport()
    source = source_engine(sqlite_path)
    target = target_engine(postgres_url_value)
    try:
        with source.connect() as source_connection, target.connect() as target_connection:
            _ensure_source_integrity(source_connection)
            expected = set(_application_table_names())
            source_names = set(inspect(source_connection).get_table_names()) & expected
            target_names = set(inspect(target_connection).get_table_names()) & expected
            report.add("table-count", source_names == target_names == expected, f"source={len(source_names)} target={len(target_names)} expected={len(expected)}")
            if source_names != expected or target_names != expected:
                return report
            sources = _source_tables(source_connection)
            for table in application_metadata().sorted_tables:
                source_count = _row_count(source_connection, sources[table.name])
                target_count = _row_count(target_connection, table)
                report.add(f"rows:{table.name}", source_count == target_count, f"source={source_count} target={target_count}")
                keys_match = _primary_keys_match(source_connection, target_connection, sources[table.name], table)
                report.add(f"primary-keys:{table.name}", keys_match, "ordered primary-key values match")
                integer_pks = [column for column in table.primary_key.columns if column.type.python_type is int]
                if len(integer_pks) == 1:
                    pk = integer_pks[0]
                    source_max = source_connection.execute(select(func.max(sources[table.name].c[pk.name]))).scalar_one()
                    target_max, sequence_value = _sequence_state(target_connection, table, pk.name)
                    report.add(f"max-id:{table.name}", source_max == target_max, f"source={source_max} target={target_max}")
                    if sequence_value is not None:
                        valid = target_max is None or int(sequence_value) >= int(target_max)
                        report.add(f"sequence:{table.name}", valid, f"max={target_max} sequence={sequence_value}")
            _verify_foreign_keys(target_connection, report)
            critical = {
                "profiles-clients": ("user_clients", "user_profiles"),
                "account-identities": ("account_identities", "user_profiles"),
                "account-client-links": ("account_client_links", "account_identities"),
                "favorite-stores": ("favorite_stores", "user_profiles"),
                "favorite-products": ("favorite_products", "user_profiles"),
                "shopping-items": ("shopping_items", "user_profiles"),
            }
            for label, (child, parent) in critical.items():
                relevant = [item for item in report.checks if item[0] == f"fk:{child}->{parent}"]
                report.add(f"critical:{label}", bool(relevant) and all(item[1] for item in relevant), "relationship integrity")
        return report
    finally:
        source.dispose()
        target.dispose()
