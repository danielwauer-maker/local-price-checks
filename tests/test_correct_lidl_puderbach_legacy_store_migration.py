from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260916_02_correct_lidl_puderbach_legacy_store.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("correct_lidl_legacy", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(*, with_business_reference: bool = False):
    metadata = sa.MetaData()
    stores = sa.Table(
        "stores",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("postal_code", sa.String(10)),
        sa.Column("city", sa.String(120)),
        sa.Column("address", sa.String(255)),
        sa.Column("external_id", sa.String(255)),
        sa.Column("benchmark_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("active", sa.Boolean, nullable=False, default=True),
    )
    candidates = sa.Table(
        "store_discovery_candidates",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("matched_store_id", sa.Integer, sa.ForeignKey("stores.id")),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("postal_code", sa.String(10), nullable=False),
        sa.Column("address", sa.String(255)),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("source_external_id", sa.String(255)),
        sa.Column("status", sa.String(30)),
        sa.Column("address_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("coordinates_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("official_source_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("verification_note", sa.Text),
        sa.Column("updated_at", sa.DateTime),
    )
    activation = sa.Table(
        "store_activation_states",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("lifecycle_status", sa.String(30), nullable=False),
        sa.Column("identity_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("manually_suspended", sa.Boolean, nullable=False, default=False),
        sa.Column("last_test_run_id", sa.Integer),
        sa.Column("last_error", sa.Text),
        sa.Column("published_at", sa.DateTime),
        sa.Column("suspended_at", sa.DateTime),
    )
    business = None
    if with_business_reference:
        business = sa.Table(
            "business_rows",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        )
    return metadata, stores, candidates, activation, business


def _seed(connection, stores, candidates, activation):
    connection.execute(
        stores.insert(),
        [
            {
                "id": 8,
                "name": "Lidl Puderbach",
                "retailer": "Lidl",
                "postal_code": "56305",
                "city": "Puderbach",
                "address": "Urbacher Straße 31a",
                "external_id": "node/123",
                "benchmark_verified": False,
                "active": True,
            },
            {
                "id": 16,
                "name": "Lidl Puderbach (2)",
                "retailer": "Lidl",
                "postal_code": "56305",
                "city": "Puderbach",
                "address": "Urbacherstraße L264",
                "external_id": "lidl-puderbach-urbacherstr-l264",
                "benchmark_verified": False,
                "active": True,
            },
        ],
    )
    connection.execute(
        candidates.insert(),
        [
            {
                "id": 1,
                "matched_store_id": 16,
                "retailer": "Lidl",
                "postal_code": "56305",
                "address": "Urbacher Straße 31a",
                "source": "osm",
                "source_external_id": "node/123",
                "status": "promoted",
                "address_verified": True,
                "coordinates_verified": True,
                "official_source_verified": True,
                "verification_note": "old",
            },
            {
                "id": 2,
                "matched_store_id": 16,
                "retailer": "Lidl",
                "postal_code": "56305",
                "address": "Urbacherstraße L264",
                "source": "official:lidl",
                "source_external_id": "lidl-puderbach-urbacherstr-l264",
                "status": "promoted",
                "address_verified": True,
                "coordinates_verified": True,
                "official_source_verified": True,
                "verification_note": "official",
            },
        ],
    )
    connection.execute(
        activation.insert(),
        [
            {
                "id": 1,
                "store_id": 8,
                "lifecycle_status": "promoted",
                "identity_verified": False,
                "manually_suspended": False,
            },
            {
                "id": 2,
                "store_id": 16,
                "lifecycle_status": "promoted",
                "identity_verified": True,
                "manually_suspended": False,
            },
        ],
    )


def test_repair_removes_legacy_store_rejects_wrong_alias_and_normalizes_canonical(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata, stores, candidates, activation, _ = _schema()
    metadata.create_all(engine)

    with engine.begin() as connection:
        _seed(connection, stores, candidates, activation)
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()

        remaining = connection.execute(
            sa.select(stores.c.id, stores.c.name, stores.c.address).order_by(stores.c.id)
        ).all()
        assert remaining == [(16, "Lidl Puderbach", "Urbacherstraße L264")]

        candidate_rows = connection.execute(
            sa.select(
                candidates.c.id,
                candidates.c.matched_store_id,
                candidates.c.status,
                candidates.c.address_verified,
                candidates.c.coordinates_verified,
                candidates.c.official_source_verified,
                candidates.c.verification_note,
            ).order_by(candidates.c.id)
        ).all()
        assert candidate_rows[0][0:6] == (1, None, "rejected", False, False, False)
        assert "L264" in candidate_rows[0].verification_note
        assert candidate_rows[1][0:3] == (2, 16, "promoted")

        activation_links = connection.execute(
            sa.select(activation.c.store_id).order_by(activation.c.store_id)
        ).scalars().all()
        assert activation_links == [16]


def test_repair_fails_closed_if_legacy_store_has_business_data(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata, stores, candidates, activation, business = _schema(
        with_business_reference=True
    )
    assert business is not None
    metadata.create_all(engine)

    with engine.begin() as connection:
        _seed(connection, stores, candidates, activation)
        connection.execute(business.insert().values(id=1, store_id=8))
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        with pytest.raises(RuntimeError, match="business-data dependencies"):
            migration.upgrade()

        assert connection.execute(
            sa.select(sa.func.count()).select_from(stores).where(stores.c.id == 8)
        ).scalar_one() == 1


def test_repair_fails_closed_if_canonical_store_is_missing(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata, stores, candidates, activation, _ = _schema()
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            stores.insert().values(
                id=8,
                name="Lidl Puderbach",
                retailer="Lidl",
                postal_code="56305",
                city="Puderbach",
                address="Urbacher Straße 31a",
                external_id="node/123",
                benchmark_verified=False,
                active=True,
            )
        )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        with pytest.raises(RuntimeError, match="Canonical Store 16 is missing"):
            migration.upgrade()


def test_repair_refuses_to_reject_official_source_at_legacy_address(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata, stores, candidates, activation, _ = _schema()
    metadata.create_all(engine)

    with engine.begin() as connection:
        _seed(connection, stores, candidates, activation)
        connection.execute(
            candidates.update()
            .where(candidates.c.id == 1)
            .values(source="official:lidl")
        )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        with pytest.raises(RuntimeError, match="claims official Lidl evidence"):
            migration.upgrade()

        assert connection.execute(
            sa.select(sa.func.count()).select_from(stores).where(stores.c.id == 8)
        ).scalar_one() == 1
