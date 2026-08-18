from app.engine_v140.lidl_manifest import manifest_offers
from app.engine_v140.source_registry import RetailSource


def _source():
    return RetailSource(
        key="lidl_puderbach",
        retailer="Lidl",
        store_name="Lidl Puderbach",
        url="https://www.lidl.de/l/prospekte/current/ar/0",
        mode="leaflet_viewer",
        locality="store_specific",
        notes="test",
        supports_products=True,
        store_specific=True,
    )


def _rows(payloads):
    return manifest_offers(
        payloads,
        _source(),
        valid_from="17.08.2026",
        valid_to="22.08.2026",
    )


def test_global_online_catalogue_is_not_an_offer_source_by_itself():
    payloads = [{
        "url": "https://www.lidl.de/api/products",
        "page_hint": 8,
        "data": {
            "products": [{
                "productId": "100409109",
                "title": "SILVERCREST Küchenmaschine",
                "price": "49.99",
                "canonicalUrl": "https://www.lidl.de/p/silvercrest-kuechenmaschine/p100409109",
            }]
        },
    }]
    assert _rows(payloads) == []


def test_split_local_hotspot_fields_are_joined_on_page_one():
    payloads = [{
        "url": "https://viewer.example/manifest",
        "page_hint": 1,
        "data": {
            "pages": [{
                "pageNumber": 1,
                "hotspots": [{
                    "type": "offer",
                    "content": {
                        "brandName": "Milbona",
                        "productName": "Deutsche Markenbutter",
                        "packageSize": "250 g",
                    },
                    "pricing": {
                        "offerPrice": "1.99",
                        "regularPrice": "2.49",
                    },
                }],
            }]
        },
    }]
    rows = _rows(payloads)
    assert len(rows) == 1
    assert "Milbona" in rows[0].product_name
    assert "Markenbutter" in rows[0].product_name
    assert rows[0].price == 1.99
    assert rows[0].regular_price == 2.49
    assert rows[0].source_text.startswith("PDF Seite 1: ManifestHotspot")
    assert rows[0].local_store_offer is True


def test_page_hotspot_id_may_enrich_from_catalogue_but_page_is_authority():
    payloads = [
        {
            "url": "https://viewer.example/products",
            "page_hint": 8,
            "data": {
                "products": [{
                    "productId": "900001",
                    "title": "Milbona Joghurt",
                    "price": "0.99",
                    "regularPrice": "1.29",
                    "canonicalUrl": "https://www.lidl.de/p/milbona-joghurt/p900001",
                }]
            },
        },
        {
            "url": "https://viewer.example/hotspots",
            "page_hint": 1,
            "data": {
                "pages": [
                    {"pageNumber": 1, "hotspots": [{"type": "offer", "productId": "900001"}]},
                ]
            },
        },
    ]
    rows = _rows(payloads)
    assert len(rows) == 1
    assert rows[0].product_name == "Milbona Joghurt"
    assert rows[0].price == 0.99
    assert rows[0].source_text.startswith("PDF Seite 1: ManifestHotspot+Catalog")


def test_online_only_marker_on_hotspot_keeps_offer_out_of_local_scope():
    payloads = [{
        "url": "https://viewer.example/manifest",
        "data": {
            "pages": [{
                "pageNumber": 8,
                "hotspots": [{
                    "type": "offer",
                    "label": "Nur online",
                    "product": {
                        "productName": "SILVERCREST Reiskocher",
                        "offerPrice": "19.99",
                    },
                }],
            }]
        },
        "page_hint": 8,
    }]
    rows = _rows(payloads)
    assert len(rows) == 1
    assert rows[0].local_store_offer is False
    assert rows[0].source_text.startswith("PDF Seite 8: ManifestHotspot")
