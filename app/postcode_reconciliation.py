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
    "no_expected_stores": ("Keine erwarteten Märkte", "gray"),
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


def reconcile_postcode_coverage(
    db: Session,
    postcode: CoveragePostalCode,
    *,
    source_results: tuple[RetailerSourceResult, ...] | None = None,
) -> PostcodeCoverageSummary:
    candidates = db.query(StoreDiscoveryCandidate).filter_by(postal_code=postcode.postal_code).all()
    expected_rows = [row for row in candidates if row.source.startswith("official:")]
    discovered_rows = [row for row in candidates if not row.source.startswith("official:")]
    matched_discovered_ids: set[int] = set()
    matched_expected_ids: set[int] = set()
    official_for_discovered: set[int] = set()
    for expected in expected_rows:
        matches = [row for row in discovered_rows if row.id not in matched_discovered_ids and candidates_match(expected, row)]
        if not matches:
            continue
        match = min(
            matches,
            key=lambda row: haversine_km(expected.latitude, expected.longitude, row.latitude, row.longitude),
        )
        matched_expected_ids.add(expected.id)
        matched_discovered_ids.add(match.id)
        official_for_discovered.add(match.id)

    expected = len(expected_rows)
    found = len(discovered_rows)
    address_verified = sum(bool(row.address_verified) for row in discovered_rows)
    coordinates_verified = sum(bool(row.coordinates_verified) for row in discovered_rows)
    official_verified = sum(
        bool(row.official_source_verified or row.id in official_for_discovered) for row in discovered_rows
    )
    postcode_stores = db.query(Store).filter(Store.postal_code == postcode.postal_code).all()
    promoted_ids = {
        store.id
        for candidate in candidates
        for store in postcode_stores
        if store_matches_candidate(store, candidate)
    }
    missing_expected = expected - len(matched_expected_ids)
    additional_discovered = found - len(matched_discovered_ids)
    results = source_results or retailer_source_results(postcode.postal_code)
    incomplete_sources = any(
        result.status in {"manual_verification_required", "source_unavailable"} for result in results
    )

    if not postcode.enabled:
        status = "disabled"
    elif missing_expected:
        status = "incomplete"
    elif expected == 0 and incomplete_sources:
        status = "source_unavailable"
    elif expected == 0 and found == 0:
        status = "no_expected_stores"
    elif (
        additional_discovered
        or address_verified < found
        or coordinates_verified < found
        or official_verified < found
        or len(promoted_ids) < expected
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
        promoted=len(promoted_ids),
        missing_expected=missing_expected,
        additional_discovered=additional_discovered,
        status=status,
        status_label=label,
        status_color=color,
        source_results=results,
    )
