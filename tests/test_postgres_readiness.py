from __future__ import annotations

import os
import sqlite3
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.admin_seed import seed_admin_catalog
from app.category_classifier import ensure_auto_category
from app.client_models import AccountClientLink, AccountIdentity, ClientDevice, UserClient
from app.config import database_url
from app.db import Base, create_database_engine
from app.db_transfer import MigrationSafetyError, migrate_sqlite_to_postgres, verify_migration
from app.model_registry import metadata
from app.models import FavoriteProduct, FavoriteStore, MasterProduct, ShoppingItem, Store, UserProfile
from app.product_search import search_products


def test_database_configuration_supports_sqlite_and_psycopg():
    assert database_url("sqlite:///development.sqlite3").get_backend_name() == "sqlite"
    pg = database_url("postgresql+psycopg://lokero:secret@localhost/lokero")
    assert pg.drivername == "postgresql+psycopg"
    assert create_database_engine("sqlite://").dialect.name == "sqlite"
    assert create_database_engine(str(pg)).dialect.name == "postgresql"


def test_model_registry_contains_additive_models():
    names = set(metadata().tables)
    assert {
        "account_client_links",
        "client_devices",
        "shopping_item_checks",
        "collection_quality_snapshots",
        "coverage_postal_codes",
        "store_discovery_candidates",
    } <= names
    assert len(names) == 44


def test_alembic_baseline_creates_complete_sqlite_schema(tmp_path: Path):
    target = tmp_path / "alembic.sqlite3"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{target.as_posix()}"}
    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
    engine = create_engine(f"sqlite:///{target.as_posix()}")
    try:
        from sqlalchemy import inspect

        assert set(metadata().tables) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_category_hierarchy_migration_preserves_existing_ids_and_assignment(tmp_path: Path):
    target = tmp_path / "category-upgrade.sqlite3"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{target.as_posix()}"}
    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "20260825_01"], check=True, env=env)
    with sqlite3.connect(target) as connection:
        connection.execute(
            "INSERT INTO master_products (id, brand, name, package_size, normalized_key) VALUES (7, NULL, 'Gouda', NULL, 'gouda')"
        )
        connection.execute(
            "INSERT INTO product_categories (id, name, slug, active, sort_order) VALUES (11, 'Käse', 'kaese', 1, 40)"
        )
        connection.execute(
            """
            INSERT INTO product_admin_data
                (id, master_product_id, category_id, name_locked, category_locked, notes, updated_at)
            VALUES (13, 7, 11, 0, 1, NULL, '2026-08-25 00:00:00')
            """
        )
        connection.commit()

    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
    with sqlite3.connect(target) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(product_categories)")}
        assignment = connection.execute(
            "SELECT master_product_id, category_id FROM product_admin_data WHERE id = 13"
        ).fetchone()
        category = connection.execute(
            "SELECT id, slug, parent_id FROM product_categories WHERE id = 11"
        ).fetchone()
    assert "parent_id" in columns
    assert assignment == (7, 11)
    assert category == (11, "kaese", None)


def test_sqlite_backup_helper_is_consistent_and_never_overwrites(tmp_path: Path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample (id, value) VALUES (7, 'kept')")
    command = [
        os.sys.executable,
        "scripts/backup_database.py",
        "sqlite",
        "--source",
        str(source),
        "--output",
        str(backup),
    ]
    subprocess.run(command, check=True)
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT id, value FROM sample").fetchone() == (7, "kept")
    assert subprocess.run(command, capture_output=True).returncode == 1


def _postgres_admin_url() -> str | None:
    return os.getenv("POSTGRES_TEST_URL")


@pytest.fixture
def postgres_database():
    base_value = _postgres_admin_url()
    if not base_value:
        pytest.skip("POSTGRES_TEST_URL is required for PostgreSQL integration tests")
    from sqlalchemy.engine import make_url

    base = make_url(base_value)
    database_name = f"lokero_test_{uuid.uuid4().hex}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    target = base.set(database=database_name).render_as_string(hide_password=False)
    try:
        env = {**os.environ, "DATABASE_URL": target}
        subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
        subprocess.run([os.sys.executable, "-m", "alembic", "check"], check=True, env=env)
        yield target
    finally:
        admin.dispose()
        cleanup = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with cleanup.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name"), {"name": database_name})
            connection.execute(text(f'DROP DATABASE "{database_name}"'))
        cleanup.dispose()


def _representative_sqlite(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        session.add_all(
            [
                UserProfile(id=101, display_name="Canonical", postal_code="56269", city="Dierdorf", latitude=50.55, longitude=7.65, radius_km=20),
                Store(id=201, retailer="REWE", name="REWE migration fixture", postal_code="56269", city="Dierdorf", address="Testweg 1", active=True, benchmark_verified=True),
                MasterProduct(id=301, name="Migration Milk", normalized_key="migration-milk"),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserClient(id=401, client_key="migration-client-key-0001", user_id=101),
                FavoriteStore(id=501, user_id=101, store_id=201),
                FavoriteProduct(id=601, user_id=101, master_product_id=301),
                ShoppingItem(id=701, user_id=101, master_product_id=301, quantity=2),
                AccountIdentity(id=801, user_id=101, provider="supabase", provider_subject="verified-subject", email="verified@example.test"),
            ]
        )
        session.flush()
        session.add_all(
            [
                ClientDevice(id=901, client_id=401, device_key="migration-device-key-0001", device_type="mobile", os_name="Android", browser_name="Chrome"),
                AccountClientLink(id=1001, identity_id=801, client_id=401),
            ]
        )
        session.commit()
    engine.dispose()


@pytest.mark.postgres
def test_connected_user_data_migrates_without_phantom_profile(tmp_path: Path, postgres_database: str):
    sqlite_path = tmp_path / "representative.sqlite3"
    _representative_sqlite(sqlite_path)
    dry_run = migrate_sqlite_to_postgres(sqlite_path, postgres_database, dry_run=True)
    assert dry_run.row_counts["user_profiles"] == 1
    summary = migrate_sqlite_to_postgres(sqlite_path, postgres_database)
    assert summary.row_counts["account_client_links"] == 1
    report = verify_migration(sqlite_path, postgres_database)
    assert report.passed, report.render()

    engine = create_engine(postgres_database)
    with engine.begin() as connection:
        assert connection.execute(select(func.count()).select_from(UserProfile.__table__)).scalar_one() == 1
        assert connection.execute(select(UserClient.user_id).where(UserClient.id == 401)).scalar_one() == 101
        assert connection.execute(select(ClientDevice.client_id).where(ClientDevice.id == 901)).scalar_one() == 401
        assert connection.execute(select(AccountIdentity.user_id).where(AccountIdentity.id == 801)).scalar_one() == 101
        link = connection.execute(select(AccountClientLink.identity_id, AccountClientLink.client_id).where(AccountClientLink.id == 1001)).one()
        assert tuple(link) == (801, 401)
        assert connection.execute(select(FavoriteStore.user_id).where(FavoriteStore.id == 501)).scalar_one() == 101
        assert connection.execute(select(FavoriteProduct.user_id).where(FavoriteProduct.id == 601)).scalar_one() == 101
        assert connection.execute(select(ShoppingItem.user_id).where(ShoppingItem.id == 701)).scalar_one() == 101
        new_id = connection.execute(UserProfile.__table__.insert().values(display_name="After migration").returning(UserProfile.id)).scalar_one()
        assert new_id > 101
    engine.dispose()


@pytest.mark.postgres
def test_migration_refuses_nonempty_target(tmp_path: Path, postgres_database: str):
    sqlite_path = tmp_path / "source.sqlite3"
    _representative_sqlite(sqlite_path)
    engine = create_engine(postgres_database)
    with engine.begin() as connection:
        connection.execute(UserProfile.__table__.insert().values(id=999, display_name="Existing"))
    engine.dispose()
    with pytest.raises(MigrationSafetyError, match="refusing to write"):
        migrate_sqlite_to_postgres(sqlite_path, postgres_database)


@pytest.mark.postgres
def test_schema_preflight_rejects_source_and_target_drift(tmp_path: Path, postgres_database: str):
    mutations = {
        "unexpected-column": "ALTER TABLE user_profiles ADD COLUMN legacy_payload TEXT",
        "missing-column": "ALTER TABLE user_profiles DROP COLUMN city",
        "unexpected-table": "CREATE TABLE legacy_secrets (id INTEGER PRIMARY KEY, payload TEXT)",
    }
    target = create_engine(postgres_database)
    for label, statement in mutations.items():
        sqlite_path = tmp_path / f"{label}.sqlite3"
        _representative_sqlite(sqlite_path)
        source = create_engine(f"sqlite:///{sqlite_path.as_posix()}")
        with source.begin() as connection:
            connection.execute(text(statement))
        source.dispose()

        with pytest.raises(MigrationSafetyError, match="source schema differs"):
            migrate_sqlite_to_postgres(sqlite_path, postgres_database, dry_run=True)
        with pytest.raises(MigrationSafetyError, match="source schema differs"):
            migrate_sqlite_to_postgres(sqlite_path, postgres_database)
        with target.connect() as connection:
            assert connection.execute(select(func.count()).select_from(UserProfile.__table__)).scalar_one() == 0
        report = verify_migration(sqlite_path, postgres_database)
        assert not report.passed
        assert any(name == "schema:source" and not passed for name, passed, _ in report.checks)

    pristine = tmp_path / "pristine.sqlite3"
    _representative_sqlite(pristine)
    with target.begin() as connection:
        connection.execute(text("ALTER TABLE user_profiles ADD COLUMN unexpected_target_data TEXT"))
    target.dispose()
    report = verify_migration(pristine, postgres_database)
    assert not report.passed
    assert any(name == "schema:target" and not passed for name, passed, _ in report.checks)


@pytest.mark.postgres
def test_verification_detects_intentional_mismatch(tmp_path: Path, postgres_database: str):
    sqlite_path = tmp_path / "source.sqlite3"
    _representative_sqlite(sqlite_path)
    migrate_sqlite_to_postgres(sqlite_path, postgres_database)
    engine = create_engine(postgres_database)
    with engine.begin() as connection:
        connection.execute(ShoppingItem.__table__.delete().where(ShoppingItem.id == 701))
    engine.dispose()
    report = verify_migration(sqlite_path, postgres_database)
    assert not report.passed
    assert any(name == "rows:shopping_items" and not passed for name, passed, _ in report.checks)


@pytest.mark.postgres
def test_backend_starts_and_serves_health_against_postgres(postgres_database: str):
    env = {
        **os.environ,
        "DATABASE_URL": postgres_database,
        "AUTO_CREATE_SCHEMA": "false",
        "SCHEDULER_ENABLED": "false",
        "MANUAL_COLLECTION_ENABLED": "false",
    }
    code = (
        "from fastapi.testclient import TestClient; "
        "from app.api_main import app; "
        "client = TestClient(app); "
        "client.__enter__(); "
        "response = client.get('/health'); "
        "assert response.status_code == 200, response.text; "
        "assert response.json()['status'] in {'ok', 'degraded'}; "
        "client.__exit__(None, None, None)"
    )
    subprocess.run([os.sys.executable, "-c", code], check=True, env=env)


@pytest.mark.postgres
def test_taxonomy_search_matches_on_postgresql(postgres_database: str):
    engine = create_engine(postgres_database)
    with Session(engine) as session:
        seed_admin_catalog(session)
        products = [
            MasterProduct(name="PostgreSQL Lachsfilet", normalized_key="postgres-search-lachs"),
            MasterProduct(name="PostgreSQL Fischstäbchen", normalized_key="postgres-search-fischstaebchen"),
            MasterProduct(name="PostgreSQL Pepsi", normalized_key="postgres-search-pepsi"),
        ]
        session.add_all(products)
        session.flush()
        for product in products:
            ensure_auto_category(session, product)
        session.commit()

        fish = {match.product.name for match in search_products(session, query="Fisch")}
        cola = {match.product.name for match in search_products(session, query="Cola")}
        assert {"PostgreSQL Lachsfilet", "PostgreSQL Fischstäbchen"}.issubset(fish)
        assert "PostgreSQL Pepsi" in cola
    engine.dispose()
