from __future__ import annotations

from .models import Store
from .web_offer_audit import WebAuditError
from .edeka_fellenzer_offer_audit import FELLENZER_MARKET_ID, fetch_fellenzer_offers
from .edeka_web_offer_api_audit import (
    _persist_edeka_result,
    run_web_offer_audit as run_legacy_edeka_audit,
)
from .edeka_web_offer_category_audit import _fetch_all_categories


def _market_id(store: Store) -> str:
    return "".join(character for character in str(store.external_id or "") if character.isdigit())


def run_web_offer_audit(db, store: Store, period_key: str = "current", source_url: str | None = None):
    """Run EDEKA audits from the strongest source without regressing to zero.

    Puderbach/Fellenzer uses the retailer's official local store site first.
    The category-aware central API remains the preferred generic EDEKA path.
    If EDEKA omits category/facet metadata or category completion cannot be
    proven, fall back to the established API collector instead of persisting a
    zero-offer failure.  No path writes public Offer rows.
    """
    if store.retailer != "EDEKA":
        return run_legacy_edeka_audit(db, store, period_key=period_key, source_url=source_url)

    if _market_id(store) == FELLENZER_MARKET_ID:
        try:
            result = fetch_fellenzer_offers(store)
            return _persist_edeka_result(db, store, period_key, result)
        except WebAuditError:
            # The local official source is preferred but must never take the
            # whole audit down.  Continue with the generic EDEKA sources.
            pass

    try:
        result = _fetch_all_categories(store)
        return _persist_edeka_result(db, store, period_key, result)
    except WebAuditError:
        # Category completeness is an enhancement.  Missing facets or an
        # endpoint change must not turn a previously usable API snapshot into
        # a zero-offer run.
        return run_legacy_edeka_audit(db, store, period_key=period_key, source_url=source_url)
