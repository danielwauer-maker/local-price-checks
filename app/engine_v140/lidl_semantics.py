from __future__ import annotations

from enum import Enum
import json
import re
from typing import Any
from urllib.parse import urlparse


class LidlSourceKind(str, Enum):
    LOCAL_PROSPECT = "local_prospect"
    SHOP_ONLINE = "shop_online"
    NAVIGATION_RECIPE = "navigation_recipe"
    LIDL_PLUS = "lidl_plus"
    EDITORIAL = "editorial"


_EXPLICIT_LOCAL_KEYS = (
    "storeOnly", "store_only", "inStore", "in_store", "filialOffer",
    "filial_offer", "localOffer", "local_offer",
)
_SHOP_PATH = re.compile(r"(?:^|/)p(?:/|-)[^/?#]+(?:/p)?\d{6,}(?:$|[/?#])", re.I)
_SHOP_QUERY = re.compile(r"(?:^|[?&])flyx_content=p-\d{6,}(?:$|&)", re.I)


def has_explicit_local_evidence(*objects: Any) -> bool:
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if any(obj.get(key) is True for key in _EXPLICIT_LOCAL_KEYS):
            return True
        for key in ("channel", "salesChannel", "availability", "offerType"):
            value = str(obj.get(key) or "").strip().lower()
            if value in {"store", "in-store", "instore", "filiale", "stationary"}:
                return True
    return False


def has_strong_shop_signal(*objects: Any) -> bool:
    """Return true only for Lidl shop identity, not for an ordinary page link."""
    for obj in objects:
        if isinstance(obj, str):
            values = (obj,)
            product_id = bool(re.search(r'"?product_?id"?\s*[:=]\s*"?\d{6,}', obj, re.I))
        elif isinstance(obj, dict):
            values = tuple(
                str(obj.get(key) or "")
                for key in ("url", "href", "canonicalUrl", "canonicalURL", "productUrl", "deeplink")
            )
            product_id = any(obj.get(key) not in (None, "") for key in ("productId", "product_id"))
        else:
            continue
        if product_id:
            return True
        for value in values:
            low = value.lower()
            host = urlparse(value).netloc.lower()
            if _SHOP_QUERY.search(value):
                return True
            if (host.endswith("lidl.de") or not host) and _SHOP_PATH.search(low):
                return True
    return False


def classify_lidl_link(link: dict, product: dict | None = None) -> LidlSourceKind:
    url = str(link.get("url") or "").strip()
    low = " ".join(
        (
            url,
            str(link.get("title") or ""),
            str(link.get("label") or ""),
            json.dumps(product or {}, ensure_ascii=False, default=str),
        )
    ).lower()
    if has_explicit_local_evidence(link, product) and not any(
        marker in low for marker in ("nur online", "online only", "onlineshop")
    ):
        return LidlSourceKind.LOCAL_PROSPECT
    if has_strong_shop_signal(link, link.get("productDetails") or {}, product or {}):
        return LidlSourceKind.SHOP_ONLINE
    if "lidlplus" in low or "lidl plus" in low:
        return LidlSourceKind.LIDL_PLUS
    host = urlparse(url).netloc.lower()
    if "rezepte.lidl" in host or "/alle-rezepte" in low:
        return LidlSourceKind.NAVIGATION_RECIPE
    return LidlSourceKind.EDITORIAL
