from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import MasterProduct, MediaAsset
import app.product_media as product_media
from app.product_media import persist_product_image, persist_product_image_file


class _Response:
    def __init__(self, payload: bytes, content_type: str = "image/png"):
        self._payload = payload
        self.headers = {"content-type": content_type, "content-length": str(len(payload))}
        self.url = "https://img.example.test/product.png"

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    product = MasterProduct(name="Testprodukt", normalized_key="testprodukt", brand=None, package_size=None)
    db.add(product)
    db.commit()
    db.refresh(product)
    return db, product


def test_product_image_is_downloaded_and_reused(monkeypatch, tmp_path: Path):
    db, product = _db()
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _Response(b"\x89PNG\r\n\x1a\nabc"))

    first = persist_product_image(
        db,
        product,
        "https://img.example.test/product.png",
        alt_text="Testbild",
        media_dir=tmp_path,
    )
    db.commit()

    assert first is not None
    assert first.kind == "product"
    assert first.is_primary is True
    assert first.file_path
    assert (tmp_path / first.file_path).exists()

    second = persist_product_image(
        db,
        product,
        "https://img.example.test/product.png",
        alt_text="Testbild",
        media_dir=tmp_path,
    )
    db.commit()
    assert second.id == first.id
    assert db.query(MediaAsset).count() == 1


def test_non_image_response_is_ignored(monkeypatch, tmp_path: Path):
    db, product = _db()
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _Response(b"not-an-image", "text/html"))
    assert persist_product_image(db, product, "https://img.example.test/bad", media_dir=tmp_path) is None
    assert db.query(MediaAsset).count() == 0


def test_prospect_crop_inside_data_dir_is_persisted(monkeypatch, tmp_path: Path):
    db, product = _db()
    data_dir = tmp_path / "data"
    crop = data_dir / "prospects" / "crop.jpg"
    crop.parent.mkdir(parents=True)
    crop.write_bytes(b"jpeg-crop-payload")
    monkeypatch.setattr(product_media, "settings", type("Settings", (), {"data_dir": data_dir})())

    asset = persist_product_image_file(
        db,
        product,
        crop,
        alt_text="Offizieller Prospektausschnitt",
        media_dir=data_dir / "admin_media",
    )
    db.commit()

    assert asset is not None
    assert asset.source_url.startswith("prospect-crop:")
    assert asset.mime_type == "image/jpeg"
    assert (data_dir / "admin_media" / asset.file_path).read_bytes() == b"jpeg-crop-payload"


def test_prospect_crop_outside_data_dir_is_rejected(monkeypatch, tmp_path: Path):
    db, product = _db()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"not-allowed")
    monkeypatch.setattr(product_media, "settings", type("Settings", (), {"data_dir": data_dir})())
    assert persist_product_image_file(db, product, outside, media_dir=data_dir / "admin_media") is None
