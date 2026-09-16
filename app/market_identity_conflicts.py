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


def _official_group_existing_store_conflict(
    db: Session,
    candidate: StoreDiscoveryCandidate,
) -> PromotionIdentityConflict:
    """Fail closed when one physical source group already maps to multiple Stores.

    Official promotion may legitimately reuse a legacy Store that is only linked
    through a sibling OSM/secondary candidate. Before choosing that Store, count
    every existing Store that has credible identity evidence from any member of
    the same physical candidate group. Exact-address evidence is intentionally
    included for ambiguity detection even when two non-OSM external IDs differ:
    that conflict must be reconciled explicitly rather than silently preferring
    one Store and mutating it.
    """
    if is_osm_external_id(candidate.source_external_id):
        return PromotionIdentityConflict(False)

    # Local import avoids a module cycle during application startup.
    from .postcode_reconciliation import group_physical_candidates, store_matches_candidate

    postcode_candidates = db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.postal_code == candidate.postal_code
    ).all()
    physical_members = [candidate]
    for group in group_physical_candidates(postcode_candidates):
        if any(member.id == candidate.id for member in group.members):
            physical_members = group.members
            break

    # A lone official candidate with a different official ID is allowed to
    # represent a genuine second branch, even at the same postal address.
    # Ambiguity only exists when multiple source rows already describe one
    # physical market and those rows point at different existing Stores.
    if len(physical_members) < 2:
        return PromotionIdentityConflict(False)

    postcode_stores = [
        store
        for store in db.query(Store).filter(
            Store.postal_code == candidate.postal_code
        ).all()
        if _same_retailer(store.retailer, candidate.retailer)
    ]

    possible_matches: list[Store] = []
    for store in postcode_stores:
        strict_match = any(
            store_matches_candidate(store, member)
            for member in physical_members
        )
        address_evidence = any(
            addresses_match(store.address, member.address)
            for member in physical_members
        )
        if strict_match or address_evidence:
            possible_matches.append(store)

    if len(possible_matches) <= 1:
        return PromotionIdentityConflict(False)

    known = ", ".join(
        f"Store {store.id} / ID {store.external_id or '–'} / {store.address}"
        for store in possible_matches
    )
    return PromotionIdentityConflict(
        True,
        (
            "Mehrere bestehende Stores passen zu diesem physischen Markt: "
            f"{known}. Bitte Marktidentitäten zuerst bereinigen; die Promotion "
            "wählt bei widersprüchlicher Bestandsidentität niemals automatisch "
            "einen Store aus."
        ),
    )


def weak_candidate_promotion_conflict(
    db: Session,
    candidate: StoreDiscoveryCandidate,
) -> PromotionIdentityConflict:
    """Fail closed before source ambiguity can create or reinforce duplicates."""
    official_group_conflict = _official_group_existing_store_conflict(db, candidate)
    if official_group_conflict.blocked:
        return official_group_conflict

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
