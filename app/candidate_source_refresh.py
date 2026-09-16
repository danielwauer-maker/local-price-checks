from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Mapping

from .coverage_models import StoreDiscoveryCandidate


# These fields describe the physical-market identity. Once an operator has
# verified/promoted that identity, a later provider refresh is evidence to
# review, not permission to silently rewrite the accepted market.
IDENTITY_FIELDS: tuple[str, ...] = (
    "postal_code",
    "retailer",
    "name",
    "address",
    "city",
    "latitude",
    "longitude",
    "source_external_id",
)

_SOURCE_DRIFT_MARKER = "[source-refresh-drift]"
_COORDINATE_ABS_TOLERANCE = 1e-6


def candidate_identity_is_locked(candidate: StoreDiscoveryCandidate) -> bool:
    """Return whether source refreshes must preserve the accepted identity."""
    return bool(
        candidate.matched_store_id is not None
        or candidate.status in {"verified", "promoted"}
        or candidate.address_verified
        or candidate.coordinates_verified
    )


def _base_verification_note(note: str | None) -> str:
    parts = [part.strip() for part in (note or "").split(" | ") if part.strip()]
    return " | ".join(part for part in parts if not part.startswith(_SOURCE_DRIFT_MARKER))


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    if value is None:
        return "–"
    return str(value)


def _identity_value_changed(field: str, old: Any, new: Any) -> bool:
    if field in {"latitude", "longitude"} and old is not None and new is not None:
        try:
            return not math.isclose(
                float(old),
                float(new),
                rel_tol=0.0,
                abs_tol=_COORDINATE_ABS_TOLERANCE,
            )
        except (TypeError, ValueError):
            return old != new
    return old != new


def refresh_candidate_from_source(
    candidate: StoreDiscoveryCandidate,
    values: Mapping[str, Any],
    *,
    reset_verification_on_identity_change: bool,
) -> bool:
    """Refresh one discovery row without overwriting accepted identity.

    Returns ``True`` when incoming source data differs from a locked identity.
    In that case the accepted identity/gates remain untouched and the drift is
    recorded in ``verification_note`` for operator review. Non-identity
    provenance such as ``source_url`` may still refresh safely.
    """
    identity_changes = {
        field: (getattr(candidate, field), values[field])
        for field in IDENTITY_FIELDS
        if field in values
        and _identity_value_changed(field, getattr(candidate, field), values[field])
    }
    locked = candidate_identity_is_locked(candidate)

    # Source URL is provenance rather than physical identity. Keep it fresh even
    # when identity fields are locked so the admin can inspect the newest source.
    if "source_url" in values:
        candidate.source_url = values["source_url"]

    if identity_changes and locked:
        details = "; ".join(
            f"{field}: {_format_value(old)} -> {_format_value(new)}"
            for field, (old, new) in identity_changes.items()
        )
        base = _base_verification_note(candidate.verification_note)
        drift = f"{_SOURCE_DRIFT_MARKER} Quellenabweichung erkannt; bestätigte Identität beibehalten: {details}"
        candidate.verification_note = f"{base} | {drift}" if base else drift
        candidate.updated_at = datetime.utcnow()
        return True

    for field, value in values.items():
        if field == "source_url":
            continue
        setattr(candidate, field, value)

    # If a prior drift has disappeared because the source now agrees with the
    # accepted candidate, clear only our machine-written marker.
    candidate.verification_note = _base_verification_note(candidate.verification_note) or None

    if identity_changes and reset_verification_on_identity_change:
        candidate.address_verified = False
        candidate.coordinates_verified = False
        candidate.status = "discovered"
        candidate.verified_at = None

    candidate.updated_at = datetime.utcnow()
    return False
