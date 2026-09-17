from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import model_registry  # noqa: F401 - register Store foreign keys
from app.admin_market_identity_routes import (
    _market_identity_view_model,
    delete_false_market,
)
from app.db import Base
from app.models import Store


def _db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _rewe(
    name: str,
    address: str,
    *,
    external_id: str | None,
    source_url: str | None,
    active: bool = False,
    verified: bool = False,
    postal_code: str = "56587",
    city: str = "Straßenhaus",
    latitude: float = 50.54205,
    longitude: float = 7.51990,
) -> Store:
    return Store(
        retailer="REWE",
        name=name,
        address=address,
        postal_code=postal_code,
        city=city,
        latitude=latitude,
        longitude=longitude,
        active=active,
        benchmark_verified=verified,
        external_id=external_id,
        source_url=source_url,
    )


def test_same_official_id_is_confirmed_alias_not_possible_false_market():
    db = _db()
    canonical = _rewe(
        "REWE Straßenhaus",
        "Kirschbüchel 2",
        external_id="1940425",
        source_url="https://www.rewe.de/marktseite/strassenhaus/1940425/",
        active=True,
        verified=True,
    )
    alias = _rewe(
        "REWE Dennis Weirich Legacy",
        "Kirschbüchel 2",
        external_id="1940425",
        source_url=None,
    )
    db.add_all([canonical, alias])
    db.commit()

    view = _market_identity_view_model(db)

    assert len(view["confirmed_aliases"]) == 1
    assert view["confirmed_aliases"][0]["alias"].id == alias.id
    assert view["confirmed_aliases"][0]["kind"] == "official_id"
    assert view["confirmed_aliases"][0]["delete_allowed"] is False
    assert view["possible_false_markets"] == []


def test_confirmed_alias_cannot_be_deleted_even_when_it_has_no_references():
    db = _db()
    canonical = _rewe(
        "REWE Straßenhaus",
        "Kirschbüchel 2",
        external_id="1940425",
        source_url="https://www.rewe.de/marktseite/strassenhaus/1940425/",
        active=True,
        verified=True,
    )
    alias = _rewe(
        "REWE Dennis Weirich Legacy",
        "Kirschbüchel 2",
        external_id="1940425",
        source_url=None,
    )
    db.add_all([canonical, alias])
    db.commit()
    alias_id = alias.id

    with pytest.raises(HTTPException) as caught:
        delete_false_market(alias_id, confirm="LOESCHEN", db=db, actor="admin")

    assert caught.value.status_code == 409
    assert db.get(Store, alias_id) is not None


def test_unique_weak_osm_alias_is_the_only_delete_candidate_class():
    db = _db()
    canonical = _rewe(
        "REWE Official",
        "Kirschbüchel 2",
        external_id="1940425",
        source_url="https://www.rewe.de/marktseite/strassenhaus/1940425/",
        active=True,
        verified=True,
    )
    weak = _rewe(
        "REWE Map Alias",
        "Raiffeisenstraße",
        external_id="way/92219239",
        source_url="https://www.openstreetmap.org/way/92219239",
        active=False,
        verified=False,
        latitude=50.541989,
        longitude=7.519881,
    )
    db.add_all([canonical, weak])
    db.commit()
    weak_id = weak.id

    view = _market_identity_view_model(db)

    assert view["confirmed_aliases"] == []
    assert len(view["possible_false_markets"]) == 1
    row = view["possible_false_markets"][0]
    assert row["alias"].id == weak_id
    assert row["kind"] == "weak_map_proximity"
    assert row["delete_allowed"] is True

    delete_false_market(weak_id, confirm="LOESCHEN", db=db, actor="admin")
    assert db.get(Store, weak_id) is None
    assert db.get(Store, canonical.id) is not None


def test_canonical_market_status_is_effective_across_retained_alias_rows():
    db = _db()
    canonical = _rewe(
        "REWE Canonical",
        "Königsberger Straße 20-22",
        external_id="321019",
        source_url="https://www.rewe.de/marktseite/dierdorf/321019/",
        postal_code="56269",
        city="Dierdorf",
        active=False,
        verified=False,
    )
    historical_alias = _rewe(
        "REWE Legacy Public",
        "Königsberger Str. 20-22",
        external_id="321019",
        source_url=None,
        postal_code="56269",
        city="Dierdorf",
        active=True,
        verified=True,
    )
    db.add_all([canonical, historical_alias])
    db.commit()

    view = _market_identity_view_model(db)
    assert len(view["market_rows"]) == 1
    row = view["market_rows"][0]

    assert row["store"].id == canonical.id
    assert row["alias_count"] == 1
    assert row["public"] is True
    assert row["status"] == "public"
    assert row["beta_scope"] is True


def test_outside_beta_public_market_is_labeled_not_treated_as_identity_error():
    db = _db()
    netto = Store(
        retailer="Netto Marken-Discount",
        name="Netto Dierdorf",
        address="Königsberger Straße 24",
        postal_code="56269",
        city="Dierdorf",
        latitude=50.547325,
        longitude=7.639524,
        active=True,
        benchmark_verified=True,
        external_id="6822",
    )
    db.add(netto)
    db.commit()

    view = _market_identity_view_model(db)
    row = view["market_rows"][0]

    assert row["store"].id == netto.id
    assert row["public"] is True
    assert row["status"] == "public"
    assert row["beta_scope"] is False


def test_different_official_ids_remain_two_canonical_market_rows():
    db = _db()
    first = _rewe(
        "PETZ REWE Bahnhofstraße",
        "Bahnhofstr. 30",
        external_id="8534500",
        source_url="https://www.rewe.de/marktseite/altenkirchen/8534500/",
        postal_code="57610",
        city="Altenkirchen",
        active=True,
        verified=True,
        latitude=50.685665,
        longitude=7.638153,
    )
    second = _rewe(
        "PETZ REWE Dammweg",
        "Dammweg 10",
        external_id="2500021",
        source_url="https://www.rewe.de/marktseite/altenkirchen/2500021/",
        postal_code="57610",
        city="Altenkirchen",
        active=True,
        verified=True,
        latitude=50.6894,
        longitude=7.64644,
    )
    db.add_all([first, second])
    db.commit()

    view = _market_identity_view_model(db)

    assert len(view["market_rows"]) == 2
    assert view["confirmed_aliases"] == []
    assert view["possible_false_markets"] == []
