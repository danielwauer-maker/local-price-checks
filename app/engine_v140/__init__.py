"""Benchmarked Local Price Checks 1.4.0 extraction engine.

This namespace is intentionally isolated from the mobile Web-MVP data model while
we migrate the proven REWE/Netto/ALDI parser pipeline. Adapters in the Web app
consume its CollectedOffer output and map it to MasterProduct/Offer records.
"""

# OCR is invoked explicitly by the canonical Lidl manifest pipeline. Keeping it
# out of a runtime monkey patch makes page selection, deadlines and diagnostics
# visible to the collector instead of silently OCRing every viewer page.
