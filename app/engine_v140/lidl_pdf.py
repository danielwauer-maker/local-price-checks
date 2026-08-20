from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from typing import Any

import pymupdf

from .collectors import CollectedOffer, cat, clean_product_name, compute_unit_price, product_name_issue, size, upr, upr_unit
from .lidl_semantics import LidlSourceKind, classify_lidl_link


_PROMO_PRICE = re.compile(r"(?<![\d.,])(\d{1,3}[.,]\d{2})\s*\*", re.I)
_ANY_PRICE = re.compile(r"(?<![\d.,])(\d{1,3}[.,]\d{2})(?![\d])", re.I)
_PACKAGE = re.compile(
    r"\bje\s+(?:(?:\d{1,2}\s*[x×]\s*)?\d+(?:[.,]\d+)?\s*[- ]?"
    r"(?:kg|g|l|ml|cl|stück|stk\.?|packung|pckg\.?|becher|dose|flasche|netz|topf|tray)|stück)\b",
    re.I,
)
_STOP_NAME = re.compile(
    r"^(?:ursprung|klasse|je\b|1\s*(?:kg|l)\s*=|ganze\s+bohnen|koffeinhaltig|"
    r"versch\.|höhe\b|lizenzsorte|winterhart|normalpreis|typ\b|fassungsvermögen|"
    r"zubereitung|material|für\s+(?:drinnen|draußen))",
    re.I,
)
_DROP_NAME = re.compile(
    r"^(?:aktion|tiefpreis|garantie|mit\s+lidl\s+plus|ab\s+(?:mo|di|mi|do|fr|sa)|"
    r"weitere|saison|highlight|der\s+woche|kg-preis|filial-angebote|online-angebote)$",
    re.I,
)
_NONFOOD_PRIVATE_LABEL = re.compile(r"^(?:PARKSIDE|LIVARNO|SILVERCREST|CRIVIT)\s+", re.I)
_OBVIOUS_FOOD_REMAINDER = re.compile(
    r"^(?:berliner|brot|brötchen|croissant|kuchen|joghurt|käse|milch|wurst|fleisch|salat|gemüse|obst)\b",
    re.I,
)


@dataclass(frozen=True)
class LidlPdfExtraction:
    offers: list[CollectedOffer]
    pages_with_text: set[int]
    pages_with_local_offers: set[int]
    ocr_candidate_pages: set[int]
    image_crops: int


@dataclass(frozen=True)
class _Block:
    rect: pymupdf.Rect
    text: str


def _number(raw: str) -> float:
    return float(raw.replace(",", "."))


def _segments(block: _Block) -> list[_Block]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", block.text) if part.strip()]
    if len(parts) <= 1:
        return [block]
    line_total = max(1, sum(max(1, part.count("\n") + 1) for part in parts))
    y = block.rect.y0
    result: list[_Block] = []
    for part in parts:
        ratio = max(1, part.count("\n") + 1) / line_total
        height = block.rect.height * ratio
        result.append(_Block(pymupdf.Rect(block.rect.x0, y, block.rect.x1, y + height), part))
        y += height
    return result


def _product_name(text: str) -> str | None:
    lines = [re.sub(r"\s+", " ", line).strip(" ,;:|•") for line in text.splitlines()]
    name_lines: list[str] = []
    for line in lines:
        if not line:
            continue
        if _PACKAGE.search(line) or _STOP_NAME.search(line):
            break
        if _DROP_NAME.match(line):
            continue
        if re.fullmatch(r"[-–]?\d+(?:[.,]\d+)?%", line):
            continue
        name_lines.append(line)
        if len(name_lines) >= 4:
            break
    name = clean_product_name(" ".join(name_lines))
    without_private_label = _NONFOOD_PRIVATE_LABEL.sub("", name)
    if without_private_label != name and _OBVIOUS_FOOD_REMAINDER.match(without_private_label):
        name = without_private_label
    if not name or product_name_issue(name) or len(name) < 3:
        return None
    return name


def _price_values(text: str) -> tuple[float, float | None, float | None] | None:
    promo = [_number(match) for match in _PROMO_PRICE.findall(text)]
    if not promo:
        return None
    selected = promo[-1]
    all_values = [_number(match) for match in _ANY_PRICE.findall(text)]
    preceding = [value for value in all_values if value > selected]
    plus = bool(re.search(r"lidl\s+plus", text, re.I))
    if plus and preceding:
        return preceding[-1], None, selected
    regular = preceding[0] if preceding and re.search(r"(?:\buvp\b|\bstatt\b|-\d+%)", text, re.I) else None
    return selected, regular, None


def _rect_distance(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    dx = max(a.x0 - b.x1, b.x0 - a.x1, 0.0)
    dy = max(a.y0 - b.y1, b.y0 - a.y1, 0.0)
    center = abs((a.x0 + a.x1) - (b.x0 + b.x1)) * 0.08 + abs((a.y0 + a.y1) - (b.y0 + b.y1)) * 0.05
    return dx + dy + center


def _shop_regions(flyer: dict | None, page_index: int, page_rect: pymupdf.Rect) -> list[pymupdf.Rect]:
    pages = (flyer or {}).get("pages") or []
    if page_index >= len(pages) or not isinstance(pages[page_index], dict):
        return []
    regions = []
    for link in pages[page_index].get("links") or []:
        if not isinstance(link, dict) or classify_lidl_link(link) is not LidlSourceKind.SHOP_ONLINE:
            continue
        try:
            x0 = page_rect.width * float(link.get("left")) / 100.0
            y0 = page_rect.height * float(link.get("top")) / 100.0
            x1 = x0 + page_rect.width * float(link.get("width")) / 100.0
            y1 = y0 + page_rect.height * float(link.get("height")) / 100.0
        except (TypeError, ValueError):
            continue
        regions.append(pymupdf.Rect(x0 - 12, y0 - 10, x1 + 12, y1 + 90) & page_rect)
    return regions


def _shop_titles(flyer: dict | None, page_index: int) -> list[str]:
    pages = (flyer or {}).get("pages") or []
    if page_index >= len(pages) or not isinstance(pages[page_index], dict):
        return []
    return [
        str(link.get("title") or (link.get("productDetails") or {}).get("title") or "").strip()
        for link in pages[page_index].get("links") or []
        if isinstance(link, dict) and classify_lidl_link(link) is LidlSourceKind.SHOP_ONLINE
    ]


def _matches_shop_title(name: str, titles: list[str]) -> bool:
    def tokens(value: str) -> set[str]:
        return {
            token for token in re.findall(r"[a-zäöüß0-9]+", value.lower())
            if len(token) >= 3 and token not in {"und", "oder", "mit", "fuer", "für", "stueck", "stück"}
        }

    name_tokens = tokens(name)
    if not name_tokens:
        return False
    for title in titles:
        title_tokens = tokens(title)
        overlap = name_tokens & title_tokens
        if overlap and len(overlap) >= min(2, len(name_tokens), len(title_tokens)):
            coverage = len(overlap) / min(len(name_tokens), len(title_tokens))
            if coverage >= 0.6:
                return True
    return False


def _local_link_regions(flyer: dict | None, page_index: int, page_rect: pymupdf.Rect) -> list[pymupdf.Rect]:
    pages = (flyer or {}).get("pages") or []
    if page_index >= len(pages) or not isinstance(pages[page_index], dict):
        return []
    regions = []
    for link in pages[page_index].get("links") or []:
        if not isinstance(link, dict) or classify_lidl_link(link) is LidlSourceKind.SHOP_ONLINE:
            continue
        try:
            x0 = page_rect.width * float(link.get("left")) / 100.0
            y0 = page_rect.height * float(link.get("top")) / 100.0
            x1 = x0 + page_rect.width * float(link.get("width")) / 100.0
            y1 = y0 + page_rect.height * float(link.get("height")) / 100.0
        except (TypeError, ValueError):
            continue
        regions.append(pymupdf.Rect(x0, y0, x1, y1) & page_rect)
    return regions


def _region_membership(rect: pymupdf.Rect, regions: list[pymupdf.Rect]) -> set[int]:
    center = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    return {index for index, region in enumerate(regions) if center in region}


def _inside_shop_region(rect: pymupdf.Rect, regions: list[pymupdf.Rect]) -> bool:
    center = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    return any(center in region or bool(rect & region) and (rect & region).get_area() >= rect.get_area() * 0.25 for region in regions)


def _crop_offer(page, rect: pymupdf.Rect, target: Path, identity: str) -> Path | None:
    page_rect = page.rect
    width = max(150.0, rect.width * 2.1)
    height = max(130.0, rect.height * 2.2)
    center_x = (rect.x0 + rect.x1) / 2
    center_y = (rect.y0 + rect.y1) / 2
    clip = pymupdf.Rect(center_x - width / 2, center_y - height / 2, center_x + width / 2, center_y + height / 2) & page_rect
    try:
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7), clip=clip, alpha=False)
        target.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(identity.encode("utf-8", errors="ignore")).hexdigest()[:20]
        path = target / f"lidl-offer-{digest}.jpg"
        if not path.exists():
            pixmap.save(path)
        return path
    except (OSError, RuntimeError, ValueError):
        return None


def extract_lidl_pdf_offers(
    pdf_path: Path,
    source,
    *,
    valid_from: str,
    valid_to: str,
    flyer: dict | None = None,
    crop_dir: Path | None = None,
) -> LidlPdfExtraction:
    document = pymupdf.open(pdf_path)
    offers: list[CollectedOffer] = []
    pages_with_text: set[int] = set()
    pages_with_local: set[int] = set()
    ocr_candidates: set[int] = set()
    crop_count = 0

    for page_index, page in enumerate(document):
        page_no = page_index + 1
        full_text = page.get_text("text", sort=True).strip()
        if len(full_text) >= 80:
            pages_with_text.add(page_no)
        raw_blocks = [
            _Block(pymupdf.Rect(*block[:4]), block[4].strip())
            for block in page.get_text("blocks", sort=True)
            if block[4].strip() and block[1] < page.rect.height * 0.95
        ]
        product_blocks = [segment for block in raw_blocks for segment in _segments(block) if _PACKAGE.search(segment.text)]
        price_blocks = [(block, _price_values(block.text)) for block in raw_blocks]
        price_blocks = [(block, values) for block, values in price_blocks if values is not None]
        regions = _shop_regions(flyer, page_index, page.rect)
        shop_titles = _shop_titles(flyer, page_index)
        local_regions = _local_link_regions(flyer, page_index, page.rect)

        pairs: list[tuple[float, int, int]] = []
        for product_index, product in enumerate(product_blocks):
            for price_index, (price, _values) in enumerate(price_blocks):
                distance = _rect_distance(product.rect, price.rect)
                product_regions = _region_membership(product.rect, local_regions)
                price_regions = _region_membership(price.rect, local_regions)
                if product_regions and product_regions & price_regions:
                    distance -= 90
                elif product_regions and not product_regions & price_regions:
                    distance += 120
                if distance <= 175:
                    pairs.append((distance, product_index, price_index))
        used_products: set[int] = set()
        used_prices: set[int] = set()
        for _distance, product_index, price_index in sorted(pairs):
            if product_index in used_products or price_index in used_prices:
                continue
            product = product_blocks[product_index]
            price_block, values = price_blocks[price_index]
            name = _product_name(product.text)
            if not name:
                continue
            used_products.add(product_index)
            used_prices.add(price_index)
            price, regular, app_price = values
            combined = f"{product.text}\n{price_block.text}"
            if app_price is None and re.search(r"\bnormalpreis\b", product.text, re.I):
                prior = [value for value in (_number(match) for match in _ANY_PRICE.findall(price_block.text)) if value > price]
                if prior:
                    price, app_price = prior[-1], price
            quantity, unit = size(combined)
            unit_price = upr(combined)
            unit_price_unit = upr_unit(combined)
            effective_price = app_price if app_price is not None else price
            if unit_price is None:
                unit_price, unit_price_unit = compute_unit_price(effective_price, quantity, unit)
            online = _inside_shop_region(product.rect, regions) or _matches_shop_title(name, shop_titles)
            source_kind = "LidlPdfShopRegion" if online else "LidlPdfText"
            image_path = None
            if not online and crop_dir is not None:
                image_path = _crop_offer(
                    page,
                    product.rect | price_block.rect,
                    crop_dir,
                    f"{pdf_path}:{page_no}:{name}:{price}",
                )
                crop_count += int(image_path is not None)
            offer = CollectedOffer(
                source.key,
                source.store_name,
                source.retailer,
                name[:180],
                cat(name),
                price,
                regular_price=regular,
                app_price=app_price,
                unit_price=unit_price,
                unit_price_unit=unit_price_unit,
                quantity=quantity,
                unit=unit,
                valid_from=valid_from,
                valid_to=valid_to,
                source_text=f"PDF Seite {page_no}: {source_kind} {combined}"[:4000],
                source_url=source.url,
                local_store_offer=not online,
                confidence=.99 if not online else .98,
            )
            if image_path is not None:
                setattr(offer, "image_path", str(image_path))
                offer.image_alt = name
            offers.append(offer)
            if not online:
                pages_with_local.add(page_no)

        if page_no not in pages_with_text:
            ocr_candidates.add(page_no)

    document.close()
    return LidlPdfExtraction(
        offers=offers,
        pages_with_text=pages_with_text,
        pages_with_local_offers=pages_with_local,
        ocr_candidate_pages=ocr_candidates,
        image_crops=crop_count,
    )
