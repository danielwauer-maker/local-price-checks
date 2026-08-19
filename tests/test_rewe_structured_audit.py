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
