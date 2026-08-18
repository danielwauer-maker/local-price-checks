from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfWriter

from .collectors import (
    canonical_unit_price_unit,
    compute_unit_price,
    images,
    parse_lidl_text,
    structured_network_offers,
)
from .lidl_manifest import (
    add_image_pdf_page,
    embedded_json_states,
    logical_page_images,
    manifest_offers,
    manifest_page_count,
)

_TOTAL_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")


@dataclass
class LidlFlipbookResult:
    offers: list
    pdf_path: Path
    page_count: int
    final_url: str
    fetch_mode: str
    diagnostics: str


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


def _visual_signature(page) -> str:
    try:
        payload = page.screenshot(full_page=False, animations="disabled")
        return hashlib.sha256(payload).hexdigest()
    except Exception:
        return ""


def _page_fingerprint(page, body: str) -> str:
    visual = _visual_signature(page)
    if visual:
        return visual
    normalized = re.sub(r"\b\d{1,3}\s*/\s*\d{1,3}\b", "PAGE/TOTAL", body)
    normalized = re.sub(r"/page/\d+", "/page/N", normalized, flags=re.I)
    return hashlib.sha256(normalized[-3000:].encode("utf-8", errors="ignore")).hexdigest()


def _extract_total_pages(body: str) -> int | None:
    candidates = []
    for current, total in _TOTAL_RE.findall(body):
        try:
            c, t = int(current), int(total)
        except ValueError:
            continue
        if 1 <= c <= t <= 120 and t >= 4:
            candidates.append(t)
    return max(candidates) if candidates else None


def _extract_current_page(body: str) -> int | None:
    candidates = []
    for current, total in _TOTAL_RE.findall(body):
        try:
            c, t = int(current), int(total)
        except ValueError:
            continue
        if 1 <= c <= t <= 120 and t >= 4:
            candidates.append((t, c))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _dismiss_cookies(page) -> None:
    for label in ("Alle akzeptieren", "Akzeptieren", "Zustimmen", "Alle Cookies akzeptieren"):
        try:
            button = page.get_by_role("button", name=label, exact=False)
            if button.count() and button.first.is_visible():
                button.first.click(timeout=1500)
                page.wait_for_timeout(600)
                return
        except Exception:
            pass


def _click_next(page) -> str | None:
    css_selectors = (
        'button[aria-label*="Nächste" i]',
        'button[aria-label*="Naechste" i]',
        'button[aria-label*="Weiter" i]',
        'button[aria-label*="Next" i]',
        '[role="button"][aria-label*="Nächste" i]',
        '[role="button"][aria-label*="Weiter" i]',
        'button[title*="Nächste" i]',
        'button[title*="Weiter" i]',
        'button[title*="Next" i]',
    )
    for selector in css_selectors:
        try:
            locator = page.locator(selector)
            for idx in range(min(locator.count(), 4)):
                node = locator.nth(idx)
                if node.is_visible() and node.is_enabled():
                    node.click(timeout=1800)
                    return f"click:{selector}"
        except Exception:
            pass

    for label in ("Nächste Seite", "Nächste", "Weiter", "Next page", "Next"):
        try:
            locator = page.get_by_role("button", name=re.compile(label, re.I))
            for idx in range(min(locator.count(), 4)):
                node = locator.nth(idx)
                if node.is_visible() and node.is_enabled():
                    node.click(timeout=1800)
                    return f"role:{label}"
        except Exception:
            pass

    try:
        page.keyboard.press("ArrowRight")
        return "keyboard:ArrowRight"
    except Exception:
        return None


def _advance_and_wait(page, previous_fingerprint: str, previous_page: int | None) -> tuple[bool, str | None]:
    method = _click_next(page)
    if not method:
        return False, None

    for _ in range(12):
        page.wait_for_timeout(350)
        body = _visible_body(page)
        current_page = _extract_current_page(body)
        fingerprint = _page_fingerprint(page, body)
        page_changed = previous_page is not None and current_page is not None and current_page != previous_page
        visual_changed = bool(fingerprint and fingerprint != previous_fingerprint)
        if page_changed or visual_changed:
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            return True, method
    return False, method


def _dedupe_offers(offers: list) -> list:
    seen = set()
    out = []
    for offer in offers:
        page_match = re.search(r"PDF Seite (\d+)", offer.source_text or "")
        page_no = int(page_match.group(1)) if page_match else None
        key = (
            offer.product_name.lower().strip(),
            round(float(offer.price), 2),
            offer.quantity,
            offer.unit,
            offer.valid_from,
            offer.valid_to,
            page_no,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(offer)
    return out


def _next_page_hint(current_page: int | None) -> int | None:
    if current_page is None:
        return None
    if current_page <= 1:
        return 2
    return current_page + 2


def capture_lidl_flipbook(
    source,
    *,
    valid_from,
    valid_to,
    target_dir: Path,
    max_pages: int = 80,
) -> LidlFlipbookResult:
    """Capture Lidl's live leaflet including manifest data and logical pages.

    The current Lidl viewer advances in spreads: after the single cover page the
    visible counter typically moves 2, 4, 6 ... while the leaflet itself contains
    every logical page. We therefore keep viewer-state count separate from archive
    page count and split two-page spreads into one audit page per logical leaflet
    page. JSON/manifest responses and embedded app state are inspected recursively
    for page-scoped product/hotspot data.
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
    captured_states = 0
    archived_pages: set[int] = set()
    final_url = source.url
    vf = valid_from.strftime("%d.%m.%Y")
    vt = valid_to.strftime("%d.%m.%Y")
    navigation_methods: set[str] = set()
    all_payloads: list[dict] = []
    payload_hashes: set[str] = set()
    capture_hint = {"page": 1}

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
                        "hotspot", "publication", "spread", "manifest", "annotation",
                    )
                )
                if "json" not in ctype and not relevant_url:
                    return
                data = response.json()
                raw = json.dumps(data, ensure_ascii=False, default=str)
                if len(raw) > 5_000_000:
                    return
                low = raw.lower()
                if not any(
                    token in low
                    for token in (
                        "price", "preis", "offer", "angebot", "product", "produkt",
                        "article", "artikel", "gtin", "ean", "hotspot", "flyer", "page",
                        "publication", "spread", "manifest", "annotation",
                    )
                ):
                    return
                digest = hashlib.sha256((response.url + "\n" + raw).encode("utf-8", errors="ignore")).hexdigest()
                if digest in payload_hashes:
                    return
                payload_hashes.add(digest)
                item = {"url": response.url, "data": data, "page_hint": capture_hint.get("page")}
                if len(page_payloads) < 300:
                    page_payloads.append(item)
                if len(all_payloads) < 900:
                    all_payloads.append(item)
            except Exception:
                pass

        page.on("response", capture_response)
        try:
            page.goto(source.url, wait_until="domcontentloaded", timeout=45000)
            _dismiss_cookies(page)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                page.wait_for_timeout(2500)

            for state in embedded_json_states(page):
                raw = json.dumps(state.get("data"), ensure_ascii=False, default=str)
                digest = hashlib.sha256(("dom-state\n" + raw).encode("utf-8", errors="ignore")).hexdigest()
                if digest not in payload_hashes:
                    payload_hashes.add(digest)
                    all_payloads.append(state)

            explicit_total = manifest_page_count(all_payloads) or _extract_total_pages(_visible_body(page))

            for logical_state in range(1, max_pages + 1):
                body = _visible_body(page)
                if not body and logical_state > 1:
                    break
                final_url = page.url or source.url
                current_page = _extract_current_page(body) or capture_hint.get("page") or logical_state
                capture_hint["page"] = current_page
                if explicit_total is None:
                    explicit_total = manifest_page_count(all_payloads) or _extract_total_pages(body)

                fingerprint = _page_fingerprint(page, body)
                if fingerprint in fingerprints:
                    break
                fingerprints.add(fingerprint)
                captured_states += 1

                html = _inject_network_json(page.content(), list(page_payloads))
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
                    offer.source_text = f"PDF Seite {current_page}: {original}"[:4000]
                    if offer.unit_price is None:
                        offer.unit_price, offer.unit_price_unit = compute_unit_price(
                            offer.app_price if offer.app_price is not None else offer.price,
                            offer.quantity,
                            offer.unit,
                        )
                    elif not offer.unit_price_unit:
                        offer.unit_price_unit = canonical_unit_price_unit(offer.unit)
                all_offers.extend(page_offers)

                for page_no, image_payload in logical_page_images(page, current_page, explicit_total):
                    if page_no in archived_pages:
                        continue
                    add_image_pdf_page(writer, image_payload)
                    archived_pages.add(page_no)

                if explicit_total is not None and len(archived_pages) >= explicit_total:
                    break

                page_payloads.clear()
                capture_hint["page"] = _next_page_hint(current_page)
                changed, method = _advance_and_wait(page, fingerprint, current_page)
                if method:
                    navigation_methods.add(method)
                if not changed:
                    break
        finally:
            context.close()
            browser.close()

    manifest_rows = manifest_offers(all_payloads, source, valid_from=vf, valid_to=vt)
    for offer in manifest_rows:
        if offer.unit_price is None:
            offer.unit_price, offer.unit_price_unit = compute_unit_price(
                offer.app_price if offer.app_price is not None else offer.price,
                offer.quantity,
                offer.unit,
            )
        elif not offer.unit_price_unit:
            offer.unit_price_unit = canonical_unit_price_unit(offer.unit)
    all_offers.extend(manifest_rows)

    if len(archived_pages) < 2:
        nav = ",".join(sorted(navigation_methods)) or "kein Navigationscontrol gefunden"
        raise RuntimeError(
            "Lidl-Flipbook konnte nicht vollständig erfasst werden; "
            f"viewer_states={captured_states}, logische_seiten={len(archived_pages)}, navigation={nav}"
        )

    with target.open("wb") as fh:
        writer.write(fh)

    offers = _dedupe_offers(all_offers)
    total_label = str(explicit_total) if explicit_total is not None else "automatisch"
    nav_label = ",".join(sorted(navigation_methods)) or "unbekannt"
    diagnostics = (
        f"lidl_flipbook={len(archived_pages)} logische Seiten "
        f"(viewer_states={captured_states}, viewer_total={total_label}), "
        f"page_offers={len(offers)}, manifest_payloads={len(all_payloads)}, "
        f"manifest_offers={len(manifest_rows)}, navigation={nav_label}"
    )
    return LidlFlipbookResult(
        offers=offers,
        pdf_path=target,
        page_count=len(archived_pages),
        final_url=final_url,
        fetch_mode="playwright-flipbook-manifest",
        diagnostics=diagnostics,
    )