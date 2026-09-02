from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .coverage_models import StoreDiscoveryCandidate
from .models import Store
from .physical_market_identity import (
    has_strong_retailer_identity,
    is_osm_external_id,
    normalized_retailer,
)
from .postcode_coverage_service import addresses_match


@dataclass(frozen=True)
class PromotionIdentityConflict:
    blocked: bool
    reason: str | None = None
    canonical_store: Store | None = None


def _same_retailer(left: str, right: str) -> bool:
    return normalized_retailer(left) == normalized_retailer(right)


def weak_candidate_promotion_conflict(
    db: Session,
    candidate: StoreDiscoveryCandidate,
) -> PromotionIdentityConflict:
    """Fail closed before a weak map row can create a duplicate Store."""
    if not is_osm_external_id(candidate.source_external_id):
        return PromotionIdentityConflict(False)

    strong_stores = [
        store
        for store in db.query(Store).filter(
            Store.postal_code == candidate.postal_code
        ).all()
        if _same_retailer(store.retailer, candidate.retailer)
        and has_strong_retailer_identity(store)
    ]
    if not strong_stores:
        return PromotionIdentityConflict(False)

    exact = next(
        (
            store
            for store in strong_stores
            if addresses_match(store.address, candidate.address)
        ),
        None,
    )
    if exact is not None:
        return PromotionIdentityConflict(False, canonical_store=exact)

    official_candidates = db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.id != candidate.id,
        StoreDiscoveryCandidate.postal_code == candidate.postal_code,
        StoreDiscoveryCandidate.official_source_verified.is_(True),
        StoreDiscoveryCandidate.source.like("official:%"),
    ).all()
    distinct_official_match = next(
        (
            row
            for row in official_candidates
            if _same_retailer(row.retailer, candidate.retailer)
            and not is_osm_external_id(row.source_external_id)
            and addresses_match(row.address, candidate.address)
        ),
        None,
    )
    if distinct_official_match is not None:
        return PromotionIdentityConflict(
            True,
            (
                f"Für diese Adresse existiert bereits der offizielle Kandidat "
                f"{distinct_official_match.id} mit Händler-ID "
                f"{distinct_official_match.source_external_id}. Bitte diesen "
                "offiziellen Datensatz statt des schwachen OSM/Map-Alias promovieren."
            ),
        )

    canonical = strong_stores[0] if len(strong_stores) == 1 else None
    known = ", ".join(
        f"Store {store.id} / ID {store.external_id or '–'} / {store.address}"
        for store in strong_stores
    )
    return PromotionIdentityConflict(
        True,
        (
            f"Möglicher Doppelmarkt: {candidate.name} ({candidate.address}) ist nur "
            f"über OSM/Map belegt. In PLZ {candidate.postal_code} existiert bereits "
            f"starke Händlerevidenz für {known}. Eine abweichende Map-Adresse und "
            "räumliche Nähe reichen nicht für eine zweite Filiale; dafür ist eine "
            "eigene offizielle Händler-ID oder eindeutige offizielle Quelle nötig."
        ),
        canonical,
    )
