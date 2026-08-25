"""Safe, reusable SQLite-to-PostgreSQL transfer and verification helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import (
    Boolean,
    Connection,
    Date,
    DateTime,
    Engine,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    select,
    text,
)
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


def _type_signature(column_type: Any) -> tuple[str, int | None]:
    """Normalize SQLAlchemy-reflected types across SQLite and PostgreSQL."""

    if isinstance(column_type, Boolean):
        return ("boolean", None)
    if isinstance(column_type, DateTime):
        return ("datetime", None)
    if isinstance(column_type, Date):
        return ("date", None)
    if isinstance(column_type, Integer):
        return ("integer", None)
    if isinstance(column_type, Float):
        return ("float", None)
    if isinstance(column_type, LargeBinary):
        return ("binary", getattr(column_type, "length", None))
    if isinstance(column_type, Text):
        return ("text", None)
    if isinstance(column_type, String):
        return ("string", column_type.length)
    return (column_type.__class__.__name__.lower(), getattr(column_type, "length", None))


def _foreign_key_signatures_from_metadata(table: Table) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            constraint.elements[0].column.table.name,
            tuple(element.column.name for element in constraint.elements),
        )
        for constraint in table.foreign_key_constraints
    }


def _foreign_key_signatures_from_inspector(rows: list[dict[str, Any]]) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    return {
        (tuple(row["constrained_columns"]), row["referred_table"], tuple(row["referred_columns"]))
        for row in rows
    }


def _unique_signatures_from_metadata(table: Table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _unique_signatures_from_inspector(rows: list[dict[str, Any]]) -> set[tuple[str, ...]]:
    return {tuple(row["column_names"]) for row in rows}


def _index_signatures_from_metadata(table: Table) -> set[tuple[tuple[str, ...], bool]]:
    return {
        (tuple(column.name for column in index.columns), bool(index.unique))
        for index in table.indexes
    }


def _index_signatures_from_inspector(rows: list[dict[str, Any]]) -> set[tuple[tuple[str, ...], bool]]:
    return {
        (tuple(row["column_names"]), bool(row["unique"]))
        for row in rows
        if not row.get("duplicates_constraint")
    }


def schema_differences(connection: Connection, *, expected_metadata: MetaData | None = None) -> list[str]:
    """Return semantic schema drift against supplied or current metadata."""

    inspector = inspect(connection)
    expected = expected_metadata if expected_metadata is not None else application_metadata()
    expected_names = set(expected.tables)
    actual_names = set(inspector.get_table_names())
    differences: list[str] = []
    missing = expected_names - actual_names
    unexpected = actual_names - expected_names - {ALEMBIC_TABLE}
    if missing:
        differences.append(f"missing tables={sorted(missing)}")
    if unexpected:
        differences.append(f"unexpected tables={sorted(unexpected)}")

    for table_name in sorted(expected_names & actual_names):
        expected_table = expected.tables[table_name]
        actual_columns = {row["name"]: row for row in inspector.get_columns(table_name)}
        expected_columns = {column.name: column for column in expected_table.columns}
        missing_columns = set(expected_columns) - set(actual_columns)
        unexpected_columns = set(actual_columns) - set(expected_columns)
        if missing_columns:
            differences.append(f"{table_name}: missing columns={sorted(missing_columns)}")
        if unexpected_columns:
            differences.append(f"{table_name}: unexpected columns={sorted(unexpected_columns)}")
        for column_name in sorted(set(expected_columns) & set(actual_columns)):
            expected_column = expected_columns[column_name]
            actual_column = actual_columns[column_name]
            expected_type = _type_signature(expected_column.type)
            actual_type = _type_signature(actual_column["type"])
            if expected_type != actual_type:
                differences.append(f"{table_name}.{column_name}: type expected={expected_type} actual={actual_type}")
            if bool(expected_column.nullable) != bool(actual_column["nullable"]):
                differences.append(
                    f"{table_name}.{column_name}: nullable expected={expected_column.nullable} actual={actual_column['nullable']}"
                )

        expected_pk = tuple(column.name for column in expected_table.primary_key.columns)
        actual_pk = tuple(inspector.get_pk_constraint(table_name).get("constrained_columns") or ())
        if expected_pk != actual_pk:
            differences.append(f"{table_name}: primary key expected={expected_pk} actual={actual_pk}")

        expected_fks = _foreign_key_signatures_from_metadata(expected_table)
        actual_fks = _foreign_key_signatures_from_inspector(inspector.get_foreign_keys(table_name))
        if expected_fks != actual_fks:
            differences.append(f"{table_name}: foreign keys expected={sorted(expected_fks)!r} actual={sorted(actual_fks)!r}")

        expected_uniques = _unique_signatures_from_metadata(expected_table)
        actual_uniques = _unique_signatures_from_inspector(inspector.get_unique_constraints(table_name))
        if expected_uniques != actual_uniques:
            differences.append(f"{table_name}: unique constraints expected={sorted(expected_uniques)!r} actual={sorted(actual_uniques)!r}")

        expected_indexes = _index_signatures_from_metadata(expected_table)
        actual_indexes = _index_signatures_from_inspector(inspector.get_indexes(table_name))
        if expected_indexes != actual_indexes:
            differences.append(f"{table_name}: indexes expected={sorted(expected_indexes)!r} actual={sorted(actual_indexes)!r}")
    return differences


def _ensure_schema(source: Connection, target: Connection) -> None:
    source_differences = schema_differences(source)
    target_differences = schema_differences(target)
    if source_differences:
        raise MigrationSafetyError("SQLite source schema differs from the current baseline: " + "; ".join(source_differences))
    if target_differences:
        raise MigrationSafetyError("PostgreSQL target schema differs from the current baseline: " + "; ".join(target_differences))


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
            try:
                _ensure_source_integrity(source_connection)
            except MigrationSafetyError as exc:
                report.add("source-integrity", False, str(exc))
                return report
            report.add("source-integrity", True, "SQLite integrity_check and foreign_key_check passed")
            source_schema_differences = schema_differences(source_connection)
            target_schema_differences = schema_differences(target_connection)
            report.add(
                "schema:source",
                not source_schema_differences,
                "matches baseline" if not source_schema_differences else "; ".join(source_schema_differences),
            )
            report.add(
                "schema:target",
                not target_schema_differences,
                "matches baseline" if not target_schema_differences else "; ".join(target_schema_differences),
            )
            if source_schema_differences or target_schema_differences:
                return report
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
