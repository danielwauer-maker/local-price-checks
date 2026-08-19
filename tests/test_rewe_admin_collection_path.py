from dataclasses import replace
import io
import json
import zipfile

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import admin_collector_routes, collection_service, prospects, rewe_audit_runtime
from app.db import Base
from app.engine_v140.collectors import CollectedOffer
from app.models import CollectionRun, Offer, OfferOccurrence, Store
from app.prospect_models import OfferProvenance, Prospect, ProspectArchive
from app.support_export import build_support_export


def _pdf_with_text(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def test_admin_background_rewe_collection_archives_successful_session(
    monkeypatch,
    tmp_path,
):
    """Exercise the production admin job through DB import and prospect audit."""
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'admin-rewe.sqlite'}", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)

    db = TestSession()
    store = Store(
        retailer="REWE",
        name="REWE:XL Hundertmark",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        external_id="321019",
        source_url="https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    store_id = store.id
    db.close()

    offer = CollectedOffer(
        source_key="rewe_dierdorf",
        store_name="REWE:XL Hundertmark",
        retailer="REWE",
        product_name="Milka Schokolade",
        category="Süßwaren",
        price=0.95,
        quantity=0.09,
        unit="kg",
        unit_price=10.56,
        unit_price_unit="kg",
        valid_from="17.08.2026",
        valid_to="22.08.2026",
        source_text="Milka Schokolade je 90-g-Tafel (1 kg = 10,56 €)",
        source_url=store.source_url,
        local_store_offer=True,
        confidence=0.99,
    )
    collector_calls = []

    def collector(source):
        collector_calls.append(source.url)
        return {
            "source": source,
            "raw": b"<html><body><article>Milka Schokolade 0,95 Euro</article></body></html>",
            "content_type": "text/html; charset=utf-8",
            "fetch_mode": "playwright-1",
            "final_url": source.url,
            "offers": [offer],
            "status": "parsed",
        }

    monkeypatch.setattr(admin_collector_routes, "SessionLocal", TestSession)
    monkeypatch.setattr(collection_service, "collect_one", collector)
    monkeypatch.setattr(
        rewe_audit_runtime,
        "_render_rewe_snapshot",
        lambda html, source_url: _pdf_with_text("Milka Schokolade 0,95 Euro"),
    )
    monkeypatch.setattr(
        rewe_audit_runtime,
        "settings",
        replace(rewe_audit_runtime.settings, data_dir=tmp_path),
    )

    admin_collector_routes._run_store_collection_background(store_id)

    db = TestSession()
    run = db.query(CollectionRun).one()
    assert collector_calls == [store.source_url]
    assert run.status == "success"
    assert run.offers_received == 1
    assert run.offers_imported == 1
    assert "artifact_status=PASS" in (run.message or "")
    assert "archive_created=true" in (run.message or "")
    assert "archive_count=1" in (run.message or "")
    assert "provenance_links=1" in (run.message or "")
    assert "audit_fehler" not in (run.message or "")

    assert db.query(Offer).count() == 1
    assert db.query(OfferOccurrence).count() == 1
    assert db.query(Prospect).filter_by(store_id=store_id, active=True).count() == 1
    archive = db.query(ProspectArchive).filter_by(store_id=store_id).one()
    provenance = db.query(OfferProvenance).filter_by(prospect_archive_id=archive.id).one()
    assert provenance.prospect_page == 1
    assert archive.pdf_bytes.startswith(b"%PDF")
    assert archive.pdf_url.startswith("web-snapshot://captured-session/")

    _, support_payload = build_support_export(db)
    with zipfile.ZipFile(io.BytesIO(support_payload)) as support_zip:
        manifest = json.loads(support_zip.read("manifest.json"))
        exported_archives = json.loads(support_zip.read("prospect_archives.json"))
        exported_provenance = json.loads(support_zip.read("offer_provenance.json"))
    assert manifest["counts"]["prospect_archives"] == 1
    assert manifest["counts"]["offer_provenance"] == 1
    assert exported_archives[0]["pdf_sha256"] == archive.pdf_sha256
    assert exported_provenance[0]["prospect_page"] == 1
    db.close()


def test_rewe_artifact_failure_preserves_recall_and_downgrades_health(
    monkeypatch,
):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    db = TestSession()
    store = Store(
        retailer="REWE",
        name="REWE:XL Hundertmark",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()

    offer = CollectedOffer(
        source_key="rewe_dierdorf",
        store_name=store.name,
        retailer="REWE",
        product_name="Milka Schokolade",
        category="Süßwaren",
        price=0.95,
        valid_from="17.08.2026",
        valid_to="22.08.2026",
        source_text="Milka Schokolade",
        source_url="https://www.rewe.de/angebote/dierdorf/321019/x/",
        local_store_offer=True,
        confidence=0.99,
    )

    class BrokenArtifactHandler:
        def archive_before_import(self, *_args):
            raise RuntimeError("fixture archive failed")

        def finalize_after_import(self, *_args):
            raise AssertionError("finalizer must not run")

    _, summary, run = collection_service.collect_structured_for_store(
        db,
        store.name,
        collector_fn=lambda source: {
            "source": source,
            "raw": b"<html><body>Milka</body></html>",
            "fetch_mode": "fixture",
            "final_url": source.url,
            "offers": [offer],
        },
        artifact_handler=BrokenArtifactHandler(),
    )

    assert summary.imported == 1
    assert db.query(Offer).count() == 1
    assert run.status == "warning"
    assert "artifact_status=FAIL" in (run.message or "")
    assert "archive_created=false" in (run.message or "")
    db.close()


def test_rewe_prospect_discovery_cannot_start_parallel_snapshot_path():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    db = TestSession()
    store = Store(
        retailer="REWE",
        name="REWE:XL Hundertmark",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()

    with pytest.raises(ValueError, match="kanonischen Collection-Lifecycle"):
        prospects.discover_and_store_prospect(db, store, "current")

    assert db.query(Prospect).count() == 0
    assert db.query(ProspectArchive).count() == 0
    db.close()


def test_rewe_missing_archive_and_missing_offers_is_failed():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    db = TestSession()
    store = Store(
        retailer="REWE",
        name="REWE:XL Hundertmark",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()

    class BrokenArtifactHandler:
        def archive_before_import(self, *_args):
            raise RuntimeError("fixture archive failed")

        def finalize_after_import(self, *_args):
            raise AssertionError("finalizer must not run")

    _, summary, run = collection_service.collect_structured_for_store(
        db,
        store.name,
        collector_fn=lambda source: {
            "source": source,
            "raw": b"<html><body></body></html>",
            "fetch_mode": "fixture",
            "final_url": source.url,
            "offers": [],
        },
        artifact_handler=BrokenArtifactHandler(),
    )

    assert summary.imported == 0
    assert run.status == "failed"
    assert "artifact_status=FAIL" in (run.message or "")
    db.close()
