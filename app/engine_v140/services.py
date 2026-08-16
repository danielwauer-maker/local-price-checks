import re
from datetime import date
from itertools import combinations

ONLINE_ONLY_PATTERNS = [
    r"nur\s+online",
    r"online\s*only",
    r"ausschlie(?:ß|ss)lich\s+online",
    r"nur\s+im\s+onlineshop",
    r"nur\s+im\s+online-shop",
    r"nur\s+per\s+versand",
    r"versandangebot",
    r"onlinebestellung\s+erforderlich",
    r"nur\s+online\s+bestellbar",
    r"webshop\s*only",
]
SAFE_WEB_CONTEXT = ["prospekt", "angebote", "marktseite"]

def classify_offer(source_text: str = "", source_url: str | None = None):
    text = " ".join(filter(None, [source_text, source_url or ""])).lower()
    for p in ONLINE_ONLY_PATTERNS:
        if re.search(p, text, flags=re.I):
            return False, f"online_only:{p}"
    return True, "local_or_unspecified"

def effective_price(offer):
    return offer.unit_price if offer.unit_price is not None else offer.price

def optimize_items(items, offers, max_stores=2):
    candidates = {}
    for item in items:
        rows = []
        for o in offers:
            if not o.local_store_offer:
                continue
            if o.product.category.lower() != item.category.lower():
                continue
            if item.exact_brand and item.preferred_brand:
                if (o.product.brand or "").lower() != item.preferred_brand.lower():
                    continue
            rows.append(o)
        candidates[item.id] = rows
    store_ids = sorted({o.store_id for rows in candidates.values() for o in rows})
    if not store_ids:
        return None
    best = None
    for count in range(1, min(max_stores, len(store_ids)) + 1):
        for combo in combinations(store_ids, count):
            picks, total = [], 0.0
            feasible = True
            for item in items:
                opts = [o for o in candidates[item.id] if o.store_id in combo]
                if not opts:
                    feasible = False
                    break
                chosen = min(opts, key=lambda o: o.price)
                picks.append((item, chosen))
                total += chosen.price * item.quantity_needed
            if feasible:
                score = (round(total,2), count)
                if best is None or score < best["score"]:
                    best = {"score": score, "total": round(total,2), "store_ids": combo, "picks": picks}
    return best
