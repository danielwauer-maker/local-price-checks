from __future__ import annotations

from datetime import date, datetime
import html as html_lib
import json
import re
from typing import Any

from bs4 import BeautifulSoup

from ..clock import app_today
from .week_utils import classify_week, parse_any_date


_PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)")
_NEXT_WEEK_DATED_RE = re.compile(
    r"nächste\s+woche.{0,180}?(\d{1,2}\.\d{1,2}\.?)\s*(?:bis|[–-])\s*(\d{1,2}\.\d{1,2}\.?)",
    re.I | re.S,
)


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _script_payloads(document: str) -> list[Any]:
    soup = BeautifulSoup(document or "", "html.parser")
    payloads: list[Any] = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text("", strip=False)
        if not raw or len(raw) > 4_000_000:
            continue
        text = raw.strip()
        if not text or text[0] not in "[{":
            continue
        try:
            payloads.append(json.loads(text))
        except Exception:
            continue
    return payloads


def _week_containers(document: str) -> list[dict]:
    containers: list[dict] = []
    seen: set[int] = set()
    for payload in _script_payloads(document):
        for node in _walk_dicts(payload):
            candidates = [node]
            nested = node.get("offers")
            if isinstance(nested, dict):
                candidates.append(nested)
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                current = candidate.get("current")
                nxt = candidate.get("next")
                if not isinstance(current, dict) or not isinstance(nxt, dict):
                    continue
                if not any(key in current for key in ("categories", "fromDate", "untilDate", "available")):
                    continue
                marker = id(candidate)
                if marker in seen:
                    continue
                seen.add(marker)
                containers.append(candidate)
    return containers


def _date_value(value: Any, ref: date) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    return parse_any_date(text, ref)


def _price_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number / 100.0, 2) if number > 500 else number
    match = _PRICE_RE.search(str(value).replace("€", " "))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _first_image_url(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("https://", "http://")) and any(
            token in text.lower() for token in ("image", "img", "rewe-static", ".jpg", ".jpeg", ".png", ".webp")
        ):
            return text
        return None
    if isinstance(value, dict):
        for key in ("url", "src", "href", "imageUrl", "imageURL"):
            found = _first_image_url(value.get(key))
            if found:
                return found
        for child in value.values():
            found = _first_image_url(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_image_url(child)
            if found:
                return found
    return None


def _categories(week: dict) -> list[dict]:
    value = week.get("categories")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _offer_rows(category: dict) -> list[dict]:
    value = category.get("offers")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _parse_week(week: dict, *, period: str, ref: date) -> tuple[list[dict], str | None]:
    if period not in {"current", "next"}:
        return [], "invalid_period"
    available = week.get("available")
    if period == "next" and available is not True:
        return [], None
    if period == "current" and available is False:
        return [], "current_not_available"

    valid_from = _date_value(week.get("fromDate"), ref)
    valid_to = _date_value(week.get("untilDate"), ref)
    if not valid_from or not valid_to or valid_to < valid_from:
        return [], f"{period}_invalid_dates"
    if classify_week(valid_from, ref) != period:
        return [], f"{period}_out_of_horizon"

    rows: list[dict] = []
    for category in _categories(week):
        category_name = str(category.get("title") or "").strip()
        for raw in _offer_rows(category):
            cell_type = str(raw.get("cellType") or "DEFAULT").strip().upper()
            if cell_type != "DEFAULT":
                continue
            title = str(raw.get("title") or raw.get("name") or "").strip()
            if len(title) < 3:
                continue
            price_data = raw.get("priceData") if isinstance(raw.get("priceData"), dict) else {}
            price = _price_value(price_data.get("price") if price_data else raw.get("price"))
            if price is None or price <= 0:
                continue
            subtitle = str(raw.get("subtitle") or "").strip()
            overline = str(raw.get("overline") or "").strip()
            image_url = _first_image_url(raw.get("images")) or _first_image_url(raw.get("image"))
            source_text = " · ".join(
                part
                for part in (
                    "Angebote im Markt",
                    overline,
                    title,
                    subtitle,
                    f"Aktionspreis {price:.2f} €".replace(".", ","),
                    f"Gültig {valid_from:%d.%m.%Y} bis {valid_to:%d.%m.%Y}",
                )
                if part
            )
            rows.append(
                {
                    "period": period,
                    "product_name": title,
                    "category": category_name,
                    "price": price,
                    # Deliberately do not map priceData.regularPrice here. In
                    # REWE payloads this field can contain labels such as
                    # "Knaller" and is not a confirmed observed shelf price.
                    "regular_price": None,
                    "valid_from": valid_from.strftime("%d.%m.%Y"),
                    "valid_to": valid_to.strftime("%d.%m.%Y"),
                    "source_text": source_text,
                    "image_url": image_url,
                    "image_alt": title if image_url else None,
                }
            )

    deduped: list[dict] = []
    seen: set[tuple] = set()
    for row in rows:
        key = (
            row["period"],
            row["product_name"].casefold(),
            row["price"],
            row["valid_from"],
            row["source_text"],
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped, None


def parse_rewe_structured_weeks(document: str, *, ref: date | None = None) -> tuple[list[dict], dict]:
    """Parse only explicit current/next REWE week containers captured from the official page.

    This intentionally does not call the certificate-bound mobile endpoint.
    It consumes structured JSON only when that JSON is already part of the
    official REWE page/browser capture used by Spareno.
    """
    ref = ref or app_today()
    containers = _week_containers(document)
    if not containers:
        return [], {
            "structured_found": False,
            "next_available": False,
            "errors": [],
            "current_count": 0,
            "next_count": 0,
        }

    all_rows: list[dict] = []
    errors: list[str] = []
    next_available = False
    for container in containers:
        current = container.get("current") or {}
        nxt = container.get("next") or {}
        next_available = next_available or nxt.get("available") is True
        current_rows, current_error = _parse_week(current, period="current", ref=ref)
        next_rows, next_error = _parse_week(nxt, period="next", ref=ref)
        all_rows.extend(current_rows)
        all_rows.extend(next_rows)
        if current_error:
            errors.append(current_error)
        if next_error:
            errors.append(next_error)

    deduped: list[dict] = []
    seen: set[tuple] = set()
    for row in all_rows:
        key = (row["period"], row["product_name"].casefold(), row["price"], row["valid_from"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    return deduped, {
        "structured_found": True,
        "next_available": next_available,
        "errors": sorted(set(errors)),
        "current_count": sum(1 for row in deduped if row["period"] == "current"),
        "next_count": sum(1 for row in deduped if row["period"] == "next"),
    }


def visible_next_week_is_published(text: str, *, ref: date | None = None) -> bool:
    """Return true only for an explicitly dated next-week range, never for 'Ab Samstag'."""
    ref = ref or app_today()
    match = _NEXT_WEEK_DATED_RE.search(text or "")
    if not match:
        return False
    start = parse_any_date(match.group(1), ref)
    return bool(start and classify_week(start, ref) == "next")


def append_rewe_audit_appendix(document: str, rows: list[dict]) -> str:
    """Make captured structured rows visible in the immutable REWE audit PDF.

    The appendix is derived only from data already captured during the same
    official REWE page request. It does not invent or enrich offer facts.
    """
    if not rows:
        return document
    lines = [
        '<section id="spareno-rewe-structured-audit" style="font-family:Arial,sans-serif;padding:16px">',
        "<h2>Spareno Prüfanhang – strukturierte REWE-Angebotsdaten</h2>",
        "<p>Quelle: strukturierte Daten aus demselben offiziellen REWE-Seitenabruf.</p>",
    ]
    for row in rows:
        title = html_lib.escape(str(row.get("product_name") or ""))
        period = "Aktuelle Woche" if row.get("period") == "current" else "Nächste Woche"
        price = f"{float(row.get('price') or 0):.2f}".replace(".", ",")
        valid_from = html_lib.escape(str(row.get("valid_from") or ""))
        valid_to = html_lib.escape(str(row.get("valid_to") or ""))
        lines.append(
            "<p><strong>"
            + title
            + "</strong> · "
            + html_lib.escape(period)
            + " · "
            + price
            + " € · "
            + valid_from
            + "–"
            + valid_to
            + "</p>"
        )
    lines.append("</section>")
    appendix = "".join(lines)
    if re.search(r"</body\s*>", document, flags=re.I):
        return re.sub(r"</body\s*>", appendix + "</body>", document, count=1, flags=re.I)
    return document + appendix
