from __future__ import annotations

from functools import lru_cache
from math import asin, cos, radians, sin, sqrt

import httpx

# Fast/local V1 cache for the initial test region. No browser geolocation is used.
KNOWN_CENTERS = {
    ("57614", "steimel"): (50.6199, 7.6264),
    ("56269", "dierdorf"): (50.5466, 7.6537),
    ("56305", "puderbach"): (50.5985, 7.6106),
    ("56587", "strassenhaus"): (50.5407, 7.5187),
    ("56587", "straßenhaus"): (50.5407, 7.5187),
    ("56587", "oberhonnefeld-gierend"): (50.5562, 7.5162),
}


@lru_cache(maxsize=512)
def _geocode_postal_city(postal_code: str, city: str):
    """Resolve only the explicitly entered postal code/town on the server.

    This is a fallback for locations outside the bundled MVP test region. It
    does not request device location and does not send a street/house number.
    """
    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "postalcode": postal_code,
                "city": city,
                "country": "Germany",
                "countrycodes": "de",
                "format": "jsonv2",
                "limit": 1,
            },
            headers={"User-Agent": "LocalPriceChecks/0.2 (postal-city geocoder)"},
            timeout=8,
        )
        response.raise_for_status()
        rows = response.json()
        if rows:
            return float(rows[0]["lat"]), float(rows[0]["lon"])
    except Exception:
        return None
    return None


def resolve_center(postal_code: str, city: str):
    postal = (postal_code or "").strip()
    town = (city or "").strip()
    known = KNOWN_CENTERS.get((postal, town.lower()))
    if known:
        return known
    if not postal or not town:
        return None
    return _geocode_postal_city(postal, town)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))
