from app.engine_v140.lidl_manifest_debug import _payload_record, _safe_url


def test_lidl_debug_strips_query_and_fragment_from_urls():
    value = _safe_url("https://viewer.example/api/manifest?token=secret&store=123#page=4")
    assert value == "https://viewer.example/api/manifest"


def test_lidl_debug_keeps_relevant_structure_and_samples():
    payload = {
        "publication": {
            "pages": [
                {
                    "pageNumber": 1,
                    "products": [
                        {
                            "productId": "4711",
                            "productName": "Milbona Joghurt",
                            "offerPrice": "0.99",
                            "regularPrice": "1.29",
                        }
                    ],
                }
            ]
        }
    }
    row = _payload_record("https://viewer.example/api/manifest?token=secret", payload, 1)
    assert row["url"] == "https://viewer.example/api/manifest"
    assert row["page_hint"] == 1
    assert row["size_bytes"] > 0
    paths = {entry["path"] for entry in row["structure"]}
    assert "$.publication.pages" in paths
    assert "$.publication.pages[0]" in paths
    assert "$.publication.pages[0].products" in paths
    product = next(entry for entry in row["structure"] if entry["path"] == "$.publication.pages[0].products[0]")
    assert product["samples"]["productId"] == "4711"
    assert product["samples"]["productName"] == "Milbona Joghurt"
    assert product["samples"]["offerPrice"] == "0.99"
