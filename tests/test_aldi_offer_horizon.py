from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.aldi_live_collector import (
    _next_week_horizon_end,
    _prune_stale_aldi_week_offers,
    _select_current_aldi_week_offers,
)
from app.db import Base
from app.models import MasterProduct, Offer, Store


def _row(name: str, valid_from: str, valid_to: str, price: float = 1.99):
    return SimpleNamespace(
        product_name=name,
        price=price,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def test_next_week_horizon_ends_on_following_sunday():
    assert _next_week_horizon_end(date(2026, 9, 15)) == date(2026, 9, 27)
    assert _next_week_horizon_end(date(2026, 9, 14)) == date(2026, 9, 27)
    assert _next_week_horizon_end(date(2026, 9, 20)) == date(2026, 9, 27)


def test_aldi_selection_keeps_current_and_published_next_week_but_not_stale_or_far_future():
    stale = _row("Altbestand", "07.09.2026", "12.09.2026")
    current = _row("Aktuelle Woche", "14.09.2026", "19.09.2026")
    later_this_week = _row("Ab Donnerstag", "17.09.2026", "19.09.2026")
    next_week = _row("Nächste Woche", "21.09.2026", "26.09.2026")
    far_future = _row("Übernächste Woche", "28.09.2026", "03.10.2026")

    selected, active_window, available_windows = _select_current_aldi_week_offers(
        [stale, current, later_this_week, next_week, far_future],
        today=date(2026, 9, 15),
    )

    assert selected == [current, later_this_week, next_week]
    assert active_window == ("14.09.2026", "19.09.2026")
    assert available_windows == {
        ("07.09.2026", "12.09.2026"),
        ("14.09.2026", "19.09.2026"),
        ("17.09.2026", "19.09.2026"),
        ("21.09.2026", "26.09.2026"),
        ("28.09.2026", "03.10.2026"),
    }


def test_aldi_selection_uses_spareno_business_date_when_today_is_omitted(monkeypatch):
    current = _row("Aktuelle Woche", "14.09.2026", "19.09.2026")
    next_week = _row("Nächste Woche", "21.09.2026", "26.09.2026")
    far_future = _row("Übernächste Woche", "28.09.2026", "03.10.2026")
    monkeypatch.setattr("app.aldi_live_collector.app_today", lambda: date(2026, 9, 15))

    selected, active_window, _ = _select_current_aldi_week_offers(
        [current, next_week, far_future]
    )

    assert selected == [current, next_week]
    assert active_window == ("14.09.2026", "19.09.2026")


def test_prune_handles_current_and_next_week_independently():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    store = Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Test",
        active=True,
    )
    products = [
        MasterProduct(name="Current Safe", normalized_key="current-safe"),
        MasterProduct(name="Current Stale", normalized_key="current-stale"),
        MasterProduct(name="Next Safe", normalized_key="next-safe"),
        MasterProduct(name="Next Stale", normalized_key="next-stale"),
    ]
    db.add_all([store, *products])
    db.flush()

    current_safe = Offer(
        store_id=store.id,
        master_product_id=products[0].id,
        price=1.11,
        valid_from=date(2026, 9, 14),
        valid_to=date(2026, 9, 19),
        source_url="https://www.aldi-sued.de/angebote",
    )
    current_stale = Offer(
        store_id=store.id,
        master_product_id=products[1].id,
        price=2.22,
        valid_from=date(2026, 9, 14),
        valid_to=date(2026, 9, 19),
        source_url="https://www.aldi-sued.de/angebote",
    )
    next_safe = Offer(
        store_id=store.id,
        master_product_id=products[2].id,
        price=3.33,
        valid_from=date(2026, 9, 21),
        valid_to=date(2026, 9, 26),
        source_url="https://www.aldi-sued.de/angebote",
    )
    next_stale = Offer(
        store_id=store.id,
        master_product_id=products[3].id,
        price=4.44,
        valid_from=date(2026, 9, 21),
        valid_to=date(2026, 9, 26),
        source_url="https://www.aldi-sued.de/angebote",
    )
    db.add_all([current_safe, current_stale, next_safe, next_stale])
    db.commit()

    current_rows = [
        _row(
            "Current Safe" if index == 0 else f"Current Product {index}",
            "14.09.2026",
            "19.09.2026",
            1.11 if index == 0 else float(index + 10),
        )
        for index in range(20)
    ]
    next_rows = [
        _row(
            "Next Safe" if index == 0 else f"Next Product {index}",
            "21.09.2026",
            "26.09.2026",
            3.33 if index == 0 else float(index + 40),
        )
        for index in range(20)
    ]

    pruned = _prune_stale_aldi_week_offers(db, store, [*current_rows, *next_rows])

    assert pruned == 2
    remaining = {offer.product.name for offer in db.query(Offer).all()}
    assert remaining == {"Current Safe", "Next Safe"}
