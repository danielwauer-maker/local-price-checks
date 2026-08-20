from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
import hashlib
import json
import re
import time
from pathlib import Path

import httpx
from pypdf import PdfReader, PdfWriter

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
    manifest_page_count,
)
from .lidl_ocr import offers_from_leaflet_image
from .lidl_pdf import extract_lidl_pdf_offers
from .lidl_semantics import LidlSourceKind, classify_lidl_link
from .lidl_schwarz_runtime import _page_online_only, schwarz_manifest_offers

_TOTAL_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")


@dataclass
class LidlFlipbookResult:
    offers: list
    pdf_path: Path
    page_count: int
    final_url: str
    fetch_mode: str
    diagnostics: str
    warning: str | None = None
    pdf_url: str | None = None


class LidlCollectionTimeout(RuntimeError):
    def __init__(self, phase: str, elapsed_seconds: float):
        self.phase = phase
        self.elapsed_seconds = elapsed_seconds
        super().__init__(
            f"error_type=timeout phase={phase} elapsed_seconds={elapsed_seconds:.1f}"
        )


_TOTAL_TIMEOUT_SECONDS = 540.0
_PHASE_TIMEOUTS = {
    "viewer_manifest": 65.0,
    "pdf_text_extract": 100.0,
    "structured_extract": 20.0,
    "page_assets": 80.0,
    "ocr_fallback": 240.0,
    "artifact_archive": 80.0,
}


class _RuntimeBudget:
    def __init__(self, total_seconds: float):
        self.started = time.monotonic()
        self.total_seconds = total_seconds
        self.phase = "starting"
        self.phase_started = self.started
        self.phase_seconds = total_seconds

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def begin(self, phase: str) -> None:
        self.phase = phase
        self.phase_started = time.monotonic()
        self.phase_seconds = _PHASE_TIMEOUTS.get(phase, self.total_seconds)
        self.check()

    def remaining(self) -> float:
        now = time.monotonic()
        return min(
            self.total_seconds - (now - self.started),
            self.phase_seconds - (now - self.phase_started),
        )

    def check(self) -> None:
        if self.remaining() <= 0:
            raise LidlCollectionTimeout(self.phase, self.elapsed)


def _report(progress, phase: str, budget: _RuntimeBudget, **values) -> None:
    if progress:
        progress(phase, elapsed_seconds=round(budget.elapsed, 1), **values)


def _offer_page_numbers(offers: list) -> set[int]:
    found: set[int] = set()
    for offer in offers:
        match = re.search(r"\bPDF\s+Seite\s+(\d+)\b", getattr(offer, "source_text", "") or "", re.I)
        if match:
            found.add(int(match.group(1)))
    return found


def _structured_authority_pages(offers: list) -> set[int]:
    """Only a local, price-bearing source may suppress fallback extraction."""
    return _offer_page_numbers(
        [
            offer for offer in offers
            if bool(getattr(offer, "local_store_offer", True))
            and "SchwarzShopHotspot" not in (getattr(offer, "source_text", "") or "")
        ]
    )


def _schwarz_flyer(payloads: list[dict]) -> dict | None:
    for payload in payloads:
        data = payload.get("data")
        flyer = data.get("flyer") if isinstance(data, dict) else None
        if isinstance(flyer, dict) and isinstance(flyer.get("pages"), list):
            return flyer
    return None


def _schwarz_page_assets(flyer: dict) -> list[dict]:
    assets = []
    for index, page in enumerate(flyer.get("pages") or []):
        if not isinstance(page, dict):
            continue
        page_no = page.get("number") or index + 1
        try:
            page_no = int(page_no)
        except (TypeError, ValueError):
            page_no = index + 1
        url = page.get("zoom") or page.get("image") or page.get("thumbnail")
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            assets.append(
                {
                    "page_no": page_no,
                    "url": url,
                    "online_only": _page_online_only(page),
                }
            )
    return assets


def _ocr_candidate_assets(
    page_assets: list[dict],
    structured_pages: set[int],
    *,
    fallback_pages: set[int] | None = None,
) -> list[dict]:
    """Return only local pages that still lack a structured offer."""
    return [
        asset for asset in page_assets
        if asset["page_no"] not in structured_pages and not asset["online_only"]
        and (fallback_pages is None or asset["page_no"] in fallback_pages)
    ]


def _shop_hotspot_count(flyer: dict) -> int:
    return sum(
        1
        for page in flyer.get("pages") or []
        if isinstance(page, dict)
        for link in page.get("links") or []
        if isinstance(link, dict) and classify_lidl_link(link) is LidlSourceKind.SHOP_ONLINE
    )


_FOOD_WORDS = {
    "kaffee", "caffè", "pepsi", "schwip", "trauben", "zitron", "feigen",
    "möhren", "zwiebel", "salat", "mais", "joghurt", "käse", "milch",
    "fleisch", "wurst", "brot", "brötchen", "obst", "gemüse", "bier",
    "wein", "saft", "wasser", "schokolade", "keks", "chips", "pom-bär",
}


def _is_food_offer(offer) -> bool:
    text = f"{getattr(offer, 'category', '')} {getattr(offer, 'product_name', '')}".lower()
    if any(word in text for word in _FOOD_WORDS):
        return True
    return getattr(offer, "category", "") not in {"Sonstiges", "Non-Food"}


def _download_cached_asset(asset: dict, cache_dir: Path, timeout_seconds: float) -> tuple[int, bytes, bool, str]:
    url = asset["url"]
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{url_hash}.asset"
    if cache_path.exists() and cache_path.stat().st_size > 1000:
        payload = cache_path.read_bytes()
        return asset["page_no"], payload, True, hashlib.sha256(payload).hexdigest()
    response = httpx.get(url, follow_redirects=True, timeout=max(1.0, timeout_seconds))
    response.raise_for_status()
    payload = response.content
    if len(payload) < 1000:
        raise RuntimeError(f"Lidl-Seitenasset ist leer/zu klein: page={asset['page_no']}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(payload)
    return asset["page_no"], payload, False, hashlib.sha256(payload).hexdigest()


def _download_assets(
    assets: list[dict],
    cache_dir: Path,
    budget: _RuntimeBudget,
    progress,
    *,
    pages_total: int,
    pages_structured: int,
    pages_done_start: int,
) -> tuple[dict[int, bytes], int, int, bool]:
    downloaded: dict[int, bytes] = {}
    content_seen: dict[str, bytes] = {}
    cached = 0
    errors = 0
    timed_out = False
    executor = ThreadPoolExecutor(max_workers=min(8, max(1, len(assets))))
    futures = {
        executor.submit(
            _download_cached_asset,
            asset,
            cache_dir,
            min(20.0, max(1.0, budget.remaining())),
        ): asset
        for asset in assets
    }
    try:
        for future in as_completed(futures, timeout=max(0.1, budget.remaining())):
            budget.check()
            try:
                page_no, payload, was_cached, digest = future.result()
                if digest in content_seen:
                    payload = content_seen[digest]
                    was_cached = True
                else:
                    content_seen[digest] = payload
                downloaded[page_no] = payload
                cached += int(was_cached)
            except Exception:
                errors += 1
            _report(
                progress,
                "page_assets",
                budget,
                pages_total=pages_total,
                pages_structured=pages_structured,
                pages_ocr=len(assets),
                pages_done=pages_done_start,
                assets_cached=cached,
            )
    except FuturesTimeout:
        timed_out = True
        for future in futures:
            future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return downloaded, cached, errors, timed_out


def _download_official_pdf(flyer: dict, target: Path, budget: _RuntimeBudget) -> Path:
    budget.check()
    url = flyer.get("hiResPdfUrl") or flyer.get("pdfUrl")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise RuntimeError("Schwarz-Manifest enthält keine direkte offizielle PDF-URL")
    if target.exists() and target.stat().st_size > 10_000:
        return target
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=max(1.0, min(60.0, budget.remaining())),
    )
    response.raise_for_status()
    if len(response.content) < 10_000 or not response.content.startswith(b"%PDF"):
        raise RuntimeError("Offizielles Lidl-PDF ist leer oder ungültig")
    target.write_bytes(response.content)
    budget.check()
    return target


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
    """Dismiss Lidl CMP dialogs and remove residual consent overlays.

    The CMP can appear late and can live in an iframe, so this is intentionally
    idempotent and is called again before every archived leaflet image.
    """
    labels = (
        "Alle ablehnen", "Ablehnen", "Nur notwendige", "Nur erforderliche",
        "Alle akzeptieren", "Akzeptieren", "Zustimmen", "Speichern",
    )
    for _ in range(3):
        clicked = False
        for frame in list(page.frames):
            for label in labels:
                try:
                    button = frame.get_by_role("button", name=re.compile(label, re.I))
                    for idx in range(min(button.count(), 3)):
                        node = button.nth(idx)
                        if node.is_visible() and node.is_enabled():
                            node.click(timeout=1200)
                            clicked = True
                            break
                    if clicked:
                        break
                except Exception:
                    pass
            if clicked:
                break
        if clicked:
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass
        else:
            break

    # Some CMP layers survive after the preference action or are rendered as a
    # generic fixed overlay. Remove only elements that clearly contain consent
    # language; never remove leaflet content based on class name alone.
    cleanup_js = """
    () => {
      const words = [
        'verarbeitung ihrer daten', 'cookie', 'cookies', 'datenschutz',
        'privacy', 'consent', 'zustimmen', 'alle akzeptieren', 'ablehnen'
      ];
      const selectors = [
        '[role="dialog"]', '[aria-modal="true"]',
        '[class*="consent" i]', '[id*="consent" i]',
        '[class*="cookie" i]', '[id*="cookie" i]',
        '[class*="privacy" i]', '[id*="privacy" i]'
      ];
      const candidates = new Set();
      for (const sel of selectors) {
        try { document.querySelectorAll(sel).forEach(el => candidates.add(el)); } catch (_) {}
      }
      document.querySelectorAll('body *').forEach(el => {
        const style = getComputedStyle(el);
        if ((style.position === 'fixed' || style.position === 'sticky') && Number(style.zIndex || 0) >= 10) {
          candidates.add(el);
        }
      });
      for (const el of candidates) {
        const text = (el.innerText || el.textContent || '').toLowerCase();
        if (words.some(w => text.includes(w))) el.remove();
      }
      document.documentElement.style.overflow = 'auto';
      if (document.body) document.body.style.overflow = 'auto';
    }
    """
    for frame in list(page.frames):
        try:
            frame.evaluate(cleanup_js)
        except Exception:
            pass
    try:
        page.wait_for_timeout(200)
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
        _dismiss_cookies(page)
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
    total_timeout_seconds: float = _TOTAL_TIMEOUT_SECONDS,
    progress=None,
) -> LidlFlipbookResult:
    """Collect Lidl from one manifest response without visual page traversal.

    The Schwarz response already contains every logical page, direct page
    assets and the official PDF. Structured page data is evaluated first; OCR
    is only scheduled for pages that have no structured local offer.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright ist für Lidl-Flipbook-Erfassung nicht verfügbar") from exc

    budget = _RuntimeBudget(total_timeout_seconds)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"lidl-flipbook-{valid_from.isoformat()}-{valid_to.isoformat()}.pdf"
    final_url = source.url
    vf = valid_from.strftime("%d.%m.%Y")
    vt = valid_to.strftime("%d.%m.%Y")
    all_payloads: list[dict] = []
    payload_hashes: set[str] = set()

    budget.begin("viewer_manifest")
    _report(progress, "viewer_manifest", budget, pages_done=0)
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
                item = {"url": response.url, "data": data, "page_hint": 1}
                if len(all_payloads) < 120:
                    all_payloads.append(item)
            except Exception:
                pass

        page.on("response", capture_response)
        try:
            page.goto(
                source.url,
                wait_until="domcontentloaded",
                timeout=max(1000, int(min(45.0, budget.remaining()) * 1000)),
            )
            _dismiss_cookies(page)
            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=max(1000, int(min(12.0, budget.remaining()) * 1000)),
                )
            except Exception:
                page.wait_for_timeout(max(100, int(min(2.5, budget.remaining()) * 1000)))
            _dismiss_cookies(page)
            budget.check()
            final_url = page.url or source.url

            for state in embedded_json_states(page):
                raw = json.dumps(state.get("data"), ensure_ascii=False, default=str)
                digest = hashlib.sha256(("dom-state\n" + raw).encode("utf-8", errors="ignore")).hexdigest()
                if digest not in payload_hashes:
                    payload_hashes.add(digest)
                    all_payloads.append(state)
        finally:
            context.close()
            browser.close()

    flyer = _schwarz_flyer(all_payloads)
    if flyer is None:
        raise RuntimeError(
            "Lidl-Schwarz-Manifest fehlt; visueller Volltraversal ist aus Laufzeitgründen deaktiviert"
        )
    page_assets = _schwarz_page_assets(flyer)[:max_pages]
    explicit_total = len(flyer.get("pages") or []) or manifest_page_count(all_payloads)
    _report(progress, "viewer_manifest", budget, pages_total=explicit_total, pages_done=0)

    budget.begin("pdf_text_extract")
    _report(progress, "pdf_text_extract", budget, pages_total=explicit_total, pages_done=0)
    _download_official_pdf(flyer, target, budget)
    pdf_extraction = extract_lidl_pdf_offers(
        target,
        source,
        valid_from=vf,
        valid_to=vt,
        flyer=flyer,
        crop_dir=target_dir / "offer-crops",
    )
    _report(
        progress,
        "pdf_text_extract",
        budget,
        pages_total=explicit_total,
        pages_structured=len(pdf_extraction.pages_with_local_offers),
        pages_done=len(pdf_extraction.pages_with_text),
    )

    budget.begin("structured_extract")
    manifest_rows = schwarz_manifest_offers(all_payloads, source, valid_from=vf, valid_to=vt)
    structured_rows = [*pdf_extraction.offers, *manifest_rows]
    for offer in structured_rows:
        if offer.unit_price is None:
            offer.unit_price, offer.unit_price_unit = compute_unit_price(
                offer.app_price if offer.app_price is not None else offer.price,
                offer.quantity,
                offer.unit,
            )
        elif not offer.unit_price_unit:
            offer.unit_price_unit = canonical_unit_price_unit(offer.unit)
    structured_pages = _offer_page_numbers(structured_rows)
    sufficient_structured_pages = _structured_authority_pages(structured_rows)
    online_pages = {asset["page_no"] for asset in page_assets if asset["online_only"]}
    ocr_assets = _ocr_candidate_assets(
        page_assets,
        sufficient_structured_pages,
        fallback_pages=pdf_extraction.ocr_candidate_pages,
    )
    pages_done = len(pdf_extraction.pages_with_text | online_pages)
    _report(
        progress,
        "structured_extract",
        budget,
        pages_total=explicit_total,
        pages_structured=len(structured_pages),
        pages_ocr=len(ocr_assets),
        pages_done=pages_done,
    )

    budget.begin("page_assets")
    _report(
        progress,
        "page_assets",
        budget,
        pages_total=explicit_total,
        pages_structured=len(structured_pages),
        pages_ocr=len(ocr_assets),
        pages_done=pages_done,
    )
    downloaded, assets_cached, asset_errors, asset_timeout = _download_assets(
        ocr_assets,
        target_dir / "asset-cache",
        budget,
        progress,
        pages_total=explicit_total,
        pages_structured=len(structured_pages),
        pages_done_start=pages_done,
    ) if ocr_assets else ({}, 0, 0, False)

    budget.begin("ocr_fallback")
    _report(
        progress,
        "ocr_fallback",
        budget,
        pages_total=explicit_total,
        pages_structured=len(structured_pages),
        pages_ocr=len(downloaded),
        pages_done=pages_done,
        assets_cached=assets_cached,
    )
    ocr_rows = []
    ocr_errors = 0
    ocr_completed = 0
    ocr_timeout = False
    executor = ThreadPoolExecutor(max_workers=min(4, max(1, len(downloaded))))
    futures = {
        executor.submit(
            offers_from_leaflet_image,
            source,
            payload,
            page_no=page_no,
            valid_from=vf,
            valid_to=vt,
            timeout_seconds=min(18.0, max(1.0, budget.remaining())),
        ): page_no
        for page_no, payload in downloaded.items()
    }
    try:
        for future in as_completed(futures, timeout=max(0.1, budget.remaining())):
            try:
                rows, _text, online = future.result()
                if not online:
                    ocr_rows.extend(rows)
            except Exception:
                ocr_errors += 1
            ocr_completed += 1
            pages_done += 1
            _report(
                progress,
                "ocr_fallback",
                budget,
                pages_total=explicit_total,
                pages_structured=len(structured_pages),
                pages_ocr=len(downloaded),
                pages_done=pages_done,
                assets_cached=assets_cached,
            )
    except FuturesTimeout:
        ocr_timeout = True
        for future in futures:
            future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    offers = _dedupe_offers([*structured_rows, *ocr_rows])
    warnings = []
    if asset_timeout:
        warnings.append(f"error_type=timeout phase=page_assets elapsed_seconds={budget.elapsed:.1f}")
    if ocr_timeout:
        warnings.append(f"error_type=timeout phase=ocr_fallback elapsed_seconds={budget.elapsed:.1f}")
    if asset_errors:
        warnings.append(f"asset_errors={asset_errors}")
    if ocr_errors:
        warnings.append(f"ocr_errors={ocr_errors}")
    if not offers and warnings:
        phase = "ocr_fallback" if ocr_timeout else "page_assets"
        raise LidlCollectionTimeout(phase, budget.elapsed)

    budget.begin("artifact_archive")
    _report(
        progress,
        "artifact_archive",
        budget,
        pages_total=explicit_total,
        pages_structured=len(structured_pages),
        pages_ocr=len(downloaded),
        pages_done=pages_done,
        assets_cached=assets_cached,
    )
    try:
        archive_pages = len(PdfReader(str(target)).pages)
    except Exception as exc:
        raise RuntimeError(f"Offizielles Lidl-PDF ist nicht lesbar: {exc}") from exc
    if archive_pages < 2:
        raise RuntimeError("Offizielles Lidl-PDF enthält weniger als zwei Seiten")

    warning = " ".join(warnings) or None
    local_rows = [offer for offer in offers if bool(getattr(offer, "local_store_offer", False))]
    food_offers = sum(1 for offer in local_rows if _is_food_offer(offer))
    nonfood_local_offers = len(local_rows) - food_offers
    online_rejected = sum(1 for offer in offers if not bool(getattr(offer, "local_store_offer", False)))
    manifest_text_offers = sum(
        1 for offer in manifest_rows if "SchwarzFlyerPageText" in (offer.source_text or "")
    )
    diagnostics = (
        f"phase=complete pages_total={explicit_total} pages_structured={len(structured_pages)} "
        f"pages_ocr={len(downloaded)} pages_done={pages_done} assets_cached={assets_cached} "
        f"manifest_payloads={len(all_payloads)} manifest_offers={len(manifest_rows)} "
        f"shop_hotspots_seen={_shop_hotspot_count(flyer)} online_rejected={online_rejected} "
        f"pdf_text_offers={len(pdf_extraction.offers)} manifest_text_offers={manifest_text_offers} "
        f"ocr_offers={len(ocr_rows)} food_offers={food_offers} "
        f"nonfood_local_offers={nonfood_local_offers} image_crops={pdf_extraction.image_crops} "
        f"archive_pages={archive_pages} "
        f"viewer_navigation=0 elapsed_seconds={budget.elapsed:.1f}"
    )
    return LidlFlipbookResult(
        offers=offers,
        pdf_path=target,
        page_count=archive_pages,
        final_url=final_url,
        fetch_mode="playwright-manifest-direct-assets",
        diagnostics=diagnostics,
        warning=warning,
        pdf_url=flyer.get("hiResPdfUrl") or flyer.get("pdfUrl"),
    )
