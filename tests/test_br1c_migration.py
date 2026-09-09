import os
import sqlite3
import subprocess
from pathlib import Path


def test_br1c_upgrade_preserves_existing_source_products_without_guessing_links(tmp_path: Path):
    target = tmp_path / "br1b.sqlite3"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{target.as_posix()}"}
    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "20260909_02"], check=True, env=env)

    with sqlite3.connect(target) as connection:
        connection.execute(
            "INSERT INTO stores (id, retailer, name, postal_code, city, address, active, benchmark_verified) "
            "VALUES (11, 'REWE', 'REWE Migration', '56269', 'Dierdorf', 'Testweg 1', 1, 1)"
        )
        connection.execute(
            "INSERT INTO master_products (id, brand, name, package_size, normalized_key) "
            "VALUES (21, 'Brand', 'Migration Product', '500 g', 'brand migration product|500g')"
        )
        connection.execute(
            "INSERT INTO source_products "
            "(id, master_product_id, store_id, retailer, source_key, external_product_id, identity_key, source_name, first_observed_at, last_observed_at, match_confidence) "
            "VALUES (31, 21, 11, 'REWE', 'fixture', 'source-local-123', 'legacy-source-key', 'Migration Product', "
            "'2026-09-08 08:00:00', '2026-09-08 08:00:00', 0.9)"
        )
        connection.commit()

    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "20260909_03"], check=True, env=env)

    with sqlite3.connect(target) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(source_products)")}
        source = connection.execute(
            "SELECT id, master_product_id, store_id, external_product_id, retailer_product_id "
            "FROM source_products WHERE id = 31"
        ).fetchone()
        retailer_count = connection.execute("SELECT COUNT(*) FROM retailer_products").fetchone()[0]
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    assert "retailer_product_id" in columns
    assert source == (31, 21, 11, "source-local-123", None)
    assert retailer_count == 0
    assert revision == "20260909_03"
