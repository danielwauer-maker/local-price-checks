from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.canonical_lokero_market_routes import _released_physical_stores
from app.db import Base
from app.models import CollectionRun, Store, UserProfile
from app.physical_market_identity import collapse_physical_stores, physical_store_key
from app.scrape_health import scrape_health_rows


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _store(name, address, external_id, *, verified=True):
    return Store(
        retailer="REWE",
        name=name,
        postal_code="56269",
        city="Dierdorf",
        address=address,
        latitude=50.5474,
        longitude=7.6506,
        active=True,
        benchmark_verified=verified,
        external_id=external_id,
        source_url=f"https://www.rewe.de/marktseite/dierdorf/{external_id}/markt/",
    )


def test_german_street_spellings_share_physical_identity():
    left = _store("REWE Dierdorf", "Königsberger Str. 20-22", "321019")
    right = _store("REWE:XL Hundertmark", "Königsberger Straße 20-22", "321019")
    left.id, right.id = 1, 2
    assert physical_store_key(left) == physical_store_key(right)
    assert len(collapse_physical_stores([left, right])) == 1


def test_public_market_helper_returns_only_one_physical_store():
    db = _db()
    alias = _store("REWE Dierdorf", "Königsberger Str. 20-22", "321019", verified=False)
    canonical = _store("REWE:XL Hundertmark", "Königsberger Straße 20-22", "321019", verified=True)
    db.add_all([alias, canonical])
    db.commit()
    user = UserProfile(latitude=50.5474, longitude=7.6506, radius_km=15)

    rows = _released_physical_stores(db, user)

    assert len(rows) == 1
    assert rows[0].name == "REWE:XL Hundertmark"
    db.close()


def test_scrape_health_counts_duplicate_aliases_once():
    db = _db()
    alias = _store("REWE Dierdorf", "Königsberger Str. 20-22", "321019", verified=False)
    canonical = _store("REWE:XL Hundertmark", "Königsberger Straße 20-22", "321019", verified=True)
    db.add_all([alias, canonical])
    db.commit()
    db.refresh(canonical)
    db.add(CollectionRun(
        store_id=canonical.id,
        source_key="rewe-test",
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        status="success",
        offers_received=100,
        offers_imported=100,
    ))
    db.commit()

    rows = [row for row in scrape_health_rows(db) if row.retailer == "REWE"]

    assert len(rows) == 1
    assert rows[0].state == "healthy"
    db.close()
