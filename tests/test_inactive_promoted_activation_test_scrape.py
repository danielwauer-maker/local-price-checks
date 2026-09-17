from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.admin_collector_routes as collector_routes
import app.web_collector as web_collector
from app.db import SessionLocal
from app.market_activation import (
    StoreActivationState,
    begin_test_scrape,
    can_start_test_scrape,
)
from app.models import CollectionRun, Store


def _store(db, *, name: str, active: bool = False, benchmark_verified: bool = False) -> Store:
    token = uuid4().hex[:10]
    row = Store(
        retailer="REWE",
        name=name,
        postal_code="56587",
        city="Straßenhaus",
        address=f"Kirschbüchel {token}",
        latitude=50.542010,
        longitude=7.519868,
        active=active,
        benchmark_verified=benchmark_verified,
        external_id=f"test-{token}",
        source_url="https://example.invalid/rewe",
    )
    db.add(row)
    db.flush()
    return row


def _state(db, store: Store, *, lifecycle: str = "promoted", identity: bool = True, suspended: bool = False):
    row = StoreActivationState(
        store_id=store.id,
        lifecycle_status=lifecycle,
        identity_verified=identity,
        manually_suspended=suspended,
        suspension_reason="test" if suspended else None,
    )
    db.add(row)
    db.commit()
    return row


def _cleanup(*store_ids: int) -> None:
    db = SessionLocal()
    try:
        db.query(StoreActivationState).filter(StoreActivationState.store_id.in_(store_ids)).delete(
            synchronize_session=False
        )
        db.query(CollectionRun).filter(CollectionRun.store_id.in_(store_ids)).delete(
            synchronize_session=False
        )
        db.query(Store).filter(Store.id.in_(store_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_promoted_identity_verified_inactive_store_can_begin_test_scrape_without_publication():
    db = SessionLocal()
    store_id = None
    try:
        store = _store(db, name=f"REWE activation {uuid4().hex}", active=False)
        store_id = store.id
        _state(db, store)

        assert can_start_test_scrape(db, store) is True
        state = begin_test_scrape(db, store)
        db.refresh(store)

        assert state.lifecycle_status == "scrape_pending"
        assert store.active is False
        assert store.benchmark_verified is False
    finally:
        db.close()
        if store_id is not None:
            _cleanup(store_id)


def test_inactive_store_still_fails_activation_gate_when_identity_unverified_or_suspended():
    db = SessionLocal()
    ids: list[int] = []
    try:
        unverified = _store(db, name=f"REWE unverified {uuid4().hex}")
        ids.append(unverified.id)
        _state(db, unverified, identity=False)
        assert can_start_test_scrape(db, unverified) is False

        suspended = _store(db, name=f"REWE suspended {uuid4().hex}")
        ids.append(suspended.id)
        _state(db, suspended, suspended=True)
        assert can_start_test_scrape(db, suspended) is False
    finally:
        db.close()
        if ids:
            _cleanup(*ids)


def test_web_collector_requires_explicit_store_id_for_inactive_activation_test(monkeypatch):
    db = SessionLocal()
    ids: list[int] = []
    try:
        shared_name = f"REWE duplicate activation {uuid4().hex}"
        legacy = _store(db, name=shared_name, active=False)
        target = _store(db, name=shared_name, active=False)
        ids.extend([legacy.id, target.id])
        db.commit()

        monkeypatch.setattr(
            web_collector,
            "source_for_store_record",
            lambda store: SimpleNamespace(
                url="https://example.invalid/rewe",
                retailer=store.retailer,
                store_name=store.name,
            ),
        )
        seen: dict[str, object] = {}

        def fake_collect_structured(_db, store_ref, **kwargs):
            seen["store_ref"] = store_ref
            return {"_artifact_managed": True}, SimpleNamespace(imported=1), SimpleNamespace()

        monkeypatch.setattr(web_collector, "collect_structured_for_store", fake_collect_structured)

        with pytest.raises(web_collector.CollectionError, match="explizite Store-ID"):
            web_collector.collect_store_from_web(db, shared_name, allow_inactive=True)

        with pytest.raises(web_collector.CollectionError, match="Markt ist inaktiv"):
            web_collector.collect_store_from_web(db, shared_name)

        web_collector.collect_store_from_web(
            db,
            shared_name,
            allow_inactive=True,
            store_id=target.id,
        )
        assert seen["store_ref"] == target.id
    finally:
        db.close()
        if ids:
            _cleanup(*ids)


def test_background_activation_test_uses_exact_inactive_store_and_completes(monkeypatch):
    setup = SessionLocal()
    ids: list[int] = []
    try:
        shared_name = f"REWE worker duplicate {uuid4().hex}"
        legacy = _store(setup, name=shared_name, active=False)
        target = _store(setup, name=shared_name, active=False)
        ids.extend([legacy.id, target.id])
        _state(setup, target, lifecycle="scrape_pending")
        target_id = target.id
    finally:
        setup.close()

    seen: dict[str, object] = {}

    def fake_collect(db, store_name, **kwargs):
        seen["store_name"] = store_name
        seen.update(kwargs)
        run = CollectionRun(
            store_id=kwargs["store_id"],
            source_key="test:activation",
            status="success",
            offers_received=10,
            offers_imported=10,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return {}, SimpleNamespace(imported=10), run

    monkeypatch.setattr(collector_routes, "collect_store_from_web", fake_collect)

    try:
        collector_routes._run_store_collection_background(target_id, True)

        verify = SessionLocal()
        try:
            state = verify.query(StoreActivationState).filter_by(store_id=target_id).one()
            target = verify.get(Store, target_id)
            assert state.lifecycle_status == "quality_review"
            assert state.last_test_run_id is not None
            assert target.active is False
            assert target.benchmark_verified is False
        finally:
            verify.close()

        assert seen["allow_inactive"] is True
        assert seen["store_id"] == target_id
    finally:
        if ids:
            _cleanup(*ids)


def test_normal_background_collection_still_skips_inactive_store(monkeypatch):
    db = SessionLocal()
    store_id = None
    try:
        store = _store(db, name=f"REWE normal inactive {uuid4().hex}", active=False)
        store_id = store.id
        db.commit()
    finally:
        db.close()

    called = False

    def forbidden_collect(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("normal collection must not run for an inactive store")

    monkeypatch.setattr(collector_routes, "collect_store_from_web", forbidden_collect)
    try:
        collector_routes._run_store_collection_background(store_id, False)
        assert called is False
    finally:
        if store_id is not None:
            _cleanup(store_id)
