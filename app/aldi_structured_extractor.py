from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .engine_v140.collectors import CollectedOffer, best_img, cat, infer_validity, size
from .engine_v140.price_units import compute_unit_price


_SAVING_PAIR_RE = re.compile(
    r"\bSpare\s+\d{1,2}\s*%\s*(\d{1,3}[.,]\d{2})\s*€(?:\s*[²*]?\s*)(\d{1,3}[.,]\d{2})\s*€",
    re.IGNORECASE,
)
_SIZE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stück|stk\.?)\b", re.I)
_UNIT_ONLY_RE = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stück|stk\.?)\b", re.I)
_PRICE_RE = re.compile(r"\d{1,3}[.,]\d{2}\s*€")
_DEPOSIT_RE = re.compile(
    r"(?:(\d{1,3}[.,]\d{2})\s*€\s*\+?\s*(?:Pfand|Mehrweg|Einweg)|(?:Pfand|Mehrweg|Einweg)\s*(\d{1,3}[.,]\d{2})\s*€)",
    re.I,
)
_NAV_PREFIX_RE = re.compile(r"^(?:alle\s+anzeigen\s+)+", re.I)


def _norm(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _deposit_values(text: str) -> set[float]:
    values: set[float] = set()
    for match in _DEPOSIT_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2)
        if raw:
            values.add(float(raw.replace(",", ".")))
    return values


def _container_for_saving_marker(node: Tag) -> Tag | None:
    """Return the smallest DOM ancestor that contains exactly one saving pair.

    The old ALDI parser flattened the entire page and could therefore borrow a
    price/title from a neighboring card. By selecting the smallest ancestor
    with one complete ``Spare … promo regular`` pair, every parsed row is
    bounded to one concrete DOM card.
    """
    current: Tag | None = node
    best: Tag | None = None
    for _ in range(10):
        if current is None or current.name in {"html", "body"}:
            break
        text = _norm(current.get_text(" ", strip=True))
        pairs = list(_SAVING_PAIR_RE.finditer(text))
        if len(pairs) == 1 and _SIZE_RE.search(text):
            best = current
            break
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return best


def _title_from_card(card: Tag) -> str | None:
    parts = [_norm(part) for part in card.stripped_strings if _norm(part)]
    marker_idx = next((i for i, part in enumerate(parts) if re.search(r"\bSpare\s+\d{1,2}\s*%", part, re.I)), len(parts))
    before = parts[:marker_idx]

    # Prefer the nearest package-bearing textual node. Pure quantity/unit-price
    # lines start with a number and are not product identities.
    for idx in range(len(before) - 1, -1, -1):
        raw = _NAV_PREFIX_RE.sub("", before[idx]).strip(" ·|:-")
        if not _SIZE_RE.search(raw) or _UNIT_ONLY_RE.search(raw):
            continue
        if _PRICE_RE.search(raw) and raw.count("€") >= 2:
            continue
        if not any(ch.isalpha() for ch in raw):
            continue

        # If a short preceding label is repeated as a prefix in the selected
        # node (for example ``Kühlung BBQ``), remove only that exact repeated
        # label. This is structural de-duplication, not category guessing.
        if idx > 0:
            previous = _NAV_PREFIX_RE.sub("", before[idx - 1]).strip(" ·|:-")
            if 3 <= len(previous) <= 48 and raw.lower().startswith(previous.lower() + " ") and not _SIZE_RE.search(previous):
                raw = raw[len(previous) :].strip(" ·|:-")
        return raw[:180] if len(raw) >= 3 else None

    return None


def _card_image(card: Tag, base_url: str, product_name: str, all_images: list[dict]) -> tuple[str | None, str | None]:
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


def parse_aldi_offer_cards(source, html: str, visible_text: str, all_images: list[dict] | None = None):
    """Parse ALDI stationary offers from isolated DOM cards.

    Fail closed when a card cannot provide one unambiguous saving pair, a
    concrete package-bearing product title, package size, or explicit weekly
    validity. Deposit amounts are never accepted as promotional prices.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    valid_from, valid_to, _, _ = infer_validity(visible_text or "")
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
