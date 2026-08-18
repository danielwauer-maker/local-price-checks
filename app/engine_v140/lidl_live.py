from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .browser_fetch import browser_fetch
from .collectors import (
    canonical_unit_price_unit,
    compute_unit_price,
    images,
    parse_lidl_text,
    structured_network_offers,
    visible,
)

_DATE_RANGE_RE = re.compile(
    r"(\d{1,2}\.\d{1,2}\.\d{4})\s*[–—-]\s*(\d{1,2}\.\d{1,2}\.\d{4})"
)


@dataclass(frozen=True)
class LidlLeaflet:
    url: str
    title: str
    valid_from: date
    valid_to: date


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%d.%m.%Y").date()


def _leaflets_from_html(base_url: str, html: str) -> list[LidlLeaflet]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[LidlLeaflet] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href:
            continue
        title = " ".join(anchor.stripped_strings).strip()
        if "aktionsprospekt" not in title.lower():
            continue
        match = _DATE_RANGE_RE.search(title)
        if not match:
            continue
        try:
            valid_from = _parse_date(match.group(1))
            valid_to = _parse_date(match.group(2))
        except ValueError:
            continue
        url = urljoin(base_url, str(href))
        if url in seen:
            continue
        seen.add(url)
        rows.append(LidlLeaflet(url, title, valid_from, valid_to))
    return rows


def resolve_lidl_leaflet(source_url: str, target_date: date) -> LidlLeaflet:
    """Resolve Lidl's generic prospect landing page to the exact action leaflet.

    Lidl exposes dated ``Aktionsprospekt`` links on the official prospect page.
    Prefer a leaflet whose validity contains ``target_date``. If the initial
    HTML shell does not expose those links, render the landing page once with
    Chromium and repeat the same deterministic selection.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9",
    }
    rows: list[LidlLeaflet] = []
    final_url = source_url
    try:
        with httpx.Client(follow_redirects=True, timeout=30, headers=headers) as client:
            response = client.get(source_url)
            response.raise_for_status()
            final_url = str(response.url)
            rows = _leaflets_from_html(final_url, response.text)
    except Exception:
        rows = []

    if not rows:
        rendered = browser_fetch(source_url)
        final_url = rendered.final_url or source_url
        rows = _leaflets_from_html(final_url, rendered.content.decode("utf-8", errors="replace"))

    current = [row for row in rows if row.valid_from <= target_date <= row.valid_to]
    if current:
        return sorted(current, key=lambda row: (row.valid_from, row.valid_to), reverse=True)[0]

    # During Sunday/evening transitions Lidl can already remove the ending
    # leaflet. Prefer the nearest future leaflet, otherwise the latest past one.
    future = sorted((row for row in rows if row.valid_from > target_date), key=lambda row: row.valid_from)
    if future:
        return future[0]
    past = sorted((row for row in rows if row.valid_to < target_date), key=lambda row: row.valid_to, reverse=True)
    if past:
        return past[0]
    raise RuntimeError(f"Kein datiertes Lidl-Aktionsprospekt auffindbar: {source_url}")


def collect_lidl_leaflet(source, *, valid_from: date, valid_to: date):
    """Render one concrete Lidl leaflet and extract local offer candidates.

    The leaflet viewer is JavaScript-driven. Chromium captures both the final
    DOM and relevant JSON/network responses; the conservative Lidl text parser
    and the generic structured-network parser are combined and deduplicated.
    """
    rendered = browser_fetch(source.url)
    html = rendered.content.decode("utf-8", errors="replace")
    visible_text = visible(html)
    imgs = images(html, rendered.final_url or source.url)

    offers = parse_lidl_text(source, visible_text, imgs)
    structured = structured_network_offers(html, source, imgs)
    existing = {(o.product_name.lower(), o.price, o.quantity, o.unit) for o in offers}
    for offer in structured:
        key = (offer.product_name.lower(), offer.price, offer.quantity, offer.unit)
        if key not in existing:
            offers.append(offer)
            existing.add(key)

    vf = valid_from.strftime("%d.%m.%Y")
    vt = valid_to.strftime("%d.%m.%Y")
    for offer in offers:
        offer.valid_from = vf
        offer.valid_to = vt
        offer.source_url = source.url
        if offer.unit_price is None:
            offer.unit_price, offer.unit_price_unit = compute_unit_price(
                offer.app_price if offer.app_price is not None else offer.price,
                offer.quantity,
                offer.unit,
            )
        elif not offer.unit_price_unit:
            offer.unit_price_unit = canonical_unit_price_unit(offer.unit)

    return {
        "source": source,
        "raw": rendered.content,
        "content_type": rendered.content_type,
        "fetch_mode": rendered.mode,
        "final_url": rendered.final_url,
        "offers": offers,
        "status": "parsed" if offers else "no_safe_offers",
    }
