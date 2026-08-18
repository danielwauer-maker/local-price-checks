from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CollectionRun, Store
import app.web_collector as web_collector


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session()


def test_rewe_structured_success_falls_back_to_trusted_audit_snapshot(monkeypatch):
    db = _db()
    store = Store(
        retailer="REWE",
        name="REWE Dennis Weirich",
        postal_code="56587",
        city="Straßenhaus",
        address="Kirschbüchel 2",
        external_id="1940425",
        source_url="https://www.rewe.de/angebote/strassenhaus/1940425/rewe-markt-kirschbuechel-2/",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    import app.prospects as prospects
    monkeypatch.setattr(
        prospects,
        "discover_and_store_prospect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("strict snapshot rejected")),
    )
    monkeypatch.setattr(
        web_collector,
        "_trusted_structured_web_snapshot",
        lambda *_args, **_kwargs: "audit=web-snapshot:12 Seiten",
    )

    status = web_collector._ensure_audit_artifact(db, store, store.source_url)
    assert status == "audit=web-snapshot:12 Seiten"
    db.close()


def test_audit_failure_is_written_to_collection_run_message():
    db = _db()
    store = Store(
        retailer="REWE",
        name="REWE Test",
        postal_code="56587",
        city="Straßenhaus",
        address="Test 1",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()
    db.refresh(store)

    run = CollectionRun(store_id=store.id, source_key="rewe-test", status="success", message="fetch=playwright-1")
    db.add(run)
    db.commit()
    db.refresh(run)

    web_collector._append_run_diagnostic(db, run, "audit_fehler=ValueError: Beispiel")
    db.refresh(run)
    assert "fetch=playwright-1" in run.message
    assert "audit_fehler=ValueError: Beispiel" in run.message
    db.close()
