from __future__ import annotations

from .edeka_multi_source_audit import fetch_combined_edeka
from .edeka_web_offer_api_audit import (
    _persist_edeka_result,
    run_web_offer_audit as run_legacy_edeka_audit,
)
from .models import Store
from .web_offer_audit import WebAuditError


def run_web_offer_audit(db, store: Store, period_key: str = "current", source_url: str | None = None):
    """Run EDEKA audit as central-primary plus optional local supplement.

    The central EDEKA market source is always collected first.  For verified
    markets with an official local merchant source (currently Fellenzer
    071378), local offers are added afterwards and conservative cross-source
    deduplication keeps overlaps visible only once.  No path writes public
    Offer rows.
    """
    if store.retailer != "EDEKA":
        return run_legacy_edeka_audit(db, store, period_key=period_key, source_url=source_url)

    try:
        result = fetch_combined_edeka(store)
        return _persist_edeka_result(db, store, period_key, result)
    except WebAuditError:
        # The established EDEKA central API remains the final diagnostic
        # fallback; local-source failures must never take the audit down.
        return run_legacy_edeka_audit(db, store, period_key=period_key, source_url=source_url)
