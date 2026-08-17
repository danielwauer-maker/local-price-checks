"""Full Local Price Checks 1.4.0 structured web collector.

The benchmarked source is kept in ordered source parts during the migration to
the mobile Web-MVP repository. The parts are concatenated and executed inside
this module so its original relative imports and public API stay unchanged.

Small compatibility wrappers below keep the benchmarked source parts intact
while adapting known live-site changes discovered during server smoke tests.
"""
from pathlib import Path

_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("_collectors_*.part"))
if len(_parts) != 4:
    raise RuntimeError(f"v1.4 web collector incomplete: expected 4 source parts, got {len(_parts)}")
_source = "".join(p.read_text(encoding="utf-8") for p in _parts)
exec(compile(_source, str(_here / "collectors_v140.py"), "exec"), globals(), globals())


# ---------------------------------------------------------------------------
# Netto live-site compatibility
# ---------------------------------------------------------------------------
# The original Netto parser correctly extracts offer cards but did not attach
# the page-level validity range to the resulting CollectedOffer objects. The
# Web-MVP import gate intentionally rejects undated offers, so attach the
# explicit official page range after parsing instead of weakening that gate.
_base_parse_netto_text = parse_netto_text


def _parse_netto_text_with_validity(source, text, imgs=None):
    offers = _base_parse_netto_text(source, text, imgs)
    valid_from, valid_to, _, _ = infer_validity(text)
    if valid_from and valid_to:
        vf = valid_from.strftime("%d.%m.%Y")
        vt = valid_to.strftime("%d.%m.%Y")
        for offer in offers:
            if not offer.valid_from:
                offer.valid_from = vf
            if not offer.valid_to:
                offer.valid_to = vt
    return offers


parse_netto_text = _parse_netto_text_with_validity


# Netto's initial HTML response can contain only the shell of the filial page;
# the offer cards are then hydrated in the browser. The generic collector only
# falls back to Playwright on HTTP errors. For Netto, retry once with the
# existing browser collector when a successful HTTP response nevertheless
# yields zero safe offers.
_base_collect_one = collect_one


def collect_one(source):
    result = _base_collect_one(source)
    if (
        source.retailer != "Netto Marken-Discount"
        or result.get("offers")
        or result.get("fetch_mode") != "http"
    ):
        return result

    rendered = browser_fetch(source.url)
    html = rendered.content.decode("utf-8", errors="replace")
    visible_text = visible(html)
    imgs = images(html, rendered.final_url or source.url)
    offers = parse_netto_text(source, visible_text, imgs)

    structured = structured_network_offers(html, source, imgs)
    if structured:
        existing = {(o.product_name.lower(), o.price, o.quantity, o.unit) for o in offers}
        for offer in structured:
            key = (offer.product_name.lower(), offer.price, offer.quantity, offer.unit)
            if key not in existing:
                offers.append(offer)
                existing.add(key)

    # Network-derived offers can also inherit the explicit validity printed on
    # the same official filial page when the payload itself omits dates.
    valid_from, valid_to, _, _ = infer_validity(visible_text)
    if valid_from and valid_to:
        vf = valid_from.strftime("%d.%m.%Y")
        vt = valid_to.strftime("%d.%m.%Y")
        for offer in offers:
            if not offer.valid_from:
                offer.valid_from = vf
            if not offer.valid_to:
                offer.valid_to = vt

    for offer in offers:
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
