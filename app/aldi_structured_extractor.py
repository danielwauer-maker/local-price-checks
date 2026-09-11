from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .engine_v140.collectors import CollectedOffer, best_img, cat, infer_validity, size
from .engine_v140.price_units import compute_unit_price
from .engine_v140.week_utils import parse_any_date


_SAVING_PAIR_RE = re.compile(
    r"\bSpare\s+\d{1,2}\s*%\s*(\d{1,3}[.,]\d{2})\s*€(?:\s*[²*]?\s*)(\d{1,3}[.,]\d{2})\s*€",
    re.IGNORECASE,
)
_SIZE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stück|stk\.?)\b", re.I)
_UNIT_ONLY_RE = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stück|stk\.?)\b", re.I)
_UNIT_PRICE_RE = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml)\s*\([^)]*€/\s*1?\s*(?:kg|g|l|ml)", re.I)
_PRICE_RE = re.compile(r"\d{1,3}[.,]\d{2}\s*€")
_DEPOSIT_RE = re.compile(
    r"(?:(\d{1,3}[.,]\d{2})\s*€\s*\+?\s*(?:Pfand|Mehrweg|Einweg)|(?:Pfand|Mehrweg|Einweg)\s*(\d{1,3}[.,]\d{2})\s*€)",
    re.I,
)
_NAV_PREFIX_RE = re.compile(r"^(?:alle\s+anzeigen\s+)+", re.I)
_ALDI_EXPLICIT_WEEK_RE = re.compile(
    r"\bWochenangebote\s+(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?,?\s*"
    r"(\d{1,2}\.\d{1,2}\.?)\s*[–-]\s*"
    r"(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?,?\s*(\d{1,2}\.\d{1,2}\.?)",
    re.I,
)
_CATEGORY_LABELS = {
    "aktion",
    "kühlung",
    "tiefkühlung",
    "vegan",
    "bio",
    "regional",
}


def _norm(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _deposit_values(text: str) -> set[float]:
    values: set[float] = set()
    for match in _DEPOSIT_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2)
        if raw:
            values.add(float(raw.replace(",", ".")))
    return values


def _explicit_aldi_week_window(text: str):
    """Return an explicit ALDI weekly range without guessing missing dates."""
    valid_from, valid_to, _, _ = infer_validity(text or "")
    if valid_from and valid_to:
        return valid_from, valid_to

    match = _ALDI_EXPLICIT_WEEK_RE.search(text or "")
    if not match:
        return None, None
    start = parse_any_date(match.group(1))
    end = parse_any_date(match.group(2))
    if not start or not end:
        return None, None
    if end < start:
        try:
            end = end.replace(year=start.year + 1)
        except ValueError:
            return None, None
    duration = end - start
    if duration < timedelta(0) or duration > timedelta(days=7):
        return None, None
    return start, end


def _container_for_saving_marker(node: Tag) -> Tag | None:
    """Return the smallest DOM ancestor that contains exactly one saving pair."""
    current: Tag | None = node
    for _ in range(12):
        if current is None or current.name in {"html", "body"}:
            break
        text = _norm(current.get_text(" ", strip=True))
        pairs = list(_SAVING_PAIR_RE.finditer(text))
        if len(pairs) == 1 and _SIZE_RE.search(text):
            return current
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return None


def _clean_title_part(value: str) -> str:
    value = _NAV_PREFIX_RE.sub("", _norm(value)).strip(" ·|:-")
    return value


def _is_noise_part(value: str) -> bool:
    lowered = value.lower().strip()
    if not lowered:
        return True
    if lowered in _CATEGORY_LABELS:
        return True
    if lowered.startswith("spare "):
        return True
    if _PRICE_RE.search(value):
        return True
    if _UNIT_PRICE_RE.search(value):
        return True
    return False


def _title_from_card(card: Tag) -> str | None:
    """Build a concrete title even when ALDI splits name and pack size across nodes.

    The live ALDI cards render product name, pack size and calculated quantity in
    separate DOM nodes. The first v2 parser required name+size inside one text
    node and therefore collapsed to almost no rows. We now select the first
    package token before the saving marker and attach the nearest meaningful
    product/brand nodes, while still staying inside the isolated card.
    """
    parts = [_clean_title_part(part) for part in card.stripped_strings]
    parts = [part for part in parts if part]
    marker_idx = next(
        (i for i, part in enumerate(parts) if re.search(r"\bSpare\s+\d{1,2}\s*%", part, re.I)),
        len(parts),
    )
    before = parts[:marker_idx]

    # Existing compact cards: title and package are already one node.
    for idx, raw in enumerate(before):
        if not _SIZE_RE.search(raw) or _UNIT_ONLY_RE.search(raw) or _is_noise_part(raw):
            continue
        if not any(ch.isalpha() for ch in raw):
            continue
        if idx > 0:
            previous = _clean_title_part(before[idx - 1])
            if (
                3 <= len(previous) <= 48
                and raw.lower().startswith(previous.lower() + " ")
                and not _SIZE_RE.search(previous)
            ):
                raw = raw[len(previous) :].strip(" ·|:-")
        return raw[:180] if len(raw) >= 3 else None

    # Live DOM: e.g. "Rinder-Cevapcici" / "400 g" / "0,4 kg (...)".
    # Use the earliest size-only node; later ones are usually normalized unit
    # quantity or unit-price text. Attach at most two nearest textual nodes so a
    # brand can be retained without pulling navigation/category labels.
    size_idx = next(
        (
            i
            for i, raw in enumerate(before)
            if _SIZE_RE.search(raw) and _UNIT_ONLY_RE.search(raw) and not _UNIT_PRICE_RE.search(raw)
        ),
        None,
    )
    if size_idx is None:
        return None

    pack = before[size_idx]
    prefix_parts: list[str] = []
    for raw in reversed(before[:size_idx]):
        candidate = _clean_title_part(raw)
        if _is_noise_part(candidate) or _SIZE_RE.search(candidate):
            continue
        if not any(ch.isalpha() for ch in candidate):
            continue
        prefix_parts.append(candidate)
        if len(prefix_parts) >= 2:
            break
    prefix_parts.reverse()
    if not prefix_parts:
        return None

    name = _norm(" ".join([*prefix_parts, pack]))
    return name[:180] if len(name) >= 4 else None


def _card_image(
    card: Tag,
    base_url: str,
    product_name: str,
    all_images: list[dict],
) -> tuple[str | None, str | None]:
    for img in card.find_all("img"):
        alt = _norm(str(img.get("alt") or ""))
        raw_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not raw_url:
            srcset = str(img.get("srcset") or img.get("data-srcset") or "")
            if srcset:
                raw_url = srcset.split(",")[0].strip().split(" ")[0]
        if raw_url:
            return urljoin(base_url, str(raw_url)), alt or product_name

    fallback = best_img(all_images or [], product_name)
    if fallback:
        return fallback.get("url"), fallback.get("alt")
    return None, None


def parse_aldi_offer_cards(
    source,
    html: str,
    visible_text: str,
    all_images: list[dict] | None = None,
):
    """Parse ALDI stationary offers from isolated DOM cards.

    Fail closed when a card cannot provide one unambiguous saving pair, a
    concrete package-bearing product title, package size, or explicit weekly
    validity. Deposit amounts are never accepted as promotional prices.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    valid_from, valid_to = _explicit_aldi_week_window(visible_text or "")
    if not valid_from or not valid_to:
        return []
    vf = valid_from.strftime("%d.%m.%Y")
    vt = valid_to.strftime("%d.%m.%Y")

    cards: list[Tag] = []
    seen_nodes: set[int] = set()
    for text_node in soup.find_all(string=re.compile(r"\bSpare\s+\d{1,2}\s*%", re.I)):
        parent = text_node.parent
        if not isinstance(parent, Tag):
            continue
        card = _container_for_saving_marker(parent)
        if card is None or id(card) in seen_nodes:
            continue
        seen_nodes.add(id(card))
        cards.append(card)

    result = []
    seen = set()
    for card in cards:
        block = _norm(card.get_text(" ", strip=True))
        pair = _SAVING_PAIR_RE.search(block)
        if not pair:
            continue
        promo = float(pair.group(1).replace(",", "."))
        regular = float(pair.group(2).replace(",", "."))
        if promo <= 0 or regular <= promo or promo in _deposit_values(block):
            continue

        name = _title_from_card(card)
        if not name:
            continue
        quantity, unit = size(name)
        if quantity is None or not unit:
            continue

        unit_price, unit_price_unit = compute_unit_price(promo, quantity, unit)
        image_url, image_alt = _card_image(card, source.url, name, all_images or [])
        offer = CollectedOffer(
            source.key,
            source.store_name,
            source.retailer,
            name,
            cat(name),
            promo,
            regular_price=regular,
            unit_price=unit_price,
            unit_price_unit=unit_price_unit,
            quantity=quantity,
            unit=unit,
            valid_from=vf,
            valid_to=vt,
            source_text=block,
            source_url=source.url,
            image_url=image_url,
            image_alt=image_alt,
            confidence=.99,
        )
        key = (name.lower(), promo, quantity, unit, vf, vt)
        if key not in seen:
            seen.add(key)
            result.append(offer)
    return result
