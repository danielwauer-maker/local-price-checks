from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from app.engine_v140.lidl_pdf import extract_lidl_pdf_offers
from app.engine_v140.lidl_semantics import LidlSourceKind, classify_lidl_link
from app.extractor_adapter import assess_collected_offer


FIXTURE = Path(__file__).parent / "fixtures" / "lidl_kw34_pdf_manifest_excerpt.json"


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


def test_real_pdf_excerpt_extracts_local_food_and_rejects_shop_regions(tmp_path):
    pdf_path = tmp_path / "lidl-page-1.pdf"
    fixture = _render_excerpt(pdf_path)
    flyer = {"pages": [{"links": fixture["links"]}]}

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
    assert any("livarno" in name for name in rejected)
    assert any("parkside" in name for name in rejected)
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


def test_shop_hotspot_is_rejected_online_not_as_quality():
    link = {
        "url": "https://www.lidl.de/p/livarno-bettwaesche/p100409050?flyx_content=p-100409050",
        "productDetails": {"productId": "100409050"},
    }
    assert classify_lidl_link(link) is LidlSourceKind.SHOP_ONLINE

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
    assert classify_lidl_link(link) is LidlSourceKind.NAVIGATION_RECIPE
