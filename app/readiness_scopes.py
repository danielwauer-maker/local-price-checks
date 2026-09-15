from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.orm import Session

from .production_readiness import TARGET_MARKETS, build_multi_market_readiness


@dataclass(frozen=True)
class ReadinessScope:
    key: str
    label: str
    target_keys: tuple[str, ...]


BETA_1_SCOPE_KEY = "beta-1"
ALL_TARGETS_SCOPE_KEY = "all-target-markets"
DEFAULT_READINESS_SCOPE = BETA_1_SCOPE_KEY

_BETA_1_TARGET_KEYS = (
    "edeka-fellenzer-puderbach",
    "aldi-dierdorf",
    "rewe-hundertmark-dierdorf",
    "aldi-oberhonnefeld",
)
_ALL_TARGET_KEYS = tuple(target.key for target in TARGET_MARKETS)

READINESS_SCOPES: Mapping[str, ReadinessScope] = {
    BETA_1_SCOPE_KEY: ReadinessScope(
        key=BETA_1_SCOPE_KEY,
        label="Beta 1 · REWE / EDEKA / ALDI SÜD",
        target_keys=_BETA_1_TARGET_KEYS,
    ),
    ALL_TARGETS_SCOPE_KEY: ReadinessScope(
        key=ALL_TARGETS_SCOPE_KEY,
        label="Alle definierten Zielmärkte",
        target_keys=_ALL_TARGET_KEYS,
    ),
}


def readiness_scope(scope_key: str = DEFAULT_READINESS_SCOPE) -> ReadinessScope:
    """Resolve a configured readiness scope and fail closed for unknown scopes."""

    try:
        scope = READINESS_SCOPES[scope_key]
    except KeyError as exc:
        raise ValueError(f"unknown readiness scope: {scope_key}") from exc

    configured_keys = set(_ALL_TARGET_KEYS)
    unknown_keys = [key for key in scope.target_keys if key not in configured_keys]
    if unknown_keys:
        raise ValueError(
            f"readiness scope {scope.key!r} references unknown target markets: "
            + ", ".join(unknown_keys)
        )
    if len(set(scope.target_keys)) != len(scope.target_keys):
        raise ValueError(f"readiness scope {scope.key!r} contains duplicate target markets")
    if not scope.target_keys:
        raise ValueError(f"readiness scope {scope.key!r} must contain at least one target market")
    return scope


def apply_readiness_scope(
    report: Mapping[str, Any],
    *,
    scope_key: str = DEFAULT_READINESS_SCOPE,
) -> dict[str, Any]:
    """Apply a release scope to the canonical all-market readiness assessment.

    The underlying per-store readiness result is never altered. Out-of-scope
    markets remain visible for operations, but they do not affect the selected
    release scope's READY/IN_PROGRESS status or counters.
    """

    scope = readiness_scope(scope_key)
    scoped_keys = set(scope.target_keys)
    rows = []
    for original in report.get("stores", []):
        row = dict(original)
        row["in_scope"] = row.get("target_key") in scoped_keys
        rows.append(row)

    scoped_rows = [row for row in rows if row["in_scope"]]
    observed_keys = {row.get("target_key") for row in scoped_rows}
    missing_scope_keys = [key for key in scope.target_keys if key not in observed_keys]
    if missing_scope_keys:
        raise ValueError(
            f"canonical readiness report is missing scoped target markets: "
            + ", ".join(missing_scope_keys)
        )

    collector_primary = sum(
        1 for row in scoped_rows if row.get("source_strategy") == "collector_primary"
    )
    external_primary = sum(
        1 for row in scoped_rows if row.get("source_strategy") == "external_primary"
    )
    blocked = sum(1 for row in scoped_rows if row.get("source_strategy") == "blocked")

    return {
        **dict(report),
        "scope_key": scope.key,
        "scope_label": scope.label,
        "status": "READY" if collector_primary == len(scope.target_keys) else "IN_PROGRESS",
        "collector_primary": collector_primary,
        "external_primary": external_primary,
        "blocked": blocked,
        "target_count": len(scope.target_keys),
        "all_target_count": len(rows),
        "stores": rows,
    }


def build_scoped_market_readiness(
    db: Session,
    *,
    scope_key: str = DEFAULT_READINESS_SCOPE,
) -> dict[str, Any]:
    """Build canonical store readiness and calculate release status for one scope."""

    return apply_readiness_scope(
        build_multi_market_readiness(db),
        scope_key=scope_key,
    )
