from __future__ import annotations

import hashlib
import html as html_lib
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .clock import app_today
from .collection_service import CollectionError, collect_pdf_for_store, collect_structured_for_store
from .config import settings
from .models import Store
from .engine_v140.source_registry import source_for_store_record

PDF_RE = re.compile(r"\.pdf(?:$|[?#])", re.I)
INLINE_PDF_RE = re.compile(r"[\"']([^\"']+\.pdf(?:\?[^\"']*)?)[\"']", re.I)
PROSPECT_WORDS = ("prospekt", "wochenprospekt", "angebote", "handzettel", "flyer")


def _rank_link(url: str, text: str = "") -> tuple[int, int]:
    hay = f"{url} {text}".lower()
    score = 0
    if PDF_RE.search(url):
        score += 100
    for word in PROSPECT_WORDS:
        if word in hay:
            score += 10
    if "online" in hay and "prospekt" not in hay:
        score -= 5
    return score, -len(url)


def _inline_pdf_links(base_url: str, html: str) -> list[str]:
    decoded = html_lib.unescape(html).replace("\\/", "/")
    seen: set[str] = set()
    links: list[str] = []
    for raw in INLINE_PDF_RE.findall(decoded):
        url = urljoin(base_url, raw)
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _links_from_html(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[tuple[int, int], str]] = []
    seen: set[str] = set()
    for url in _inline_pdf_links(base_url, html):
        seen.add(url)
        candidates.append((_rank_link(url, "prospekt pdf"), url))
    for tag in soup.find_all(["a", "iframe", "embed", "object"]):
        raw = tag.get("href") or tag.get("src") or tag.get("data")
        if not raw:
            continue
        url = urljoin(base_url, str(raw))
        if url in seen:
            continue
        seen.add(url)
        text = tag.get_text(" ", strip=True)
        score = _rank_link(url, text)
        if score[0] > 0:
            candidates.append((score, url))
    candidates.sort(reverse=True)
    return [url for _, url in candidates]


def _rendered_links(url: str) -> list[str]:
    if not settings.collector_browser_enabled:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=settings.collector_timeout_seconds * 1000)
            html = page.content()
            browser.close()
        return _links_from_html(url, html)
    except Exception:
        return []


def discover_official_pdf(source_url: str) -> str:
    headers = {"User-Agent": "LocalPriceChecks/0.3 (+market onboarding)"}
    with httpx.Client(follow_redirects=True, timeout=settings.collector_timeout_seconds, headers=headers) as client:
        response = client.get(source_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "application/pdf" in content_type or PDF_RE.search(str(response.url)):
            return str(response.url)
        links = _links_from_html(str(response.url), response.text)
        if not links:
            links = _rendered_links(str(response.url))
        for link in links:
            try:
                probe = client.head(link)
                ctype = probe.headers.get("content-type", "").lower()
                if "application/pdf" in ctype or PDF_RE.search(str(probe.url)):
                    return str(probe.url)
            except Exception:
                if PDF_RE.search(link):
                    return link
    raise CollectionError(f"Kein offizieller PDF-Prospekt auffindbar: {source_url}")


def download_pdf(url: str, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    target = target_dir / f"prospect-{digest}.pdf"
    headers = {"User-Agent": "LocalPriceChecks/0.3 (+market onboarding)"}
    with httpx.Client(follow_redirects=True, timeout=settings.collector_timeout_seconds, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise CollectionError(f"Quelle liefert keine PDF-Datei: {url}")
        target.write_bytes(response.content)
    return target


def netto_weekly_prospect_url(store: Store) -> str:
    if store.retailer != "Netto Marken-Discount":
        raise CollectionError(f"Kein Netto-Markt: {store.name}")
    if not store.external_id:
        raise CollectionError(f"Netto storeid fehlt: {store.name}")
    week = app_today().isocalendar().week
    return f"https://wochenprospekt.netto-online.de/hz{week:02d}_kess/?storeid={store.external_id}"


def _archive_downloaded_prospect(db: Session, store: Store, *, source_url: str, pdf_url: str, pdf_path: Path) -> None:
    from .prospects import save_prospect
    save_prospect(db, store, period_key="current", source_url=source_url, pdf_url=pdf_url, pdf_path=pdf_path)


def _collect_netto_from_official_prospect(db: Session, store: Store, source):
    prospect_url = netto_weekly_prospect_url(store)
    pdf_url = discover_official_pdf(prospect_url)
    pdf_path = download_pdf(pdf_url, settings.data_dir / "prospects" / source.key)
    _archive_downloaded_prospect(db, store, source_url=prospect_url, pdf_url=pdf_url, pdf_path=pdf_path)
    return collect_pdf_for_store(db, store.name, pdf_path)


def collect_store_from_web(db: Session, store_name: str):
    """Collect an active market for QA or production.

    Collection and release are deliberately separate. benchmark_verified is
    only the user-facing release gate. Active unverified markets may be scraped
    so admins can audit them before release.
    """
    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        raise CollectionError(f"Unbekannter Markt: {store_name}")
    if not store.active:
        raise CollectionError(f"Markt ist inaktiv: {store_name}")
    source = source_for_store_record(store)
    if not source:
        raise CollectionError(f"Keine Quelle registriert oder automatisch ableitbar für: {store.name}")

    if store.retailer == "Netto Marken-Discount":
        return _collect_netto_from_official_prospect(db, store, source)

    structured_error = None
    try:
        result, summary, run = collect_structured_for_store(db, store.name)
        if summary.imported:
            return result, summary, run
    except Exception as exc:
        structured_error = exc

    try:
        pdf_url = discover_official_pdf(source.url)
        pdf_path = download_pdf(pdf_url, settings.data_dir / "prospects" / source.key)
        _archive_downloaded_prospect(db, store, source_url=source.url, pdf_url=pdf_url, pdf_path=pdf_path)
        return collect_pdf_for_store(db, store.name, pdf_path)
    except Exception as pdf_error:
        if structured_error:
            raise CollectionError(
                f"Strukturierter Abruf fehlgeschlagen: {structured_error}; PDF-Fallback fehlgeschlagen: {pdf_error}"
            ) from pdf_error
        raise
