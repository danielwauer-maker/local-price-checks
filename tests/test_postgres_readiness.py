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
        "store_activation_states",
        "store_quality_assessments",
        "shared_shopping_lists",
        "shared_shopping_list_members",
        "shared_shopping_list_invites",
        "shared_shopping_list_items",
        "shared_shopping_list_user_state",
        "favorite_shares",
        "favorite_share_item_visibility",
        "favorite_share_subscriptions",
    } <= names
    assert len(names) == 54


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
    admin_url = _postgres_admin_url()
    if not admin_url:
        pytest.skip("POSTGRES_TEST_URL is not configured")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    database_name = f"lokero_test_{uuid.uuid4().hex[:10]}"
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    base_url = admin_url.rsplit("/", 1)[0]
    target_url = f"{base_url}/{database_name}"
    try:
        yield target_url
    finally:
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


@pytest.mark.postgres
def test_postgres_create_all_accepts_complete_model_registry(postgres_database: str):
    engine = create_database_engine(postgres_database)
    try:
        Base.metadata.create_all(bind=engine)
        from sqlalchemy import inspect

        assert set(metadata().tables) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_sqlite_to_postgres_transfer_preserves_user_state_and_search(postgres_database: str, tmp_path: Path):
    sqlite_path = tmp_path / "source.sqlite3"
    sqlite_engine = create_database_engine(f"sqlite:///{sqlite_path.as_posix()}")
    Base.metadata.create_all(bind=sqlite_engine)
    with Session(sqlite_engine) as source:
        seed_admin_catalog(source)
        category = ensure_auto_category(source, "Gouda jung")
        product = MasterProduct(name="Gouda jung", normalized_key="gouda jung")
        source.add(product)
        source.flush()
        user = UserProfile(display_name="Transfer User", latitude=50.5, longitude=7.6, radius_km=15)
        source.add(user)
        source.flush()
        store = Store(retailer="REWE", name="Transfer REWE", city="Dierdorf", active=True, benchmark_verified=True)
        source.add(store)
        source.flush()
        source.add(FavoriteProduct(user_id=user.id, master_product_id=product.id))
        source.add(FavoriteStore(user_id=user.id, store_id=store.id))
        source.add(ShoppingItem(user_id=user.id, master_product_id=product.id, quantity=2))
        admin = product.admin_data
        if admin is None:
            from app.models import ProductAdminData

            admin = ProductAdminData(master_product_id=product.id)
            source.add(admin)
        admin.category_id = category.id
        source.commit()

    target_engine = create_database_engine(postgres_database)
    try:
        Base.metadata.create_all(bind=target_engine)
        migrate_sqlite_to_postgres(sqlite_engine, target_engine)
        verification = verify_migration(sqlite_engine, target_engine)
        assert verification.ok, verification
        with Session(target_engine) as target:
            assert target.scalar(select(func.count()).select_from(UserProfile)) == 1
            assert target.scalar(select(func.count()).select_from(FavoriteProduct)) == 1
            assert target.scalar(select(func.count()).select_from(FavoriteStore)) == 1
            assert target.scalar(select(func.count()).select_from(ShoppingItem)) == 1
            results = search_products(target, "gouda")
            assert results and results[0].product.name == "Gouda jung"
    finally:
        target_engine.dispose()
        sqlite_engine.dispose()
