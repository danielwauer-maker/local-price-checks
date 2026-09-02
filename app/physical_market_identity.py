from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from .models import Store


def _fold(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ß", "ss")
    # Normalize German street spelling before punctuation is stripped. This
    # intentionally treats "Str.", "Str", "Straße" and "Strasse" as equal.
    text = re.sub(r"\bstr(?:asse|aße)?\.?\b", "strasse", text)
    text = re.sub(r"\bstra(?:ss|ß)e\b", "strasse", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalized_retailer(value: str | None) -> str:
    folded = _fold(value)
    if folded.startswith("netto"):
        return "netto marken discount"
    if folded in {"aldi sud", "aldi sued"}:
        return "aldi sud"
    return folded


def normalized_address(store: Store) -> tuple[str, str, str]:
    return (_fold(store.postal_code), _fold(store.city), _fold(store.address))


def _external_id(store: Store) -> str:
    return (store.external_id or "").strip().casefold()


def is_osm_external_id(value: str | None) -> bool:
    return bool(re.match(r"^(?:node|way|relation)/\d+$", (value or "").strip().casefold()))


def has_strong_retailer_identity(store: Store) -> bool:
    """Whether a Store row carries an identity that is stronger than map discovery.

    Public/benchmark rows are always strong. For pre-public rows a retailer
    external id (for example REWE 1940425 or EDEKA 071378) is strong, whereas
    OSM node/way/relation ids are deliberately treated only as discovery
    provenance.
    """
    if store.benchmark_verified:
        return True
    external_id = _external_id(store)
    return bool(external_id and not is_osm_external_id(external_id))


def is_weak_discovery_store(store: Store) -> bool:
    """Return True for a non-public Store created only from map/discovery identity."""
    return bool(
        not store.benchmark_verified
        and is_osm_external_id(store.external_id)
    )


def physical_store_key(store: Store) -> tuple[str, ...]:
    """Return the exact/conservative identity key for one physical market.

    Exact address identity remains the first pass. A second reconciliation pass
    in ``canonical_store_map`` can quarantine weak OSM-derived aliases when the
    same retailer/postcode has exactly one stronger official market identity.
    This prevents a wrong map address from creating a second public/collector
    market without collapsing two genuinely official branches.
    """
    retailer = normalized_retailer(store.retailer)
    postal_code, city, address = normalized_address(store)
    if postal_code and city and address:
        return ("address", retailer, postal_code, city, address)
    external_id = _fold(store.external_id)
    if external_id:
        return ("external", retailer, external_id)
    return ("row", str(store.id))


def _preference(store: Store) -> tuple[int, ...]:
    source = (store.source_url or "").lower()
    official = int(any(host in source for host in (
        "rewe.de", "edeka.de", "lidl.de", "aldi-sued.de", "netto-online.de", "penny.de"
    )))
    return (
        int(bool(store.benchmark_verified)),
        int(has_strong_retailer_identity(store)),
        int(bool(store.active)),
        official,
        int(bool(store.source_url)),
        int(store.latitude is not None and store.longitude is not None),
        len(store.name or ""),
        -int(store.id or 0),
    )


def _exact_groups(stores: list[Store]) -> tuple[list[Store], dict[int, Store]]:
    selected: dict[tuple[str, ...], Store] = {}
    order: list[tuple[str, ...]] = []
    grouped_rows: dict[tuple[str, ...], list[Store]] = {}
    for store in stores:
        key = physical_store_key(store)
        grouped_rows.setdefault(key, []).append(store)
        current = selected.get(key)
        if current is None:
            selected[key] = store
            order.append(key)
        elif _preference(store) > _preference(current):
            selected[key] = store
    representatives = [selected[key] for key in order]
    exact_map: dict[int, Store] = {}
    for key, rows in grouped_rows.items():
        canonical = selected[key]
        for row in rows:
            exact_map[row.id] = canonical
    return representatives, exact_map


def canonical_store_map(stores: Iterable[Store]) -> dict[int, Store]:
    """Map every Store row to the safest canonical physical market.

    Pass 1 collapses exact same-address/external-id aliases.

    Pass 2 handles the failure mode seen with map discovery: if a retailer has
    exactly one *strong* official Store identity in a postcode, additional
    non-public OSM-derived Store rows in the same retailer/postcode are treated
    as quarantined aliases even when their map address differs. They may still
    be reviewed/rejected in onboarding, but they cannot become a second normal
    collector/public market just because a map provider placed the same branch
    at another address.

    If there are two or more strong official identities in the postcode, no
    postcode-level collapse happens. This preserves real multi-branch cases
    such as two REWE stores at different addresses in Altenkirchen.
    """
    rows = list(stores)
    representatives, mapping = _exact_groups(rows)

    by_retailer_postcode: dict[tuple[str, str], list[Store]] = {}
    for store in representatives:
        key = (normalized_retailer(store.retailer), _fold(store.postal_code))
        by_retailer_postcode.setdefault(key, []).append(store)

    rep_alias_target: dict[int, Store] = {}
    for group in by_retailer_postcode.values():
        strong = [store for store in group if has_strong_retailer_identity(store)]
        if len(strong) != 1:
            continue
        canonical = strong[0]
        for store in group:
            if store.id == canonical.id:
                continue
            if is_weak_discovery_store(store):
                rep_alias_target[store.id] = canonical

    for row in rows:
        representative = mapping[row.id]
        mapping[row.id] = rep_alias_target.get(representative.id, representative)
    return mapping


def collapse_physical_stores(stores: Iterable[Store]) -> list[Store]:
    rows = list(stores)
    mapping = canonical_store_map(rows)
    result: list[Store] = []
    seen: set[int] = set()
    for row in rows:
        canonical = mapping[row.id]
        if canonical.id in seen:
            continue
        seen.add(canonical.id)
        result.append(canonical)
    return result


@dataclass(frozen=True)
class StoreAliasGroup:
    canonical: Store
    aliases: tuple[Store, ...]
    reason: str


def alias_groups(stores: Iterable[Store]) -> list[StoreAliasGroup]:
    """Return hidden Store rows together with their canonical market for admin QA."""
    rows = list(stores)
    mapping = canonical_store_map(rows)
    grouped: dict[int, list[Store]] = {}
    canonical_by_id: dict[int, Store] = {}
    for row in rows:
        canonical = mapping[row.id]
        canonical_by_id[canonical.id] = canonical
        if row.id != canonical.id:
            grouped.setdefault(canonical.id, []).append(row)

    result: list[StoreAliasGroup] = []
    for canonical_id, aliases in grouped.items():
        canonical = canonical_by_id[canonical_id]
        reasons = []
        for alias in aliases:
            if physical_store_key(alias) == physical_store_key(canonical):
                reasons.append("gleiche normalisierte Adresse/Identität")
            elif is_weak_discovery_store(alias) and has_strong_retailer_identity(canonical):
                reasons.append("OSM/Map-Alias neben eindeutiger offizieller Händleridentität in derselben PLZ")
            else:
                reasons.append("kanonische Marktidentität")
        reason = "; ".join(dict.fromkeys(reasons))
        result.append(StoreAliasGroup(canonical=canonical, aliases=tuple(aliases), reason=reason))
    return result


def duplicate_groups(stores: Iterable[Store]) -> list[list[Store]]:
    return [[group.canonical, *group.aliases] for group in alias_groups(stores)]
