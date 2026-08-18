from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter

from .collectors import (
    canonical_unit_price_unit,
    compute_unit_price,
    images,
    parse_lidl_text,
    structured_network_offers,
)

_PAGE_RE = re.compile(r"/page/(\d+)", re.I)
_TOTAL_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")


@dataclass
class LidlFlipbookResult:
    offers: list
    pdf_path: Path
    page_count: int
    final_url: str
    fetch_mode: str
    diagnostics: str


def _page_url(url: str, page_no: int) -> str:
    if _PAGE_RE.search(url):
        return _PAGE_RE.sub(f"/page/{page_no}", url, count=1)
    base = url.rstrip("/")
    if "/view/flyer" in base:
        return f"{base}/page/{page_no}"
    return f"{base}/view/flyer/page/{page_no}"


def _inject_network_json(html: str, payloads: list[dict]) -> str:
    raw = json.dumps(payloads, ensure_ascii=False, default=str).replace("</script>", "<\\/script>")
    script = f'<script id="lpc-network-json" type="application/json">{raw}</script>'
    if "</body>" in html:
        return html.replace("</body>", script + "</body>", 1)
    return html + script


def _visible_body(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000) or ""
    except Exception:
        return ""


def _image_signature(page) -> str:
    try:
        rows = page.locator("img").evaluate_all(
            """els => els.map(e => [e.currentSrc || e.src || '', e.naturalWidth || 0, e.naturalHeight || 0])
                .filter(x => x[0] && x[1] >= 300 && x[2] >= 300)
                .slice(0, 12)"""
        )
    except Exception:
        rows = []
    return json.dumps(rows, sort_keys=True, ensure_ascii=False)


def _page_fingerprint(page, body: str) -> str:
    # The viewer chrome is mostly constant. Large image URLs are the strongest
    # signal that the requested leaflet page actually changed.
    material = _image_signature(page) + "\n" + body[-1500:]
    return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()


def _extract_total_pages(body: str) -> int | None:
    candidates = []
    for current, total in _TOTAL_RE.findall(body):
        try:
            c, t = int(current), int(total)
        except ValueError:
            continue
        if 1 <= c <= t <= 120:
            candidates.append(t)
    return max(candidates) if candidates else None


def _dedupe_offers(offers: list) -> list:
    seen = set()
    out = []
    for offer in offers:
        key = (
            offer.product_name.lower().strip(),
            round(float(offer.price), 2),
            offer.quantity,
            offer.unit,
            offer.valid_from,
            offer.valid_to,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(offer)
    return out


def capture_lidl_flipbook(
    source,
    *,
    valid_from,
    valid_to,
    target_dir: Path,
    max_pages: int = 80,
) -> LidlFlipbookResult:
    """Capture a complete official Lidl leaflet with page-scoped offer data.

    Lidl's leaflet is a JavaScript flipbook. We keep one Chromium context open,
    visit each concrete ``/page/N`` route, capture JSON responses for that page,
    parse visible/structured offer data, and print exactly one audit page per
    viewer page. Repeated page fingerprints or viewer page clamping terminate
    the crawl when the viewer does not expose an explicit page count.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright ist für Lidl-Flipbook-Erfassung nicht verfügbar") from exc

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"lidl-flipbook-{valid_from.isoformat()}-{valid_to.isoformat()}.pdf"
    writer = PdfWriter()
    all_offers = []
    fingerprints: set[str] = set()
    explicit_total: int | None = None
    captured_pages = 0
    final_url = source.url
    vf = valid_from.strftime("%d.%m.%Y")
    vt = valid_to.strftime("%d.%m.%Y")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1440, "height": 1100},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.7"},
        )
        page = context.new_page()
        page_payloads: list[dict] = []

        def capture_response(response):
            try:
                ctype = (response.headers.get("content-type") or "").lower()
                url_low = response.url.lower()
                relevant_url = any(
                    token in url_low
                    for token in (
                        "flyer", "leaflet", "prospekt", "brochure", "catalog", "page",
                        "offer", "angebot", "product", "produkt", "article", "artikel",
                    )
                )
                if "json" not in ctype and not relevant_url:
                    return
                if len(page_payloads) >= 250:
                    return
                data = response.json()
                raw = json.dumps(data, ensure_ascii=False, default=str)
                if len(raw) > 2_500_000:
                    return
                low = raw.lower()
                if any(
                    token in low
                    for token in (
                        "price", "preis", "offer", "angebot", "product", "produkt",
                        "article", "artikel", "gtin", "ean", "hotspot", "flyer", "page",
                    )
                ):
                    page_payloads.append({"url": response.url, "data": data})
            except Exception:
                pass

        page.on("response", capture_response)
        try:
            for page_no in range(1, max_pages + 1):
                if explicit_total is not None and page_no > explicit_total:
                    break
                page_payloads.clear()
                requested = _page_url(source.url, page_no)
                page.goto(requested, wait_until="domcontentloaded", timeout=45000)
                if page_no == 1:
                    for label in ("Alle akzeptieren", "Akzeptieren", "Zustimmen", "Alle Cookies akzeptieren"):
                        try:
                            button = page.get_by_role("button", name=label, exact=False)
                            if button.count():
                                button.first.click(timeout=1500)
                                page.wait_for_timeout(600)
                                break
                        except Exception:
                            pass
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    page.wait_for_timeout(2200)

                final_url = page.url or requested
                actual = _PAGE_RE.search(final_url)
                if actual and int(actual.group(1)) != page_no:
                    break

                body = _visible_body(page)
                if not body and page_no > 1:
                    break
                if explicit_total is None:
                    explicit_total = _extract_total_pages(body)

                fingerprint = _page_fingerprint(page, body)
                if fingerprint in fingerprints:
                    break
                fingerprints.add(fingerprint)

                html = _inject_network_json(page.content(), list(page_payloads))
                soup = BeautifulSoup(html, "html.parser")
                imgs = images(html, final_url)
                page_offers = parse_lidl_text(source, body, imgs)
                structured = structured_network_offers(html, source, imgs)
                existing = {(o.product_name.lower(), o.price, o.quantity, o.unit) for o in page_offers}
                for offer in structured:
                    key = (offer.product_name.lower(), offer.price, offer.quantity, offer.unit)
                    if key not in existing:
                        page_offers.append(offer)
                        existing.add(key)

                for offer in page_offers:
                    offer.valid_from = vf
                    offer.valid_to = vt
                    offer.source_url = source.url
                    original = (offer.source_text or "").strip()
                    offer.source_text = f"PDF Seite {page_no}: {original}"[:4000]
                    if offer.unit_price is None:
                        offer.unit_price, offer.unit_price_unit = compute_unit_price(
                            offer.app_price if offer.app_price is not None else offer.price,
                            offer.quantity,
                            offer.unit,
                        )
                    elif not offer.unit_price_unit:
                        offer.unit_price_unit = canonical_unit_price_unit(offer.unit)
                all_offers.extend(page_offers)

                # Print one viewer state per logical leaflet page. Keeping only
                # the first printed page prevents browser chrome overflow from
                # inflating the prospect page count.
                payload = page.pdf(
                    format="A4",
                    landscape=True,
                    print_background=True,
                    margin={"top": "4mm", "right": "4mm", "bottom": "4mm", "left": "4mm"},
                )
                reader = PdfReader(BytesIO(payload))
                if not reader.pages:
                    raise RuntimeError(f"Lidl-Viewer Seite {page_no} konnte nicht archiviert werden")
                writer.add_page(reader.pages[0])
                captured_pages += 1
        finally:
            context.close()
            browser.close()

    if captured_pages < 2:
        raise RuntimeError("Lidl-Flipbook lieferte weniger als zwei unterschiedliche Prospektseiten")
    with target.open("wb") as fh:
        writer.write(fh)

    offers = _dedupe_offers(all_offers)
    total_label = str(explicit_total) if explicit_total is not None else "automatisch"
    diagnostics = f"lidl_flipbook={captured_pages} Seiten (viewer_total={total_label}), page_offers={len(offers)}"
    return LidlFlipbookResult(
        offers=offers,
        pdf_path=target,
        page_count=captured_pages,
        final_url=final_url,
        fetch_mode="playwright-flipbook",
        diagnostics=diagnostics,
    )
