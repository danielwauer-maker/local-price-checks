from datetime import datetime, timedelta
from uuid import uuid4

from app.db import SessionLocal
from app.freshness import market_freshness
from app.models import CollectionRun, Store


def test_stale_alias_does_not_degrade_current_physical_market():
    suffix = uuid4().hex[:8]
    canonical_name = f"REWE canonical freshness {suffix}"
    alias_name = f"REWE alias freshness {suffix}"
    db = SessionLocal()
    store_ids: list[int] = []
    try:
        canonical = Store(
            retailer="REWE",
            name=canonical_name,
            postal_code="56269",
            city="Dierdorf",
            address=f"Teststraße {suffix}",
            active=True,
            benchmark_verified=True,
            external_id=f"retailer-{suffix}",
            source_url="https://www.rewe.de/marktseite/test/",
        )
        alias = Store(
            retailer="REWE",
            name=alias_name,
            postal_code="56269",
            city="Dierdorf",
            address=f"Teststraße {suffix}",
            active=True,
            benchmark_verified=True,
        )
        db.add_all([canonical, alias])
        db.flush()
        store_ids = [canonical.id, alias.id]

        db.add_all([
            CollectionRun(
                store_id=canonical.id,
                source_key=f"canonical-{suffix}:web",
                started_at=datetime.utcnow() - timedelta(minutes=5),
                finished_at=datetime.utcnow() - timedelta(minutes=4),
                status="success",
                offers_received=10,
                offers_imported=10,
            ),
            CollectionRun(
                store_id=alias.id,
                source_key=f"alias-{suffix}:web",
                started_at=datetime.utcnow() - timedelta(days=8),
                finished_at=datetime.utcnow() - timedelta(days=8),
                status="success",
                offers_received=10,
                offers_imported=10,
            ),
        ])
        db.commit()

        rows = market_freshness(db)
        matching = [row for row in rows if row["store"].id in store_ids]

        assert len(matching) == 1
        assert matching[0]["store"].id == canonical.id
        assert matching[0]["state"] == "current"
        assert matching[0]["run"].store_id == canonical.id
    finally:
        if store_ids:
            db.query(CollectionRun).filter(CollectionRun.store_id.in_(store_ids)).delete(
                synchronize_session=False
            )
            db.query(Store).filter(Store.id.in_(store_ids)).delete(synchronize_session=False)
            db.commit()
        db.close()
