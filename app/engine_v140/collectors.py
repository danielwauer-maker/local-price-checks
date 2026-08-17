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

    The page contains a navigation item named "Aktuelle Filial-Angebote", then
    the actual standalone heading "Filial-Angebote" above the product cards,
    and later another "Filial-Angebote" label inside "Aktuelle Prospekte".
    Select the standalone heading that occurs before the first
    "Aktuelle Prospekte" boundary and whose following lines contain local-card
    markers. This avoids both false matches.
    """
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    prospect_idx = next(
        (i for i, line in enumerate(lines) if line.lower().strip() == "aktuelle prospekte"),
        len(lines),
    )
    starts = [
        i for i, line in enumerate(lines[:prospect_idx])
        if line.lower().strip() == "filial-angebote"
    ]
    if not starts:
        return []

    # Prefer the last valid standalone heading before "Aktuelle Prospekte".
    # On the live filial page this is the real product-card section.
    start = starts[-1] + 1
    end = prospect_idx
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
    bare_action_price = re.compile(r"^(\d{1,3}[.,]\d{2})\*?$", re.I)

    i = 0
    while i < len(section):
        marker = section[i].lower().strip()
        if marker not in {"filiale", "filiale & shop"}:
            i += 1
            continue

        j = i + 1
        while j < len(section) and section[j].lower().strip() in {"image", "zu den angeboten"}:
            j += 1
        if j >= len(section):
            break

        name_line = section[j].strip()
        name = clean_product_name(name_line)
        if not name or product_name_issue(name):
            i += 1
            continue

        k = j + 1
        while k < len(section) and section[k].lower().strip() not in {"filiale", "filiale & shop"}:
            k += 1
        block_lines = section[j:k]
        block = " ".join(block_lines)

        pair = pair_re.search(block)
        regular = None
        promo = None
        if pair:
            regular = float(pair.group(1).replace(",", "."))
            promo = float(pair.group(2).replace(",", "."))
        else:
            # "Aktion" is usually a separate line followed by a bare price.
            for idx, value in enumerate(block_lines[:-1]):
                if value.lower().strip() == "aktion":
                    m = bare_action_price.match(block_lines[idx + 1].strip())
                    if m:
                        promo = float(m.group(1).replace(",", "."))
                        break

        if promo is None or promo <= 0:
            i = max(i + 1, k)
            continue

        q, u = size(name_line)
        if q is None and re.search(r"\bstück\b", name_line, re.I):
            q, u = 1.0, "stück"

        # Lower trailing prices can be Netto+/app prices. Only classify them as
        # such when the card explicitly mentions the digital mechanism.
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
        i = max(i + 1, k)

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
