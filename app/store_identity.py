from __future__ import annotations

import re
from typing import Iterable, TypeVar

T = TypeVar("T")


def _norm(value: object) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "", text)


def physical_store_key(store: object) -> tuple[str, str, str]:
    """Return a conservative physical-store identity key.

    Prefer retailer + external_id when a stable branch id exists. Fall back to
    retailer + postcode/city/address so differently named rows for the same
    physical branch collapse without merging real branches at different
    addresses.
    """
    retailer = _norm(getattr(store, "retailer", ""))
    external_id = _norm(getattr(store, "external_id", ""))
    if retailer and external_id:
        return ("external", retailer, external_id)

    postal_code = _norm(getattr(store, "postal_code", ""))
    city = _norm(getattr(store, "city", ""))
    address = _norm(getattr(store, "address", ""))
    return ("address", retailer, f"{postal_code}|{city}|{address}")


def _quality(store: object) -> tuple[int, int, int, int]:
    source_url = str(getattr(store, "source_url", "") or "").strip().lower()
    has_http_source = int(source_url.startswith("https://") or source_url.startswith("http://"))
    has_external_id = int(bool(str(getattr(store, "external_id", "") or "").strip()))
    benchmark_verified = int(bool(getattr(store, "benchmark_verified", False)))
    store_id = int(getattr(store, "id", 0) or 0)
    return (has_http_source, has_external_id, benchmark_verified, -store_id)


def deduplicate_physical_stores(stores: Iterable[T]) -> list[T]:
    """Keep one canonical row per physical store without deleting provenance."""
    canonical: dict[tuple[str, str, str], T] = {}
    order: list[tuple[str, str, str]] = []
    for store in stores:
        key = physical_store_key(store)
        current = canonical.get(key)
        if current is None:
            canonical[key] = store
            order.append(key)
        elif _quality(store) > _quality(current):
            canonical[key] = store
    return [canonical[key] for key in order]
