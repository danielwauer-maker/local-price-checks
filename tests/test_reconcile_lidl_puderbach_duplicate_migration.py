from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260916_01_reconcile_lidl_puderbach_duplicate.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("reconcile_lidl_duplicate", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_distinct_31a_and_official_l264_rows_are_not_rolled_back(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata = sa.MetaData()

    stores = sa.Table(
        "stores",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("retailer", sa.String(80), nullable=False),
        sa.Column("postal_code", sa.String(10)),
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
        sa.Column("source_external_id", sa.String(255)),
        sa.Column("status", sa.String(30)),
        sa.Column("address_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("coordinates_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("official_source_verified", sa.Boolean, nullable=False, default=False),
        sa.Column("updated_at", sa.DateTime),
    )
    sa.Table(
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
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            stores.insert(),
            [
                {
                    "id": 8,
                    "retailer": "Lidl",
                    "postal_code": "56305",
                    "address": "Urbacher Straße 31a",
                    "external_id": None,
                    "benchmark_verified": False,
                    "active": False,
                },
                {
                    "id": 16,
                    "retailer": "Lidl",
                    "postal_code": "56305",
                    "address": "Urbacherstraße L264",
                    "external_id": "lidl-puderbach-urbacherstr-l264",
                    "benchmark_verified": False,
                    "active": True,
                },
            ],
        )
        connection.execute(
            candidates.insert(),
            {
                "id": 5,
                "matched_store_id": 16,
                "retailer": "Lidl",
                "postal_code": "56305",
                "address": "Urbacherstraße L264",
                "source_external_id": "lidl-puderbach-urbacherstr-l264",
                "status": "promoted",
                "address_verified": True,
                "coordinates_verified": True,
                "official_source_verified": True,
            },
        )

        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()

        ids = connection.execute(sa.select(stores.c.id).order_by(stores.c.id)).scalars().all()
        assert ids == [8, 16]
        assert connection.execute(
            sa.select(candidates.c.matched_store_id).where(candidates.c.id == 5)
        ).scalar_one() == 16
