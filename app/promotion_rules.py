from __future__ import annotations

from dataclasses import dataclass
import math
import re


_PERCENT_PATTERNS = (
    re.compile(r"(?:-|−)\s*(\d{1,2}(?:[.,]\d+)?)\s*%", re.I),
    re.compile(r"\b(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:rabatt|günstiger|guenstiger|sparen|ersparnis)\b", re.I),
)
_FREE_ITEM_PATTERNS = (
    re.compile(r"\b(\d{1,2})\s*für\s*(\d{1,2})(?![.,]\d)\b", re.I),
    re.compile(r"\b(\d{1,2})\s*(?:zum\s+preis\s+von|zahlen\s+nur)\s*(\d{1,2})(?![.,]\d)\b", re.I),
)
_PLUS_FREE_RE = re.compile(r"\b(\d{1,2})\s*\+\s*(\d{1,2})\s*(?:gratis|kostenlos)\b", re.I)
_FIXED_BUNDLE_RE = re.compile(
    r"\b(\d{1,2})\s*(?:stück\s*)?(?:für|nur)\s*(?:€\s*)?(\d{1,3}[,.]\d{2})\s*€?\b",
    re.I,
)
_TIER_PRICE_RE = re.compile(
    r"\b(?:ab|ar)\s*(\d{1,2})\s*(?:stück|stk\.?)\b[^\d€]{0,24}(\d{1,3}[,.]\d{2})\s*€?",
    re.I,
)
_EXPLICIT_UNIT_PRICE_RE = re.compile(
    r"(?:\bje(?:\s+(?:stück|stk\.?|packung|croissant|brötchen|artikel))?\s*|\beinzelpreis\s*)"
    r"(?:€\s*)?(\d{1,3}[,.]\d{2})\s*€?",
    re.I,
)
_MULTIBUY_SIGNAL_RE = re.compile(
    r"(?:\b\d{1,2}\s*\+\s*\d{1,2}\s*(?:gratis|kostenlos)\b|"
    r"\b\d{1,2}\s*(?:für|zum\s+preis\s+von|zahlen\s+nur)\s*\d{1,2}(?![.,]\d)\b|"
    r"\b\d{1,2}\s*(?:stück\s*)?(?:für|nur)\s*€?\s*\d{1,3}[,.]\d{2}\b|"
    r"\b(?:ab|ar)\s*\d{1,2}\s*(?:stück|stk\.?)\b)",
    re.I,
)
_SPECIAL_PRICE_RE = re.compile(
    r"SPECIAL_PRICE\s+kind=([a-z0-9_+-]+)\s+label=(.+?)\s+price=(\d{1,3}[.,]\d{2})(?:\s|$)",
    re.I,
)


@dataclass(frozen=True)
class PromotionInfo:
    kind: str
    buy_quantity: int | None = None
    pay_quantity: int | None = None
    bundle_price: float | None = None
    regular_bundle_price: float | None = None
    effective_unit_price: float | None = None
    savings_amount: float | None = None
    discount_percent: float | None = None
    label: str | None = None
    confidence: float = 1.0
    special_price: float | None = None
    minimum_quantity: int | None = None

    @property
    def valid(self) -> bool:
        if self.kind == "free_item":
            return bool(
                self.buy_quantity
                and self.pay_quantity
                and self.buy_quantity > self.pay_quantity > 0
                and self.bundle_price is not None
                and self.regular_bundle_price is not None
                and self.bundle_price > 0
                and self.regular_bundle_price > self.bundle_price
            )
        if self.kind == "fixed_bundle":
            return bool(self.buy_quantity and self.buy_quantity > 1 and self.bundle_price and self.bundle_price > 0)
        if self.kind in {"member_price", "lidl_plus", "app_price", "loyalty_price", "tier_price"}:
            return bool(
                self.bundle_price is not None
                and self.special_price is not None
                and 0 < self.special_price < self.bundle_price
                and (self.kind != "tier_price" or (self.minimum_quantity or 0) >= 2)
            )
        return False


def extract_discount_percent(text: str | None) -> float | None:
    value = text or ""
    for pattern in _PERCENT_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        try:
            percent = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if 0.5 <= percent <= 90:
            return round(percent, 1)
    return None


def _psychological_price(raw: float) -> float:
    if raw <= 0:
        return raw
    euro = math.floor(raw)
    endings = [0.09, 0.19, 0.29, 0.39, 0.49, 0.59, 0.69, 0.79, 0.89, 0.99]
    candidates = []
    for base in {max(0, euro - 1), euro, euro + 1}:
        candidates.extend(base + ending for ending in endings)
    best = min(candidates, key=lambda value: abs(value - raw))
    tolerance = max(0.06, raw * 0.035)
    return round(best if abs(best - raw) <= tolerance else raw, 2)


def infer_reference_price(offer_price: float, discount_percent: float | None) -> float | None:
    if discount_percent is None or not (0 < discount_percent < 95) or offer_price <= 0:
        return None
    raw = offer_price / (1.0 - discount_percent / 100.0)
    inferred = _psychological_price(raw)
    return inferred if inferred > offer_price else None


def has_multibuy_signal(text: str | None) -> bool:
    return bool(_MULTIBUY_SIGNAL_RE.search(text or ""))


def _explicit_unit_price(text: str) -> float | None:
    match = _EXPLICIT_UNIT_PRICE_RE.search(text or "")
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return value if 0.01 <= value <= 500 else None


def _free_item_unit_price(text: str, regular_price: float | None) -> float | None:
    explicit = _explicit_unit_price(text)
    if explicit is not None:
        return explicit
    if regular_price is not None and regular_price > 0:
        return regular_price
    return None


def _free_item_info(text: str, buy: int, paid: int, regular_price: float | None) -> PromotionInfo | None:
    if not (1 <= paid < buy <= 24):
        return None
    unit = _free_item_unit_price(text, regular_price)
    if unit is None:
        return None
    regular_total = round(unit * buy, 2)
    bundle = round(unit * paid, 2)
    savings = round(regular_total - bundle, 2)
    return PromotionInfo(
        kind="free_item",
        buy_quantity=buy,
        pay_quantity=paid,
        bundle_price=bundle,
        regular_bundle_price=regular_total,
        effective_unit_price=round(bundle / buy, 4),
        savings_amount=savings,
        discount_percent=round((1 - bundle / regular_total) * 100, 1),
        label=f"{buy} für {paid}",
        confidence=0.99,
    )


def _special_price_info(text: str, offer_price: float | None) -> PromotionInfo | None:
    if offer_price is None or offer_price <= 0:
        return None
    matches = list(_SPECIAL_PRICE_RE.finditer(text or ""))
    if not matches:
        return None
    match = matches[-1]
    try:
        special = float(match.group(3).replace(",", "."))
    except ValueError:
        return None
    if not 0 < special < float(offer_price):
        return None
    raw_kind = match.group(1).lower()
    base_label = re.sub(r"\s+", " ", match.group(2)).strip()
    kind = "lidl_plus" if raw_kind == "lidl_plus" else "member_price"
    label = base_label or ("Lidl Plus" if kind == "lidl_plus" else "Vorteilspreis")
    return PromotionInfo(
        kind=kind,
        bundle_price=round(float(offer_price), 2),
        special_price=round(special, 2),
        savings_amount=round(float(offer_price) - special, 2),
        discount_percent=None,
        label=f"{label} · {special:.2f} €".replace(".", ","),
        confidence=1.0,
    )


def _tier_price_info(text: str, offer_price: float | None) -> PromotionInfo | None:
    if offer_price is None or offer_price <= 0:
        return None
    match = _TIER_PRICE_RE.search(text or "")
    if not match:
        return None
    minimum = int(match.group(1))
    special = float(match.group(2).replace(",", "."))
    if not 2 <= minimum <= 24 or not 0 < special < float(offer_price):
        return None
    return PromotionInfo(
        kind="tier_price",
        bundle_price=round(float(offer_price), 2),
        special_price=round(special, 2),
        minimum_quantity=minimum,
        savings_amount=round(float(offer_price) - special, 2),
        label=f"ab {minimum} Stück · {special:.2f} €".replace(".", ","),
        confidence=0.99,
    )


def parse_multibuy(
    text: str | None,
    *,
    offer_price: float | None,
    regular_price: float | None = None,
) -> PromotionInfo | None:
    value = text or ""
    special = _special_price_info(value, offer_price)
    if special is not None:
        return special
    tier = _tier_price_info(value, offer_price)
    if tier is not None:
        return tier

    if not has_multibuy_signal(value):
        return None

    plus = _PLUS_FREE_RE.search(value)
    if plus:
        paid = int(plus.group(1))
        free = int(plus.group(2))
        info = _free_item_info(value, paid + free, paid, regular_price)
        return info if info and info.valid else None

    for pattern in _FREE_ITEM_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        buy = int(match.group(1))
        paid = int(match.group(2))
        info = _free_item_info(value, buy, paid, regular_price)
        if info and info.valid:
            return info
        return None

    fixed = _FIXED_BUNDLE_RE.search(value)
    if fixed:
        buy = int(fixed.group(1))
        bundle = float(fixed.group(2).replace(",", "."))
        if not (2 <= buy <= 24) or bundle <= 0:
            return None
        normal_unit = regular_price if regular_price and regular_price > 0 else None
        regular_total = round(normal_unit * buy, 2) if normal_unit else None
        savings = round(regular_total - bundle, 2) if regular_total and regular_total > bundle else None
        discount = round((1 - bundle / regular_total) * 100, 1) if regular_total and regular_total > bundle else None
        return PromotionInfo(
            kind="fixed_bundle",
            buy_quantity=buy,
            bundle_price=round(bundle, 2),
            regular_bundle_price=regular_total,
            effective_unit_price=round(bundle / buy, 4),
            savings_amount=savings,
            discount_percent=discount,
            label=f"{buy} für {bundle:.2f} €".replace(".", ","),
            confidence=0.98,
        )

    return None


def promotion_payload(info: PromotionInfo | None) -> dict | None:
    if info is None or not info.valid:
        return None
    return {
        "kind": info.kind,
        "buyQuantity": info.buy_quantity,
        "payQuantity": info.pay_quantity,
        "bundlePrice": info.bundle_price,
        "regularBundlePrice": info.regular_bundle_price,
        "effectiveUnitPrice": info.effective_unit_price,
        "savingsAmount": info.savings_amount,
        "discountPercent": info.discount_percent,
        "label": info.label,
        "confidence": info.confidence,
        "specialPrice": info.special_price,
        "minimumQuantity": info.minimum_quantity,
    }
