from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.aldi_live_collector import (
    _discover_weekly_page_urls,
    _harden_aldi_row,
    _select_current_aldi_week_offers,
    is_official_aldi_offer_url,
    is_official_aldi_weekly_url,
    parse_aldi_stationary_chain_offers,
)
from app.collection_service import CollectionError
from app.db import Base
from app.engine_v140.collectors import CollectedOffer
from app.engine_v140.source_registry import RetailSource
from app.models import Store
from app import web_collector


def _source(store_name: str = "ALDI SÜD Dierdorf") -> RetailSource:
    return RetailSource(
        key="aldi-test",
        retailer="ALDI SÜD",
        store_name=store_name,
        url="https://www.aldi-sued.de/angebote",
        mode="prospect_discovery",
        locality="regional_chain",
        notes="test",
        supports_products=True,
        store_specific=False,
    )


def _offer(name: str, valid_from: str, valid_to: str, price: float = 1.99) -> CollectedOffer:
    return CollectedOffer(
        "aldi-test",
        "ALDI SÜD Dierdorf",
        "ALDI SÜD",
        name,
        "Sonstiges",
        price,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def test_official_aldi_offer_url_is_strict():
    assert is_official_aldi_offer_url("https://www.aldi-sued.de/angebote")
    assert is_official_aldi_offer_url("https://www.aldi-sued.de/tools/features/angebote")
    assert not is_official_aldi_offer_url("https://www.aldi-sued.de/filialen")
    assert not is_official_aldi_offer_url("https://example.org/angebote")
    assert not is_official_aldi_offer_url("http://www.aldi-sued.de/angebote")


def test_official_aldi_weekly_url_allows_only_known_categories_and_safe_pagination():
    root = "https://www.aldi-sued.de/produkte/wochenangebote/eigenmarken-im-angebot/k/1588161427299188"
    assert is_official_aldi_weekly_url(root)
    assert is_official_aldi_weekly_url(root + "?page=2")
    assert not is_official_aldi_weekly_url(root + "?page=999")
    assert not is_official_aldi_weekly_url(root + "?foo=2")
    assert not is_official_aldi_weekly_url("https://www.aldi-sued.de/produkte/wochenangebote/irgendwas")
    assert not is_official_aldi_weekly_url("https://example.org" + root.split("aldi-sued.de", 1)[1])


def test_discover_weekly_page_urls_stays_on_same_category():
    root = "https://www.aldi-sued.de/produkte/wochenangebote/eigenmarken-im-angebot/k/1588161427299188"
    html = """
    <a href="?page=2">2</a>
    <a href="?page=3">3</a>
    <a href="/produkte/wochenangebote/markenprodukte-im-angebot/k/1588161427299189?page=2">other</a>
    <a href="https://example.org/?page=2">external</a>
    """
    assert _discover_weekly_page_urls(html, root) == [root + "?page=2", root + "?page=3"]


def test_current_week_selection_discards_stale_aldi_cards():
    stale = _offer("August Altbestand", "03.08.2026", "09.08.2026")
    current_a = _offer("Aktuelle Milch", "07.09.2026", "12.09.2026", 1.11)
    current_b = _offer("Aktuelle Butter", "07.09.2026", "12.09.2026", 1.79)

    selected, active_window, available_windows = _select_current_aldi_week_offers(
        [stale, current_a, current_b],
        today=date(2026, 9, 12),
    )

    assert selected == [current_a, current_b]
    assert active_window == ("07.09.2026", "12.09.2026")
    assert available_windows == {
        ("03.08.2026", "09.08.2026"),
        ("07.09.2026", "12.09.2026"),
    }


def test_current_week_selection_still_fails_closed_for_overlapping_active_windows():
    rows = [
        _offer("Fenster A", "07.09.2026", "12.09.2026"),
        _offer("Fenster B", "10.09.2026", "13.09.2026"),
    ]

    with pytest.raises(CollectionError, match="mehrere aktuell gültige Angebotswochen"):
        _select_current_aldi_week_offers(rows, today=date(2026, 9, 12))


def test_current_week_selection_fails_closed_without_active_week():
    rows = [
        _offer("August Altbestand", "03.08.2026", "09.08.2026"),
        _offer("Nächste Woche", "14.09.2026", "19.09.2026"),
    ]

    with pytest.raises(CollectionError, match="keine eindeutig aktuell gültige Angebotswoche"):
        _select_current_aldi_week_offers(rows, today=date(2026, 9, 12))


def test_chain_parser_allows_generic_filial_selector_but_requires_explicit_week():
    text = """
    Filialauswahl
    Wähle deine Filiale aus, um die verfügbaren Produkte zu entdecken.
    Wochenangebote Mo., 14.9. – Sa., 19.9.
    GUT BIO Apfelsaft
    1 l
    1,49 €
    """

    rows = parse_aldi_stationary_chain_offers(_source(), text)

    assert len(rows) == 1
    row = rows[0]
    assert row.product_name == "GUT BIO Apfelsaft"
    assert row.price == 1.49
    assert row.valid_from == "14.09.2026"
    assert row.valid_to == "19.09.2026"


def test_chain_parser_rejects_undated_action_rows():
    text = """
    Angebote ab Montag
    GUT BIO Apfelsaft
    1 l
    1,49 €
    """

    assert parse_aldi_stationary_chain_offers(_source(), text) == []


def test_both_target_stores_use_same_stationary_chain_scope():
    text = """
    Wochenangebote Mo., 14.9. – Sa., 19.9.
    NATUR LIEBLINGE Karotten
    1 kg
    1,11 €
    """

    dierdorf = parse_aldi_stationary_chain_offers(_source("ALDI SÜD Dierdorf"), text)
    oberhonnefeld = parse_aldi_stationary_chain_offers(
        _source("ALDI SÜD Oberhonnefeld-Gierend"), text
    )

    assert [(r.product_name, r.price, r.valid_from, r.valid_to) for r in dierdorf] == [
        (r.product_name, r.price, r.valid_from, r.valid_to) for r in oberhonnefeld
    ]


def test_aldi_hardening_rejects_deposit_selected_card_bleed():
    row = CollectedOffer(
        "aldi-test",
        "ALDI SÜD Dierdorf",
        "ALDI SÜD",
        "Vegan FARMER NATURALS",
        "Sonstiges",
        0.25,
        quantity=200,
        unit="g",
        valid_from="07.09.2026",
        valid_to="13.09.2026",
        source_text=(
            "Vegan FARMER NATURALS 200 g 1,69 € + 0,25 € Pfand EINWEG "
            "Walnusskerne 200 g 0,2 kg (9,95 €/1 kg) Spare 33 % 1,99 € 2,99 €"
        ),
    )

    assert _harden_aldi_row(row, []) is None


def test_aldi_hardening_recovers_specific_title_price_regular_and_image():
    row = CollectedOffer(
        "aldi-test",
        "ALDI SÜD Dierdorf",
        "ALDI SÜD",
        "Kühlung BBQ",
        "Sonstiges",
        3.99,
        quantity=400,
        unit="g",
        valid_from="07.09.2026",
        valid_to="13.09.2026",
        source_text=(
            "Kühlung BBQ Rinder-Cevapcici 400 g 0,4 kg (9,98 €/1 kg) "
            "Spare 24 % 3,99 € 5,29 €"
        ),
    )
    imgs = [{"url": "https://img.example/rinder.jpg", "alt": "Rinder-Cevapcici 400 g"}]

    hardened = _harden_aldi_row(row, imgs)

    assert hardened is not None
    assert hardened.product_name == "Rinder-Cevapcici 400 g"
    assert hardened.price == 3.99
    assert hardened.regular_price == 5.29
    assert hardened.unit_price == 9.98
    assert hardened.unit_price_unit == "kg"
    assert hardened.image_url == "https://img.example/rinder.jpg"


def test_web_collector_routes_aldi_to_dedicated_collector(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    store = Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="test",
        active=True,
        benchmark_verified=False,
    )
    db.add(store)
    db.commit()

    called = {}

    def fake_collect(session, target, *, benchmark_context):
        called["store_id"] = target.id
        called["context"] = benchmark_context
        return "result", "summary", "run"

    monkeypatch.setattr(web_collector, "collect_aldi_web_for_store", fake_collect)

    result = web_collector.collect_store_from_web(db, store.name)

    assert result == ("result", "summary", "run")
    assert called["store_id"] == store.id
