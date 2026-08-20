from types import SimpleNamespace

from app.engine_v140.lidl_schwarz_runtime import schwarz_manifest_offers


def _source():
    return SimpleNamespace(
        key="lidl_puderbach",
        store_name="Lidl Puderbach",
        retailer="Lidl",
        url="https://www.lidl.de/l/prospekte/example/view/flyer/page/1",
    )


def test_schwarz_flyer_shop_product_is_emitted_only_for_online_rejection_accounting():
    payloads = [{
        "url": "https://endpoints.leaflets.schwarz/v4/flyer",
        "page_hint": 1,
        "data": {
            "flyer": {
                "pages": [
                    {
                        "links": [
                            {
                                "title": "Milbona Joghurt",
                                "productDetails": {"productId": "471100", "title": "Milbona Joghurt"},
                            }
                        ],
                        "altText": "Milbona Joghurt im Lidl Aktionsprospekt",
                        "keyWords": "Milbona,Joghurt",
                    },
                    {"links": [], "altText": "Werbung", "keyWords": ""},
                ],
                "products": {
                    "uuid-a": {
                        "productId": "471100",
                        "title": "Joghurt Natur 500 g",
                        "brand": "Milbona",
                        "price": "0.99",
                        "canonicalUrl": "/p/milbona-joghurt/p471100",
                    }
                },
            }
        },
    }]

    rows = schwarz_manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    joined = [row for row in rows if row.price == 0.99]
    assert len(joined) == 1
    assert joined[0].local_store_offer is False
    assert "PDF Seite 1" in joined[0].source_text
    assert "Milbona" in joined[0].product_name


def test_schwarz_flyer_marks_page_level_online_only_products_non_local():
    payloads = [{
        "url": "https://endpoints.leaflets.schwarz/v4/flyer",
        "page_hint": 8,
        "data": {
            "flyer": {
                "pages": [
                    {"links": [], "altText": "Lokale Angebote", "keyWords": ""},
                    {"links": [], "altText": "Werbung", "keyWords": ""},
                    {"links": [], "altText": "Werbung", "keyWords": ""},
                    {"links": [], "altText": "Werbung", "keyWords": ""},
                    {"links": [], "altText": "Werbung", "keyWords": ""},
                    {"links": [], "altText": "Werbung", "keyWords": ""},
                    {"links": [], "altText": "Werbung", "keyWords": ""},
                    {
                        "links": [
                            {"productDetails": {"productId": "100409109", "title": "Küchenmaschine"}}
                        ],
                        "altText": "Shoppe auf lidl.de. Nur online. SILVERCREST Küchenmaschine 49.99",
                        "keyWords": "Onlineshop",
                    },
                ],
                "products": {
                    "uuid-b": {
                        "productId": "100409109",
                        "title": "Küchenmaschine",
                        "brand": "SILVERCREST",
                        "price": "49.99",
                    }
                },
            }
        },
    }]

    rows = schwarz_manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    online = [row for row in rows if row.price == 49.99]
    assert len(online) == 1
    assert online[0].local_store_offer is False


def test_schwarz_flyer_does_not_emit_unreferenced_global_catalog_product():
    payloads = [{
        "url": "https://endpoints.leaflets.schwarz/v4/flyer",
        "page_hint": 1,
        "data": {
            "flyer": {
                "pages": [{"links": [], "altText": "Lokale Angebotsseite", "keyWords": ""}],
                "products": {
                    "uuid-c": {
                        "productId": "999999",
                        "title": "Nur globaler Katalogartikel",
                        "price": "12.99",
                    }
                },
            }
        },
    }]

    rows = schwarz_manifest_offers(payloads, _source(), valid_from="17.08.2026", valid_to="22.08.2026")
    assert all(row.price != 12.99 for row in rows)
