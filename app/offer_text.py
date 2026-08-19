from __future__ import annotations

from dataclasses import dataclass
import html
import re


@dataclass(frozen=True)
class OfferTextDetails:
    detail_text: str | None = None
    package_label: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    unit_price_unit: str | None = None


def _number(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(".", "").replace(",", ".")) if "," in value else float(value)
    except ValueError:
        return None


def _clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_offer_text(value: str | None) -> OfferTextDetails:
    """Extract user-facing packaging metadata from retailer card text.

    Typical supported examples::

        je 400-g-Becher, (1 kg = 4,73 €)
        je 750-ml-Fl., (1 l = 4,65 €)
        je 1-l-Pckg.
        je 6 x 0,33-l-Fl., (1 l = 1,51 €)

    The original compact line is retained as ``detail_text`` so the UI can show
    the retailer wording even when not every token can be normalised safely.
    """
    text = _clean_text(value)
    if not text:
        return OfferTextDetails()

    unit_price = None
    unit_price_unit = None
    up = re.search(
        r"\b1\s*(kg|l)\s*[=:=]\s*(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|euro)?",
        text,
        flags=re.I,
    )
    if up:
        unit_price_unit = up.group(1).lower()
        unit_price = _number(up.group(2))

    quantity = None
    unit = None
    package_label = None

    multi = re.search(
        r"\bje\s+(\d{1,2})\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*[- ]?\s*(kg|g|l|ml|cl)\b",
        text,
        flags=re.I,
    )
    if multi:
        count = int(multi.group(1))
        each = _number(multi.group(2))
        raw_unit = multi.group(3).lower()
        if each is not None:
            quantity = count * each
            unit = raw_unit
            shown = multi.group(2).replace(".", ",")
            package_label = f"{count} x {shown} {raw_unit}"
    else:
        single = re.search(
            r"\bje\s+(\d+(?:[.,]\d+)?)\s*[- ]?\s*(kg|g|l|ml|cl)\b",
            text,
            flags=re.I,
        )
        if single:
            quantity = _number(single.group(1))
            unit = single.group(2).lower()
            shown = single.group(1).replace(".", ",")
            package_label = f"{shown} {unit}"

    detail_text = None
    start = re.search(r"\bje\s+", text, flags=re.I)
    if start:
        tail = text[start.start():]
        # Stop before the next obvious product/price card boundary where possible.
        stop = re.search(r"\s(?:Aktion|Knaller|Tiefpreis)\s+\d", tail, flags=re.I)
        if stop:
            tail = tail[: stop.start()]
        detail_text = tail[:220].strip(" ,;-") or None

    return OfferTextDetails(
        detail_text=detail_text,
        package_label=package_label,
        quantity=quantity,
        unit=unit,
        unit_price=unit_price,
        unit_price_unit=unit_price_unit,
    )
