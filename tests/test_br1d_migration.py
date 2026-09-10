import os
import sqlite3
import subprocess
from pathlib import Path


def test_br1d_upgrade_preserves_existing_media_without_backfill_or_id_changes(tmp_path: Path):
    target = tmp_path / "br1c.sqlite3"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{target.as_posix()}"}
    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "20260909_03"], check=True, env=env)

    with sqlite3.connect(target) as connection:
        connection.execute(
            "INSERT INTO master_products (id, brand, name, package_size, normalized_key) "
            "VALUES (21, 'Brand', 'Migration Product', '500 g', 'br1d migration product')"
        )
        connection.execute(
            "INSERT INTO media_assets "
            "(id, kind, master_product_id, file_path, source_url, alt_text, mime_type, is_primary, active, created_at) "
            "VALUES (31, 'product', 21, 'existing.png', 'https://example.test/existing.png', "
            "'Existing', 'image/png', 1, 1, '2026-09-09 08:00:00')"
        )
        connection.execute(
            "INSERT INTO media_asset_metadata "
            "(id, media_asset_id, media_source, priority, audit_relevant, external_product_id, canonical_url) "
            "VALUES (41, 31, 'official_product', 300, 0, 'retailer-123', '/product/123')"
        )
        connection.commit()

    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "20260910_01"], check=True, env=env)

    with sqlite3.connect(target) as connection:
        asset = connection.execute(
            "SELECT id, master_product_id, source_url, is_primary, active FROM media_assets WHERE id = 31"
        ).fetchone()
        old_meta = connection.execute(
            "SELECT media_asset_id, media_source, external_product_id FROM media_asset_metadata WHERE id = 41"
        ).fetchone()
        library_count = connection.execute("SELECT COUNT(*) FROM product_media_library_metadata").fetchone()[0]
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]

    assert asset == (31, 21, "https://example.test/existing.png", 1, 1)
    assert old_meta == (31, "official_product", "retailer-123")
    assert library_count == 0
    assert revision == "20260910_01"
