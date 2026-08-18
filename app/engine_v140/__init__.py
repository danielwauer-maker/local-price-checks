"""Benchmarked Local Price Checks 1.4.0 extraction engine.

This namespace is intentionally isolated from the mobile Web-MVP data model while
we migrate the proven REWE/Netto/ALDI parser pipeline. Adapters in the Web app
consume its CollectedOffer output and map it to MasterProduct/Offer records.
"""

# Lidl's live viewer currently exposes its production data through the Schwarz
# leaflet API (`/v4/flyer`). Install the production-specific bridge before
# lidl_flipbook imports `manifest_offers`, while retaining the generic parser as
# a fallback for older/other manifest shapes.
from .lidl_schwarz_runtime import install as _install_lidl_schwarz_runtime

_install_lidl_schwarz_runtime()
