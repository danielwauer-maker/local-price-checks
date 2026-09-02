from app.models import Store
from app.physical_market_identity import (
    alias_groups,
    canonical_store_map,
    collapse_physical_stores,
    has_strong_retailer_identity,
    is_weak_discovery_store,
)


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
    assert has_strong_retailer_identity(official) is True
    assert is_weak_discovery_store(osm_alias) is True
    assert "naher OSM/Map-Alias" in alias_groups([osm_alias, official])[0].reason


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


def test_close_rows_without_clear_strong_weak_evidence_remain_separate():
    first = _store(
        20, "REWE Test 1", "Testweg 1", source_url=None,
        lat=50.6200, lng=7.6300,
    )
    second = _store(
        21, "REWE Test 2", "Testweg 2", source_url=None,
        lat=50.6210, lng=7.6310,
    )

    assert {row.id for row in collapse_physical_stores([first, second])} == {20, 21}


def test_close_weak_rows_never_collapse_by_proximity_alone():
    first = _store(
        22, "REWE Map 1", "Testweg 1", external_id="node/101",
        source_url=None, lat=50.6200, lng=7.6300,
    )
    second = _store(
        23, "REWE Map 2", "Testweg 2", external_id="way/202",
        source_url=None, lat=50.6210, lng=7.6310,
    )

    assert {row.id for row in collapse_physical_stores([first, second])} == {22, 23}


def test_different_official_ids_override_an_exact_address_match():
    first = _store(24, "REWE A", "Gemeinsame Straße 1", external_id="official-a")
    second = _store(25, "REWE B", "Gemeinsame Str. 1", external_id="official-b")

    assert {row.id for row in collapse_physical_stores([first, second])} == {24, 25}


def test_same_official_id_collapses_even_when_addresses_differ():
    first = _store(26, "REWE Import A", "Alte Straße 1", external_id="same-id")
    second = _store(27, "REWE Import B", "Neue Straße 9", external_id="same-id")

    assert len(collapse_physical_stores([first, second])) == 1


def test_weak_alias_cannot_transitively_bridge_two_strong_official_stores():
    first = _store(
        30, "REWE Official A", "A-Straße 1", external_id="official-a",
        lat=50.6200, lng=7.6300,
    )
    weak = _store(
        31, "REWE Map", "Falsche Straße", external_id="node/303",
        source_url=None, lat=50.6200, lng=7.6310,
    )
    second = _store(
        32, "REWE Official B", "B-Straße 2", external_id="official-b",
        lat=50.6200, lng=7.6320,
    )

    mapping = canonical_store_map([first, weak, second])

    assert mapping[30].id == 30
    assert mapping[32].id == 32
    assert mapping[31].id == 31
    assert {row.id for row in collapse_physical_stores([first, weak, second])} == {30, 31, 32}
