from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.aldi_live_collector import (
    _harden_aldi_row,
    is_official_aldi_offer_url,
    parse_aldi_stationary_chain_offers,
)
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


def test_official_aldi_offer_url_is_strict():
    assert is_official_aldi_offer_url("https://www.aldi-sued.de/angebote")
    assert is_official_aldi_offer_url("https://www.aldi-sued.de/tools/features/angebote")
    assert not is_official_aldi_offer_url("https://www.aldi-sued.de/filialen")
    assert not is_official_aldi_offer_url("https://example.org/angebote")
    assert not is_official_aldi_offer_url("http://www.aldi-sued.de/angebote")


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
