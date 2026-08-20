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

# Deeply nested page OCR/accessibility metadata contains the page-level context
# needed to distinguish local leaflet content from shop-only product links.
from .lidl_schwarz_hardening import install as _install_lidl_schwarz_hardening

_install_lidl_schwarz_hardening()

# OCR is invoked explicitly by the canonical Lidl manifest pipeline. Keeping it
# out of a runtime monkey patch makes page selection, deadlines and diagnostics
# visible to the collector instead of silently OCRing every viewer page.
