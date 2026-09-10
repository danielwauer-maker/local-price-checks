from __future__ import annotations

import io
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import MasterProduct, MediaAsset
from app.product_media import persist_product_image, persist_product_image_file, preferred_product_media
from app.product_media_admin import product_media_library, review_product_media, set_preferred_product_media
from app.product_media_library import ProductMediaLibraryMetadata
import app.product_media as product_media


class _Response:
    def __init__(self, payload: bytes, url: str = "https://img.example.test/product.png"):
        self._payload = payload
        self.headers = {"content-type": "image/png", "content-length": str(len(payload))}
        self.url = url

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _png(width: int = 640, height: int = 480) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(stream, format="PNG")
    return stream.getvalue()


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    product = MasterProduct(name="BR1D Produkt", normalized_key="br1d-produkt", brand=None, package_size=None)
    db.add(product)
    db.commit()
    db.refresh(product)
    return db, product


def test_remote_image_records_quality_and_provenance(monkeypatch, tmp_path: Path):
    db, product = _db()
    payload = _png(800, 600)
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _Response(payload))

    asset = persist_product_image(
        db,
        product,
        "https://img.example.test/product.png",
        media_dir=tmp_path,
        media_source="official_retailer",
        retailer="REWE",
        source_name="rewe_product_api",
        confidence=0.97,
    )
    db.commit()

    meta = db.query(ProductMediaLibraryMetadata).filter_by(media_asset_id=asset.id).one()
    assert (meta.width, meta.height, meta.image_format) == (800, 600, "png")
    assert meta.aspect_ratio == 1.3333
    assert len(meta.content_sha256) == 64
    assert len(meta.perceptual_hash) == 16
    assert meta.quality_score >= 65
    assert meta.retailer == "REWE"
    assert meta.source_name == "rewe_product_api"
    assert meta.confidence == 0.97
    assert meta.first_observed_at is not None
    assert meta.last_observed_at is not None


def test_manual_preference_cannot_be_degraded_by_new_collector_image(monkeypatch, tmp_path: Path):
    db, product = _db()
    data_dir = tmp_path / "data"
    crop = data_dir / "prospects" / "crop.png"
    crop.parent.mkdir(parents=True)
    crop.write_bytes(_png(500, 500))
    monkeypatch.setattr(product_media, "settings", type("Settings", (), {"data_dir": data_dir})())

    crop_asset = persist_product_image_file(db, product, crop, media_dir=data_dir / "admin_media")
    review_product_media(db, product.id, crop_asset.id, verification_status="verified", actor="test")
    set_preferred_product_media(db, product.id, crop_asset.id, actor="test")

    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _Response(_png(900, 900)))
    new_asset = persist_product_image(
        db,
        product,
        "https://img.example.test/manufacturer.png",
        media_dir=data_dir / "admin_media",
        media_source="manufacturer_official",
    )
    db.commit()

    assert new_asset.id != crop_asset.id
    assert preferred_product_media(db, product.id, purpose="public").id == crop_asset.id
    assert crop_asset.is_primary is True
    assert new_asset.is_primary is False


def test_rejected_primary_falls_back_without_deleting_history(monkeypatch, tmp_path: Path):
    db, product = _db()
    urls = iter([
        "https://img.example.test/official.png",
        "https://img.example.test/fallback.png",
    ])
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _Response(_png(), next(urls)))

    official = persist_product_image(
        db, product, "https://img.example.test/official.png",
        media_dir=tmp_path, media_source="official_product",
    )
    fallback = persist_product_image(
        db, product, "https://img.example.test/fallback.png",
        media_dir=tmp_path, media_source="retailer_cdn",
    )
    db.commit()
    assert preferred_product_media(db, product.id).id == official.id

    review_product_media(
        db, product.id, official.id,
        verification_status="rejected", actor="test", reason="wrong product",
    )
    db.commit()

    assert db.get(MediaAsset, official.id) is not None
    assert db.get(MediaAsset, official.id).active is False
    assert preferred_product_media(db, product.id).id == fallback.id
    rejected = db.query(ProductMediaLibraryMetadata).filter_by(media_asset_id=official.id).one()
    assert rejected.review_reason == "wrong product"

    reviewed_again = persist_product_image(
        db, product, "https://img.example.test/official.png",
        media_dir=tmp_path, media_source="official_product",
    )
    db.commit()
    assert reviewed_again.id == official.id
    assert reviewed_again.active is False
    assert preferred_product_media(db, product.id).id == fallback.id

    review_product_media(
        db, product.id, official.id,
        verification_status="verified", actor="test",
        is_broken=False, is_placeholder=False, is_logo=False,
    )
    db.commit()
    assert db.get(MediaAsset, official.id).active is True
    assert preferred_product_media(db, product.id).id == official.id


def test_duplicate_content_is_reported_but_assets_are_not_merged(monkeypatch, tmp_path: Path):
    db, product = _db()
    payload = _png(400, 400)
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _Response(payload))

    first = persist_product_image(db, product, "https://img.example.test/a.png", media_dir=tmp_path)
    second = persist_product_image(db, product, "https://img.example.test/b.png", media_dir=tmp_path)
    db.commit()

    rows = product_media_library(db, product.id)
    assert first.id != second.id
    assert db.query(MediaAsset).count() == 2
    assert {row["duplicate_count"] for row in rows} == {2}
    assert len({row["content_sha256"] for row in rows}) == 1
