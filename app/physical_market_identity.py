from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .geo import haversine_km
from .models import Store

_PROXIMITY_KM = 0.20
_OSM_EXTERNAL_PREFIXES = ("node/", "way/", "relation/")
_OFFICIAL_HOSTS = ("rewe.de", "edeka.de", "lidl.de", "aldi-sued.de", "netto-online.de", "penny.de")


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


def _official_external_id(store: Store) -> str | None:
    value = (store.external_id or "").strip()
    folded = value.casefold()
    if not value or folded.startswith(_OSM_EXTERNAL_PREFIXES):
        return None
    return _fold(value)


def _has_official_source(store: Store) -> bool:
    source = (store.source_url or "").casefold()
    return any(host in source for host in _OFFICIAL_HOSTS)


def physical_store_key(store: Store) -> tuple[str, ...]:
    """Stable exact identity used for discovery and diagnostics.

    Exact address remains useful, but system-wide collapsing additionally uses
    ``same_physical_market`` so a bad OSM address cannot create a second market
    at essentially the same physical pin.
    """
    retailer = normalized_retailer(store.retailer)
    official_id = _official_external_id(store)
    if official_id:
        return ("official", retailer, official_id)
    postal_code, city, address = normalized_address(store)
    if postal_code and city and address:
        return ("address", retailer, postal_code, city, address)
    external_id = _fold(store.external_id)
    if external_id:
        return ("external", retailer, external_id)
    return ("row", str(store.id))


def same_physical_market(left: Store, right: Store) -> bool:
    if normalized_retailer(left.retailer) != normalized_retailer(right.retailer):
        return False

    left_official = _official_external_id(left)
    right_official = _official_external_id(right)
    if left_official and right_official:
        return left_official == right_official

    left_pc, left_city, left_address = normalized_address(left)
    right_pc, right_city, right_address = normalized_address(right)
    if left_pc and left_city and left_address and (left_pc, left_city, left_address) == (right_pc, right_city, right_address):
        return True

    # Fallback for bad map/address assignments: same retailer + postcode + very
    # close coordinates. Never use this to join two independently identified
    # official branches; the guard above keeps those separate.
    if not left_pc or left_pc != right_pc:
        return False
    if None in (left.latitude, left.longitude, right.latitude, right.longitude):
        return False
    return haversine_km(left.latitude, left.longitude, right.latitude, right.longitude) <= _PROXIMITY_KM


def _preference(store: Store) -> tuple[int, ...]:
    return (
        int(bool(_official_external_id(store))),
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
    rows = list(stores)
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, left in enumerate(rows):
        for j in range(i + 1, len(rows)):
            if same_physical_market(left, rows[j]):
                union(i, j)

    groups: dict[int, list[Store]] = {}
    for i, row in enumerate(rows):
        groups.setdefault(find(i), []).append(row)
    return list(groups.values())


def collapse_physical_stores(stores: Iterable[Store]) -> list[Store]:
    """Return one preferred Store row per resolved physical market."""
    return [max(group, key=_preference) for group in _components(stores)]


def canonical_store_map(stores: Iterable[Store]) -> dict[int, Store]:
    """Map every alias row id to the preferred physical Store row."""
    mapping: dict[int, Store] = {}
    for group in _components(stores):
        preferred = max(group, key=_preference)
        for store in group:
            mapping[store.id] = preferred
    return mapping


def duplicate_groups(stores: Iterable[Store]) -> list[list[Store]]:
    return [group for group in _components(stores) if len(group) > 1]
