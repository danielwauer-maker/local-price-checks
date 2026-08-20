from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
import math
import re
import time
from pathlib import Path

import pymupdf
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .collectors import CollectedOffer, cat, compute_unit_price, size, upr, upr_unit
from .offer_quality import evaluate_offer
from .product_cleaning import clean_product_name, product_name_issue
from .source_registry import RetailSource
from .week_utils import infer_validity


_ALPHA_RE = re.compile(r"[A-Za-zÄÖÜäöüß]{3,}")
_QUANTITY_RE = re.compile(
    r"\b(?:je\s*)?(?:(\d{1,2})\s*[x×]\s*)?(\d+(?:[,.]\d+)?)\s*[- ]?"
    r"(kg|g|l|ml|stück|st\.?|packung|becher|dose|flasche|glas|beutel|schale|netz|bund)\b",
    re.I,
)
_UNIT_PRICE_RE = re.compile(
    r"(?:1\s*)?(kg|l|100\s*g|100\s*ml)\s*(?:=|:)\s*(?:€\s*)?(\d{1,3}(?:[,.]\d{1,2})?)",
    re.I,
)
_IGNORE_CONTEXT = (
    "extra punkte",
    "sofort-rabatt",
    "sofort rabatt",
    "mindestumsatz",
    "neuanmelder",
    "gutscheinwert",
    "coupon nutzen",
    "gratis dazu",
)
_TITLE_NOISE = (
    "versch. sorten",
    "verschiedene sorten",
    "klasse i",
    "klasse ii",
    "fett i. tr",
    "fett i.tr",
    "tiefgefroren",
    "gekühlt",
    "je ",
    "1 kg =",
    "1 l =",
    "statt ",
    "mit app",
    "extra punkte",
    "haltungsform",
    "angebot",
    "ready-to-eat",
    "ready to eat",
    "mit ",
    "oder ",
    "auch ",
    "festkochend",
    "klassisch",
    "schweizer",
    "naturell",
    "mild-würzig",
    "geschmack",
    "aroma",
    "getrocknete",
)
_CATEGORY_HEADERS = {
    "obst & gemüse",
    "fleisch",
    "wurst",
    "käse & kühlregal",
    "kühlregal & tk",
    "schnelle küche",
    "frühstück",
    "knabbereien",
    "getränke",
    "drogerie",
    "frischfisch-theke",
}
_COUNTRIES = {
    "deutschland",
    "niederlande",
    "spanien",
    "italien",
    "frankreich",
    "portugal",
    "griechenland",
    "südafrika",
    "senegal",
    "peru",
    "rumänien",
    "neuseeland",
}
_EXTRACTION_CACHE_VERSION = 1


@dataclass(frozen=True)
class OcrWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2


@dataclass
class EdekaPriceAnchor:
    bbox: tuple[int, int, int, int]
    price: float
    reference_price: float | None = None
    raw_tokens: tuple[str, ...] = ()

    @property
    def center_x(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2


@dataclass
class EdekaPdfExtraction:
    offers: list[CollectedOffer]
    page_count: int
    native_text_pages: list[int]
    ocr_pages: list[int]
    price_anchors_detected: int
    price_anchors_matched: int
    price_anchors_ignored: int
    price_anchors_unmatched: int
    pages_with_unmatched_prices: list[int]
    page_offer_recall: float
    diagnostics_path: Path | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def price_anchor_match_rate(self) -> float:
        eligible = self.price_anchors_detected - self.price_anchors_ignored
        if eligible <= 0:
            return 0.0
        return round(self.price_anchors_matched / eligible * 100.0, 1)

    @property
    def technical_warning(self) -> str | None:
        if not self.price_anchors_unmatched:
            return None
        pages = ",".join(map(str, self.pages_with_unmatched_prices)) or "-"
        return (
            f"unmatched_local_price_anchors={self.price_anchors_unmatched} "
            f"pages_with_unmatched_prices={pages}"
        )


def _prepared_page(page) -> Image.Image:
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(2.0, 2.0),
        alpha=False,
        colorspace=pymupdf.csRGB,
    )
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _ocr_words(image: Image.Image, timeout_seconds: float) -> list[OcrWord]:
    try:
        import pytesseract
    except Exception as exc:  # pragma: no cover - production dependency guard
        raise RuntimeError("pytesseract ist für bildbasierte EDEKA-PDFs erforderlich") from exc

    prepared = ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(1.35)
    data = pytesseract.image_to_data(
        prepared,
        lang="deu",
        config="--psm 11",
        output_type=pytesseract.Output.DICT,
        timeout=max(1.0, timeout_seconds),
    )
    words = []
    for index, raw in enumerate(data.get("text") or []):
        text = str(raw or "").strip()
        confidence = float(data["conf"][index])
        if not text or confidence < 0:
            continue
        words.append(
            OcrWord(
                text=text,
                left=int(data["left"][index]),
                top=int(data["top"][index]),
                width=int(data["width"][index]),
                height=int(data["height"][index]),
                confidence=confidence,
            )
        )
    return words


def _red_components(image: Image.Image) -> list[tuple[int, int, int, int]]:
    scale = 4
    reduced = image.resize((image.width // scale, image.height // scale))
    width, height = reduced.size
    red = [r > 160 and g < 125 and b < 120 for r, g, b in reduced.getdata()]
    seen = [False] * len(red)
    boxes = []
    for y in range(height):
        for x in range(width):
            offset = y * width + x
            if seen[offset] or not red[offset]:
                continue
            seen[offset] = True
            queue = deque([(x, y)])
            points = []
            while queue:
                px, py = queue.popleft()
                points.append((px, py))
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    noffset = ny * width + nx
                    if red[noffset] and not seen[noffset]:
                        seen[noffset] = True
                        queue.append((nx, ny))
            if len(points) < 70:
                continue
            x0 = max(0, min(point[0] for point in points) * scale - 8)
            y0 = max(0, min(point[1] for point in points) * scale - 8)
            x1 = min(image.width, (max(point[0] for point in points) + 1) * scale + 8)
            y1 = min(image.height, (max(point[1] for point in points) + 1) * scale + 8)
            box_width = x1 - x0
            box_height = y1 - y0
            if 90 <= box_width <= 230 and 80 <= box_height <= 185:
                boxes.append((x0, y0, x1, y1))
    return boxes


def _tag_number_tokens(image: Image.Image, bbox: tuple[int, int, int, int]) -> list[dict]:
    import pytesseract

    crop = image.crop(bbox)
    prepared = Image.new("L", crop.size)
    prepared.putdata(
        [0 if r > 170 and g > 170 and b > 170 else 255 for r, g, b in crop.getdata()]
    )
    prepared = prepared.filter(ImageFilter.MaxFilter(3))
    data = pytesseract.image_to_data(
        prepared,
        config="--psm 11 -c tessedit_char_whitelist=0123456789,.%€-",
        output_type=pytesseract.Output.DICT,
    )
    tokens = []
    for index, raw in enumerate(data.get("text") or []):
        text = str(raw or "").strip()
        confidence = float(data["conf"][index])
        if text and confidence >= 0:
            tokens.append(
                {
                    "text": text,
                    "confidence": confidence,
                    "height": int(data["height"][index]),
                    "width": int(data["width"][index]),
                    "top": int(data["top"][index]),
                }
            )
    return tokens


def _numeric_price(raw: str) -> float | None:
    normalized = (raw or "").replace(",", ".")
    direct = re.search(r"(?<!\d)(\d{1,3})\.(\d{2})(?!\d)", normalized)
    if direct:
        value = float(f"{direct.group(1)}.{direct.group(2)}")
        return value if 0.05 <= value <= 500 else None
    digits = re.sub(r"\D", "", raw or "")
    if not 3 <= len(digits) <= 5:
        return None
    value = int(digits) / 100
    return value if 0.05 <= value <= 500 else None


def _anchor_from_box(image: Image.Image, bbox: tuple[int, int, int, int]) -> EdekaPriceAnchor | None:
    tokens = _tag_number_tokens(image, bbox)
    candidates = []
    for token in tokens:
        value = _numeric_price(token["text"])
        if value is None or "%" in token["text"]:
            continue
        score = token["height"] * token["width"] + token["top"] * 2
        candidates.append((score, value, token))
    if not candidates:
        return None
    candidates.sort(reverse=True, key=lambda item: item[0])
    current = candidates[0][1]
    higher = [value for _, value, _ in candidates[1:] if value > current]
    reference = min(higher) if higher else None
    return EdekaPriceAnchor(
        bbox=bbox,
        price=current,
        reference_price=reference,
        raw_tokens=tuple(token["text"] for token in tokens),
    )


def _line_groups(words: list[OcrWord], *, x0: float, y0: float, x1: float, y1: float) -> list[dict]:
    selected = [
        word
        for word in words
        if x0 <= word.center_x <= x1 and y0 <= word.center_y <= y1
    ]
    selected.sort(key=lambda word: (word.center_y, word.left))
    lines: list[dict] = []
    for word in selected:
        match = next(
            (
                line
                for line in reversed(lines[-5:])
                if abs(line["center_y"] - word.center_y) <= max(10.0, min(20.0, word.height * 0.55))
            ),
            None,
        )
        if match is None:
            lines.append({"center_y": word.center_y, "words": [word]})
        else:
            match["words"].append(word)
            match["center_y"] = sum(item.center_y for item in match["words"]) / len(match["words"])
    result = []
    for line in lines:
        line_words = sorted(line["words"], key=lambda word: word.left)
        result.append(
            {
                "text": " ".join(word.text for word in line_words),
                "top": min(word.top for word in line_words),
                "bottom": max(word.bottom for word in line_words),
                "left": min(word.left for word in line_words),
                "right": max(word.right for word in line_words),
                "max_height": max(word.height for word in line_words),
                "confidence": sum(word.confidence for word in line_words) / len(line_words),
            }
        )
    return sorted(result, key=lambda line: (line["top"], line["left"]))


def _normalize_context(text: str) -> str:
    value = (text or "").replace("Ikg", "1 kg").replace("Ixg", "1 kg")
    value = re.sub(r"\bI\s*kg\b", "1 kg", value, flags=re.I)
    value = re.sub(r"\bI\s*l\b", "1 l", value, flags=re.I)
    value = re.sub(r"\b(\d+(?:[,.]\d+)?)\s+mi\b", r"\1 ml", value, flags=re.I)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _dense_ocr_lines(image: Image.Image, bbox: tuple[int, int, int, int], *, psm: int = 6) -> list[str]:
    import pytesseract

    crop = image.crop(bbox)
    text = pytesseract.image_to_string(
        crop,
        lang="deu",
        config=f"--psm {psm}",
        timeout=12,
    )
    return [re.sub(r"\s+", " ", line).strip(" |") for line in text.splitlines() if line.strip()]


def _quantity(text: str) -> tuple[float | None, str | None]:
    match = _QUANTITY_RE.search(_normalize_context(text))
    if not match:
        return size(text)
    count = float(match.group(1)) if match.group(1) else 1.0
    quantity = float(match.group(2).replace(",", ".")) * count
    unit = match.group(3).lower().rstrip(".")
    if unit in {"flasche", "dose"} and quantity <= 10:
        return quantity, "l"
    unit = {
        "st": "stück",
        "packung": "stück",
        "becher": "stück",
        "dose": "stück",
        "flasche": "stück",
        "glas": "stück",
        "beutel": "stück",
        "schale": "stück",
        "netz": "stück",
        "bund": "stück",
    }.get(unit, unit)
    return quantity, unit


def _unit_price(text: str) -> tuple[float | None, str | None]:
    normalized = _normalize_context(text)
    match = next(
        (
            candidate
            for candidate in _UNIT_PRICE_RE.finditer(normalized)
            if not re.match(r"\s*(?:g|ml)\b", normalized[candidate.end():], re.I)
        ),
        None,
    )
    if not match:
        return upr(normalized), upr_unit(normalized)
    raw_unit = match.group(1).lower().replace(" ", "")
    value = float(match.group(2).replace(",", "."))
    if value <= 0 or value > 500:
        return None, None
    if raw_unit == "100g":
        return value * 10, "kg"
    if raw_unit == "100ml":
        return value * 10, "l"
    return value, raw_unit


def _usable_title_line(text: str) -> bool:
    value = clean_product_name(text or "").strip(" -,:;.")
    low = value.lower()
    alpha_words = re.findall(r"[A-Za-zÄÖÜäöüß]+", value)
    if not _ALPHA_RE.search(value) or not any(len(word) >= 4 for word in alpha_words) or len(value) < 4 or len(value) > 65:
        return False
    normalized = _normalize_context(value).lower()
    if "€" in value or re.search(r"\b(?:1\s*kg|1\s*l|100\s*g)\b", normalized):
        return False
    if sum(character.isalpha() for character in value) / max(len(value), 1) < 0.55:
        return False
    if low in _COUNTRIES or low in _CATEGORY_HEADERS or low in {"stück", "packung", "becher", "flasche"} or any(low.startswith(prefix) for prefix in _TITLE_NOISE):
        return False
    if _QUANTITY_RE.search(value) or _UNIT_PRICE_RE.search(_normalize_context(value)):
        return False
    if re.search(r"\b(?:klasse|fett|vol\.?|pfand|abtopfgew|packung|becher|flasche|schale)\b", low):
        return False
    if any(token in low for token in ("edeka.de", "lebensmittel", "wochenend", "knüller", "payback", "echt nrw", "extra°punkte", "extra punkte")):
        return False
    return not product_name_issue(value)


def _dense_product_name(lines: list[str]) -> str:
    package_indices = [
        index
        for index, line in enumerate(lines)
        if _QUANTITY_RE.search(_normalize_context(line))
        or re.search(r"\bje\s+(?:Stück|Topf|Bund)\b", line, re.I)
    ]
    # A column crop can still contain the tail of the preceding card.  The
    # package line closest to the price anchor is the last one in reading
    # order; using the first one associates the preceding offer instead.
    boundary = package_indices[-1] if package_indices else len(lines)
    candidates = []
    for index in range(boundary - 1, max(-1, boundary - 10), -1):
        raw_value = re.split(
            r"\b(?:Klasse|Handelsklasse|versch\.?|tiefgefroren|je\s+\d)\b",
            lines[index],
            maxsplit=1,
            flags=re.I,
        )[0]
        raw_value = re.sub(
            r"^(?:Deutschland|Niederlande|Spanien|Italien|Frankreich|Portugal|Griechenland|Österreich)\s+",
            "",
            raw_value,
            flags=re.I,
        )
        value = clean_product_name(raw_value).strip(" -,:;.")
        value = re.sub(r"^[A-ZÄÖÜ]{1,2}\s+[-_]+\s*", "", value).strip()
        value = re.sub(r"[,;]\s*[a-zäöüß]{1,2}$", "", value).strip(" -,:;.")
        if not _usable_title_line(value):
            continue
        value = re.sub(r"^(?:EDEKA|GUT\s*&\s*GÜNSTIG)\s+(?=(?:Mango|Avocado|Zitron|Kartoff|Beeren|Möhren|Zwiebel))", "", value, flags=re.I)
        alpha_words = re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", value)
        distance = boundary - index
        score = len(alpha_words) * 14 + min(len(value), 50) - distance * 10
        if len(alpha_words) == 1:
            score -= 30
        candidates.append((score, index, value))
    if candidates:
        candidates.sort(reverse=True)
        _score, best_index, best_value = candidates[0]
        best_words = re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", best_value)
        may_join_single_neighbor = len(best_words) == 1 or best_value.lstrip().startswith(("„", "\"", "'"))
        adjacent = next(
            (
                (index, value) for _candidate_score, index, value in candidates[1:]
                if may_join_single_neighbor
                and abs(index - best_index) == 1
                and len(re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", value)) == 1
                and len(f"{best_value} {value}") <= 65
            ),
            None,
        )
        if adjacent:
            ordered = [(best_index, best_value), adjacent]
            ordered.sort()
            return " ".join(value for _, value in ordered)
        return best_value
    for line in lines:
        value = clean_product_name(line).strip(" -,:;.")
        if _usable_title_line(value):
            return value
    return ""


def _name_quality(name: str) -> float:
    words = re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", name or "")
    letters = sum(character.isalpha() for character in name or "")
    symbols = sum(not character.isalnum() and not character.isspace() and character not in "&-/" for character in name or "")
    uppercase_letters = sum(character.isupper() for character in name or "")
    uppercase_ratio = uppercase_letters / max(letters, 1)
    uppercase_penalty = 45 if letters >= 6 and uppercase_ratio > 0.85 and symbols else 0
    return len(words) * 25 + min(letters, 70) - symbols * 12 - (18 if len(words) == 1 else 0) - uppercase_penalty


def _product_name(lines: list[dict], anchor_top: int) -> str:
    package_indices = [
        index
        for index, line in enumerate(lines)
        if line["top"] < anchor_top and _QUANTITY_RE.search(_normalize_context(line["text"]))
    ]
    boundary = package_indices[-1] if package_indices else len(lines)
    candidates = []
    for index in range(boundary - 1, max(-1, boundary - 8), -1):
        text = lines[index]["text"].strip()
        if _usable_title_line(text):
            distance = max(0, lines[boundary]["top"] - lines[index]["bottom"]) if boundary < len(lines) else max(0, anchor_top - lines[index]["bottom"])
            score = float(lines[index].get("max_height", 0)) * 4.0 - distance * 0.22 + min(len(text), 50) * 0.08
            candidates.append((score, index, text))
    if not candidates:
        for line in reversed(lines):
            if line["bottom"] >= anchor_top or anchor_top - line["bottom"] > 260:
                continue
            if _usable_title_line(line["text"]):
                candidates.append((float(line.get("max_height", 0)) * 4.0, lines.index(line), line["text"]))
                break
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    _, best_index, best_text = candidates[0]
    selected = [(best_index, best_text)]
    for _score, index, text in candidates[1:]:
        if abs(index - best_index) == 1 and abs(lines[index].get("max_height", 0) - lines[best_index].get("max_height", 0)) <= 7:
            selected.append((index, text))
            break
    selected.sort()
    name = clean_product_name(" ".join(text for _, text in selected))
    name = re.sub(r"\s+(?:oder|und|mit|aus|von|für)$", "", name, flags=re.I).strip(" -,:;.")
    return name if _usable_title_line(name) else ""


def _expected_price(quantity: float | None, unit: str | None, unit_price: float | None, unit_price_unit: str | None) -> float | None:
    if quantity is None or not unit or unit_price is None or not unit_price_unit:
        return None
    if unit == "g" and unit_price_unit == "kg":
        return quantity * unit_price / 1000
    if unit == "kg" and unit_price_unit == "kg":
        return quantity * unit_price
    if unit == "ml" and unit_price_unit == "l":
        return quantity * unit_price / 1000
    if unit == "l" and unit_price_unit == "l":
        return quantity * unit_price
    return None


def _offer_crop(
    image: Image.Image,
    anchor: EdekaPriceAnchor,
    *,
    page_no: int,
    identity: str,
    crop_dir: Path | None,
) -> tuple[Path | None, tuple[int, int, int, int]]:
    center_x = anchor.center_x
    column_width = image.width / 3
    column = min(2, max(0, int(center_x / column_width)))
    x0 = max(0, int(column * column_width) - 28)
    x1 = min(image.width, int((column + 1) * column_width) + 28)
    y0 = max(0, anchor.bbox[1] - 480)
    y1 = min(image.height, anchor.bbox[3] + 150)
    bbox = (x0, y0, x1, y1)
    if crop_dir is None:
        return None, bbox
    crop_dir.mkdir(parents=True, exist_ok=True)
    target = crop_dir / f"p{page_no:02d}-{identity[:16]}.jpg"
    image.crop(bbox).save(target, format="JPEG", quality=88, optimize=True)
    return target, bbox


def _page_offer(
    source: RetailSource,
    image: Image.Image,
    words: list[OcrWord],
    anchor: EdekaPriceAnchor,
    *,
    page_no: int,
    valid_from: str | None,
    valid_to: str | None,
    source_url: str,
    crop_dir: Path | None,
) -> tuple[CollectedOffer | None, dict]:
    lines = _line_groups(
        words,
        x0=max(0, anchor.center_x - 220),
        y0=max(0, anchor.bbox[1] - 480),
        x1=min(image.width, anchor.center_x + 220),
        y1=anchor.bbox[3] + 180,
    )
    _unused_crop_path, product_bbox = _offer_crop(
        image,
        anchor,
        page_no=page_no,
        identity="preview",
        crop_dir=None,
    )
    dense_lines = _dense_ocr_lines(image, product_bbox)
    dense_context = "\n".join(dense_lines)
    context = _normalize_context(dense_context or "\n".join(line["text"] for line in lines))
    low_context = context.lower()
    if any(marker in low_context for marker in _IGNORE_CONTEXT) and not _QUANTITY_RE.search(context):
        return None, {"status": "ignored", "reason": "editorial_price", "context": context[:600]}

    dense_name = _dense_product_name(dense_lines)
    alternate_lines: list[str] = []
    # A raw ``mi`` instead of ``ml`` is a useful signal to ask sparse-layout
    # OCR for a second reading before normalizing the common glyph confusion.
    dense_has_quantity = any(_QUANTITY_RE.search(line) for line in dense_lines)
    if _name_quality(dense_name) < 45 or not dense_has_quantity:
        alternate_lines = _dense_ocr_lines(image, product_bbox, psm=11)
        alternate_name = _dense_product_name(alternate_lines)
        if _name_quality(alternate_name) >= _name_quality(dense_name) - 5:
            dense_name = alternate_name
    sparse_name = _product_name(lines, anchor.bbox[1])
    name = max((dense_name, sparse_name), key=_name_quality)
    name = re.sub(r"\s+[A-Za-zÄÖÜäöüß]$", "", name).strip(" _-,:;.")
    if not name:
        return None, {"status": "unmatched", "reason": "product_name", "context": context[:600]}

    measurement_candidates: list[str] = []
    for candidate_lines in (alternate_lines, dense_lines):
        package_indices = [
            index for index, line in enumerate(candidate_lines)
            if _QUANTITY_RE.search(_normalize_context(line))
            or re.search(r"\bje\s+(?:Stück|Topf|Bund)\b", line, re.I)
        ]
        if package_indices:
            package_index = package_indices[-1]
            measurement_candidates.append(_normalize_context(
                "\n".join(candidate_lines[max(0, package_index - 2): package_index + 3])
            ))
    measurement_context = max(
        measurement_candidates or [context],
        key=lambda value: (
            int(_quantity(value)[0] is not None),
            int(_unit_price(value)[0] is not None),
            -len(value),
        ),
    )
    quantity, unit = _quantity(measurement_context)
    unit_price, unit_price_unit = _unit_price(measurement_context)
    price = anchor.price
    expected = _expected_price(quantity, unit, unit_price, unit_price_unit)
    if expected is not None and 0.05 <= expected <= 500:
        if abs(price - expected) / max(price, 0.05) > 0.03:
            price = round(expected + 1e-9, 2)
    if unit_price is None and quantity is not None and unit:
        unit_price, unit_price_unit = compute_unit_price(price, quantity, unit)

    crop_identity = sha256(f"{page_no}|{name}|{price}|{anchor.bbox}".encode("utf-8")).hexdigest()
    crop_path, crop_bbox = _offer_crop(
        image,
        anchor,
        page_no=page_no,
        identity=crop_identity,
        crop_dir=crop_dir,
    )
    source_text = (
        f"PDF Seite {page_no}: EDEKA OCR bbox={crop_bbox} price_bbox={anchor.bbox} "
        f"{context}"
    )[:4000]
    offer = CollectedOffer(
        source.key,
        source.store_name,
        source.retailer,
        name[:180],
        cat(name),
        price,
        regular_price=anchor.reference_price,
        unit_price=unit_price,
        unit_price_unit=unit_price_unit,
        quantity=quantity,
        unit=unit,
        valid_from=valid_from,
        valid_to=valid_to,
        source_text=source_text,
        source_url=source_url,
        image_alt=name,
        local_store_offer=True,
        confidence=0.97,
    )
    if crop_path is not None:
        offer.audit_image_path = str(crop_path)
        offer.image_media_source = "prospect_crop"
    assessment = evaluate_offer(offer)
    if not assessment.accepted:
        return None, {
            "status": "unmatched",
            "reason": f"offer_quality:{'|'.join(assessment.reasons)}",
            "context": context[:600],
        }
    return offer, {
        "status": "accepted",
        "product_name": offer.product_name,
        "price": offer.price,
        "quantity": offer.quantity,
        "unit": offer.unit,
        "unit_price": offer.unit_price,
        "unit_price_unit": offer.unit_price_unit,
        "crop_bbox": crop_bbox,
    }


def _validity(text: str) -> tuple[str | None, str | None]:
    compact = re.sub(r"\s+", " ", text or "")
    weekly = re.search(
        r"KW\s*\d+\s*[: -]?"
        r"(\d{1,2})[.](\d{1,2})[.]?(?:20\d{2})?\s*[-–]\s*"
        r"(\d{1,2})[.](\d{1,2})[.](20\d{2})",
        compact,
        re.I,
    )
    if weekly:
        start_day, start_month, end_day, end_month, year = weekly.groups()
        return f"{int(start_day):02d}.{int(start_month):02d}.{year}", f"{int(end_day):02d}.{int(end_month):02d}.{year}"
    start, end, _, _ = infer_validity(text)
    if start and end and (end - start).days > 10:
        return None, None
    return (
        start.strftime("%d.%m.%Y") if start else None,
        end.strftime("%d.%m.%Y") if end else None,
    )


def _dedupe_exact(rows: list[CollectedOffer]) -> list[CollectedOffer]:
    seen = set()
    result = []
    for row in rows:
        page = re.search(r"PDF Seite (\d+)", row.source_text or "")
        key = (
            row.product_name.lower(),
            round(float(row.price or 0), 2),
            row.quantity,
            row.unit,
            int(page.group(1)) if page else None,
        )
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def _offer_cache_payload(row: CollectedOffer) -> dict:
    return {
        "product_name": row.product_name,
        "category": row.category,
        "price": row.price,
        "regular_price": row.regular_price,
        "app_price": row.app_price,
        "unit_price": row.unit_price,
        "unit_price_unit": row.unit_price_unit,
        "quantity": row.quantity,
        "unit": row.unit,
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
        "source_text": row.source_text,
        "image_url": row.image_url,
        "image_alt": row.image_alt,
        "local_store_offer": row.local_store_offer,
        "confidence": row.confidence,
        "audit_image_path": getattr(row, "audit_image_path", None),
        "image_media_source": getattr(row, "image_media_source", None),
    }


def _offer_from_cache(source: RetailSource, payload: dict, *, source_url: str) -> CollectedOffer:
    row = CollectedOffer(
        source.key,
        source.store_name,
        source.retailer,
        str(payload["product_name"]),
        str(payload.get("category") or cat(str(payload["product_name"]))),
        payload.get("price"),
        regular_price=payload.get("regular_price"),
        app_price=payload.get("app_price"),
        unit_price=payload.get("unit_price"),
        unit_price_unit=payload.get("unit_price_unit"),
        quantity=payload.get("quantity"),
        unit=payload.get("unit"),
        valid_from=payload.get("valid_from"),
        valid_to=payload.get("valid_to"),
        source_text=str(payload.get("source_text") or ""),
        source_url=source_url,
        image_url=payload.get("image_url"),
        image_alt=payload.get("image_alt"),
        local_store_offer=bool(payload.get("local_store_offer", True)),
        confidence=float(payload.get("confidence", 0.97)),
    )
    if payload.get("audit_image_path"):
        row.audit_image_path = str(payload["audit_image_path"])
    if payload.get("image_media_source"):
        row.image_media_source = str(payload["image_media_source"])
    return row


def _cached_extraction(
    source: RetailSource,
    cache_path: Path,
    *,
    digest: str,
    source_url: str,
    diagnostics_path: Path,
) -> EdekaPdfExtraction | None:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if payload.get("cache_version") != _EXTRACTION_CACHE_VERSION or payload.get("pdf_sha256") != digest:
            return None
        rows = [_offer_from_cache(source, item, source_url=source_url) for item in payload["offers"]]
        if any(getattr(row, "audit_image_path", None) and not Path(row.audit_image_path).is_file() for row in rows):
            return None
        return EdekaPdfExtraction(
            offers=rows,
            page_count=int(payload["page_count"]),
            native_text_pages=list(payload["native_text_pages"]),
            ocr_pages=list(payload["ocr_pages"]),
            price_anchors_detected=int(payload["price_anchors_detected"]),
            price_anchors_matched=int(payload["price_anchors_matched"]),
            price_anchors_ignored=int(payload["price_anchors_ignored"]),
            price_anchors_unmatched=int(payload["price_anchors_unmatched"]),
            pages_with_unmatched_prices=list(payload["pages_with_unmatched_prices"]),
            page_offer_recall=float(payload["page_offer_recall"]),
            diagnostics_path=diagnostics_path,
            notes=list(payload.get("notes") or []) + ["EDEKA extraction reused by pdf_sha256"],
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def extract_edeka_pdf_offers(
    source: RetailSource,
    pdf_path: str | Path,
    *,
    source_url: str | None = None,
    diagnostics_root: Path | None = None,
    timeout_seconds_per_page: float = 45.0,
) -> EdekaPdfExtraction:
    path = Path(pdf_path)
    payload = path.read_bytes()
    digest = sha256(payload).hexdigest()
    document = pymupdf.open(stream=payload, filetype="pdf")
    root = diagnostics_root
    if root is None:
        try:
            from ..config import settings

            data_root = settings.data_dir.resolve(strict=False)
            resolved = path.resolve(strict=False)
            root = data_root / "diagnostics" / "edeka" if resolved.is_relative_to(data_root) else None
        except Exception:
            root = None
    run_root = root / digest if root is not None else None
    crop_dir = run_root / "crops" if run_root is not None else None
    diagnostics_path = run_root / "analysis.json" if run_root is not None else None
    cache_path = run_root / "extraction-v1.json" if run_root is not None else None
    if cache_path is not None and diagnostics_path is not None and cache_path.is_file() and diagnostics_path.is_file():
        cached = _cached_extraction(
            source,
            cache_path,
            digest=digest,
            source_url=source_url or source.url,
            diagnostics_path=diagnostics_path,
        )
        if cached is not None:
            return cached

    page_records = []
    native_pages = []
    ocr_pages = []
    offers = []
    detected = matched = ignored = unmatched = 0
    pages_unmatched = []
    all_text = "\n".join(page.get_text("text") or "" for page in document)
    valid_from, valid_to = _validity(all_text)
    started = time.monotonic()

    for page_no, page in enumerate(document, 1):
        native_text = page.get_text("text") or ""
        text_objects = sum(1 for block in page.get_text("dict").get("blocks", []) if block.get("type") == 0)
        images = len(page.get_images(full=True))
        textlayer_usable = len(native_text.strip()) >= 120
        record = {
            "page": page_no,
            "text_objects": text_objects,
            "text_chars": len(native_text),
            "images": images,
            "price_candidates": 0,
            "textlayer_usable": textlayer_usable,
            "ocr_required": not textlayer_usable,
            "ocr_words": 0,
            "product_candidates": 0,
            "accepted_offers": [],
            "rejected_candidates": [],
        }
        if textlayer_usable:
            native_pages.append(page_no)
            page_records.append(record)
            continue

        ocr_pages.append(page_no)
        image = _prepared_page(page)
        words = _ocr_words(image, timeout_seconds_per_page)
        record["image_width"] = image.width
        record["image_height"] = image.height
        record["ocr_words"] = len(words)
        if not valid_from or not valid_to:
            ocr_text = "\n".join(word.text for word in words)
            page_from, page_to = _validity(ocr_text)
            valid_from = valid_from or page_from
            valid_to = valid_to or page_to

        anchors = []
        for bbox in _red_components(image):
            anchor = _anchor_from_box(image, bbox)
            if anchor is not None:
                anchors.append(anchor)
        anchors.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
        record["price_candidates"] = len(anchors)
        record["product_candidates"] = len(anchors)
        detected += len(anchors)
        page_unmatched = 0
        for anchor in anchors:
            offer, decision = _page_offer(
                source,
                image,
                words,
                anchor,
                page_no=page_no,
                valid_from=valid_from,
                valid_to=valid_to,
                source_url=source_url or source.url,
                crop_dir=crop_dir,
            )
            decision["price"] = anchor.price
            decision["price_bbox"] = anchor.bbox
            decision["price_tokens"] = list(anchor.raw_tokens)
            if offer is not None:
                offers.append(offer)
                matched += 1
                record["accepted_offers"].append(decision)
            elif decision["status"] == "ignored":
                ignored += 1
                record["rejected_candidates"].append(decision)
            else:
                unmatched += 1
                page_unmatched += 1
                record["rejected_candidates"].append(decision)
        if page_unmatched:
            pages_unmatched.append(page_no)
        page_records.append(record)

    offers = _dedupe_exact(offers)
    eligible = detected - ignored
    page_recall = round(matched / eligible * 100.0, 1) if eligible else 0.0
    if run_root is not None:
        run_root.mkdir(parents=True, exist_ok=True)
        assert diagnostics_path is not None
        diagnostics_path.write_text(
            json.dumps(
                {
                    "pdf_sha256": digest,
                    "runtime_seconds": round(time.monotonic() - started, 1),
                    "page_count": len(document),
                    "native_text_pages": native_pages,
                    "ocr_pages": ocr_pages,
                    "price_anchors_detected": detected,
                    "price_anchors_matched": matched,
                    "price_anchors_ignored": ignored,
                    "price_anchors_unmatched": unmatched,
                    "page_offer_recall": page_recall,
                    "pages_with_unmatched_prices": pages_unmatched,
                    "pages": page_records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    notes = [
        (
            f"EDEKA PDF layout parser: pages={len(document)} native_text_pages={len(native_pages)} "
            f"ocr_pages={len(ocr_pages)} offers={len(offers)}"
        ),
        (
            f"price_anchors_detected={detected} price_anchors_matched={matched} "
            f"price_anchors_ignored={ignored} price_anchors_unmatched={unmatched} "
            f"page_offer_recall={page_recall:.1f}"
        ),
    ]
    if cache_path is not None:
        cache_path.write_text(
            json.dumps(
                {
                    "cache_version": _EXTRACTION_CACHE_VERSION,
                    "pdf_sha256": digest,
                    "page_count": len(document),
                    "native_text_pages": native_pages,
                    "ocr_pages": ocr_pages,
                    "price_anchors_detected": detected,
                    "price_anchors_matched": matched,
                    "price_anchors_ignored": ignored,
                    "price_anchors_unmatched": unmatched,
                    "pages_with_unmatched_prices": pages_unmatched,
                    "page_offer_recall": page_recall,
                    "offers": [_offer_cache_payload(row) for row in offers],
                    "notes": notes,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return EdekaPdfExtraction(
        offers=offers,
        page_count=len(document),
        native_text_pages=native_pages,
        ocr_pages=ocr_pages,
        price_anchors_detected=detected,
        price_anchors_matched=matched,
        price_anchors_ignored=ignored,
        price_anchors_unmatched=unmatched,
        pages_with_unmatched_prices=pages_unmatched,
        page_offer_recall=page_recall,
        diagnostics_path=diagnostics_path,
        notes=notes,
    )
