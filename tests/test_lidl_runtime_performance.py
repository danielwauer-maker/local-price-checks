from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_collector_routes import _expire_stuck_lidl_run
from app.collection_progress import CollectionProgressReporter
from app.db import Base
from app.engine_v140.lidl_flipbook import (
    LidlCollectionTimeout,
    _RuntimeBudget,
    _download_cached_asset,
    _ocr_candidate_assets,
    _offer_page_numbers,
    _schwarz_page_assets,
    _structured_authority_pages,
)
from app.engine_v140.lidl_ocr import _benchmark_anchor_offers
from app.models import CollectionRun, CollectionRunProgress, Store


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_lidl_ocr_is_only_planned_for_local_pages_without_structured_hits():
    flyer = {
        "pages": [
            {"number": 1, "zoom": "https://assets.example/1.jpg", "altText": "Lokale Angebote"},
            {"number": 2, "zoom": "https://assets.example/2.jpg", "altText": "Lokale Angebote"},
            {"number": 3, "zoom": "https://assets.example/3.jpg", "altText": "Shoppe auf lidl.de. Nur online"},
        ]
    }
    assets = _schwarz_page_assets(flyer)
    structured = _offer_page_numbers([SimpleNamespace(source_text="PDF Seite 1: ManifestHotspot")])

    candidates = _ocr_candidate_assets(assets, structured)

    assert [row["page_no"] for row in candidates] == [2]


def test_catalogue_link_does_not_suppress_page_ocr():
    catalogue = SimpleNamespace(source_text="PDF Seite 1: SchwarzFlyerLink+Catalog {}")
    hotspot = SimpleNamespace(source_text="PDF Seite 2: ManifestHotspot {}")
    assert _structured_authority_pages([catalogue, hotspot]) == {2}


def test_benchmarked_grocery_anchors_recover_sparse_lidl_cards(monkeypatch):
    crops = {
        "lavazza": "LAVAZZA Caffè Crema 12 99 Ganze Bohnen. Je 1 kg",
        "pepsi": "PEPSI SCHWIP SCHWAP Je 1,75 l 1 l = -,57",
        "funny-frisch": "FUNNY-FRISCH Pom-Bär Je 75 g Mit Lidl Plus 0 88",
        "trauben": "Helle kernlose Trauben Je 500 g 1 kg = 2.50",
    }
    monkeypatch.setattr(
        "app.engine_v140.lidl_ocr._anchor_crop_text",
        lambda image, tokens, needle, timeout_seconds: crops[needle],
    )
    tokens = [
        {"text": "LAVAZZA", "left": 0, "top": 0, "width": 10, "height": 10},
        {"text": "PEPSI", "left": 0, "top": 100, "width": 10, "height": 10},
        {"text": "FUNNY-FRISCH", "left": 0, "top": 200, "width": 10, "height": 10},
        {"text": "Trauben", "left": 100, "top": 300, "width": 10, "height": 10},
        {"text": "1.25", "left": 120, "top": 320, "width": 40, "height": 60},
    ]
    source = SimpleNamespace(
        key="lidl", store_name="Lidl Puderbach", retailer="Lidl", url="https://www.lidl.de/prospekte/test"
    )
    text = "Lavazza Pepsi Funny-Frisch Helle kernlose Trauben"

    rows = _benchmark_anchor_offers(
        source,
        object(),
        tokens,
        text,
        valid_from="17.08.2026",
        valid_to="22.08.2026",
        timeout_seconds=18,
    )

    by_name = {row.product_name: row for row in rows}
    assert by_name["Lavazza Caffè Crema"].price == 12.99
    assert by_name["Pepsi / Schwip Schwap"].price == 1.0
    assert by_name["Funny-Frisch Pom-Bär"].price == 0.88
    assert by_name["Helle kernlose Trauben"].price == 1.25


def test_lidl_asset_cache_avoids_second_download(monkeypatch, tmp_path):
    calls = []

    class Response:
        content = b"asset" * 500

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr("app.engine_v140.lidl_flipbook.httpx.get", fake_get)
    asset = {"page_no": 7, "url": "https://assets.example/page-7.jpg"}

    first = _download_cached_asset(asset, tmp_path, 5)
    second = _download_cached_asset(asset, tmp_path, 5)

    assert first[2] is False
    assert second[2] is True
    assert first[3] == second[3]
    assert calls == [asset["url"]]


def test_lidl_runtime_budget_raises_structured_timeout():
    budget = _RuntimeBudget(0)
    with pytest.raises(LidlCollectionTimeout) as exc:
        budget.begin("viewer_manifest")
    assert exc.value.phase == "viewer_manifest"
    assert "error_type=timeout" in str(exc.value)


def test_collection_progress_is_persisted_structurally():
    db = _database()
    store = Store(
        retailer="Lidl",
        name="Lidl Runtime Test",
        postal_code="56305",
        city="Puderbach",
        address="Teststraße 1",
        active=True,
    )
    db.add(store)
    db.flush()
    run = CollectionRun(store_id=store.id, source_key="lidl:test", status="running")
    db.add(run)
    db.commit()

    CollectionProgressReporter(db, run).update(
        "ocr_fallback",
        pages_total=73,
        pages_structured=12,
        pages_ocr=61,
        pages_done=20,
        assets_cached=4,
    )

    progress = db.query(CollectionRunProgress).one()
    db.refresh(run)
    assert progress.phase == "ocr_fallback"
    assert progress.pages_total == 73
    assert progress.pages_structured == 12
    assert progress.pages_ocr == 61
    assert progress.pages_done == 20
    assert "phase=ocr_fallback" in run.message


def test_lidl_watchdog_closes_stuck_running_run(monkeypatch):
    db = _database()
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
    store = Store(
        retailer="Lidl",
        name="Lidl Watchdog Test",
        postal_code="56305",
        city="Puderbach",
        address="Teststraße 2",
        active=True,
    )
    db.add(store)
    db.flush()
    run = CollectionRun(store_id=store.id, source_key="lidl:test", status="running")
    db.add(run)
    db.flush()
    db.add(CollectionRunProgress(run_id=run.id, phase="ocr_fallback", elapsed_seconds=540))
    db.commit()
    monkeypatch.setattr("app.admin_collector_routes.SessionLocal", factory)

    _expire_stuck_lidl_run(store.id)

    db.expire_all()
    closed = db.get(CollectionRun, run.id)
    progress = db.query(CollectionRunProgress).filter_by(run_id=run.id).one()
    assert closed.status == "failed"
    assert closed.finished_at is not None
    assert "error_type=timeout" in closed.message
    assert "phase=ocr_fallback" in closed.message
    assert progress.error_type == "timeout"
