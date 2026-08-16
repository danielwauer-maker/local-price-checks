from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

# Datenschutzarmer V1-Ansatz: keine Browser-Geolocation. Bekannte PLZ/Ort-Zentren
# können lokal gepflegt werden; später kann ein serverseitiger Geocoder ergänzt werden.
KNOWN_CENTERS = {
    ("57614", "steimel"): (50.6199, 7.6264),
    ("56269", "dierdorf"): (50.5466, 7.6537),
    ("56305", "puderbach"): (50.5985, 7.6106),
    ("56587", "strassenhaus"): (50.5407, 7.5187),
    ("56587", "straßenhaus"): (50.5407, 7.5187),
    ("56587", "oberhonnefeld-gierend"): (50.5562, 7.5162),
}


def resolve_center(postal_code: str, city: str):
    return KNOWN_CENTERS.get(((postal_code or "").strip(), (city or "").strip().lower()))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))
