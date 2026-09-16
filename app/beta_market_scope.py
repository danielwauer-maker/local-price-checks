"""Central product scope for the current postcode beta.

Discovery intentionally supports more retailers.  This module only defines
which physical markets participate in beta coverage/readiness calculations.
"""

from __future__ import annotations


BETA_RETAILERS: tuple[str, ...] = (
    "REWE",
    "EDEKA",
    "ALDI SÜD",
)

_BETA_RETAILER_SET = frozenset(BETA_RETAILERS)


def is_beta_retailer(retailer: str | None) -> bool:
    """Return whether a canonical retailer name belongs to the beta scope."""
    return retailer in _BETA_RETAILER_SET
