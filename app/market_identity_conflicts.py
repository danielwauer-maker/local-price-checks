from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .coverage_models import StoreDiscoveryCandidate
from .models import Store
from .physical_market_identity import has_strong_retailer_identity, is_osm_external_id, normalized_retailer
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
    """Block a weak map candidate from creating a duplicate Store.

    A candidate is weak here only when its source identity is OSM node/way/
    relation based. If the postcode already contains exactly one stronger Store
    identity for that retailer, the map candidate must either match that Store's
    address or have a matching official retailer candidate proving a distinct
    second branch. Otherwise it stays in onboarding/manual review.
    """
    if not is_osm_external_id(candidate.source_external_id):
        return PromotionIdentityConflict(False)

    stores = [
        store
        for store in db.query(Store).filter(Store.postal_code == candidate.postal_code).all()
        if _same_retailer(store.retailer, candidate.retailer)
        and has_strong_retailer_identity(store)
    ]
    if len(stores) != 1:
        return PromotionIdentityConflict(False)

    canonical = stores[0]
    if addresses_match(canonical.address, candidate.address):
        return PromotionIdentityConflict(False, canonical_store=canonical)

    official_candidates = db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.postal_code == candidate.postal_code,
        StoreDiscoveryCandidate.official_source_verified.is_(True),
        StoreDiscoveryCandidate.source.like("official:%"),
    ).all()
    distinct_official_match = any(
        _same_retailer(row.retailer, candidate.retailer)
        and addresses_match(row.address, candidate.address)
        for row in official_candidates
    )
    if distinct_official_match:
        return PromotionIdentityConflict(False)

    return PromotionIdentityConflict(
        True,
        (
            f"Möglicher Doppelmarkt: {candidate.name} ({candidate.address}) ist nur über "
            f"OSM/Map belegt. In PLZ {candidate.postal_code} existiert bereits die "
            f"starke Händleridentität {canonical.name} (Store {canonical.id}, "
            f"ID {canonical.external_id or '–'}, {canonical.address}). "
            "Für eine zweite Filiale muss zuerst eine eigene offizielle Händlerquelle/Markt-ID bestätigt werden."
        ),
        canonical,
    )
