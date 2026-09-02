from app.models import Store
from app.physical_market_identity import alias_groups, canonical_store_map, collapse_physical_stores


def _store(
    row_id,
    name,
    address,
    *,
    city="Dierdorf",
    postal_code="56269",
    external_id=None,
    verified=False,
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
    )


def test_same_physical_rewe_address_collapses_even_with_different_names():
    generic = _store(1, "REWE Dierdorf", "Königsberger Str. 20-22")
    official = _store(
        2,
        "REWE:XL Hundertmark",
        "Königsberger Straße 20 - 22",
        external_id="321019",
        verified=True,
    )

    collapsed = collapse_physical_stores([generic, official])

    assert [row.id for row in collapsed] == [2]
    aliases = canonical_store_map([generic, official])
    assert aliases[1].id == 2
    assert aliases[2].id == 2


def test_strassenhaus_wrong_map_address_is_quarantined_next_to_one_official_identity():
    # Production failure mode: the OSM/map row points to Raiffeisenstraße while
    # the real REWE Dennis Weirich carries retailer id 1940425 at Kirschbüchel 2.
    map_alias = _store(
        16,
        "REWE (2)",
        "Raiffeisenstraße",
        city="Straßenhaus",
        postal_code="56587",
        external_id="way/92219239",
        source_url="http://www.rewe.de",
    )
    official = _store(
        15,
        "REWE Dennis Weirich",
        "Kirschbüchel 2",
        city="Straßenhaus",
        postal_code="56587",
        external_id="1940425",
        source_url=None,
    )

    collapsed = collapse_physical_stores([map_alias, official])
    assert [row.id for row in collapsed] == [15]

    mapping = canonical_store_map([map_alias, official])
    assert mapping[16].id == 15
    groups = alias_groups([map_alias, official])
    assert len(groups) == 1
    assert groups[0].canonical.id == 15
    assert [row.id for row in groups[0].aliases] == [16]
    assert "OSM/Map-Alias" in groups[0].reason


def test_two_rewe_branches_at_different_addresses_with_official_ids_remain_separate():
    bahnhof = _store(
        5,
        "PETZ REWE Bahnhofstr. 30",
        "Bahnhofstr. 30",
        city="Altenkirchen",
        postal_code="57610",
        external_id="8534500",
        verified=True,
    )
    dammweg = _store(
        6,
        "PETZ REWE Dammweg 10",
        "Dammweg 10",
        city="Altenkirchen",
        postal_code="57610",
        external_id="2500021",
        verified=True,
    )

    assert {row.id for row in collapse_physical_stores([bahnhof, dammweg])} == {5, 6}


def test_second_osm_candidate_is_not_hidden_when_two_official_branches_exist():
    official_a = _store(
        5,
        "PETZ REWE Bahnhofstr. 30",
        "Bahnhofstr. 30",
        city="Altenkirchen",
        postal_code="57610",
        external_id="8534500",
    )
    official_b = _store(
        6,
        "PETZ REWE Dammweg 10",
        "Dammweg 10",
        city="Altenkirchen",
        postal_code="57610",
        external_id="2500021",
    )
    uncertain = _store(
        7,
        "REWE map candidate",
        "Unklare Straße 1",
        city="Altenkirchen",
        postal_code="57610",
        external_id="way/999",
    )

    # With multiple strong identities the postcode alone is insufficient. The
    # uncertain row stays visible for manual identity review instead of being
    # assigned to an arbitrary branch.
    assert {row.id for row in collapse_physical_stores([official_a, official_b, uncertain])} == {5, 6, 7}
