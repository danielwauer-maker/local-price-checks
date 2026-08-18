from __future__ import annotations

from typing import Any


def _deep_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(_deep_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        return "\n".join(_deep_text(item) for item in value.values() if item is not None)
    return ""


def install() -> None:
    from . import lidl_schwarz_runtime as runtime

    if getattr(runtime._page_text, "_lpc_deep_text", False):
        return

    def page_text(page: dict) -> str:
        # Schwarz sometimes nests OCR/accessibility text in structures deeper
        # than one dictionary level. Flatten all page metadata except raw image
        # blobs/URLs so page-level shop markers and grocery OCR become visible.
        parts = []
        for key, value in page.items():
            if str(key).lower() in {"image", "imageurl", "thumbnail", "thumbnailurl", "picture", "pictureurl"}:
                continue
            text = _deep_text(value)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()

    original_product_links = runtime._offers_from_product_links

    def local_product_links(flyer, source, valid_from, valid_to):
        # Non-local rows have no place in Local Price Checks. Dropping them at
        # source is safer than relying on downstream importer heuristics.
        return [
            row for row in original_product_links(flyer, source, valid_from, valid_to)
            if bool(getattr(row, "local_store_offer", False))
        ]

    page_text._lpc_deep_text = True
    local_product_links._lpc_local_only = True
    runtime._page_text = page_text
    runtime._offers_from_product_links = local_product_links
