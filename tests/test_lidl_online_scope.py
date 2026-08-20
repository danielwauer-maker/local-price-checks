from types import SimpleNamespace

from app.extractor_adapter import _row_is_local_offer


def _row(source_text: str, *, local_store_offer: bool = False):
    return SimpleNamespace(
        retailer="Lidl",
        source_text=source_text,
        source_url="https://www.lidl.de/l/prospekte/current/ar/0",
        local_store_offer=local_store_offer,
    )


def test_lidl_product_id_and_shop_url_are_strong_online_signals():
    row = _row(
        'PDF Seite 2: Manifest {"productId":"100409050",'
        '"title":"Milbona Joghurt",'
        '"url":"https://www.lidl.de/p/milbona-joghurt/p100409050",'
        '"price":"0.99"}'
    )
    assert _row_is_local_offer(row) is False


def test_lidl_explicit_online_only_boolean_is_rejected():
    row = _row(
        'PDF Seite 8: Manifest {"productId":"100409050",'
        '"title":"Silvercrest Küchenmaschine",'
        '"onlineOnly":true,"price":"49.99"}'
    )
    assert _row_is_local_offer(row) is False


def test_lidl_nur_online_label_is_rejected():
    row = _row(
        'PDF Seite 8: Manifest {"title":"Silvercrest Reiskocher",'
        '"label":"Nur online","price":"19.99"}'
    )
    assert _row_is_local_offer(row) is False
