"""Full Local Price Checks 1.4.0 structured web collector.

The benchmarked source is kept in ordered source parts during the migration to
the mobile Web-MVP repository. The parts are concatenated and executed inside
this module so its original relative imports and public API stay unchanged.

Small compatibility wrappers below keep the benchmarked source parts intact
while adapting known live-site changes discovered during server smoke tests.
"""
from pathlib import Path
import re

_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("_collectors_*.part"))
if len(_parts) != 4:
    raise RuntimeError(f"v1.4 web collector incomplete: expected 4 source parts, got {len(_parts)}")
_source = "".join(p.read_text(encoding="utf-8") for p in _parts)
exec(compile(_source, str(_here / "collectors_v140.py"), "exec"), globals(), globals())


# ---------------------------------------------------------------------------
# Netto live-site compatibility
# ---------------------------------------------------------------------------
_base_parse_netto_text = parse_netto_text


def _netto_live_offer_section(text: str) -> list[str]:
    """Return the real filial-offer block from the current Netto filial page.

    The global navigation contains "Aktuelle Filial-Angebote" before the actual
    offer cards. The current live page later renders a standalone heading
    "Filial-Angebote" followed by the cards and then "Aktuelle Prospekte".
    Matching the standalone heading avoids parsing the navigation/catalog shell.
    """
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    starts = [i for i, line in enumerate(lines) if line.lower().strip() == "filial-angebote"]
    if not starts:
        return []
    start = starts[-1] + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].lower().strip() == "aktuelle prospekte":
            end = i
            break
    return lines[start:end]


def _parse_netto_live_cards(source, text, imgs=None):
    """Parse the current Netto filial card format.

    Current price lines are rendered without an euro sign, for example
    ``UVP 3.29 2.49*`` or ``statt 7.99 6.99*``. The benchmark-era parser was
    more oriented toward prospect text, so this deliberately small parser is
    only used as a compatibility fallback when that parser yields no cards.
    """
    section = _netto_live_offer_section(text)
    if not section:
        return []
    imgs = imgs or []
    out = []
    valid_from, valid_to, _, _ = infer_validity(text)
    vf = valid_from.strftime("%d.%m.%Y") if valid_from else None
    vt = valid_to.strftime("%d.%m.%Y") if valid_to else None

    marker_lines = {"filiale", "filiale & shop", "image", "zu den angeboten", "alle filialangebote ansehen"}
    pair_re = re.compile(r"\b(?:UVP|statt)\s+(\d{1,3}[.,]\d{2})\s+(\d{1,3}[.,]\d{2})\*?", re.I)
    action_re = re.compile(r"\bAktion\s+(\d{1,3}[.,]\d{2})\*?", re.I)

    i = 0
    while i < len(section):
        line = section[i].strip()
        low = line.lower()
        q, u = size(line)
        if q is None or low in marker_lines or _is_noise_line(line):
            i += 1
            continue

        # Unit-price-only lines such as "3.96 / kg" must not become products.
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{1,2})?\s*(?:€\s*)?/\s*(?:kg|l|100\s*g|100\s*ml|wl)", line, re.I):
            i += 1
            continue

        name = clean_product_name(line)
        if not name or product_name_issue(name):
            i += 1
            continue

        j = i + 1
        while j < len(section) and section[j].lower().strip() not in {"filiale", "filiale & shop"}:
            # Stop at the next obvious product row even if the marker is omitted.
            if j > i + 2 and size(section[j])[0] is not None:
                maybe_prices = " ".join(section[i:j])
                if pair_re.search(maybe_prices) or action_re.search(maybe_prices):
                    break
            j += 1

        block = " ".join(section[i:j])
        pair = pair_re.search(block)
        regular = None
        promo = None
        if pair:
            regular = float(pair.group(1).replace(",", "."))
            promo = float(pair.group(2).replace(",", "."))
        else:
            action = action_re.search(block)
            if action:
                promo = float(action.group(1).replace(",", "."))
            else:
                vals = _price_without_unit_prices(block)
                if vals:
                    promo = min(vals)

        if promo is None or promo <= 0:
            i += 1
            continue

        # Netto+ / app prices are often printed as a lower trailing price.
        app_price = None
        lower_vals = [v for v in _price_without_unit_prices(block) if v < promo]
        if lower_vals and re.search(r"\b(?:netto\+|app|coupon|vorteilspreis|digitaler\s+coupon)\b", block, re.I):
            app_price = min(lower_vals)

        im = best_img(imgs, name)
        out.append(CollectedOffer(
            source.key, source.store_name, source.retailer, name[:180], cat(name), promo,
            regular_price=regular, app_price=app_price,
            unit_price=upr(block), unit_price_unit=upr_unit(block), quantity=q, unit=u,
            valid_from=vf, valid_to=vt, source_text=block, source_url=source.url,
            image_url=im["url"] if im else None, image_alt=im["alt"] if im else None,
            confidence=.97 if vf and vt else .84,
        ))
        i = max(i + 1, j)

    seen = set()
    result = []
    for offer in out:
        key = (offer.product_name.lower(), offer.price, offer.quantity, offer.unit)
        if key not in seen:
            seen.add(key)
            result.append(offer)
    return result


def _parse_netto_text_with_validity(source, text, imgs=None):
    offers = _base_parse_netto_text(source, text, imgs)
    if not offers:
        offers = _parse_netto_live_cards(source, text, imgs)

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
