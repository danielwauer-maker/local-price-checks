from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260918_01_repair_aldi_altenkirchen_source.py"
)
spec = importlib.util.spec_from_file_location("aldi_altenkirchen_source_repair", MIGRATION_PATH)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def _engine(source_url: str):
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as bind:
        bind.execute(
            sa.text(
                """
                CREATE TABLE stores (
                    id INTEGER PRIMARY KEY,
                    retailer TEXT NOT NULL,
                    name TEXT NOT NULL,
                    postal_code TEXT NOT NULL,
                    city TEXT NOT NULL,
                    address TEXT NOT NULL,
                    source_url TEXT,
                    external_id TEXT,
                    active BOOLEAN NOT NULL DEFAULT 0,
                    benchmark_verified BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO stores (
                    id, retailer, name, postal_code, city, address, source_url,
                    external_id, active, benchmark_verified
                ) VALUES (
                    17, 'ALDI SÜD', 'ALDI SÜD Altenkirchen', '57610',
                    'Altenkirchen', 'Kölner Straße 30a', :source_url,
                    NULL, 1, 1
                )
                """
            ),
            {"source_url": source_url},
        )
    return engine


def _source(engine) -> str | None:
    with engine.connect() as bind:
        return bind.execute(
            sa.text("SELECT source_url FROM stores WHERE id = 17")
        ).scalar_one()


def test_repair_replaces_only_known_stale_aldi_source():
    engine = _engine(migration.STALE_SOURCE_URL)
    with engine.begin() as bind:
        assert migration._repair_source(bind) is True
    assert _source(engine) == migration.TARGET_SOURCE_URL


def test_repair_is_idempotent_when_source_is_already_correct():
    engine = _engine(migration.TARGET_SOURCE_URL)
    with engine.begin() as bind:
        assert migration._repair_source(bind) is False
    assert _source(engine) == migration.TARGET_SOURCE_URL


def test_repair_refuses_to_overwrite_an_unexpected_source():
    unexpected = "https://example.invalid/operator-edited-source"
    engine = _engine(unexpected)
    with pytest.raises(RuntimeError, match="changed unexpectedly"):
        with engine.begin() as bind:
            migration._repair_source(bind)
    assert _source(engine) == unexpected


def test_repair_fails_closed_when_exact_store_identity_is_missing():
    engine = _engine(migration.STALE_SOURCE_URL)
    with engine.begin() as bind:
        bind.execute(sa.text("UPDATE stores SET address = 'Andere Straße 1' WHERE id = 17"))
    with pytest.raises(RuntimeError, match="found 0"):
        with engine.begin() as bind:
            migration._repair_source(bind)
