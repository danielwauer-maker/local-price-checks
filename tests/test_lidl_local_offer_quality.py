from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.engine_v140.lidl_pdf import _exact_image_identity, extract_lidl_pdf_offers
from app.engine_v140.lidl_flipbook import _reconcile_manifest_with_pdf
from app.engine_v140.lidl_semantics import LidlSourceKind, classify_lidl_link
from app.engine_v140.lidl_schwarz_runtime import schwarz_manifest_offers
from app.extractor_adapter import assess_collected_offer, import_collected_offers
from app.models import MasterProduct, Store
from app.models import Offer, OfferOccurrence
from app.prospect_models import OfferProvenance, ProspectArchive


FIXTURE = Path(__file__).parent / "fixtures" / "lidl_kw34_pdf_manifest_excerpt.json"
SPATIAL_FIXTURE = Path(__file__).parent / "fixtures" / "lidl_kw34_pages_3_12_spatial.json"


def _source():
    return SimpleNamespace(
        key="lidl_puderbach",
        store_name="Lidl Puderbach",
        retailer="Lidl",
        url="https://www.lidl.de/l/prospekte/aktionsprospekt/ar/0",
    )


def _render_excerpt(target: Path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document = pymupdf.open()
    page = document.new_page(width=fixture["page_width"], height=fixture["page_height"])
    for block in fixture["blocks"]:
        rect = pymupdf.Rect(*block["bbox"])
        page.insert_textbox(rect, block["text"], fontsize=5.5, fontname="helv")
    document.save(target)
    document.close()
    return fixture


def _insert_fixture_text(page, bbox, text, *, bold=False, size=8):
    rect = pymupdf.Rect(*bbox)
    if bold:
        for index, line in enumerate(text.splitlines()):
            page.insert_text(
                pymupdf.Point(rect.x0, rect.y0 + size + index * (size + 1)),
                line,
                fontsize=size,
                fontname="hebo",
            )
    else:
        page.insert_textbox(rect, text, fontsize=size, fontname="helv", lineheight=1.0)


def _render_spatial_fixture(target: Path):
    fixture = json.loads(SPATIAL_FIXTURE.read_text(encoding="utf-8"))
    document = pymupdf.open()
    for _ in range(12):
        document.new_page(width=fixture["page_width"], height=fixture["page_height"])
    for frozen_page in fixture["pages"]:
        page = document[frozen_page["logical_page"] - 1]
        for offer in frozen_page["offers"]:
            _insert_fixture_text(page, offer["title_bbox"], offer["title"], bold=True, size=8)
            _insert_fixture_text(page, offer["details_bbox"], offer["details"], size=5)
            if offer.get("plus_label"):
                _insert_fixture_text(page, offer["plus_label_bbox"], offer["plus_label"], bold=True, size=5)
            _insert_fixture_text(page, offer["price_bbox"], offer["price"], size=6)
            if offer.get("app_price"):
                _insert_fixture_text(page, offer["app_price_bbox"], offer["app_price"], size=6)
    document.save(target)
    document.close()
    return fixture


def test_real_pdf_excerpt_extracts_local_food_and_rejects_shop_regions(tmp_path):
    pdf_path = tmp_path / "lidl-page-1.pdf"
    fixture = _render_excerpt(pdf_path)
    flyer = {"pages": [{"links": fixture["links"]}], "products": fixture["products"]}

    result = extract_lidl_pdf_offers(
        pdf_path,
        _source(),
        valid_from="17.08.2026",
        valid_to="22.08.2026",
        flyer=flyer,
        crop_dir=tmp_path / "crops",
    )

    local = {row.product_name.lower(): row for row in result.offers if row.local_store_offer}
    rejected = {row.product_name.lower(): row for row in result.offers if not row.local_store_offer}
    assert any("lavazza" in name for name in local)
    assert any("schwip schwap" in name for name in local)
    assert any("pom-bär" in name for name in local)
    assert any("kernlose trauben" in name for name in local)
    assert any("livarno" in name for name in local)
    assert any("parkside" in name for name in local)
    assert rejected == {}
    assert result.ocr_candidate_pages == set()

    lavazza = next(row for name, row in local.items() if "lavazza" in name)
    assert lavazza.price == 12.99
    assert lavazza.quantity == 1
    assert lavazza.unit == "kg"
    assert lavazza.unit_price == 12.99
    assert "PDF Seite 1" in lavazza.source_text
    assert Path(lavazza.image_path).is_file()

    funny = next(row for name, row in local.items() if "pom-bär" in name)
    assert funny.price == 1.79
    assert funny.app_price == 0.88
    assert funny.quantity == 75
    assert funny.unit_price == 11.73

    parkside = next(row for name, row in local.items() if "parkside" in name)
    assert parkside.lidl_availability == LidlSourceKind.LOCAL_AND_ONLINE.value
    assert parkside.image_url.endswith("parkside-isolated.jpg")
    assert parkside.image_media_source == "official_product"
    assert Path(parkside.audit_image_path).is_file()

    livarno = next(row for name, row in local.items() if "livarno" in name)
    assert livarno.lidl_availability == LidlSourceKind.LOCAL_AND_ONLINE.value
    assert not getattr(livarno, "image_url", None)  # Shop variant has a different price.
    assert Path(livarno.audit_image_path).is_file()

    manifest = schwarz_manifest_offers(
        [{"data": {"flyer": flyer}}],
        _source(),
        valid_from="17.08.2026",
        valid_to="22.08.2026",
    )
    remaining = _reconcile_manifest_with_pdf(result.offers, manifest)
    assert len(remaining) == 1
    assert remaining[0].product_name == "LIVARNO Online-Regal"
    assert remaining[0].lidl_availability == LidlSourceKind.ONLINE_ONLY.value
    assert assess_collected_offer(remaining[0]).rejection == "online"


def test_shop_hotspot_is_rejected_online_not_as_quality():
    link = {
        "url": "https://www.lidl.de/p/livarno-bettwaesche/p100409050?flyx_content=p-100409050",
        "productDetails": {"productId": "100409050"},
    }
    assert classify_lidl_link(link) is LidlSourceKind.ONLINE_ONLY

    row = SimpleNamespace(
        retailer="Lidl",
        source_text='PDF Seite 1: SchwarzShopHotspot {"productId":"100409050"}',
        source_url=_source().url,
        local_store_offer=False,
        product_name="LIVARNO Bettwäsche",
        price=14.99,
        quantity=None,
        unit=None,
        unit_price=None,
        unit_price_unit=None,
        confidence=.99,
    )
    assessment = assess_collected_offer(row)
    assert assessment.accepted is False
    assert assessment.rejection == "online"


def test_recipe_link_is_navigation_not_shop_product():
    link = {"url": "https://rezepte.lidl.de/alle-rezepte?q=Weintrauben", "title": "Link"}
    assert classify_lidl_link(link) is LidlSourceKind.NAVIGATION


def test_official_image_identity_rejects_wrong_livarno_variant():
    product = {
        "productId": "100408989",
        "title": "LIVARNO Musselin-Bettwäsche, 135 x 200 cm",
        "price": "14.99",
        "image": "https://www.lidl.de/assets/livarno.jpg",
    }
    assert _exact_image_identity("LIVARNO Musselin-Bettwäsche King Size", 14.99, product) is False


def test_frozen_page_one_imports_six_local_offers_and_rejects_manifest_only(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pdf_path = tmp_path / "lidl-page-1.pdf"
    _render_excerpt(pdf_path)
    flyer = {"pages": [{"links": fixture["links"]}], "products": fixture["products"]}
    extracted = extract_lidl_pdf_offers(
        pdf_path,
        _source(),
        valid_from="17.08.2026",
        valid_to="22.08.2026",
        flyer=flyer,
        crop_dir=tmp_path / "crops",
    )
    manifest = schwarz_manifest_offers(
        [{"data": {"flyer": flyer}}],
        _source(),
        valid_from="17.08.2026",
        valid_to="22.08.2026",
    )
    rows = [*extracted.offers, *_reconcile_manifest_with_pdf(extracted.offers, manifest)]

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    db.add(Store(
        retailer="Lidl",
        name="Lidl Puderbach",
        postal_code="57610",
        city="Puderbach",
        address="Teststraße 1",
        active=True,
    ))
    db.commit()

    summary = import_collected_offers(db, rows)
    names = {row[0].lower() for row in db.query(MasterProduct.name).all()}
    assert summary.received == 7
    assert summary.imported == 6
    assert summary.rejected_online == 1
    assert any("lavazza" in name for name in names)
    assert any("schwip schwap" in name for name in names)
    assert any("pom-bär" in name for name in names)
    assert any("kernlose trauben" in name for name in names)
    assert any("livarno" in name for name in names)
    assert any("parkside" in name for name in names)
    assert not any("online-regal" in name for name in names)


def test_frozen_real_pages_three_and_twelve_reach_complete_spatial_recall(tmp_path):
    pdf_path = tmp_path / "lidl-pages-3-12.pdf"
    _render_spatial_fixture(pdf_path)

    result = extract_lidl_pdf_offers(
        pdf_path,
        _source(),
        valid_from="17.08.2026",
        valid_to="22.08.2026",
    )
    by_page = {
        page: [row for row in result.offers if f"PDF Seite {page}:" in row.source_text]
        for page in (3, 12)
    }
    page_three = {row.product_name.lower(): row for row in by_page[3]}
    page_twelve = {row.product_name.lower(): row for row in by_page[12]}

    assert len(page_three) == 9
    assert len(page_twelve) == 5
    for expected in (
        "galiamelone", "bio mini", "rote zwiebeln", "salat-mix",
        "zuckermais", "phalaenopsis", "lilien", "heidekraut", "rosen-duo",
    ):
        assert any(expected in name for name in page_three)
    for expected in ("granini", "arla", "alesto", "lenor", "pepsi"):
        assert any(expected in name for name in page_twelve)

    salad = next(row for name, row in page_three.items() if "salat-mix" in name)
    onions = next(row for name, row in page_three.items() if "rote zwiebeln" in name)
    lilies = next(row for name, row in page_three.items() if "lilien" in name)
    alesto = next(row for name, row in page_twelve.items() if "alesto" in name)
    assert (salad.price, salad.app_price) == (0.99, 0.79)
    assert onions.unit_price == 1.19
    assert (lilies.price, lilies.app_price) == (7.99, 6.99)
    assert (alesto.price, alesto.app_price) == (2.99, 1.99)
    assert result.price_anchors_detected == 14
    assert result.price_anchors_matched == 14
    assert result.price_anchors_ignored == 0
    assert result.price_anchors_unmatched == 0
    assert result.page_offer_recall == 100.0
    assert result.pages_with_unmatched_prices == ()


def test_repeated_lidl_pdf_offer_keeps_one_offer_with_two_page_occurrences(tmp_path):
    pdf_path = tmp_path / "lidl-repeated-grapes.pdf"
    document = pymupdf.open()
    for _ in range(2):
        page = document.new_page(width=459.2, height=793.7)
        _insert_fixture_text(page, [20, 100, 160, 126], "Helle kernlose Trauben", bold=True, size=8)
        _insert_fixture_text(page, [20, 128, 150, 175], "Ursprung: Spanien\nJe 500 g\n1 kg = 2.50", size=5)
        _insert_fixture_text(page, [170, 120, 250, 170], "500 g\n1.25*", size=6)
    document.save(pdf_path)
    document.close()
    extracted = extract_lidl_pdf_offers(
        pdf_path,
        _source(),
        valid_from="17.08.2026",
        valid_to="22.08.2026",
    )

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    store = Store(
        retailer="Lidl", name="Lidl Puderbach", postal_code="57610", city="Puderbach",
        address="Teststraße 1", active=True,
    )
    db.add(store)
    db.flush()
    db.add(ProspectArchive(
        store_id=store.id,
        source_url=_source().url,
        pdf_url=_source().url,
        retailer="Lidl",
        period_key="current",
        valid_from=date(2026, 8, 17),
        valid_to=date(2026, 8, 22),
        fetched_at=datetime(2026, 8, 20),
        pdf_sha256="f" * 64,
        pdf_bytes=pdf_path.read_bytes(),
        page_count=2,
        local_path=str(pdf_path),
    ))
    db.commit()

    summary = import_collected_offers(db, extracted.offers)
    assert summary.imported == 2
    assert db.query(Offer).count() == 1
    assert [row.prospect_page for row in db.query(OfferOccurrence).order_by(OfferOccurrence.prospect_page)] == [1, 2]
    assert [row.prospect_page for row in db.query(OfferProvenance).order_by(OfferProvenance.prospect_page)] == [1, 2]
