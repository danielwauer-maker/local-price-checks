from app.models import Store
from app.physical_market_identity import canonical_store_map, collapse_physical_stores


def _store(
    row_id,
    name,
    address,
    *,
    city="Dierdorf",
    postal_code="56269",
    external_id=None,
    verified=False,
    lat=None,
    lng=None,
    source_url="https://www.rewe.de/marktseite/test/",
):
    return Store(
        id=row_id,
        retailer="REWE",
        name=name,
        address=address,
        postal_code=postal_code,
        city=city,
        active=True,
        benchmark_verified=verified,
        external_id=external_id,
        source_url=source_url,
        latitude=lat,
        longitude=lng,
    )


def test_same_physical_rewe_address_collapses_even_with_different_names():
    generic = _store(1, "REWE Dierdorf", "Königsberger Str. 20-22")
    official = _store(2, "REWE:XL Hundertmark", "Königsberger Straße 20 - 22", external_id="321019", verified=True)
    collapsed = collapse_physical_stores([generic, official])
    assert [row.id for row in collapsed] == [2]
    aliases = canonical_store_map([generic, official])
    assert aliases[1].id == 2
    assert aliases[2].id == 2


def test_strassenhaus_bad_osm_address_collapses_by_nearby_pin():
    osm_alias = _store(
        16,
        "REWE (2)",
        "Raiffeisenstraße",
        city="Straßenhaus",
        postal_code="56587",
        external_id="way/92219239",
        lat=50.541989,
        lng=7.519881,
        source_url="http://www.rewe.de",
    )
    official = _store(
        15,
        "REWE Dennis Weirich",
        "Kirschbüchel 2",
        city="Straßenhaus",
        postal_code="56587",
        external_id="1940425",
        lat=50.54205,
        lng=7.51990,
        source_url="https://www.rewe.de/marktseite/strassenhaus/1940425/",
    )
    collapsed = collapse_physical_stores([osm_alias, official])
    assert [row.id for row in collapsed] == [15]
    assert canonical_store_map([osm_alias, official])[16].id == 15


def test_two_official_ids_never_collapse_only_because_they_are_close():
    first = _store(
        5,
        "PETZ REWE Bahnhofstr. 30",
        "Bahnhofstr. 30",
        city="Altenkirchen",
        postal_code="57610",
        external_id="8534500",
        verified=True,
        lat=50.6850,
        lng=7.6450,
    )
    second = _store(
        6,
        "PETZ REWE Dammweg 10",
        "Dammweg 10",
        city="Altenkirchen",
        postal_code="57610",
        external_id="2500021",
        verified=True,
        lat=50.6855,
        lng=7.6455,
    )
    assert {row.id for row in collapse_physical_stores([first, second])} == {5, 6}


def test_two_rewe_branches_at_different_addresses_remain_separate():
    bahnhof = _store(5, "PETZ REWE Bahnhofstr. 30", "Bahnhofstr. 30", city="Altenkirchen", postal_code="57610", external_id="8534500", verified=True)
    dammweg = _store(6, "PETZ REWE Dammweg 10", "Dammweg 10", city="Altenkirchen", postal_code="57610", external_id="2500021", verified=True)
    assert {row.id for row in collapse_physical_stores([bahnhof, dammweg])} == {5, 6}
