from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
import time
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

# Known official store-detail pages. Newly onboarded Lidl stores can later add
# their official store URL to Store.source_url and use the same resolver.
_LIDL_STORE_PAGES = {
    "Lidl Puderbach": "https://www.lidl.de/s/de-DE/filialen/puderbach/urbacherstr-l264/",
}


@dataclass(frozen=True)
class LidlLeaflet:
    url: str
    title: str
    valid_from: date
    valid_to: date
    store_context_confirmed: bool = False


def lidl_store_page_for(store_name: str) -> str | None:
    return _LIDL_STORE_PAGES.get(store_name)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%d.%m.%Y").date()


def _leaflets_from_html(base_url: str, html: str, *, store_context_confirmed: bool = False) -> list[LidlLeaflet]:
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
        rows.append(LidlLeaflet(url, title, valid_from, valid_to, store_context_confirmed))
    return rows


def _select_leaflet(rows: list[LidlLeaflet], target_date: date) -> LidlLeaflet:
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
    raise RuntimeError("Kein datiertes Lidl-Aktionsprospekt in der Seite gefunden")


def _resolve_with_store_context(
    source_url: str,
    store_page_url: str,
    target_date: date,
    *,
    timeout_seconds: float = 45.0,
) -> LidlLeaflet | None:
    """Best-effort: select the exact Lidl branch before opening prospect page."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1440, "height": 1100},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36",
        )
        page = context.new_page()
        try:
            started = time.monotonic()
            page.goto(
                store_page_url,
                wait_until="domcontentloaded",
                timeout=max(1000, int(min(25.0, timeout_seconds) * 1000)),
            )
            for label in ("Alle akzeptieren", "Akzeptieren", "Zustimmen", "Alle Cookies akzeptieren"):
                try:
                    button = page.get_by_role("button", name=label, exact=False)
                    if button.count():
                        button.first.click(timeout=1500)
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    pass

            selected = False
            for label in ("Meine Filiale", "Als meine Filiale festlegen", "Filiale auswählen"):
                try:
                    candidates = page.get_by_text(label, exact=False)
                    for idx in range(min(candidates.count(), 5)):
                        node = candidates.nth(idx)
                        if node.is_visible():
                            node.click(timeout=2500)
                            page.wait_for_timeout(1200)
                            selected = True
                            break
                    if selected:
                        break
                except Exception:
                    pass

            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 1:
                return None
            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=max(1000, int(min(remaining, 25.0) * 1000)),
            )
            try:
                remaining = timeout_seconds - (time.monotonic() - started)
                page.wait_for_load_state(
                    "networkidle",
                    timeout=max(500, int(min(8.0, max(0.5, remaining)) * 1000)),
                )
            except Exception:
                page.wait_for_timeout(2500)
            html = page.content()
            rows = _leaflets_from_html(page.url or source_url, html, store_context_confirmed=selected)
            if rows:
                return _select_leaflet(rows, target_date)
        finally:
            context.close()
            browser.close()
    return None


def resolve_lidl_leaflet(
    source_url: str,
    target_date: date,
    *,
    store_page_url: str | None = None,
    timeout_seconds: float = 45.0,
) -> LidlLeaflet:
    """Resolve Lidl's generic prospect landing page to the exact action leaflet.

    When an official store-detail URL is known, Chromium first selects that
    branch and only then opens the prospect page. This is preferred because
    Lidl explicitly regionalises leaflets by selected branch. Static HTML is a
    fallback for environments where the selection control is unavailable.
    """
    started = time.monotonic()
    if store_page_url:
        try:
            contextual = _resolve_with_store_context(
                source_url,
                store_page_url,
                target_date,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            contextual = None
        if contextual:
            return contextual

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9",
    }
    rows: list[LidlLeaflet] = []
    final_url = source_url
    try:
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("Lidl leaflet discovery timeout")
        with httpx.Client(follow_redirects=True, timeout=min(15.0, remaining), headers=headers) as client:
            response = client.get(source_url)
            response.raise_for_status()
            final_url = str(response.url)
            rows = _leaflets_from_html(final_url, response.text)
    except Exception:
        rows = []

    if rows:
        return _select_leaflet(rows, target_date)
    if time.monotonic() - started >= timeout_seconds:
        raise TimeoutError("Lidl leaflet discovery timeout")
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
