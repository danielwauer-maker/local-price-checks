from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app import model_registry  # noqa: F401
from app.beta_market_scope import BETA_RETAILERS, is_beta_retailer
from app.coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from app.db import Base, create_database_engine
from app.engine_v140.source_registry import source_for_store_record
from app.models import Store
from app.postcode_reconciliation import reconcile_postcode_coverage
from app.retailer_store_sources import stage_official_store_candidates


def _db():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _candidate(key: str, retailer: str, *, source: str = "osm", **overrides):
    values = dict(
        discovery_key=key,
        postal_code="99999",
        retailer=retailer,
        name=f"{retailer} Testmarkt",
        address="Marktweg 1",
        city="Testort",
        latitude=50.0,
        longitude=7.0,
        source=source,
    )
    values.update(overrides)
    return StoreDiscoveryCandidate(**values)


def _promoted_market(db, postcode: str, retailer: str, key: str):
    candidate = _candidate(
        key,
        retailer,
        postal_code=postcode,
        source=f"official:{retailer.lower()}",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
        status="promoted",
    )
    store = Store(
        retailer=retailer,
        name=f"{retailer} {postcode}",
        postal_code=postcode,
        city="Testort",
        address="Marktweg 1",
        latitude=50.0,
        longitude=7.0,
        active=True,
    )
    db.add_all([candidate, store])
    db.flush()
    candidate.matched_store_id = store.id
    return candidate, store


def test_beta_scope_is_central_and_does_not_reduce_discovery_support():
    assert BETA_RETAILERS == ("REWE", "EDEKA", "ALDI SÜD")
    assert all(is_beta_retailer(value) for value in BETA_RETAILERS)
    assert not is_beta_retailer("Lidl")


@pytest.mark.parametrize(
    ("postcode", "beta_retailer", "outside_retailer"),
    (("65618", "REWE", "PENNY"), ("56305", "EDEKA", "Lidl")),
)
def test_non_beta_market_remains_visible_but_does_not_block_complete(
    postcode, beta_retailer, outside_retailer
):
    db = _db()
    pc = CoveragePostalCode(postal_code=postcode, enabled=True)
    _promoted_market(db, postcode, beta_retailer, "beta")
    db.add(_candidate(
        "outside",
        outside_retailer,
        postal_code=postcode,
        address="Andere Straße 2",
        latitude=50.01,
    ))
    db.add(pc)
    db.commit()

    summary = reconcile_postcode_coverage(db, pc)
    assert (summary.expected, summary.found, summary.promoted) == (1, 1, 1)
    assert summary.outside_beta_found == 1
    assert summary.status == "complete"


@pytest.mark.parametrize(
    ("postcode", "retailers", "expected"),
    (
        ("57610", ("REWE", "REWE", "ALDI SÜD", "Netto Marken-Discount"), 3),
        ("56269", ("REWE", "ALDI SÜD", "Lidl", "Netto Marken-Discount"), 2),
    ),
)
def test_expected_and_found_count_only_official_beta_groups(postcode, retailers, expected):
    db = _db()
    pc = CoveragePostalCode(postal_code=postcode, enabled=True)
    db.add(pc)
    for index, retailer in enumerate(retailers):
        db.add(_candidate(
            f"{retailer}-{index}",
            retailer,
            postal_code=postcode,
            address=f"Marktweg {index + 1}",
            latitude=50.0 + index / 100,
            source=f"official:{retailer.lower()}",
            official_source_verified=True,
        ))
    db.commit()
    summary = reconcile_postcode_coverage(db, pc)
    assert (summary.expected, summary.found) == (expected, expected)
    assert summary.outside_beta_found == len(retailers) - expected


def test_expected_beta_targets_do_not_depend_on_successful_official_staging():
    db = _db()
    pc = CoveragePostalCode(postal_code="56587", city="Straßenhaus", enabled=True)
    db.add(pc)
    db.add(_candidate(
        "aldi-osm-56587",
        "ALDI SÜD",
        postal_code="56587",
        city="Oberhonnefeld-Gierend",
        address="Über dem Stellweg 5",
        latitude=50.5400,
        longitude=7.5100,
    ))
    db.commit()

    summary = reconcile_postcode_coverage(db, pc)

    # Curated beta inventory has REWE Dennis Weirich + ALDI SÜD here even if
    # the official candidate rows have not been staged yet.
    assert summary.expected == 2
    assert summary.found == 1
    assert summary.missing_expected == 1
    assert summary.status == "incomplete"


@pytest.mark.parametrize(
    ("postcode", "external_id", "address"),
    (
        ("56587", "1940425", "Kirschbüchel 2"),
        ("65606", "241184", "Brotweg 1"),
        ("65611", "240076", "In den Wallgärten 1"),
    ),
)
def test_official_rewe_candidates_are_staged_from_reviewed_market_pages(
    postcode, external_id, address
):
    db = _db()
    # Missing official pins are intentionally inherited from a unique existing
    # local identity row instead of being invented in curated source data.
    db.add(_candidate(
        f"existing-{postcode}",
        "REWE",
        postal_code=postcode,
        address=address,
        city="Straßenhaus" if postcode == "56587" else "Villmar" if postcode == "65606" else "Brechen",
    ))
    if postcode in {"56587", "65611"}:
        db.add(_candidate(
            f"existing-aldi-{postcode}",
            "ALDI SÜD",
            postal_code=postcode,
            address="Über dem Stellweg 5" if postcode == "56587" else "Kapellenstraße 88",
            city="Oberhonnefeld-Gierend" if postcode == "56587" else "Brechen",
            latitude=50.02,
        ))
    db.commit()
    stage_official_store_candidates(db, postcode)
    row = db.query(StoreDiscoveryCandidate).filter_by(
        postal_code=postcode,
        source_external_id=external_id,
    ).one()
    assert row.address == address
    assert row.source.startswith("official:")
    assert row.status == "discovered"
    assert row.matched_store_id is None


def test_aldi_internal_source_identifier_never_becomes_external_id():
    db = _db()
    db.add(_candidate(
        "aldi-osm",
        "ALDI SÜD",
        postal_code="56269",
        address="Königsberger Straße 50",
        city="Dierdorf",
        source_external_id="way/123",
    ))
    db.commit()
    stage_official_store_candidates(db, "56269")
    row = db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.postal_code == "56269",
        StoreDiscoveryCandidate.source.like("official:%"),
        StoreDiscoveryCandidate.retailer == "ALDI SÜD",
    ).one()
    assert row.source_external_id is None
    assert row.discovery_key != ""


@pytest.mark.parametrize(
    ("market_url", "offer_url"),
    (
        (
            "https://www.rewe.de/marktseite/strassenhaus/1940425/rewe-markt-kirschbuechel-2/",
            "https://www.rewe.de/angebote/strassenhaus/1940425/rewe-markt-kirschbuechel-2/",
        ),
        (
            "https://www.rewe.de/marktseite/villmar/241184/rewe-markt-brotweg-1/",
            "https://www.rewe.de/angebote/villmar/241184/rewe-markt-brotweg-1/",
        ),
        (
            "https://www.rewe.de/marktseite/brechen-niederbrechen/240076/rewe-markt-in-den-wallgaerten-1/",
            "https://www.rewe.de/angebote/brechen-niederbrechen/240076/rewe-markt-in-den-wallgaerten-1/",
        ),
    ),
)
def test_rewe_market_pages_use_generic_offer_url_normalization(market_url, offer_url):
    source = source_for_store_record(SimpleNamespace(
        id=999,
        retailer="REWE",
        name="New reviewed REWE",
        source_url=market_url,
    ))
    assert source is not None
    assert source.url == offer_url


def test_production_like_rewe_source_url_and_float_drift_resolve_one_pin():
    db = _db()
    market_url = "https://www.rewe.de/marktseite/brechen-niederbrechen/240076/rewe-markt-in-den-wallgaerten-1/"
    store = Store(
        id=12,
        retailer="REWE",
        name="REWE Brechen",
        postal_code="65611",
        city="Brechen",
        address="In den Wallgärten 4-8",
        latitude=50.362197,
        longitude=8.15777,
        active=False,
        benchmark_verified=True,
        external_id="way/28653743",
        source_url=market_url,
    )
    candidate = _candidate(
        "brechten-osm",
        "REWE",
        postal_code="65611",
        city="Brechen",
        address="In den Wallgärten 4-8",
        latitude=50.3621967,
        longitude=8.1577705,
        source_external_id="way/28653743",
        source_url=market_url,
        matched_store_id=12,
        status="promoted",
        address_verified=True,
        coordinates_verified=True,
        official_source_verified=True,
    )
    aldi = _candidate(
        "brechten-aldi-osm",
        "ALDI SÜD",
        postal_code="65611",
        city="Brechen",
        address="Kapellenstraße 88",
        latitude=50.3593728,
        longitude=8.1831378,
    )
    db.add_all([store, candidate, aldi])
    db.commit()

    stage_official_store_candidates(db, "65611")

    official = db.query(StoreDiscoveryCandidate).filter_by(
        retailer="REWE",
        postal_code="65611",
        source_external_id="240076",
    ).one()
    assert official.address == "In den Wallgärten 1"
    assert official.latitude == pytest.approx(store.latitude)
    assert official.longitude == pytest.approx(store.longitude)


def test_missing_or_ambiguous_coordinate_evidence_fails_closed():
    db = _db()
    with pytest.raises(RuntimeError, match="no unique reviewed coordinate evidence"):
        stage_official_store_candidates(db, "65606")
    assert db.query(StoreDiscoveryCandidate).count() == 0
