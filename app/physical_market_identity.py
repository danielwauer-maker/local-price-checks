from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from .geo import haversine_km
from .models import Store

_PROXIMITY_KM = 0.20
_OSM_EXTERNAL_ID = re.compile(r"^(?:node|way|relation)/\d+$", re.IGNORECASE)
_OFFICIAL_HOSTS = (
    "rewe.de",
    "edeka.de",
    "lidl.de",
    "aldi-sued.de",
    "netto-online.de",
    "penny.de",
)


def _fold(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ß", "ss")
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


def is_osm_external_id(value: str | None) -> bool:
    return bool(_OSM_EXTERNAL_ID.fullmatch((value or "").strip()))


def official_retailer_id(store: Store) -> str | None:
    value = (store.external_id or "").strip()
    if not value or is_osm_external_id(value):
        return None
    return _fold(value)


def _has_official_source(store: Store) -> bool:
    try:
        host = (urlparse(store.source_url or "").hostname or "").casefold()
    except ValueError:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in _OFFICIAL_HOSTS)


def has_strong_retailer_identity(store: Store) -> bool:
    """Return whether this row is stronger than map-only discovery evidence."""
    return bool(
        store.benchmark_verified
        or official_retailer_id(store)
        or (_has_official_source(store) and not is_osm_external_id(store.external_id))
    )


def is_weak_discovery_store(store: Store) -> bool:
    """A map row stays weak even with a generic retailer URL attached."""
    return bool(not store.benchmark_verified and is_osm_external_id(store.external_id))


def physical_store_key(store: Store) -> tuple[str, ...]:
    """Stable conservative identity key for discovery and diagnostics."""
    retailer = normalized_retailer(store.retailer)
    official_id = official_retailer_id(store)
    if official_id:
        return ("official", retailer, official_id)
    postal_code, city, address = normalized_address(store)
    if postal_code and city and address:
        return ("address", retailer, postal_code, city, address)
    external_id = _fold(store.external_id)
    if external_id:
        return ("external", retailer, external_id)
    return ("row", str(store.id))


def _coordinates_close(left: Store, right: Store) -> bool:
    if None in (left.latitude, left.longitude, right.latitude, right.longitude):
        return False
    return haversine_km(
        left.latitude,
        left.longitude,
        right.latitude,
        right.longitude,
    ) <= _PROXIMITY_KM


def same_physical_market(left: Store, right: Store) -> bool:
    """Pairwise identity evidence; collection-level ambiguity is handled below."""
    if normalized_retailer(left.retailer) != normalized_retailer(right.retailer):
        return False

    left_official = official_retailer_id(left)
    right_official = official_retailer_id(right)
    if left_official and right_official:
        return left_official == right_official

    left_address = normalized_address(left)
    right_address = normalized_address(right)
    if all(left_address) and left_address == right_address:
        return True

    if left_address[0] != right_address[0] or not left_address[0]:
        return False
    strong_weak = (
        has_strong_retailer_identity(left)
        and is_weak_discovery_store(right)
    ) or (
        has_strong_retailer_identity(right)
        and is_weak_discovery_store(left)
    )
    return strong_weak and _coordinates_close(left, right)


def _preference(store: Store) -> tuple[int, ...]:
    return (
        int(bool(official_retailer_id(store))),
        int(_has_official_source(store)),
        int(bool(store.benchmark_verified)),
        int(bool(store.active)),
        int(bool(store.external_id)),
        int(bool(store.source_url)),
        int(store.latitude is not None and store.longitude is not None),
        len(store.name or ""),
        -int(store.id or 0),
    )


def _components(stores: Iterable[Store]) -> list[list[Store]]:
    """Resolve aliases without allowing a weak row to bridge strong branches."""
    rows = list(stores)
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def members(root: int) -> list[int]:
        resolved = find(root)
        return [index for index in range(len(rows)) if find(index) == resolved]

    def official_ids(indices: Iterable[int]) -> set[str]:
        return {
            official_id
            for index in indices
            if (official_id := official_retailer_id(rows[index]))
        }

    def union(left: int, right: int) -> bool:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return True
        if len(official_ids([*members(left_root), *members(right_root)])) > 1:
            return False
        parent[right_root] = left_root
        return True

    by_official_id: dict[tuple[str, str], list[int]] = {}
    by_address: dict[tuple[str, str, str, str], list[int]] = {}
    for index, store in enumerate(rows):
        retailer = normalized_retailer(store.retailer)
        if official_id := official_retailer_id(store):
            by_official_id.setdefault((retailer, official_id), []).append(index)
        address = normalized_address(store)
        if all(address):
            by_address.setdefault((retailer, *address), []).append(index)

    for indices in by_official_id.values():
        for index in indices[1:]:
            union(indices[0], index)

    for indices in by_address.values():
        if len(official_ids(indices)) > 1:
            continue
        for index in indices[1:]:
            union(indices[0], index)

    roots = list(dict.fromkeys(find(index) for index in range(len(rows))))
    weak_roots = [
        root
        for root in roots
        if all(is_weak_discovery_store(rows[index]) for index in members(root))
    ]
    strong_roots = [
        root
        for root in roots
        if any(has_strong_retailer_identity(rows[index]) for index in members(root))
    ]
    for weak_root in weak_roots:
        weak_indices = members(weak_root)
        nearby: list[int] = []
        for strong_root in strong_roots:
            strong_indices = members(strong_root)
            if any(
                normalized_retailer(rows[weak_index].retailer)
                == normalized_retailer(rows[strong_index].retailer)
                and _fold(rows[weak_index].postal_code) == _fold(rows[strong_index].postal_code)
                and _coordinates_close(rows[weak_index], rows[strong_index])
                for weak_index in weak_indices
                for strong_index in strong_indices
            ):
                nearby.append(strong_root)
        nearby = list(dict.fromkeys(find(root) for root in nearby))
        if len(nearby) == 1:
            union(nearby[0], weak_root)

    groups: dict[int, list[Store]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(find(index), []).append(row)
    return list(groups.values())


def collapse_physical_stores(stores: Iterable[Store]) -> list[Store]:
    return [max(group, key=_preference) for group in _components(stores)]


def canonical_store_map(stores: Iterable[Store]) -> dict[int, Store]:
    mapping: dict[int, Store] = {}
    for group in _components(stores):
        preferred = max(group, key=_preference)
        for store in group:
            mapping[store.id] = preferred
    return mapping


@dataclass(frozen=True)
class StoreAliasGroup:
    canonical: Store
    aliases: tuple[Store, ...]
    reason: str


def alias_groups(stores: Iterable[Store]) -> list[StoreAliasGroup]:
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
        reasons: list[str] = []
        for alias in aliases:
            if (
                official_retailer_id(alias)
                and official_retailer_id(alias) == official_retailer_id(canonical)
            ):
                reasons.append("gleiche offizielle Händler-ID")
            elif normalized_address(alias) == normalized_address(canonical):
                reasons.append("gleiche normalisierte Adresse")
            else:
                reasons.append("eindeutiger naher OSM/Map-Alias zu starker Händleridentität")
        result.append(StoreAliasGroup(
            canonical=canonical,
            aliases=tuple(aliases),
            reason="; ".join(dict.fromkeys(reasons)),
        ))
    return result


def duplicate_groups(stores: Iterable[Store]) -> list[list[Store]]:
    return [[group.canonical, *group.aliases] for group in alias_groups(stores)]
