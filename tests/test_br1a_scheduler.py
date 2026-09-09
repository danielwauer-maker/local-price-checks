from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.scheduler as scheduler
from app.data_operations_models import DailyCollectionRun
from app.db import Base
from app.extractor_adapter import ImportSummary
from app.models import CollectionRun, Store


def test_daily_scheduler_uses_only_public_physical_stores_keeps_edeka_path_and_continues(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    stores = [
        Store(retailer="REWE", name="Public REWE", postal_code="1", city="A", address="A 1", active=True, benchmark_verified=True),
        Store(retailer="EDEKA", name="Public EDEKA", postal_code="2", city="B", address="B 1", active=True, benchmark_verified=True, external_id="071378"),
        Store(retailer="Lidl", name="Hidden Lidl", postal_code="3", city="C", address="C 1", active=True, benchmark_verified=False),
        Store(retailer="REWE", name="Inactive REWE", postal_code="4", city="D", address="D 1", active=False, benchmark_verified=True),
    ]
    db.add_all(stores); db.commit()
    monkeypatch.setattr(scheduler, "SessionLocal", Session)
    calls = []

    def complete(session, store, *, fail=False):
        calls.append((store.retailer, store.name))
        if fail:
            raise RuntimeError("isolated failure")
        run = CollectionRun(store_id=store.id, source_key="fake:web", status="success", offers_imported=1, offers_received=1)
        session.add(run); session.commit(); session.refresh(run)
        return {}, ImportSummary(received=1, imported=1), run

    monkeypatch.setattr(scheduler, "collect_store_from_web", lambda session, name, **kwargs: complete(session, next(s for s in session.query(Store) if s.name == name), fail=True))
    monkeypatch.setattr(scheduler, "collect_edeka_web_for_store", lambda session, store, **kwargs: complete(session, store))

    results = scheduler.run_verified_market_collection()
    assert calls == [("EDEKA", "Public EDEKA"), ("REWE", "Public REWE")]
    assert results["Public EDEKA"] == "success:1"
    assert results["Public REWE"] == "failed:RuntimeError"
    assert "Hidden Lidl" not in results and "Inactive REWE" not in results

    scheduler.run_verified_market_collection()
    with Session() as check:
        assert check.query(DailyCollectionRun).count() == 1


def _run_daily_outcomes(monkeypatch, statuses):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        for index, status in enumerate(statuses):
            db.add(Store(
                retailer="EDEKA",
                name=f"Daily {index} {status}",
                postal_code=str(index),
                city="Test",
                address=f"Test {index}",
                active=True,
                benchmark_verified=True,
                external_id=f"daily-{index}",
            ))
        db.commit()

    monkeypatch.setattr(scheduler, "SessionLocal", Session)

    def collect(session, store, **kwargs):
        status = store.name.rsplit(" ", 1)[-1]
        run = CollectionRun(
            store_id=store.id,
            source_key="test:daily-accounting",
            status=status,
            message=f"{status} detail" if status != "success" else None,
            offers_received=1,
            offers_imported=1 if status in {"success", "warning"} else 0,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return {}, ImportSummary(received=1, imported=run.offers_imported), run

    monkeypatch.setattr(scheduler, "collect_edeka_web_for_store", collect)
    scheduler.run_verified_market_collection()
    with Session() as db:
        return db.query(DailyCollectionRun).one()


def test_daily_run_accounting_counts_warning_as_success_and_blocker_wins(monkeypatch):
    daily = _run_daily_outcomes(monkeypatch, ["success", "warning", "blocked", "failed"])
    assert daily.stores_planned == 4
    assert daily.stores_succeeded == 2
    assert daily.stores_blocked == 1
    assert daily.stores_failed == 1
    assert daily.stores_planned == daily.stores_succeeded + daily.stores_blocked + daily.stores_failed
    assert daily.status == "blocked"
    assert "warning detail" in daily.warnings_json


def test_daily_run_warning_only_is_complete_and_sets_warning_status(monkeypatch):
    daily = _run_daily_outcomes(monkeypatch, ["success", "warning"])
    assert daily.stores_planned == 2
    assert daily.stores_succeeded == 2
    assert daily.stores_blocked == 0
    assert daily.stores_failed == 0
    assert daily.stores_planned == daily.stores_succeeded + daily.stores_blocked + daily.stores_failed
    assert daily.status == "warning"
