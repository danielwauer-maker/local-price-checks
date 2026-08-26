from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from .coverage_models import CoveragePostalCode


NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
OSM_LICENSE_URL = "https://www.openstreetmap.org/copyright"
BUNDLED_GEOMETRY_PATH = Path(__file__).resolve().parent / "static" / "postcode_geometries_b2.geojson"
_POSTCODE_RE = re.compile(r"^\d{5}$")


@dataclass(frozen=True)
class PostcodeGeometry:
    postal_code: str
    city: str | None
    center_lat: float
    center_lng: float
    source: str
    geometry: dict[str, Any]


def _coordinate_pairs(value: Any):
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    if isinstance(value, list):
        for child in value:
            yield from _coordinate_pairs(child)


def validate_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("PLZ-Geometrie muss Polygon oder MultiPolygon sein")
    pairs = list(_coordinate_pairs(geometry.get("coordinates")))
    if len(pairs) < 4:
        raise ValueError("PLZ-Geometrie enthält zu wenige Koordinaten")
    if any(not (-180 <= lng <= 180 and -90 <= lat <= 90) for lng, lat in pairs):
        raise ValueError("PLZ-Geometrie enthält ungültige Koordinaten")
    return geometry


def _geometry_center(geometry: dict[str, Any]) -> tuple[float, float]:
    pairs = list(_coordinate_pairs(geometry.get("coordinates")))
    lngs = [pair[0] for pair in pairs]
    lats = [pair[1] for pair in pairs]
    return (min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2


def load_bundled_postcode_geometries() -> dict[str, PostcodeGeometry]:
    payload = json.loads(BUNDLED_GEOMETRY_PATH.read_text(encoding="utf-8"))
    rows: dict[str, PostcodeGeometry] = {}
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        postal_code = str(properties.get("postal_code") or "")
        geometry = validate_geometry(feature.get("geometry") or {})
        rows[postal_code] = PostcodeGeometry(
            postal_code=postal_code,
            city=properties.get("city") or None,
            center_lat=float(properties["center_lat"]),
            center_lng=float(properties["center_lng"]),
            source=str(properties["geometry_source"]),
            geometry=geometry,
        )
    return rows


def apply_postcode_geometry(row: CoveragePostalCode, geometry: PostcodeGeometry) -> None:
    if row.postal_code != geometry.postal_code:
        raise ValueError("PLZ-Geometrie gehört zu einer anderen PLZ")
    row.city = row.city or geometry.city
    row.center_lat = geometry.center_lat
    row.center_lng = geometry.center_lng
    row.geometry_source = geometry.source
    row.geometry_geojson = json.dumps(
        validate_geometry(geometry.geometry), ensure_ascii=False, separators=(",", ":")
    )


def seed_bundled_postcode_geometries(db: Session) -> None:
    """Fill missing B2 geometries without replacing a newer cached import."""
    changed = False
    for postal_code, geometry in load_bundled_postcode_geometries().items():
        row = db.query(CoveragePostalCode).filter_by(postal_code=postal_code).first()
        if row is None:
            continue
        if not row.geometry_geojson:
            apply_postcode_geometry(row, geometry)
            changed = True
    if changed:
        db.commit()


def fetch_postcode_geometry(postal_code: str) -> PostcodeGeometry:
    """Fetch one exact German postcode boundary for explicit admin caching.

    This intentionally performs one request only. It is not a bulk downloader,
    autocomplete service, or request-time dependency for rendering the map.
    """
    postal_code = (postal_code or "").strip()
    if not _POSTCODE_RE.fullmatch(postal_code):
        raise ValueError("PLZ muss aus genau fünf Ziffern bestehen")
    response = httpx.get(
        NOMINATIM_SEARCH_URL,
        params={
            "postalcode": postal_code,
            "country": "Germany",
            "countrycodes": "de",
            "format": "geojson",
            "polygon_geojson": 1,
            "addressdetails": 1,
            "limit": 5,
        },
        headers={"User-Agent": "Lokero/0.5 postcode-geometry-import"},
        timeout=30,
    )
    response.raise_for_status()
    for feature in response.json().get("features", []):
        properties = feature.get("properties") or {}
        address = properties.get("address") or {}
        if str(address.get("postcode") or "")[:5] != postal_code:
            continue
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        validate_geometry(geometry)
        center_lat, center_lng = _geometry_center(geometry)
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
        )
        osm_type = str(properties.get("osm_type") or "object")
        osm_id = str(properties.get("osm_id") or "unknown")
        return PostcodeGeometry(
            postal_code=postal_code,
            city=city,
            center_lat=center_lat,
            center_lng=center_lng,
            source=f"osm:nominatim:{osm_type}/{osm_id}@{date.today().isoformat()}",
            geometry=geometry,
        )
    raise ValueError(f"Keine exakte OSM-Polygongeometrie für PLZ {postal_code} gefunden")


def import_postcode_geometry(
    db: Session,
    postal_code: str,
    *,
    provider: Callable[[str], PostcodeGeometry] = fetch_postcode_geometry,
    enabled: bool | None = None,
) -> CoveragePostalCode:
    """Cache a validated geometry; provider failure leaves stored data intact."""
    postal_code = (postal_code or "").strip()
    if not _POSTCODE_RE.fullmatch(postal_code):
        raise ValueError("PLZ muss aus genau fünf Ziffern bestehen")
    geometry = provider(postal_code)
    row = db.query(CoveragePostalCode).filter_by(postal_code=postal_code).first()
    if row is None:
        row = CoveragePostalCode(postal_code=postal_code, enabled=bool(enabled))
        db.add(row)
    elif enabled is not None:
        row.enabled = bool(enabled)
    apply_postcode_geometry(row, geometry)
    db.commit()
    db.refresh(row)
    return row


def postcode_feature(row: CoveragePostalCode, properties: dict[str, Any]) -> dict[str, Any] | None:
    if not row.geometry_geojson:
        return None
    try:
        geometry = validate_geometry(json.loads(row.geometry_geojson))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "postal_code": row.postal_code,
            "city": row.city,
            "enabled": row.enabled,
            "geometry_source": row.geometry_source,
            **properties,
        },
    }
