from app.models import Store
from app.physical_market_identity import canonical_store_map, collapse_physical_stores


def _store(row_id, name, address, *, city="Dierdorf", postal_code="56269", external_id=None, verified=False):
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
        source_url="https://www.rewe.de/marktseite/test/",
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


def test_same_physical_strassenhaus_aliases_collapse():
    generic = _store(
        3,
        "REWE Straßenhaus",
        "Kirschbüchel 2",
        city="Straßenhaus",
        postal_code="56587",
    )
    official = _store(
        4,
        "REWE Dennis Weirich",
        "Kirschbüchel 2",
        city="Straßenhaus",
        postal_code="56587",
        external_id="1940425",
        verified=True,
    )

    assert [row.id for row in collapse_physical_stores([generic, official])] == [4]


def test_two_rewe_branches_at_different_addresses_remain_separate():
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
