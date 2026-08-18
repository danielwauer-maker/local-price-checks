from app.engine_v140.lidl_ocr import is_online_shop_page, normalize_ocr_text
from app.product_detail_routes import product_family_key, variant_label


def test_lidl_ocr_recognises_explicit_online_shop_page():
    text = """
    Shoppe auf lidl.de
    SILVERCREST Küchenmaschine 49,99
    Weitere Artikel nur im Onlineshop
    """
    assert is_online_shop_page(text) is True


def test_lidl_ocr_keeps_normal_local_leaflet_page():
    text = """
    LAVAZZA Caffè Crema 12,99
    PEPSI 0,99
    Helle kernlose Trauben 1,25
    FUNNY-FRISCH Pom-Bär 0,88
    """
    assert is_online_shop_page(text) is False
    assert "Trauben" in normalize_ocr_text(text)


def test_bedding_sizes_share_one_display_family_but_keep_variant_labels():
    names = [
        "LIVARNO® Musselin-Bettwäsche, 155 x 220 cm",
        "LIVARNO® Musselin-Bettwäsche, 135 x 200 cm",
        "LIVARNO® Musselin-Bettwäsche, 200 x 220 cm",
    ]
    keys = {product_family_key(name) for name in names}
    assert len(keys) == 1
    assert variant_label(names[0]) == "155 x 220 cm"
    assert variant_label(names[1]) == "135 x 200 cm"
    assert variant_label(names[2]) == "200 x 220 cm"
