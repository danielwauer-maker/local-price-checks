from __future__ import annotations

from dataclasses import asdict, dataclass
from sqlalchemy.orm import Session

from .config import settings
from .coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from .geo import haversine_km
from .models import Store
from .postcode_coverage_service import addresses_match, normalize_identity_text
from .retailer_store_sources import RetailerSourceResult, retailer_source_results


STATUS_PRESENTATION = {
    "disabled": ("Nicht aktiviert", "gray"),
    "incomplete": ("Unvollständig", "red"),
    "verification_pending": ("Verifikation ausstehend", "yellow"),
    "complete": ("Vollständig verifiziert", "green"),
    "source_unavailable": ("Händlerquelle unvollständig", "red"),
    "no_known_stores": ("Keine Märkte bekannt", "green"),
}

# A postcode's target is the number of physical grocery stores we currently
# know should exist there, not merely the number of official-source rows that
# happen to have been staged already.  These audited counts bridge gaps while
# retailer directories are still being automated.  Candidate/store data may
# raise the target above an override, but never lower it.
AUDITED_EXPECTED_MARKET_COUNTS: dict[str, int] = {
    # 2x REWE + Lidl + ALDI SÜD + Netto Marken-Discount
    "57610": 5,
}


@dataclass(frozen=True)
class PostcodeCoverageSummary:
    postal_code: str
    city: str | None
    enabled: bool
    expected: int
    found: int
    address_verified: int
    coordinates_verified: int
    official_verified: int
    promoted: int
    missing_expected: int
    additional_discovered: int
    status: str
    status_label: str
    status_color: str
    source_results: tuple[RetailerSourceResult, ...]

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["source_results"] = [asdict(result) for result in self.source_results]
        return payload


def candidates_match(expected: StoreDiscoveryCandidate, discovered: StoreDiscoveryCandidate) -> bool:
    if expected.postal_code != discovered.postal_code or expected.retailer != discovered.retailer:
        return False
    city_matches = normalize_identity_text(expected.city) == normalize_identity_text(discovered.city)
    address_matches = addresses_match(expected.address, discovered.address)
    distance_m = haversine_km(
        expected.latitude,
        expected.longitude,
        discovered.latitude,
        discovered.longitude,
    ) * 1000
    return bool(city_matches and address_matches and distance_m <= settings.store_coordinate_tolerance_m)


def store_matches_candidate(store: Store, candidate: StoreDiscoveryCandidate) -> bool:
    """Match an existing store only through an explicit or complete identity."""
    if candidate.matched_store_id is not None:
        return store.id == candidate.matched_store_id
    if (
        candidate.source_external_id
        and store.external_id
        and candidate.source_external_id == store.external_id
    ):
        return store.retailer == candidate.retailer and store.postal_code == candidate.postal_code
    city_matches = not (store.city and candidate.city) or (
        normalize_identity_text(store.city) == normalize_identity_text(candidate.city)
    )
    return bool(
        store.retailer == candidate.retailer
        and store.postal_code == candidate.postal_code
        and addresses_match(store.address, candidate.address)
        and city_matches
    )


def _candidate_identity_key(candidate: StoreDiscoveryCandidate) -> tuple[str, str, str]:
    """Stable physical-store key used only for rollout counting.

    Official and OSM rows for the same address collapse into one market while
    different branches of the same retailer remain separate.
    """
    return (
        normalize_identity_text(candidate.retailer),
        normalize_identity_text(candidate.address),
        normalize_identity_text(candidate.city),
    )


def _store_identity_key(store: Store) -> tuple[str, str, str]:
    return (
        normalize_identity_text(store.retailer),
        normalize_identity_text(store.address),
        normalize_identity_text(store.city),
    )


def reconcile_postcode_coverage(
    db: Session,
    postcode: CoveragePostalCode,
    *,
    source_results: tuple[RetailerSourceResult, ...] | None = None,
) -> PostcodeCoverageSummary:
    candidates = db.query(StoreDiscoveryCandidate).filter_by(postal_code=postcode.postal_code).all()
    postcode_stores = db.query(Store).filter(Store.postal_code == postcode.postal_code).all()

    # Count physical markets instead of treating official and discovery sources
    # as two competing populations.  This fixes cases such as Altenkirchen,
    # where two official REWEs previously produced "Soll 2" while ALDI/Netto
    # were labelled merely as additional discoveries.
    candidate_keys = {_candidate_identity_key(row) for row in candidates}
    store_keys = {_store_identity_key(store) for store in postcode_stores}
    known_physical_keys = candidate_keys | store_keys
    found = len(known_physical_keys)
    expected = max(found, AUDITED_EXPECTED_MARKET_COUNTS.get(postcode.postal_code, 0))

    # Gate counters are also physical-market counters. Prefer a promoted Store's
    # state where available, otherwise take the strongest candidate state for
    # the same branch.
    grouped_candidates: dict[tuple[str, str, str], list[StoreDiscoveryCandidate]] = {}
    for row in candidates:
        grouped_candidates.setdefault(_candidate_identity_key(row), []).append(row)

    address_verified = coordinates_verified = official_verified = 0
    for key in known_physical_keys:
        matching_store = next((store for store in postcode_stores if _store_identity_key(store) == key), None)
        rows = grouped_candidates.get(key, [])
        if matching_store is not None:
            address_ok = bool(getattr(matching_store, "address_verified", False)) or any(row.address_verified for row in rows)
            coordinates_ok = bool(getattr(matching_store, "coordinates_verified", False)) or any(row.coordinates_verified for row in rows)
            official_ok = bool(getattr(matching_store, "official_source_verified", False)) or any(row.official_source_verified for row in rows)
        else:
            address_ok = any(row.address_verified for row in rows)
            coordinates_ok = any(row.coordinates_verified for row in rows)
            official_ok = any(row.official_source_verified for row in rows)
        address_verified += int(address_ok)
        coordinates_verified += int(coordinates_ok)
        official_verified += int(official_ok)

    promoted_ids = {
        store.id
        for candidate in candidates
        for store in postcode_stores
        if store_matches_candidate(store, candidate)
    }
    # Stores that are already in the postcode but no longer have a staging row
    # still count as promoted physical markets.
    promoted = max(len(promoted_ids), len(store_keys))

    missing_expected = max(0, expected - found)
    additional_discovered = max(0, found - expected)
    results = source_results or retailer_source_results(postcode.postal_code)
    incomplete_sources = any(
        result.status in {"manual_verification_required", "source_unavailable"} for result in results
    )

    if not postcode.enabled:
        status = "disabled"
    elif expected == 0 and found == 0:
        # An enabled postcode with no known physical markets is a valid finished
        # state. Retailer adapters may still be manual/incomplete, but that must
        # not paint an actually empty area red forever.
        status = "no_known_stores"
    elif missing_expected:
        status = "incomplete"
    elif (
        address_verified < found
        or coordinates_verified < found
        or official_verified < found
        or promoted < expected
    ):
        status = "verification_pending"
    elif incomplete_sources:
        status = "source_unavailable"
    else:
        status = "complete"
    label, color = STATUS_PRESENTATION[status]
    return PostcodeCoverageSummary(
        postal_code=postcode.postal_code,
        city=postcode.city,
        enabled=postcode.enabled,
        expected=expected,
        found=found,
        address_verified=address_verified,
        coordinates_verified=coordinates_verified,
        official_verified=official_verified,
        promoted=promoted,
        missing_expected=missing_expected,
        additional_discovered=additional_discovered,
        status=status,
        status_label=label,
        status_color=color,
        source_results=results,
    )
