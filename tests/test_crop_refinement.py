from types import SimpleNamespace
from pathlib import Path

from PIL import Image

from app.engine_v140 import crop_refinement
from app.engine_v140.crop_refinement import refine_pdf_offer_crops


def _image(path: Path, size=(900, 1200)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, format="JPEG")


def test_edeka_crop_refinement_uses_price_anchor_and_shrinks_card(tmp_path, monkeypatch):
    monkeypatch.setattr(crop_refinement, "_crop_contains_product", lambda *_args, **_kwargs: True)
    source = tmp_path / "edeka-wide.jpg"
    _image(source)
    row = SimpleNamespace(
        retailer="EDEKA",
        product_name="Golden Toast Burger",
        price=2.22,
        audit_image_path=str(source),
        image_path=str(source),
        source_text=(
            "PDF Seite 13: EDEKA OCR bbox=(0,620,417,1370) "
            "price_bbox=(248,1100,392,1220) Golden Toast Burger"
        ),
    )

    changed = refine_pdf_offer_crops([row])

    assert changed == 1
    assert row.audit_image_path != str(source)
    assert row.image_path == row.audit_image_path
    assert row.crop_quality_rejected is False
    refined = Path(row.audit_image_path)
    assert refined.is_file()
    with Image.open(source) as original, Image.open(refined) as result:
        assert result.width < original.width
        assert result.height < original.height
        assert result.width >= 80
        assert result.height >= 80


def test_edeka_wrong_product_crop_is_suppressed(tmp_path, monkeypatch):
    monkeypatch.setattr(crop_refinement, "_crop_contains_product", lambda *_args, **_kwargs: False)
    source = tmp_path / "edeka-neighbour.jpg"
    _image(source)
    row = SimpleNamespace(
        retailer="EDEKA",
        product_name="Golden Toast Burger",
        price=2.22,
        audit_image_path=str(source),
        image_path=str(source),
        source_text="PDF Seite 13: EDEKA OCR bbox=(0,620,417,1370) price_bbox=(248,1100,392,1220)",
    )

    assert refine_pdf_offer_crops([row]) == 1
    assert row.crop_quality_rejected is True
    assert row.audit_image_path is None
    assert row.image_path is None


def test_lidl_crop_refinement_removes_outer_neighbourhood(tmp_path):
    source = tmp_path / "lidl-wide.jpg"
    _image(source, size=(1000, 800))
    row = SimpleNamespace(
        retailer="Lidl",
        product_name="Dr. Oetker Ristorante Pizza",
        price=3.79,
        audit_image_path=str(source),
        image_path=str(source),
        source_text="PDF Seite 13: LidlPdfText:LOCAL_ONLY",
    )

    changed = refine_pdf_offer_crops([row])

    assert changed == 1
    assert row.crop_quality_rejected is False
    with Image.open(row.audit_image_path) as result:
        assert result.size == (720, 576)


def test_rewe_crop_is_not_modified(tmp_path):
    source = tmp_path / "rewe.jpg"
    _image(source)
    row = SimpleNamespace(
        retailer="REWE",
        product_name="Test",
        price=1.99,
        audit_image_path=str(source),
        image_path=str(source),
        source_text="",
    )

    assert refine_pdf_offer_crops([row]) == 0
    assert row.audit_image_path == str(source)
