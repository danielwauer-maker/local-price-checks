from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.engine_v140.collectors import CollectedOffer
from app.extractor_adapter import import_collected_offers
from app.models import Offer, OfferOccurrence, Store
from app.offer_text import parse_offer_text


def test_rewe_detail_line_extracts_package_and_unit_price():
    details = parse_offer_text("je 400-g-Becher, (1 kg = 4,73 €)")
    assert details.package_label == "400 g"
    assert details.quantity == 400.0
    assert details.unit == "g"
    assert details.unit_price == 4.73
    assert details.unit_price_unit == "kg"
    assert details.detail_text == "je 400-g-Becher, (1 kg = 4,73 €)"


def test_rewe_detail_line_extracts_liquid_package_and_unit_price():
    details = parse_offer_text("versch. Sorten, je 750-ml-Fl., (1 l = 4,65 €)")
    assert details.package_label == "750 ml"
    assert details.quantity == 750.0
    assert details.unit == "ml"
    assert details.unit_price == 4.65
    assert details.unit_price_unit == "l"


def test_repeated_prospect_item_keeps_two_occurrences_but_one_offer():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(Store(
        name="REWE:XL Hundertmark",
        retailer="REWE",
        postal_code="56269",
        city="Dierdorf",
        address="Königsberger Str. 20-22",
        active=True,
        source_url="https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
        external_id="321019",
    ))
    db.commit()

    common = dict(
        source_key="rewe_hundertmark",
        store_name="REWE:XL Hundertmark",
        retailer="REWE",
        product_name="Popp Kartoffel- oder Coleslaw-Salat",
        category="Kühlung",
        price=1.89,
        valid_from="17.08.2026",
        valid_to="22.08.2026",
        source_url="https://www.rewe.de/angebote/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
        local_store_offer=True,
        confidence=.99,
    )
    rows = [
        CollectedOffer(**common, source_text="PDF Seite 3: je 400-g-Becher, (1 kg = 4,73 €)"),
        CollectedOffer(**common, source_text="PDF Seite 11: je 400-g-Becher, (1 kg = 4,73 €)"),
    ]

    summary = import_collected_offers(db, rows)
    assert summary.imported == 2
    assert db.query(Offer).count() == 1
    occurrences = db.query(OfferOccurrence).order_by(OfferOccurrence.prospect_page).all()
    assert [row.prospect_page for row in occurrences] == [3, 11]
    assert all(row.package_size == "400 g" for row in occurrences)
    assert all(row.unit_price == 4.73 for row in occurrences)
    offer = db.query(Offer).one()
    assert offer.unit_price == 4.73
    assert offer.unit_price_unit == "kg"
    assert offer.product.package_size == "400 g"
