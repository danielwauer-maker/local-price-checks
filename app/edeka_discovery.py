from __future__ import annotations

import html as html_lib
import re
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .collection_quality import BenchmarkContext
from .collection_service import CollectionError, collect_pdf_for_store
from .config import settings
from .engine_v140.source_registry import source_for_store_record
from .models import Store
from .prospects import current_prospect, save_prospect


_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_RELATIVE_RE = re.compile(r"[\"']([^\"']*(?:/flyers/|/prospekt|/flyer)[^\"']*)[\"']", re.I)


def _decode_markup(value: str) -> str:
    return (
        html_lib.unescape(value or "")
        .replace("\\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\u002F", "/")
    )


def _looks_like_pdf_candidate(url: str) -> bool:
    low = (url or "").lower()
    path = low.split("?", 1)[0].rstrip("/")
    return (
        path.endswith(".pdf")
        or path.endswith("/pdf")
        or ("media.smp-it-media.de" in low and "/flyers/" in low)
        or ("/flyers/" in low and "filename=" in low and ".pdf" in low)
    )


def _extract_pdf_candidates(base_url: str, markup: str) -> list[str]:
    decoded = _decode_markup(markup)
    soup = BeautifulSoup(decoded, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        if not raw:
            return
        cleaned = str(raw).strip().rstrip(",);]")
        url = urljoin(base_url, cleaned)
        if url in seen or not _looks_like_pdf_candidate(url):
            return
        seen.add(url)
        candidates.append(url)

    for match in _URL_RE.findall(decoded):
        add(match)
    for match in _RELATIVE_RE.findall(decoded):
        add(match)
    for tag in soup.find_all(["a", "iframe", "embed", "object", "source"]):
        add(tag.get("href") or tag.get("src") or tag.get("data"))
    return candidates


def _probe_pdf(client: httpx.Client, url: str) -> str | None:
    try:
        response = client.get(url)
        response.raise_for_status()
    except Exception:
        return None
    content_type = response.headers.get("content-type", "").lower()
    if "application/pdf" in content_type or response.content.startswith(b"%PDF"):
        return str(response.url)
    return None


def _browser_pdf_candidates(source_url: str) -> list[str]:
    """Resolve JS-only EDEKA prospect links without relying on a store ID.

    EDEKA market pages can load the actual market flyer through client-side JSON
    and the SMP media backend. Capture both PDF-like response URLs and PDF URLs
    embedded in relevant JSON responses, then inspect the rendered DOM as a
    final fallback.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        if not raw:
            return
        url = urljoin(source_url, str(raw))
        if url not in seen and _looks_like_pdf_candidate(url):
            seen.add(url)
            candidates.append(url)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()

            def on_response(response) -> None:
                try:
                    content_type = (response.headers or {}).get("content-type", "").lower()
                    if "application/pdf" in content_type or _looks_like_pdf_candidate(response.url):
                        add(response.url)
                    elif "json" in content_type and any(
                        token in response.url.lower()
                        for token in ("angebot", "prospekt", "flyer", "market", "markt")
                    ):
                        for candidate in _extract_pdf_candidates(response.url, response.text()):
                            add(candidate)
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(
                source_url,
                wait_until="domcontentloaded",
                timeout=max(15_000, settings.collector_timeout_seconds * 1000),
            )
            page.wait_for_timeout(2500)
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2500)
            except Exception:
                pass
            for candidate in _extract_pdf_candidates(page.url, page.content()):
                add(candidate)
            browser.close()
    except Exception:
        return candidates
    return candidates


def discover_edeka_market_pdf(source_url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
    }
    static_candidates: list[str] = []
    static_error: Exception | None = None

    with httpx.Client(
        follow_redirects=True,
        timeout=settings.collector_timeout_seconds,
        headers=headers,
    ) as client:
        try:
            response = client.get(source_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "application/pdf" in content_type or response.content.startswith(b"%PDF"):
                return str(response.url)
            static_candidates = _extract_pdf_candidates(str(response.url), response.text)
        except Exception as exc:
            static_error = exc

        candidates = static_candidates + [
            url for url in _browser_pdf_candidates(source_url) if url not in static_candidates
        ]
        for candidate in candidates:
            resolved = _probe_pdf(client, candidate)
            if resolved:
                return resolved

    detail = f"; page_error={type(static_error).__name__}: {static_error}" if static_error else ""
    raise CollectionError(
        f"Kein offizieller EDEKA-PDF-Prospekt auffindbar: {source_url}{detail}"
    )


def _download_pdf(url: str, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    import hashlib

    target = target_dir / f"prospect-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}.pdf"
    headers = {"User-Agent": "LocalPriceChecks/0.3 (+EDEKA market prospect)"}
    with httpx.Client(
        follow_redirects=True,
        timeout=settings.collector_timeout_seconds,
        headers=headers,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise CollectionError(f"EDEKA-Quelle liefert keine PDF-Datei: {url}")
        target.write_bytes(response.content)
    return target


def collect_edeka_market_pdf(
    db: Session,
    store: Store,
    *,
    benchmark_context: BenchmarkContext | str = BenchmarkContext.NOT_APPLICABLE,
):
    if store.retailer != "EDEKA":
        raise CollectionError(f"Kein EDEKA-Markt: {store.name}")
    source = source_for_store_record(store)
    if not source:
        raise CollectionError(f"Keine EDEKA-Quelle registriert: {store.name}")

    registered = current_prospect(db, store, "current")
    pdf_url = (
        registered.pdf_url
        if registered and registered.pdf_url.startswith(("http://", "https://"))
        else None
    )
    pdf_path = Path(registered.local_path) if registered and registered.local_path else None

    if pdf_path is None or not pdf_path.is_file():
        pdf_url = pdf_url or discover_edeka_market_pdf(source.url)
        pdf_path = _download_pdf(pdf_url, settings.data_dir / "prospects" / source.key)
    if not pdf_url:
        raise CollectionError(f"Kein offizieller EDEKA-Marktprospekt auffindbar: {source.url}")

    save_prospect(
        db,
        store,
        period_key="current",
        source_url=source.url,
        pdf_url=pdf_url,
        pdf_path=pdf_path,
        valid_from=registered.valid_from if registered else None,
        valid_to=registered.valid_to if registered else None,
    )
    return collect_pdf_for_store(
        db,
        store.name,
        pdf_path,
        benchmark_context=benchmark_context,
    )
