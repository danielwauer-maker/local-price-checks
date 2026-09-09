from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collection_anomaly import CollapsePolicy, assess_offer_count
from app.db import Base
from app.models import CollectionRun, Store


def _seed(counts):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    store = Store(retailer="REWE", name="Collapse REWE", postal_code="00000", city="Test", address="Test")
    db.add(store); db.flush()
    for offset, count in enumerate(counts):
        db.add(CollectionRun(
            store_id=store.id, source_key="test", status="success", offers_imported=count,
            started_at=datetime.utcnow() - timedelta(days=offset + 1),
        ))
    db.commit()
    return db, store


def test_recent_178_184_172_then_181_is_healthy():
    db, store = _seed([178, 184, 172])
    result = assess_offer_count(db, store=store, candidate_count=181)
    assert result.state == "healthy"
    assert result.baseline == 178


def test_recent_178_184_172_then_21_is_blocked_with_reason():
    db, store = _seed([178, 184, 172])
    result = assess_offer_count(db, store=store, candidate_count=21)
    assert result.state == "blocked"
    assert result.reason == "offer_count_collapse: 21 vs recent median 178"


def test_insufficient_history_does_not_aggressively_block_above_retailer_floor():
    db, store = _seed([178, 184])
    result = assess_offer_count(db, store=store, candidate_count=100)
    assert result.state == "healthy"
    assert result.baseline is None


def test_stronger_retailer_floor_still_wins_when_history_exists():
    db, store = _seed([100, 100, 100])
    result = assess_offer_count(
        db, store=store, candidate_count=35,
        policy=CollapsePolicy(block_ratio=.20, warning_ratio=.70),
    )
    assert result.state == "blocked"
    assert "retailer_floor" in result.reason
