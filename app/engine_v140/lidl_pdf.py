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
_NON_PRODUCT_TITLE = re.compile(
    r"^(?:weitere\s+farben\s+online|standardgr(?:ö|�)ße|komfortgr(?:ö|�)ße|"
    r"king[- ]?size|ca\.\s*\d)",
    re.I,
)


@dataclass(frozen=True)
class LidlPdfExtraction:
    offers: list[CollectedOffer]
    pages_with_text: set[int]
    pages_with_local_offers: set[int]
    ocr_candidate_pages: set[int]
    image_crops: int
    price_anchors_detected: int = 0
    price_anchors_matched: int = 0
    price_anchors_ignored: int = 0
    price_anchors_unmatched: int = 0
    price_anchor_match_rate: float = 0.0
    page_offer_recall: float = 0.0
    pages_with_unmatched_prices: tuple[int, ...] = ()


@dataclass(frozen=True)
class _Block:
    rect: pymupdf.Rect
    text: str


@dataclass(frozen=True)
class _ProductCandidate:
    rect: pymupdf.Rect
    text: str
    title_text: str | None = None


@dataclass(frozen=True)
class _PriceAnchor:
    rect: pymupdf.Rect
    text: str
    price: float
    regular_price: float | None = None
    app_price: float | None = None


@dataclass(frozen=True)
class _ProductLinkEvidence:
    rect: pymupdf.Rect
    link: dict
    product: dict


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


def _product_title_spans(page) -> list[_Block]:
    """Return typographically explicit product-title spans from the PDF."""

    titles: list[_Block] = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        for line in block.get("lines", []):
            selected = []
            for span in line.get("spans", []):
                font = str(span.get("font") or "").lower()
                size_value = float(span.get("size") or 0)
                text = str(span.get("text") or "").strip()
                is_lidl_title = "cond" in font and "bold" in font
                is_test_title = font in {"helvetica-bold", "arial-boldmt"}
                if (
                    7.5 <= size_value <= 13.0
                    and (is_lidl_title or is_test_title)
                    and re.search(r"[A-Za-zÄÖÜäöüß]", text)
                ):
                    selected.append(span)
            if not selected:
                continue
            rect = pymupdf.Rect(selected[0]["bbox"])
            for span in selected[1:]:
                rect |= pymupdf.Rect(span["bbox"])
            titles.append(_Block(rect, " ".join(str(span["text"]).strip() for span in selected)))
    return titles


def _product_candidates(page, raw_blocks: list[_Block]) -> list[_ProductCandidate]:
    title_spans = _product_title_spans(page)
    candidates: list[_ProductCandidate] = []
    for block in raw_blocks:
        for segment in _segments(block):
            segment_titles = [
                title for title in title_spans
                if pymupdf.Point(
                    (title.rect.x0 + title.rect.x1) / 2,
                    (title.rect.y0 + title.rect.y1) / 2,
                ) in segment.rect
            ]
            title_groups: list[_Block] = []
            for title in sorted(segment_titles, key=lambda item: (item.rect.y0, item.rect.x0)):
                if not title_groups:
                    title_groups.append(title)
                    continue
                previous = title_groups[-1]
                vertical_gap = title.rect.y0 - previous.rect.y1
                horizontal_gap = max(title.rect.x0 - previous.rect.x1, previous.rect.x0 - title.rect.x1, 0.0)
                same_line = abs(title.rect.y0 - previous.rect.y0) <= 4
                if vertical_gap <= 4 and not (same_line and horizontal_gap > 20):
                    title_groups[-1] = _Block(previous.rect | title.rect, f"{previous.text} {title.text}")
                else:
                    title_groups.append(title)
            if not _PACKAGE.search(segment.text) and not title_groups:
                continue
            if not title_groups and _PACKAGE.search(segment.text):
                has_adjacent_title = any(
                    0 <= segment.rect.y0 - title.rect.y1 <= 24
                    and max(segment.rect.x0, title.rect.x0) < min(segment.rect.x1, title.rect.x1)
                    for title in title_spans
                )
                if has_adjacent_title:
                    continue
            if len(title_groups) > 1:
                for title in title_groups:
                    candidate = _ProductCandidate(title.rect, title.text, title.text)
                    if _product_name(title.text):
                        candidates.append(candidate)
                continue
            title_text = title_groups[0].text if title_groups else None
            candidate = _ProductCandidate(segment.rect, segment.text, title_text)
            if _product_name(title_text or segment.text):
                candidates.append(candidate)
    return candidates


def _plus_between(a: _Block, b: _Block, raw_blocks: list[_Block]) -> bool:
    corridor = (a.rect | b.rect) + (-18, -10, 18, 10)
    return any(
        re.search(r"\bmit\s+lidl\s+plus\b", block.text, re.I)
        and bool(corridor & block.rect)
        for block in raw_blocks
    )


def _price_anchors(page, raw_blocks: list[_Block]) -> list[_PriceAnchor]:
    """Build one sell-price anchor per visual offer region.

    UVP/reference prices stay metadata of the anchor. A vertically adjacent
    Lidl-Plus price is folded into the same anchor, so it cannot be counted or
    matched as a second product.
    """

    promo_spans: list[tuple[_Block, float]] = []
    for page_block in page.get_text("dict", sort=True).get("blocks", []):
        for line in page_block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "").strip()
                match = _PROMO_PRICE.search(text)
                if match:
                    promo_spans.append((_Block(pymupdf.Rect(span["bbox"]), text), _number(match.group(1))))

    priced = [(block, _price_values(block.text)) for block in raw_blocks]
    priced = [(block, values) for block, values in priced if values is not None]
    consumed: set[int] = set()
    anchors: list[_PriceAnchor] = []
    for index, (block, values) in enumerate(priced):
        if index in consumed:
            continue
        price, regular, app_price = values
        matching_spans = [
            span for span, span_price in promo_spans
            if abs(span_price - price) < 0.011
            and pymupdf.Point(
                (span.rect.x0 + span.rect.x1) / 2,
                (span.rect.y0 + span.rect.y1) / 2,
            ) in block.rect
        ]
        price_rect = matching_spans[-1].rect if matching_spans else block.rect
        partner_index = None
        if app_price is None:
            for other_index, (other, other_values) in enumerate(priced):
                if other_index == index or other_index in consumed:
                    continue
                other_price, _other_regular, other_app = other_values
                vertical_gap = max(other.rect.y0 - block.rect.y1, block.rect.y0 - other.rect.y1, 0.0)
                center_dx = abs((block.rect.x0 + block.rect.x1) - (other.rect.x0 + other.rect.x1)) / 2
                if (
                    other_app is None
                    and other.rect.y0 >= block.rect.y0
                    and other_price < price
                    and vertical_gap <= 45
                    and center_dx <= 55
                    and _plus_between(block, other, raw_blocks)
                ):
                    partner_index = other_index
                    break
        if partner_index is not None:
            other, other_values = priced[partner_index]
            consumed.add(partner_index)
            other_spans = [
                span for span, span_price in promo_spans
                if abs(span_price - other_values[0]) < 0.011
                and pymupdf.Point(
                    (span.rect.x0 + span.rect.x1) / 2,
                    (span.rect.y0 + span.rect.y1) / 2,
                ) in other.rect
            ]
            other_rect = other_spans[-1].rect if other_spans else other.rect
            anchors.append(
                _PriceAnchor(
                    price_rect | other_rect,
                    f"{block.text}\n{other.text}",
                    price,
                    regular,
                    other_values[0],
                )
            )
        else:
            anchors.append(_PriceAnchor(price_rect, block.text, price, regular, app_price))
    return anchors


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
    if _NON_PRODUCT_TITLE.search(name):
        return None
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


def _layout_distance(product: pymupdf.Rect, price: pymupdf.Rect) -> float:
    """Column-aware distance between a product label and its sell price."""

    vertical_overlap = max(0.0, min(product.y1, price.y1) - max(product.y0, price.y0))
    if vertical_overlap > 0:
        dx = max(product.x0 - price.x1, price.x0 - product.x1, 0.0)
        center_y = abs((product.y0 + product.y1) - (price.y0 + price.y1)) / 2
        center_x = abs((product.x0 + product.x1) - (price.x0 + price.x1)) / 2
        return dx * 0.72 + center_y * 0.08 + center_x * 0.025
    return _rect_distance(product, price)


def _region_text(product: _ProductCandidate, price: _PriceAnchor, raw_blocks: list[_Block]) -> str:
    normalized_product = re.sub(r"\s+", " ", product.text).strip()
    normalized_title = re.sub(r"\s+", " ", product.title_text or "").strip()
    if not normalized_title or normalized_product != normalized_title:
        return f"{product.text.strip()}\n{price.text.strip()}"
    region = (product.rect | price.rect) + (-12, -12, 12, 12)
    selected = []
    for block in raw_blocks:
        center = pymupdf.Point(
            (block.rect.x0 + block.rect.x1) / 2,
            (block.rect.y0 + block.rect.y1) / 2,
        )
        if center in region:
            selected.append(block)
    selected.sort(key=lambda block: (block.rect.y0, block.rect.x0))
    values: list[str] = []
    for text in [product.text, *(block.text for block in selected), price.text]:
        text = text.strip()
        if text and text not in values:
            values.append(text)
    return "\n".join(values)


def _product_catalog(flyer: dict | None) -> dict[str, dict]:
    products = (flyer or {}).get("products") or []
    values = products.values() if isinstance(products, dict) else products
    return {
        str(product.get("productId")): product
        for product in values
        if isinstance(product, dict) and product.get("productId") is not None
    }


def _product_link_evidence(
    flyer: dict | None,
    page_index: int,
    page_rect: pymupdf.Rect,
) -> list[_ProductLinkEvidence]:
    pages = (flyer or {}).get("pages") or []
    if page_index >= len(pages) or not isinstance(pages[page_index], dict):
        return []
    catalog = _product_catalog(flyer)
    evidence: list[_ProductLinkEvidence] = []
    for link in pages[page_index].get("links") or []:
        if not isinstance(link, dict) or classify_lidl_link(link) is not LidlSourceKind.ONLINE_ONLY:
            continue
        details = link.get("productDetails") or {}
        product = catalog.get(str(details.get("productId") or ""), {})
        try:
            x0 = page_rect.width * float(link.get("left")) / 100.0
            y0 = page_rect.height * float(link.get("top")) / 100.0
            x1 = x0 + page_rect.width * float(link.get("width")) / 100.0
            y1 = y0 + page_rect.height * float(link.get("height")) / 100.0
        except (TypeError, ValueError):
            continue
        rect = pymupdf.Rect(x0 - 12, y0 - 10, x1 + 12, y1 + 90) & page_rect
        evidence.append(_ProductLinkEvidence(rect, link, product))
    return evidence


def _evidence_title(evidence: _ProductLinkEvidence) -> str:
    return str(
        evidence.product.get("title")
        or evidence.link.get("title")
        or (evidence.link.get("productDetails") or {}).get("title")
        or ""
    ).strip()


def _title_tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-zäöüß0-9]+", value.lower())
        if len(token) >= 3 and token not in {"und", "oder", "mit", "fuer", "für", "stueck", "stück"}
    }


def _matches_shop_title(name: str, titles: list[str]) -> bool:
    def tokens(value: str) -> set[str]:
        return _title_tokens(value)

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


def _matching_product_evidence(
    rect: pymupdf.Rect,
    name: str,
    price: float,
    evidence: list[_ProductLinkEvidence],
) -> _ProductLinkEvidence | None:
    spatial = [item for item in evidence if _inside_shop_region(rect, [item.rect])]
    title_matches = [
        item for item in evidence
        if _matches_shop_title(name, [_evidence_title(item)])
    ]
    candidates: list[_ProductLinkEvidence] = []
    for item in [*spatial, *title_matches]:
        if item not in candidates:
            candidates.append(item)
    if not candidates:
        return None
    name_tokens = _title_tokens(name)
    def same_price(item: _ProductLinkEvidence) -> int:
        try:
            return int(abs(float(str(item.product.get("price")).replace(",", ".")) - price) < 0.011)
        except (TypeError, ValueError):
            return 0

    return max(
        candidates,
        key=lambda item: (
            same_price(item),
            len(name_tokens & _title_tokens(_evidence_title(item))),
            -_rect_distance(rect, item.rect),
        ),
    )


def _page_is_online_only(page_text: str) -> bool:
    low = re.sub(r"\s+", " ", page_text).lower()
    return "shoppe auf lidl.de" in low or (
        "online shoppen" in low and "onlineshop-angebote" in low
    )


def _exact_image_identity(name: str, price: float, product: dict) -> bool:
    """Require exact hotspot identity, compatible title and identical price."""
    if not product.get("productId") or not product.get("image"):
        return False
    try:
        product_price = float(str(product.get("price")).replace(",", "."))
    except (TypeError, ValueError):
        return False
    name_tokens = _title_tokens(name)
    product_title = str(product.get("title") or "")
    product_tokens = _title_tokens(product_title)
    overlap = name_tokens & product_tokens
    normalized_name = re.sub(r"\s+", " ", name.lower())
    normalized_title = re.sub(r"\s+", " ", product_title.lower())
    for marker in ("king size", "standardgröße", "standardgroesse"):
        if (marker in normalized_name) != (marker in normalized_title):
            return False
    dimensions = re.compile(r"\b\d{2,3}\s*[x×]\s*\d{2,3}\b", re.I)
    name_dimensions = {re.sub(r"\s+", "", value.lower()) for value in dimensions.findall(name)}
    title_dimensions = {re.sub(r"\s+", "", value.lower()) for value in dimensions.findall(product_title)}
    if name_dimensions and title_dimensions and name_dimensions != title_dimensions:
        return False
    return (
        abs(product_price - float(price)) < 0.011
        and len(overlap) >= min(2, len(name_tokens), len(product_tokens))
        and len(overlap) / max(1, min(len(name_tokens), len(product_tokens))) >= 0.6
    )


def _local_link_regions(flyer: dict | None, page_index: int, page_rect: pymupdf.Rect) -> list[pymupdf.Rect]:
    pages = (flyer or {}).get("pages") or []
    if page_index >= len(pages) or not isinstance(pages[page_index], dict):
        return []
    regions = []
    for link in pages[page_index].get("links") or []:
        if not isinstance(link, dict) or classify_lidl_link(link) not in {
            LidlSourceKind.LOCAL_ONLY,
            LidlSourceKind.ONLINE_ONLY,
        }:
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
    anchors_detected = 0
    anchors_matched = 0
    pages_with_unmatched: set[int] = set()

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
        product_blocks = _product_candidates(page, raw_blocks)
        price_blocks = _price_anchors(page, raw_blocks)
        product_evidence = _product_link_evidence(flyer, page_index, page.rect)
        local_regions = _local_link_regions(flyer, page_index, page.rect)
        page_online_only = _page_is_online_only(full_text)

        pairs: list[tuple[float, int, int]] = []
        for product_index, product in enumerate(product_blocks):
            for price_index, price in enumerate(price_blocks):
                distance = _layout_distance(product.rect, price.rect)
                product_regions = _region_membership(product.rect, local_regions)
                price_regions = _region_membership(price.rect, local_regions)
                if product_regions and product_regions & price_regions:
                    distance -= 90
                elif product_regions and not product_regions & price_regions:
                    distance += 120
                normalized_title = re.sub(r"\s+", " ", product.title_text or "").strip().lower()
                normalized_anchor = re.sub(r"\s+", " ", price.text).strip().lower()
                # PDF content streams sometimes place the preceding card's
                # price immediately before the next card title in one block.
                # That textual containment is not ownership evidence.
                if (
                    normalized_title
                    and normalized_title in normalized_anchor
                    and _PROMO_PRICE.match(normalized_anchor)
                    and normalized_anchor.index(normalized_title) > 0
                ):
                    distance += 90
                if distance <= 185:
                    pairs.append((distance, product_index, price_index))
        adjacency: dict[int, list[tuple[float, int]]] = {}
        for distance, product_index, price_index in pairs:
            adjacency.setdefault(product_index, []).append((distance, price_index))
        for options in adjacency.values():
            options.sort()

        price_owner: dict[int, int] = {}

        def assign(product_index: int, seen_prices: set[int]) -> bool:
            for _distance, price_index in adjacency.get(product_index, []):
                if price_index in seen_prices:
                    continue
                seen_prices.add(price_index)
                owner = price_owner.get(price_index)
                if owner is None or assign(owner, seen_prices):
                    price_owner[price_index] = product_index
                    return True
            return False

        # Constrained labels go first. The augmenting-path matcher maximizes
        # page recall before minimizing local distance, unlike the previous
        # greedy pass which let a flexible neighbour steal their only anchor.
        for product_index in sorted(adjacency, key=lambda item: (len(adjacency[item]), adjacency[item][0][0])):
            assign(product_index, set())

        assignments = [
            (
                next(distance for distance, candidate_price in adjacency[product_index] if candidate_price == price_index),
                product_index,
                price_index,
            )
            for price_index, product_index in price_owner.items()
        ]
        assigned_prices = set(price_owner)
        for price_index in range(len(price_blocks)):
            if price_index in assigned_prices:
                continue
            candidates = sorted(
                (distance, product_index)
                for distance, product_index, candidate_price in pairs
                if candidate_price == price_index
            )
            if candidates:
                distance, product_index = candidates[0]
                assignments.append((distance, product_index, price_index))
                assigned_prices.add(price_index)
        assignment_counts: dict[int, int] = {}
        for _distance, product_index, _price_index in assignments:
            assignment_counts[product_index] = assignment_counts.get(product_index, 0) + 1
        balanced: list[tuple[float, int, int]] = []
        for distance, product_index, price_index in assignments:
            alternatives = sorted(
                (candidate_distance, candidate_product)
                for candidate_distance, candidate_product, candidate_price in pairs
                if candidate_price == price_index
                and candidate_product != product_index
                and assignment_counts.get(candidate_product, 0) < assignment_counts.get(product_index, 0)
                and candidate_distance < distance
            )
            if alternatives:
                new_distance, new_product = alternatives[0]
                assignment_counts[product_index] -= 1
                assignment_counts[new_product] = assignment_counts.get(new_product, 0) + 1
                balanced.append((new_distance, new_product, price_index))
            else:
                balanced.append((distance, product_index, price_index))
        assignments = balanced
        used_products = {product_index for _distance, product_index, _price_index in assignments}
        used_prices = assigned_prices
        for _distance, product_index, price_index in sorted(assignments):
            product = product_blocks[product_index]
            price_block = price_blocks[price_index]
            name = _product_name(product.title_text or product.text)
            if not name:
                continue
            price, regular, app_price = price_block.price, price_block.regular_price, price_block.app_price
            combined = _region_text(product, price_block, raw_blocks)
            if app_price is None and re.search(r"\bnormalpreis\b", combined, re.I):
                prior = [value for value in (_number(match) for match in _ANY_PRICE.findall(price_block.text)) if value > price]
                if prior:
                    price, app_price = prior[-1], price
            quantity, unit = size(combined)
            unit_price = upr(combined)
            unit_price_unit = upr_unit(combined)
            effective_price = app_price if app_price is not None else price
            if unit_price is None:
                unit_price, unit_price_unit = compute_unit_price(effective_price, quantity, unit)
            matched_evidence = _matching_product_evidence(
                product.rect | price_block.rect,
                name,
                price,
                product_evidence,
            )
            if page_online_only:
                availability = LidlSourceKind.ONLINE_ONLY
            elif matched_evidence is not None:
                availability = LidlSourceKind.LOCAL_AND_ONLINE
            else:
                availability = LidlSourceKind.LOCAL_ONLY
            local = availability is not LidlSourceKind.ONLINE_ONLY
            source_kind = f"LidlPdfText:{availability.value}"
            image_path = None
            if local and crop_dir is not None:
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
                local_store_offer=local,
                confidence=.99 if local else .98,
            )
            offer.lidl_availability = availability.value
            if matched_evidence is not None:
                details = matched_evidence.link.get("productDetails") or {}
                catalog_product = matched_evidence.product
                offer.lidl_product_id = str(
                    catalog_product.get("productId") or details.get("productId") or ""
                )
                offer.canonical_url = str(
                    catalog_product.get("canonicalUrl")
                    or catalog_product.get("url")
                    or matched_evidence.link.get("url")
                    or ""
                )
                if local and _exact_image_identity(name, price, catalog_product):
                    offer.image_url = str(catalog_product.get("image"))
                    offer.image_media_source = "official_product"
                    offer.image_identity_key = f"lidl:productId:{offer.lidl_product_id}"
            if image_path is not None:
                setattr(offer, "image_path", str(image_path))
                offer.audit_image_path = str(image_path)
                offer.image_alt = name
            offers.append(offer)
            if local:
                pages_with_local.add(page_no)

        if not page_online_only:
            anchors_detected += len(price_blocks)
            anchors_matched += len(used_prices)
            if len(used_prices) < len(price_blocks):
                pages_with_unmatched.add(page_no)

        if page_no not in pages_with_text:
            ocr_candidates.add(page_no)

    document.close()
    unmatched = max(0, anchors_detected - anchors_matched)
    match_rate = round(anchors_matched / anchors_detected * 100.0, 1) if anchors_detected else 100.0
    result = LidlPdfExtraction(
        offers=offers,
        pages_with_text=pages_with_text,
        pages_with_local_offers=pages_with_local,
        ocr_candidate_pages=ocr_candidates,
        image_crops=crop_count,
        price_anchors_detected=anchors_detected,
        price_anchors_matched=anchors_matched,
        price_anchors_ignored=0,
        price_anchors_unmatched=unmatched,
        price_anchor_match_rate=match_rate,
        page_offer_recall=match_rate,
        pages_with_unmatched_prices=tuple(sorted(pages_with_unmatched)),
    )
    for offer in result.offers:
        offer.lidl_price_anchors_detected = anchors_detected
        offer.lidl_price_anchors_matched = anchors_matched
        offer.lidl_price_anchors_ignored = 0
        offer.lidl_price_anchors_unmatched = unmatched
        offer.lidl_price_anchor_match_rate = match_rate
        offer.lidl_page_offer_recall = match_rate
        offer.lidl_pages_with_unmatched_prices = tuple(sorted(pages_with_unmatched))
    return result
