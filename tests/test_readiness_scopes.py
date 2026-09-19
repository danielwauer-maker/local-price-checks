from __future__ import annotations

import pytest

from app.beta_market_scope import is_beta_retailer
from app.production_readiness import TARGET_MARKETS
from app.retailer_store_sources import CURATED_OFFICIAL_STORES
from app.readiness_scopes import (
    ALL_TARGETS_SCOPE_KEY,
    BETA_1_SCOPE_KEY,
    DEFAULT_READINESS_SCOPE,
    READINESS_SCOPES,
    apply_readiness_scope,
    readiness_scope,
)


def _report(*, beta_ready: bool = True) -> dict:
    beta_keys = set(READINESS_SCOPES[BETA_1_SCOPE_KEY].target_keys)
    rows = []
    for target in TARGET_MARKETS:
        if target.key in beta_keys and beta_ready:
            strategy = "collector_primary"
            status = "READY"
        else:
            strategy = "external_primary"
            status = "VALIDATION_REQUIRED"
        rows.append(
            {
                "target_key": target.key,
                "retailer": target.retailer,
                "city": target.city,
                "store_name": target.name_contains,
                "source_strategy": strategy,
                "status": status,
            }
        )
    return {
        "status": "IN_PROGRESS",
        "collector_primary": sum(
            1 for row in rows if row["source_strategy"] == "collector_primary"
        ),
        "external_primary": sum(
            1 for row in rows if row["source_strategy"] == "external_primary"
        ),
        "blocked": 0,
        "target_count": len(rows),
        "stores": rows,
    }


def test_beta_1_scope_covers_full_curated_beta_inventory():
    scope = readiness_scope(BETA_1_SCOPE_KEY)
    targets_by_key = {target.key: target for target in TARGET_MARKETS}
    curated_beta = [row for row in CURATED_OFFICIAL_STORES if is_beta_retailer(row.retailer)]

    assert DEFAULT_READINESS_SCOPE == BETA_1_SCOPE_KEY
    assert len(scope.target_keys) == 12
    assert len(scope.target_keys) == len(curated_beta)
    assert {targets_by_key[key].retailer for key in scope.target_keys} == {
        "REWE",
        "EDEKA",
        "ALDI SÜD",
    }
    assert {
        targets_by_key[key].external_id
        for key in scope.target_keys
        if targets_by_key[key].retailer == "REWE"
    } == {"321019", "1940425", "8534500", "2500021", "241184", "240076", "240052"}
    assert sum(targets_by_key[key].retailer == "ALDI SÜD" for key in scope.target_keys) == 4
    assert sum(targets_by_key[key].retailer == "EDEKA" for key in scope.target_keys) == 1


def test_out_of_scope_lidl_and_netto_do_not_block_beta_1_readiness():
    scoped = apply_readiness_scope(_report(), scope_key=BETA_1_SCOPE_KEY)

    assert scoped["scope_key"] == BETA_1_SCOPE_KEY
    assert scoped["status"] == "READY"
    assert scoped["target_count"] == 12
    assert scoped["all_target_count"] == 15
    assert scoped["collector_primary"] == 12
    assert scoped["external_primary"] == 0
    assert scoped["blocked"] == 0

    out_of_scope = [row for row in scoped["stores"] if not row["in_scope"]]
    assert {row["retailer"] for row in out_of_scope} == {
        "Lidl",
        "Netto Marken-Discount",
    }
    assert all(row["source_strategy"] == "external_primary" for row in out_of_scope)


def test_beta_1_still_fails_closed_when_one_beta_market_is_not_ready():
    report = _report()
    rewe = next(
        row for row in report["stores"]
        if row["target_key"] == "rewe-hundertmark-dierdorf"
    )
    rewe["source_strategy"] = "external_primary"
    rewe["status"] = "VALIDATION_REQUIRED"

    scoped = apply_readiness_scope(report, scope_key=BETA_1_SCOPE_KEY)

    assert scoped["status"] == "IN_PROGRESS"
    assert scoped["collector_primary"] == 11
    assert scoped["external_primary"] == 1


def test_all_targets_scope_keeps_beta_and_legacy_non_beta_targets_visible():
    scoped = apply_readiness_scope(_report(), scope_key=ALL_TARGETS_SCOPE_KEY)

    assert scoped["scope_key"] == ALL_TARGETS_SCOPE_KEY
    assert scoped["status"] == "IN_PROGRESS"
    assert scoped["target_count"] == 15
    assert scoped["all_target_count"] == 15
    assert scoped["collector_primary"] == 12
    assert scoped["external_primary"] == 3
    assert all(row["in_scope"] for row in scoped["stores"])


def test_unknown_scope_fails_closed():
    with pytest.raises(ValueError, match="unknown readiness scope"):
        readiness_scope("make-it-green")


def test_scope_cannot_silently_reference_missing_canonical_row():
    report = _report()
    report["stores"] = [
        row
        for row in report["stores"]
        if row["target_key"] != "rewe-hundertmark-dierdorf"
    ]

    with pytest.raises(ValueError, match="missing scoped target markets"):
        apply_readiness_scope(report, scope_key=BETA_1_SCOPE_KEY)
