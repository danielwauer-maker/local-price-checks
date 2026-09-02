from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .models import Store


def _fold(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ß", "ss")
    text = re.sub(r"\bstr(?:asse|\.)?\b", "strasse", text)
    text = re.sub(r"\bstraße\b", "strasse", text)
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


def physical_store_key(store: Store) -> tuple[str, ...]:
    """Return a conservative identity key for one physical grocery market.

    A complete postal-code/city/address is the primary identity. This makes
    differently named rows such as "REWE Dierdorf" and "REWE:XL Hundertmark"
    one physical market while keeping two branches at different addresses
    (for example the two REWE stores in Altenkirchen) separate.

    A retailer external id is used only when the physical address is missing.
    With neither address nor external id we deliberately fall back to the row id
    rather than risk collapsing two real branches.
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
    official = int(any(host in source for host in ("rewe.de", "edeka.de", "lidl.de", "aldi-sued.de", "netto-online.de", "penny.de")))
    return (
        int(bool(store.benchmark_verified)),
        int(bool(store.active)),
        int(bool(store.external_id)),
        official,
        int(bool(store.source_url)),
        int(store.latitude is not None and store.longitude is not None),
        len(store.name or ""),
        -int(store.id or 0),
    )


def collapse_physical_stores(stores: Iterable[Store]) -> list[Store]:
    """Return one preferred Store row per physical retailer/location."""
    selected: dict[tuple[str, ...], Store] = {}
    order: list[tuple[str, ...]] = []
    for store in stores:
        key = physical_store_key(store)
        current = selected.get(key)
        if current is None:
            selected[key] = store
            order.append(key)
        elif _preference(store) > _preference(current):
            selected[key] = store
    return [selected[key] for key in order]


def canonical_store_map(stores: Iterable[Store]) -> dict[int, Store]:
    """Map every duplicate/alias row id to the preferred physical Store row."""
    rows = list(stores)
    preferred = {physical_store_key(store): store for store in collapse_physical_stores(rows)}
    return {store.id: preferred[physical_store_key(store)] for store in rows}


def duplicate_groups(stores: Iterable[Store]) -> list[list[Store]]:
    groups: dict[tuple[str, ...], list[Store]] = {}
    for store in stores:
        groups.setdefault(physical_store_key(store), []).append(store)
    return [rows for rows in groups.values() if len(rows) > 1]
