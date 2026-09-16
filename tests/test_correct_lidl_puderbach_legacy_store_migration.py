from __future__ import annotations

from datetime import datetime
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
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("postal_code", sa.String(10)),
        sa.Column("city", sa.String(120)),
        sa.Column("address", sa.String(255)),
        sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float),
        sa.Column("external_id", sa.String(255)),
        sa.Column("source_url", sa.Text),
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
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("address", sa.String(255)),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("source_external_id", sa.String(255)),
        sa.Column("source_url", sa.Text),
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
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False, unique=True),
        sa.Column("lifecycle_status", sa.String(30), nullable=False),
        sa.Column("identity_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("manually_suspended", sa.Boolean, nullable=False, default=False),
        sa.Column("last_test_run_id", sa.Integer),
        sa.Column("last_error", sa.Text),
        sa.Column("published_at", sa.DateTime),
        sa.Column("suspended_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # Minimal production-shaped history tables used by the migration. Keeping
    # them in every test ensures the fail-closed reflection path is exercised.
    sa.Table(
        "offers",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
    )
    sa.Table(
        "normal_price_observations",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id")),
        sa.Column("retailer", sa.String(80)),
    )
    sa.Table(
        "collection_runs",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("source_key", sa.String(80), nullable=False),
    )
    sa.Table(
        "collection_quality_snapshots",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("retailer", sa.String(80), nullable=False),
    )
    sa.Table(
        "prospects",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
    )
    sa.Table(
        "prospect_archives",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.Integer, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("retailer", sa.String(80), nullable=False),
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
    now = datetime.utcnow()
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
                "latitude": 50.592267,
                "longitude": 7.6085,
                "external_id": "node/123",
                "source_url": None,
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
                "latitude": 50.592225,
                "longitude": 7.6085,
                "external_id": "lidl-puderbach-urbacherstr-l264",
                "source_url": "https://www.lidl.de/filialen/puderbach",
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
                "name": "Lidl",
                "address": "Urbacher Straße 31a",
                "city": "Puderbach",
                "latitude": 50.592267,
                "longitude": 7.6085,
                "source": "osm",
                "source_external_id": "node/123",
                "source_url": None,
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
                "name": "Lidl Puderbach",
                "address": "Urbacherstraße L264",
                "city": "Puderbach",
                "latitude": 50.592225,
                "longitude": 7.6085,
                "source": "official:lidl",
                "source_external_id": "lidl-puderbach-urbacherstr-l264",
                "source_url": "https://www.lidl.de/filialen/puderbach",
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
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": 2,
                "store_id": 16,
                "lifecycle_status": "promoted",
                "identity_verified": True,
                "manually_suspended": False,
                "created_at": now,
                "updated_at": now,
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


def test_repair_moves_verified_lidl_puderbach_history_to_canonical_store(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata, stores, candidates, activation, _ = _schema()
    metadata.create_all(engine)

    with engine.begin() as connection:
        _seed(connection, stores, candidates, activation)
        connection.execute(metadata.tables["offers"].insert().values(id=1, store_id=8))
        connection.execute(
            metadata.tables["normal_price_observations"].insert().values(
                id=1, store_id=8, retailer="Lidl"
            )
        )
        connection.execute(
            metadata.tables["collection_runs"].insert().values(
                id=10, store_id=8, source_key="lidl_puderbach:web"
            )
        )
        connection.execute(
            metadata.tables["collection_quality_snapshots"].insert().values(
                id=10, store_id=8, retailer="Lidl"
            )
        )
        connection.execute(metadata.tables["prospects"].insert().values(id=10, store_id=8))
        connection.execute(
            metadata.tables["prospect_archives"].insert().values(
                id=10, store_id=8, retailer="Lidl"
            )
        )

        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()

        assert connection.execute(
            sa.select(sa.func.count()).select_from(stores).where(stores.c.id == 8)
        ).scalar_one() == 0
        assert connection.execute(
            sa.select(stores.c.name).where(stores.c.id == 16)
        ).scalar_one() == "Lidl Puderbach"

        for table_name in (
            "offers",
            "normal_price_observations",
            "collection_runs",
            "collection_quality_snapshots",
            "prospects",
            "prospect_archives",
        ):
            table = metadata.tables[table_name]
            assert connection.execute(
                sa.select(sa.func.count()).select_from(table).where(table.c.store_id == 8)
            ).scalar_one() == 0
            assert connection.execute(
                sa.select(sa.func.count()).select_from(table).where(table.c.store_id == 16)
            ).scalar_one() == 1

        canonical_state = connection.execute(
            sa.select(
                activation.c.lifecycle_status,
                activation.c.identity_verified,
                activation.c.last_test_run_id,
            ).where(activation.c.store_id == 16)
        ).one()
        assert canonical_state == ("promoted", True, None)


def test_repair_fails_closed_if_previous_rollback_removed_canonical_store(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata, stores, candidates, activation, _ = _schema()
    metadata.create_all(engine)

    with engine.begin() as connection:
        _seed(connection, stores, candidates, activation)
        connection.execute(activation.delete().where(activation.c.store_id == 16))
        connection.execute(
            candidates.update()
            .where(candidates.c.matched_store_id == 16)
            .values(matched_store_id=None, status="verified")
        )
        connection.execute(stores.delete().where(stores.c.id == 16))

        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        with pytest.raises(RuntimeError, match="canonical Store 16 is missing"):
            migration.upgrade()

        # Fail closed: the legacy row and candidate evidence remain untouched so
        # an operator can repair the missing canonical identity explicitly.
        assert connection.execute(
            sa.select(sa.func.count()).select_from(stores).where(stores.c.id == 8)
        ).scalar_one() == 1
        assert connection.execute(
            sa.select(sa.func.count()).select_from(stores).where(stores.c.id == 16)
        ).scalar_one() == 0
        official = connection.execute(
            sa.select(candidates.c.matched_store_id, candidates.c.status)
            .where(candidates.c.id == 2)
        ).one()
        assert official == (None, "verified")


def test_repair_fails_closed_if_legacy_store_has_unknown_business_data(monkeypatch):
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

        with pytest.raises(RuntimeError, match="unknown business-data dependencies"):
            migration.upgrade()

        assert connection.execute(
            sa.select(sa.func.count()).select_from(stores).where(stores.c.id == 8)
        ).scalar_one() == 1


def test_repair_fails_closed_if_canonical_store_already_has_history(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata, stores, candidates, activation, _ = _schema()
    metadata.create_all(engine)

    with engine.begin() as connection:
        _seed(connection, stores, candidates, activation)
        connection.execute(metadata.tables["offers"].insert(), [
            {"id": 1, "store_id": 8},
            {"id": 2, "store_id": 16},
        ])
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        with pytest.raises(RuntimeError, match="already owns business history"):
            migration.upgrade()


def test_repair_fails_closed_without_exact_official_candidate(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata, stores, candidates, activation, _ = _schema()
    metadata.create_all(engine)

    with engine.begin() as connection:
        _seed(connection, stores, candidates, activation)
        connection.execute(candidates.delete().where(candidates.c.id == 2))
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        with pytest.raises(RuntimeError, match="exactly one official Lidl L264"):
            migration.upgrade()

        assert connection.execute(
            sa.select(sa.func.count()).select_from(stores).where(stores.c.id == 8)
        ).scalar_one() == 1


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
