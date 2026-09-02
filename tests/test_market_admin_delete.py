import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import model_registry  # noqa: F401 - register all Store references
from app.coverage_models import StoreDiscoveryCandidate
from app.db import Base
from app.market_activation import StoreActivationState
from app.admin_market_identity_routes import delete_false_market
from app.market_admin_delete import delete_false_store, preview_false_store_delete
from app.models import CollectionRun, FavoriteStore, Store, UserProfile


def _db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _false_store(db):
    store = Store(
        retailer="REWE",
        name="REWE falscher Map-Alias",
        address="Raiffeisenstraße",
        postal_code="56587",
        city="Straßenhaus",
        latitude=50.541989,
        longitude=7.519881,
        active=True,
        benchmark_verified=False,
        external_id="way/92219239",
        source_url="https://www.openstreetmap.org/way/92219239",
    )
    db.add(store)
    db.flush()
    candidate = StoreDiscoveryCandidate(
        discovery_key="osm-delete-test",
        postal_code="56587",
        retailer="REWE",
        name="REWE",
        address="Raiffeisenstraße",
        city="Straßenhaus",
        latitude=50.541989,
        longitude=7.519881,
        source="osm",
        source_external_id="way/92219239",
        status="promoted",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        matched_store_id=store.id,
    )
    db.add(candidate)
    db.add(StoreActivationState(
        store_id=store.id,
        lifecycle_status="promoted",
        identity_verified=True,
    ))
    db.commit()
    return store.id, candidate.id


def test_prepublic_false_store_with_only_workflow_metadata_can_be_deleted():
    db = _db()
    store_id, candidate_id = _false_store(db)
    store = db.get(Store, store_id)

    preview = preview_false_store_delete(db, store)
    assert preview.allowed is True
    assert preview.dependent_counts["store_discovery_candidates"] == 1
    assert preview.dependent_counts["store_activation_states"] == 1

    result = delete_false_store(db, store)
    assert result.allowed is True
    db.commit()

    assert db.get(Store, store_id) is None
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    assert candidate is not None
    assert candidate.status == "rejected"
    assert candidate.matched_store_id is None
    assert "dauerhaft gelöscht" in candidate.verification_note
    assert db.query(StoreActivationState).filter_by(store_id=store_id).count() == 0


def test_store_with_collection_history_is_not_hard_deleted():
    db = _db()
    store_id, _ = _false_store(db)
    db.add(CollectionRun(store_id=store_id, source_key="test", status="success"))
    db.commit()

    store = db.get(Store, store_id)
    preview = preview_false_store_delete(db, store)

    assert preview.allowed is False
    assert any("collection_runs" in blocker for blocker in preview.blockers)
    assert delete_false_store(db, store).allowed is False
    assert db.get(Store, store_id) is not None


def test_store_with_user_favorite_is_not_hard_deleted():
    db = _db()
    store_id, _ = _false_store(db)
    user = UserProfile(display_name="Delete Guard")
    db.add(user)
    db.flush()
    db.add(FavoriteStore(user_id=user.id, store_id=store_id))
    db.commit()

    preview = preview_false_store_delete(db, db.get(Store, store_id))

    assert preview.allowed is False
    assert preview.dependent_counts["favorite_stores"] == 1


def test_public_store_is_never_hard_deleted():
    db = _db()
    store_id, _ = _false_store(db)
    store = db.get(Store, store_id)
    store.benchmark_verified = True
    db.commit()

    preview = preview_false_store_delete(db, store)

    assert preview.allowed is False
    assert any("öffentlich" in blocker for blocker in preview.blockers)


def test_admin_delete_requires_exact_typed_confirmation():
    db = _db()
    store_id, _ = _false_store(db)

    with pytest.raises(HTTPException) as caught:
        delete_false_market(store_id, confirm="DELETE", db=db, actor="admin")

    assert caught.value.status_code == 400
    assert db.get(Store, store_id) is not None


def test_admin_delete_removes_exact_alias_never_canonical_target():
    db = _db()
    canonical = Store(
        retailer="REWE",
        name="REWE Official Canonical",
        address="Kirschbüchel 2",
        postal_code="56587",
        city="Straßenhaus",
        latitude=50.54205,
        longitude=7.51990,
        active=True,
        benchmark_verified=True,
        external_id="1940425",
        source_url="https://www.rewe.de/marktseite/strassenhaus/1940425/",
    )
    db.add(canonical)
    db.flush()
    canonical_id = canonical.id
    alias_id, candidate_id = _false_store(db)

    delete_false_market(alias_id, confirm="LOESCHEN", db=db, actor="admin")

    assert db.get(Store, alias_id) is None
    assert db.get(Store, canonical_id) is not None
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    assert candidate.status == "rejected"
    assert candidate.matched_store_id is None


def test_generic_delete_guard_covers_all_registered_store_business_references():
    store_reference_tables = {
        table.name
        for table in Base.metadata.tables.values()
        if any(
            foreign_key.column.table.name == "stores"
            and foreign_key.column.name == "id"
            for foreign_key in table.foreign_keys
        )
    }

    assert {
        "offers",
        "collection_runs",
        "favorite_stores",
        "prospects",
        "prospect_archives",
        "media_assets",
        "normal_price_observations",
        "collection_quality_snapshots",
        "store_quality_assessments",
        "web_offer_audit_runs",
        "web_offer_audit_items",
    } <= store_reference_tables
