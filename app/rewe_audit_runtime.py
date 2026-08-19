from __future__ import annotations

from datetime import datetime
from pathlib import Path
import html as html_module
import re

from .clock import app_today
from .config import settings
from .models import Store
from .prospect_models import ProspectArchive


SNAPSHOT_VERSION = 2

REWE_CONSENT_MARKERS = (
    "optionale cookies und technologien erlauben",
    "alle erlauben",
    "nur notwendige erlauben",
    "mehr optionen",
    "partner verwenden cookies",
    "verarbeitung ihrer daten",
)


PRINT_LAYOUT_CSS = r"""
@media print {
  html, body {
    overflow: visible !important;
    height: auto !important;
  }
  .lpc-print-card,
  article,
  [data-testid*="product" i],
  [data-testid*="offer" i],
  [class*="product-card" i],
  [class*="product_card" i],
  [class*="offer-card" i],
  [class*="offer_card" i],
  [class*="product-tile" i],
  [class*="product_tile" i] {
    break-inside: avoid-page !important;
    page-break-inside: avoid !important;
    -webkit-column-break-inside: avoid !important;
  }
  img, picture, figure {
    break-inside: avoid-page !important;
    page-break-inside: avoid !important;
  }
}
"""


def _parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _validity_from_result(result):
    offers = result.get("offers") or []
    starts = [_parse_date(getattr(row, "valid_from", None)) for row in offers]
    ends = [_parse_date(getattr(row, "valid_to", None)) for row in offers]
    starts = [x for x in starts if x]
    ends = [x for x in ends if x]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _latest_archive(db, store: Store):
    return (
        db.query(ProspectArchive)
        .filter(ProspectArchive.store_id == store.id)
        .order_by(ProspectArchive.fetched_at.desc(), ProspectArchive.id.desc())
        .first()
    )


def _has_archived_prospect(db, store: Store) -> bool:
    return _latest_archive(db, store) is not None


def _archive_contains_consent(archive: ProspectArchive | None) -> bool:
    if not archive or not archive.pdf_bytes:
        return False
    if not str(archive.pdf_url or "").startswith("web-snapshot://"):
        return False
    try:
        import fitz

        doc = fitz.open(stream=archive.pdf_bytes, filetype="pdf")
        try:
            text = " ".join(page.get_text("text") for page in doc[: min(3, doc.page_count)])
        finally:
            doc.close()
    except Exception:
        return False
    normalised = re.sub(r"\s+", " ", text.lower()).strip()
    return any(marker in normalised for marker in REWE_CONSENT_MARKERS)


def _archive_is_current_layout(archive: ProspectArchive | None) -> bool:
    if not archive:
        return False
    return f"/v{SNAPSHOT_VERSION}/" in str(archive.pdf_url or "")


def _needs_session_archive(db, store: Store) -> bool:
    """Refresh missing, consent-dirty or pre-layout-v2 REWE session snapshots."""
    archive = _latest_archive(db, store)
    return (
        archive is None
        or _archive_contains_consent(archive)
        or not _archive_is_current_layout(archive)
    )


def _inject_base_href(document: str, source_url: str) -> str:
    """Give set_content() the original REWE URL as base for relative assets."""
    if re.search(r"<base\b", document, flags=re.I):
        return document
    base = f'<base href="{html_module.escape(source_url, quote=True)}">'
    head = re.search(r"<head(?:\s[^>]*)?>", document, flags=re.I)
    if head:
        pos = head.end()
        return document[:pos] + base + document[pos:]
    html_tag = re.search(r"<html(?:\s[^>]*)?>", document, flags=re.I)
    if html_tag:
        pos = html_tag.end()
        return document[:pos] + "<head>" + base + "</head>" + document[pos:]
    return "<head>" + base + "</head>" + document


def _clean_snapshot_dom(page) -> None:
    cleanup_js = """(markers) => {
      document.querySelectorAll('script').forEach(el => el.remove());

      const normalise = value => (value || '')
        .toLowerCase()
        .replace(/\\s+/g, ' ')
        .trim();
      const hasConsentText = el => {
        const text = normalise(el && (el.innerText || el.textContent || ''));
        return markers.some(marker => text.includes(marker));
      };

      const removable = new Set();
      const selectors = [
        '[role="dialog"]', '[aria-modal="true"]',
        '[class*="cookie" i]', '[id*="cookie" i]',
        '[class*="consent" i]', '[id*="consent" i]',
        '[class*="privacy" i]', '[id*="privacy" i]',
        '[class*="cmp" i]', '[id*="cmp" i]',
        '[class*="overlay" i]', '[class*="modal" i]'
      ];

      const roots = [document];
      const seenRoots = new Set(roots);
      for (let i = 0; i < roots.length; i += 1) {
        const root = roots[i];
        let elements = [];
        try { elements = Array.from(root.querySelectorAll('*')); } catch (_) {}
        for (const el of elements) {
          if (el.shadowRoot && !seenRoots.has(el.shadowRoot)) {
            seenRoots.add(el.shadowRoot);
            roots.push(el.shadowRoot);
          }
        }
      }

      for (const root of roots) {
        for (const sel of selectors) {
          try {
            root.querySelectorAll(sel).forEach(el => {
              if (hasConsentText(el)) removable.add(el);
            });
          } catch (_) {}
        }
        let elements = [];
        try { elements = Array.from(root.querySelectorAll('*')); } catch (_) {}
        for (const el of elements) {
          if (!hasConsentText(el)) continue;
          let node = el;
          let best = null;
          for (let depth = 0; node && depth < 10; depth += 1, node = node.parentElement) {
            const style = getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            const modalLike =
              node.getAttribute('role') === 'dialog' ||
              node.getAttribute('aria-modal') === 'true' ||
              style.position === 'fixed' ||
              style.position === 'sticky' ||
              (rect.width >= window.innerWidth * 0.55 && rect.height >= window.innerHeight * 0.35);
            if (modalLike) best = node;
            if (style.position === 'fixed' && rect.width >= window.innerWidth * 0.8) break;
          }
          removable.add(best || el);
        }
      }

      const removedRects = [];
      for (const el of removable) {
        if (!el || !el.isConnected) continue;
        const rect = el.getBoundingClientRect();
        removedRects.push({left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom});
        el.remove();
      }

      for (const el of Array.from(document.body ? document.body.children : [])) {
        const style = getComputedStyle(el);
        if (style.position !== 'fixed' && style.position !== 'sticky') continue;
        const rect = el.getBoundingClientRect();
        const coversViewport = rect.width >= window.innerWidth * 0.85 && rect.height >= window.innerHeight * 0.55;
        const highLayer = Number.parseInt(style.zIndex || '0', 10) >= 100;
        if (coversViewport && highLayer && !hasConsentText(el)) {
          const overlapsRemoved = removedRects.some(r => !(rect.right < r.left || rect.left > r.right || rect.bottom < r.top || rect.top > r.bottom));
          if (overlapsRemoved) el.remove();
        }
      }

      document.documentElement.style.overflow = 'auto';
      if (document.body) {
        document.body.style.overflow = 'auto';
        document.body.style.position = 'static';
      }
    }"""

    for frame in list(page.frames):
        try:
            frame.evaluate(cleanup_js, list(REWE_CONSENT_MARKERS))
        except Exception:
            pass


def _prepare_snapshot_assets(page) -> None:
    """Trigger lazy content, promote lazy image URLs and wait for image decode."""
    page.evaluate(
        """async () => {
          const promoteLazy = () => {
            document.querySelectorAll('img').forEach(img => {
              img.loading = 'eager';
              const src = img.getAttribute('src') || '';
              const candidates = [
                img.getAttribute('data-src'),
                img.getAttribute('data-lazy-src'),
                img.getAttribute('data-original'),
                img.getAttribute('data-image-src')
              ].filter(Boolean);
              if ((!src || src.startsWith('data:image/svg') || src.includes('placeholder')) && candidates.length) {
                img.setAttribute('src', candidates[0]);
              }
              const srcset = img.getAttribute('srcset');
              const lazySrcset = img.getAttribute('data-srcset') || img.getAttribute('data-lazy-srcset');
              if (!srcset && lazySrcset) img.setAttribute('srcset', lazySrcset);
            });
            document.querySelectorAll('source').forEach(source => {
              const lazySrcset = source.getAttribute('data-srcset') || source.getAttribute('data-lazy-srcset');
              if (!source.getAttribute('srcset') && lazySrcset) source.setAttribute('srcset', lazySrcset);
            });
          };

          promoteLazy();
          const step = Math.max(500, Math.floor(window.innerHeight * 0.75));
          const maxY = Math.max(document.body?.scrollHeight || 0, document.documentElement.scrollHeight || 0);
          for (let y = 0; y <= maxY; y += step) {
            window.scrollTo(0, y);
            await new Promise(resolve => setTimeout(resolve, 90));
            promoteLazy();
          }
          window.scrollTo(0, 0);
          await new Promise(resolve => setTimeout(resolve, 250));

          const waits = Array.from(document.images || []).map(img => {
            if (img.complete) {
              if (img.decode) return img.decode().catch(() => undefined);
              return Promise.resolve();
            }
            return new Promise(resolve => {
              const done = () => resolve();
              img.addEventListener('load', done, {once: true});
              img.addEventListener('error', done, {once: true});
              setTimeout(done, 2500);
            });
          });
          await Promise.allSettled(waits);
        }"""
    )


def _mark_print_cards(page) -> None:
    """Mark visible price cards so Chromium keeps each card together on A4."""
    page.evaluate(
        """() => {
          const priceRe = /(?:\d{1,3}[.,]\d{2})\s*€/;
          const candidates = Array.from(document.querySelectorAll('article, li, section, div'));
          for (const el of candidates) {
            const text = (el.innerText || '').trim();
            if (!priceRe.test(text)) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width < 180 || rect.width > Math.max(760, window.innerWidth * 0.75)) continue;
            if (rect.height < 120 || rect.height > 950) continue;
            let parent = el.parentElement;
            let nestedPriceCards = 0;
            if (parent) {
              try {
                nestedPriceCards = Array.from(parent.children).filter(child => priceRe.test((child.innerText || '').trim())).length;
              } catch (_) {}
            }
            if (nestedPriceCards >= 2 || el.tagName === 'ARTICLE' || el.tagName === 'LI') {
              el.classList.add('lpc-print-card');
            }
          }
        }"""
    )


def archive_rewe_from_collector_result(db, store: Store, result) -> str:
    raw = result.get("raw")
    if not raw:
        raise RuntimeError("Erfolgreicher REWE-Lauf enthält kein archivierungsfähiges HTML")
    html = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    if "<html" not in html.lower() and "<body" not in html.lower():
        raise RuntimeError("REWE-Lauf enthält kein HTML-Dokument")

    source_url = result.get("final_url") or getattr(result.get("source"), "url", None) or store.source_url
    if not source_url:
        raise RuntimeError("REWE-Quelle fehlt im erfolgreichen Lauf")
    html = _inject_base_href(html, source_url)

    target_dir = settings.data_dir / "prospects" / "viewer" / str(store.id) / "current"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"rewe-session-web-v{SNAPSHOT_VERSION}-{store.id}-{app_today().isoformat()}.pdf"

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
        context = browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1440, "height": 1100},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127 Safari/537.36",
        )
        page = context.new_page()
        try:
            page.set_content(html, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                page.wait_for_timeout(1500)
            _clean_snapshot_dom(page)
            _prepare_snapshot_assets(page)
            _clean_snapshot_dom(page)
            _mark_print_cards(page)
            page.add_style_tag(content=PRINT_LAYOUT_CSS)
            page.emulate_media(media="screen")
            page.evaluate("window.scrollTo(0,0)")
            page.wait_for_timeout(250)
            payload = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "6mm", "right": "6mm", "bottom": "6mm", "left": "6mm"},
            )
        finally:
            context.close()
            browser.close()

    if not payload.startswith(b"%PDF"):
        raise RuntimeError("REWE Session-Abbild konnte nicht als PDF erzeugt werden")
    target.write_bytes(payload)

    valid_from, valid_to = _validity_from_result(result)
    from .prospects import save_prospect, _link_web_snapshot_provenance

    row = save_prospect(
        db,
        store,
        period_key="current",
        source_url=source_url,
        pdf_url=f"web-snapshot://captured-session/v{SNAPSHOT_VERSION}/{store.id}/{app_today().isoformat()}",
        pdf_path=target,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    archive = _latest_archive(db, store)
    linked = 0
    if archive:
        try:
            linked = int(_link_web_snapshot_provenance(db, store, archive) or 0)
        except Exception:
            db.rollback()
    return f"audit=session-web-snapshot-v{SNAPSHOT_VERSION}:{row.page_count} Seiten; provenance={linked}"


def install() -> None:
    from . import web_collector

    original = web_collector.collect_store_from_web
    if getattr(original, "_lpc_rewe_session_patch", False):
        return

    def wrapped(db, store_name: str):
        result, summary, run = original(db, store_name)
        store = db.query(Store).filter(Store.name == store_name).first()
        if store and store.retailer == "REWE" and getattr(summary, "imported", 0):
            try:
                if _needs_session_archive(db, store):
                    status = archive_rewe_from_collector_result(db, store, result)
                    web_collector._append_run_diagnostic(db, run, status)
            except Exception as exc:
                db.rollback()
                web_collector._append_run_diagnostic(
                    db,
                    run,
                    f"audit_session_fehler={type(exc).__name__}: {exc}",
                )
        return result, summary, run

    wrapped._lpc_rewe_session_patch = True
    web_collector.collect_store_from_web = wrapped
