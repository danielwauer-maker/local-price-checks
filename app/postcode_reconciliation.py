from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata

from sqlalchemy.orm import Session

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
    "no_known_stores": ("Keine Märkte bekannt", "green"),
}

# Manually audited rollout targets. These override only the expected market
# count. The visible/found count is still derived from unique physical markets.
AUDITED_EXPECTED_MARKET_COUNTS: dict[str, int] = {
    # 2x REWE + Lidl + ALDI SÜD + Netto Marken-Discount
    "57610": 5,
    # Manually checked: no supported grocery market in this postcode area.
    "56316": 0,
}

_GENERIC_MARKET_WORDS = {
    "markt",
    "market",
    "supermarkt",
    "filiale",
    "marktcenter",
    "center",
    "gmbh",
    "co",
    "kg",
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


@dataclass
class CandidateGroup:
    representative: StoreDiscoveryCandidate
    members: list[StoreDiscoveryCandidate]

    @property
    def has_official_source(self) -> bool:
        return any(member.source.startswith("official:") for member in self.members)


def _words(value: str | None) -> list[str]:
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", (value or "").casefold().replace("ß", "ss"))
        if not unicodedata.combining(character)
    )
    return re.findall(r"[a-z0-9]+", folded)


def _branch_tokens(candidate: StoreDiscoveryCandidate) -> set[str]:
    ignored = set(_words(candidate.retailer)) | set(_words(candidate.city)) | _GENERIC_MARKET_WORDS
    return {
        word
        for word in _words(candidate.name)
        if word not in ignored and len(word) >= 4 and not word.isdigit()
    }


def _street_key(address: str | None) -> str:
    """Normalize the street part while intentionally ignoring house/road numbers."""
    words = _words(address)
    cleaned: list[str] = []
    for word in words:
        if re.fullmatch(r"\d+[a-z]?", word):
            continue
        if re.fullmatch(r"[blks]\d+", word):
            continue
        if word in {"str", "strasse", "straße"}:
            word = "strasse"
        cleaned.append(word)
    # Joining makes "Urbacherstraße" and "Urbacher Straße" identical while
    # still requiring the actual street name to match.
    return "".join(cleaned)


def _candidate_match_score(left: StoreDiscoveryCandidate, right: StoreDiscoveryCandidate) -> float:
    """Return a confidence score that two source rows describe one branch.

    We only collapse rows for the same retailer and postcode. Official rows are
    never collapsed with another official row; this preserves genuine multi-
    branch cases such as the two REWE markets in Altenkirchen.
    """
    if left.postal_code != right.postal_code:
        return 0.0
    if normalize_identity_text(left.retailer) != normalize_identity_text(right.retailer):
        return 0.0
    if left.source.startswith("official:") and right.source.startswith("official:"):
        return 0.0

    score = 0.0
    if left.matched_store_id is not None and left.matched_store_id == right.matched_store_id:
        score = max(score, 1200.0)
    if addresses_match(left.address, right.address):
        score = max(score, 1000.0)

    left_branch = _branch_tokens(left)
    right_branch = _branch_tokens(right)
    overlap = left_branch & right_branch
    if overlap:
        score = max(score, 600.0 + 20.0 * len(overlap))

    left_street = _street_key(left.address)
    right_street = _street_key(right.address)
    if left_street and left_street == right_street:
        score = max(score, 500.0)

    try:
        distance_m = haversine_km(
            left.latitude,
            left.longitude,
            right.latitude,
            right.longitude,
        ) * 1000.0
    except (TypeError, ValueError):
        distance_m = float("inf")
    if distance_m <= 250.0:
        score = max(score, 450.0 - min(distance_m, 200.0) / 10.0)

    return score


def _representative_quality(candidate: StoreDiscoveryCandidate) -> tuple[int, int, int, int]:
    """Rank duplicate source rows so the admin keeps the most useful one.

    Official retailer records always win. For secondary rows, prefer a safe
    HTTP(S) source link, then verified identity data and finally a linked store.
    This keeps provenance available without letting a malformed URL become the
    visible representative merely because it was inserted first.
    """
    source_url = (candidate.source_url or "").strip().lower()
    safe_http_source = int(source_url.startswith("https://") or source_url.startswith("http://"))
    verified_fields = int(bool(candidate.address_verified)) + int(bool(candidate.coordinates_verified)) + int(bool(candidate.official_source_verified))
    return (
        int(candidate.source.startswith("official:")),
        safe_http_source,
        verified_fields,
        int(candidate.matched_store_id is not None),
    )


def group_physical_candidates(candidates: list[StoreDiscoveryCandidate]) -> list[CandidateGroup]:
    """Collapse source duplicates while keeping distinct physical branches.

    Official retailer rows are preferred as representatives. OSM/secondary rows
    are attached to the strongest matching branch using address, branch name,
    street and close-coordinate evidence. This intentionally keeps raw source
    rows in the database; it only defines the admin/workflow view.
    """
    official = [row for row in candidates if row.source.startswith("official:")]
    secondary = [row for row in candidates if not row.source.startswith("official:")]
    groups = [CandidateGroup(row, [row]) for row in official]

    for row in secondary:
        best_group: CandidateGroup | None = None
        best_score = 0.0
        for group in groups:
            score = max(_candidate_match_score(row, member) for member in group.members)
            if score > best_score:
                best_group = group
                best_score = score
        if best_group is not None and best_score >= 400.0:
            best_group.members.append(row)
            if _representative_quality(row) > _representative_quality(best_group.representative):
                best_group.representative = row
        else:
            groups.append(CandidateGroup(row, [row]))

    return groups


def deduplicate_candidates(candidates: list[StoreDiscoveryCandidate]) -> list[StoreDiscoveryCandidate]:
    """Return one admin-visible candidate per physical market."""
    return [group.representative for group in group_physical_candidates(candidates)]


def candidates_match(expected: StoreDiscoveryCandidate, discovered: StoreDiscoveryCandidate) -> bool:
    return _candidate_match_score(expected, discovered) >= 400.0


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


def _group_matches_store(group: CandidateGroup, store: Store) -> bool:
    return any(store_matches_candidate(store, member) for member in group.members)


def reconcile_postcode_coverage(
    db: Session,
    postcode: CoveragePostalCode,
    *,
    source_results: tuple[RetailerSourceResult, ...] | None = None,
) -> PostcodeCoverageSummary:
    candidates = db.query(StoreDiscoveryCandidate).filter_by(postal_code=postcode.postal_code).all()
    groups = group_physical_candidates(candidates)
    postcode_stores = db.query(Store).filter(Store.postal_code == postcode.postal_code).all()

    baseline_expected = sum(group.has_official_source for group in groups)
    audited_target = AUDITED_EXPECTED_MARKET_COUNTS.get(postcode.postal_code)
    expected = max(baseline_expected, audited_target) if audited_target is not None else baseline_expected
    found = len(groups)

    address_verified = sum(any(row.address_verified for row in group.members) for group in groups)
    coordinates_verified = sum(any(row.coordinates_verified for row in group.members) for group in groups)
    official_verified = sum(
        any(row.official_source_verified or row.source.startswith("official:") for row in group.members)
        for group in groups
    )
    promoted = sum(
        any(_group_matches_store(group, store) for store in postcode_stores)
        for group in groups
    )

    missing_expected = max(0, expected - found)
    additional_discovered = max(0, found - expected)

    results = source_results or retailer_source_results(postcode.postal_code)
    incomplete_sources = any(
        result.status in {"manual_verification_required", "source_unavailable"} for result in results
    )

    if not postcode.enabled:
        status = "disabled"
    elif audited_target == 0 and not groups and not postcode_stores:
        status = "no_known_stores"
    elif missing_expected:
        status = "incomplete"
    elif expected == 0 and found == 0 and incomplete_sources:
        status = "source_unavailable"
    elif expected == 0 and found == 0:
        status = "no_expected_stores"
    elif (
        additional_discovered
        or address_verified < found
        or coordinates_verified < found
        or official_verified < found
        or promoted < found
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
