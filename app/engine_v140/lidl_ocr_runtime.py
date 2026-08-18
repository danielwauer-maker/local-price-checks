from __future__ import annotations

from contextvars import ContextVar
import re

from .lidl_ocr import offers_from_leaflet_image

_capture_state: ContextVar[dict | None] = ContextVar("lidl_ocr_capture_state", default=None)


def _page_no(source_text: str | None) -> int | None:
    match = re.search(r"\bPDF\s+Seite\s+(\d+)\b", source_text or "", re.I)
    return int(match.group(1)) if match else None


def install() -> None:
    """Attach page-image OCR to the existing Lidl flipbook collector.

    The viewer already captures immutable logical page images for provenance.
    Reuse exactly those bytes for OCR instead of fetching a second source. This
    lets grocery offers that exist only as rasterized leaflet content join the
    same page-aware pipeline as structured Schwarz API products.
    """
    from . import lidl_flipbook

    if getattr(lidl_flipbook.capture_lidl_flipbook, "_lpc_ocr_bridge", False):
        return

    original_images = lidl_flipbook.logical_page_images
    original_capture = lidl_flipbook.capture_lidl_flipbook

    def logical_page_images_with_capture(page, current_page, explicit_total):
        rows = original_images(page, current_page, explicit_total)
        state = _capture_state.get()
        if state is not None:
            for page_no, image_payload in rows:
                if page_no not in state["images"]:
                    state["images"][page_no] = image_payload
        return rows

    def capture_with_ocr(source, *, valid_from, valid_to, target_dir, max_pages=80):
        state = {"images": {}}
        token = _capture_state.set(state)
        try:
            result = original_capture(
                source,
                valid_from=valid_from,
                valid_to=valid_to,
                target_dir=target_dir,
                max_pages=max_pages,
            )
        finally:
            captured = _capture_state.get() or state
            _capture_state.reset(token)

        vf = valid_from.strftime("%d.%m.%Y")
        vt = valid_to.strftime("%d.%m.%Y")
        ocr_rows = []
        online_pages: set[int] = set()
        ocr_pages = 0
        ocr_errors = 0

        for page_no, image_payload in sorted(captured.get("images", {}).items()):
            try:
                rows, _text, online = offers_from_leaflet_image(
                    source,
                    image_payload,
                    page_no=page_no,
                    valid_from=vf,
                    valid_to=vt,
                )
                ocr_pages += 1
                if online:
                    online_pages.add(page_no)
                    continue
                ocr_rows.extend(rows)
            except Exception:
                ocr_errors += 1

        # A page explicitly identified by the rendered official leaflet as the
        # Lidl online shop must never contribute a local offer, even if the
        # structured catalog itself omitted that page-level marker.
        kept = []
        for offer in result.offers:
            page_no = _page_no(getattr(offer, "source_text", None))
            if page_no in online_pages:
                continue
            kept.append(offer)
        kept.extend(ocr_rows)
        result.offers = lidl_flipbook._dedupe_offers(kept)
        result.diagnostics += (
            f", ocr_pages={ocr_pages}, ocr_offers={len(ocr_rows)}, "
            f"ocr_online_pages={len(online_pages)}, ocr_errors={ocr_errors}"
        )
        return result

    logical_page_images_with_capture._lpc_ocr_bridge = True
    capture_with_ocr._lpc_ocr_bridge = True
    lidl_flipbook.logical_page_images = logical_page_images_with_capture
    lidl_flipbook.capture_lidl_flipbook = capture_with_ocr
