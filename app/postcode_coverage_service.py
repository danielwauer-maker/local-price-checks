from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import re
import unicodedata
from typing import Any

import httpx
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .candidate_source_refresh import refresh_candidate_from_source
from .coverage_models import CoveragePostalCode, StoreDiscoveryCandidate
from .config import settings
from .coverage_service import normalize_retailer
from .geo import haversine_km
from .models import Store
from .physical_market_identity import official_retailer_id
from .postcode_geometry import seed_bundled_postcode_geometries


INITIAL_B2_POSTCODES: tuple[str, ...] = (
    "65618",
    "65611",
    "65606",
    "57614",
    "56305",
    "56269",
    "56316",
    "57610",
)
INITIAL_B2_POSTCODE_CITIES = {
    "65618": "Selters (Taunus)",
    "65611": "Brechen",
    "65606": "Villmar",
    "57614": "Steimel / Oberdreis",
    "56305": "Puderbach",
    "56269": "Dierdorf",
    "56316": "Raubach",
    "57610": "Altenkirchen (Westerwald)",
}

_POSTCODE_RE = re.compile(r"^\d{5}$")


def seed_initial_postcode_coverage(db: Session) -> None:
    """Seed the explicitly approved B2 launch postcodes once, idempotently."""
    changed = False
    for postal_code in INITIAL_B2_POSTCODES:
        row = db.query(CoveragePostalCode).filter_by(postal_code=postal_code).first()
        if row is None:
            db.add(CoveragePostalCode(
                postal_code=postal_code,
                city=INITIAL_B2_POSTCODE_CITIES[postal_code],
                enabled=True,
            ))
            changed = True
        elif not row.city:
            row.city = INITIAL_B2_POSTCODE_CITIES[postal_code]
            changed = True
    if changed:
        db.commit()
    seed_bundled_postcode_geometries(db)


def set_postcode_enabled(db: Session, postal_code: str, enabled: bool) -> CoveragePostalCode:
    postal_code = (postal_code or "").strip()
    if not _POSTCODE_RE.fullmatch(postal_code):
        raise ValueError("PLZ muss aus genau fünf Ziffern bestehen")
    row = db.query(CoveragePostalCode).filter_by(postal_code=postal_code).first()
    if row is None:
        row = CoveragePostalCode(postal_code=postal_code)
        db.add(row)
    row.enabled = bool(enabled)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def _candidate_key(source: str, element_type: str, element_id: str | int, retailer: str) -> str:
    raw = f"{source}|{element_type}|{element_id}|{retailer}".encode("utf-8")
    return sha256(raw).hexdigest()


def discover_postcode_supermarkets(postal_code: str) -> list[dict[str, Any]]:
    """Discover supermarket candidates explicitly tagged with one exact PLZ.

    We intentionally do not widen this query by radius. A market from a
    neighbouring postcode must not silently enter the selected rollout area.
    """
    postal_code = (postal_code or "").strip()
    if not _POSTCODE_RE.fullmatch(postal_code):
        raise ValueError("PLZ muss aus genau fünf Ziffern bestehen")

    query = f'''[out:json][timeout:30];
area["ISO3166-1"="DE"][admin_level=2]->.de;
(
  node["shop"="supermarket"]["addr:postcode"="{postal_code}"](area.de);
  way["shop"="supermarket"]["addr:postcode"="{postal_code}"](area.de);
  relation["shop"="supermarket"]["addr:postcode"="{postal_code}"](area.de);
);out center tags;'''
    response = httpx.post(
        "https://overpass-api.de/api/interpreter",
        content=query.encode("utf-8"),
        headers={"User-Agent": "Lokero/0.4 postcode-market-discovery"},
        timeout=40,
    )
    response.raise_for_status()

    rows: list[dict[str, Any]] = []
    for element in response.json().get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or tags.get("brand") or "").strip()
        brand = (tags.get("brand") or "").strip()
        retailer = normalize_retailer(name, brand)
        if not retailer:
            continue
        lat = element.get("lat") or (element.get("center") or {}).get("lat")
        lng = element.get("lon") or (element.get("center") or {}).get("lon")
        if lat is None or lng is None:
            continue
        street = (tags.get("addr:street") or "").strip()
        house = (tags.get("addr:housenumber") or "").strip()
        address = " ".join(x for x in (street, house) if x).strip()
        city = (tags.get("addr:city") or tags.get("addr:place") or "").strip()
        element_type = str(element.get("type") or "osm")
        element_id = element.get("id")
        rows.append({
            "discovery_key": _candidate_key("osm", element_type, element_id, retailer),
            "postal_code": postal_code,
            "retailer": retailer,
            "name": name or retailer,
            "address": address,
            "city": city,
            "latitude": float(lat),
            "longitude": float(lng),
            "source": "osm",
            "source_external_id": f"{element_type}/{element_id}",
            "source_url": tags.get("website") or tags.get("contact:website") or None,
        })
    return rows


def stage_postcode_candidates(db: Session, postal_code: str) -> tuple[int, int]:
    """Upsert discovered candidates without creating or activating Store rows."""
    created = updated = 0
    for item in discover_postcode_supermarkets(postal_code):
        if item.get("postal_code") != postal_code:
            # Provider bugs or mocked/secondary data must never leak a market
            # from a neighbouring postcode into the selected rollout area.
            continue
        row = db.query(StoreDiscoveryCandidate).filter_by(discovery_key=item["discovery_key"]).first()
        if row is None:
            row = StoreDiscoveryCandidate(**item)
            db.add(row)
            created += 1
        else:
            values = {
                field: item[field]
                for field in (
                    "postal_code", "retailer", "name", "address", "city", "latitude",
                    "longitude", "source_external_id", "source_url",
                )
            }
            refresh_candidate_from_source(
                row,
                values,
                reset_verification_on_identity_change=False,
            )
            updated += 1
    db.commit()
    return created, updated


def normalize_identity_text(value: str | None) -> str:
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", (value or "").casefold().replace("ß", "ss"))
        if not unicodedata.combining(character)
    )
    folded = re.sub(r"str(?:asse|\.)?(?=\s|\d|$)", "strasse", folded)
    return re.sub(r"[^a-z0-9]+", "", folded)


def addresses_match(left: str | None, right: str | None) -> bool:
    return bool(left and right and normalize_identity_text(left) == normalize_identity_text(right))


def _cities_match(candidate_city: str, address: dict[str, Any]) -> bool:
    expected = normalize_identity_text(candidate_city)
    returned = {
        normalize_identity_text(address.get(key))
        for key in ("city", "town", "village", "municipality", "suburb")
        if address.get(key)
    }
    return bool(expected and expected in returned)


def verify_candidate_address_coordinates(
    candidate: StoreDiscoveryCandidate,
    official_reference: StoreDiscoveryCandidate | None = None,
) -> tuple[bool, bool, str]:
    """Cross-check the concrete market address against Nominatim.

    This validates address/coordinate consistency, but does not replace the
    separate official-retailer-source gate.
    """
    if not candidate.address or not candidate.city or not _POSTCODE_RE.fullmatch(candidate.postal_code or ""):
        return False, False, "vollständige Straße/Hausnummer, Ort oder PLZ fehlt"
    threshold_m = max(1.0, float(settings.store_coordinate_tolerance_m))
    if official_reference is not None:
        postcode_ok = official_reference.postal_code == candidate.postal_code
        retailer_ok = official_reference.retailer == candidate.retailer
        city_ok = normalize_identity_text(official_reference.city) == normalize_identity_text(candidate.city)
        address_ok = addresses_match(official_reference.address, candidate.address)
        distance_m = haversine_km(
            candidate.latitude,
            candidate.longitude,
            official_reference.latitude,
            official_reference.longitude,
        ) * 1000
        identity_ok = postcode_ok and retailer_ok and city_ok and address_ok
        coordinates_ok = identity_ok and distance_m <= threshold_m
        checks = (
            f"PLZ={'ok' if postcode_ok else 'abweichend'}, "
            f"Ort={'ok' if city_ok else 'abweichend'}, "
            f"Händler={'ok' if retailer_ok else 'abweichend'}, "
            f"Adresse={'ok' if address_ok else 'abweichend'}"
        )
        note = f"Offizielle Händlerquelle: {checks}; Pin-Abweichung {distance_m:.0f} m"
        if distance_m > threshold_m:
            note += f" (über {threshold_m:.0f} m, manuelle Prüfung erforderlich)"
        return identity_ok, coordinates_ok, note

    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "street": candidate.address,
                "postalcode": candidate.postal_code,
                "city": candidate.city,
                "country": "Germany",
                "countrycodes": "de",
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 3,
            },
            headers={"User-Agent": "Lokero/0.4 market-address-verifier"},
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        return False, False, f"Geocoding fehlgeschlagen: {type(exc).__name__}"

    best: tuple[float, dict[str, Any]] | None = None
    for row in response.json():
        address = row.get("address") or {}
        returned_postcode = str(address.get("postcode") or "")[:5]
        returned_street = " ".join(
            value for value in (address.get("road"), address.get("house_number")) if value
        )
        if (
            returned_postcode != candidate.postal_code
            or not _cities_match(candidate.city, address)
            or not addresses_match(candidate.address, returned_street)
        ):
            continue
        distance = haversine_km(
            candidate.latitude,
            candidate.longitude,
            float(row["lat"]),
            float(row["lon"]),
        )
        if best is None or distance < best[0]:
            best = (distance, row)
    if best is None:
        return False, False, "Vollständige Adresse, Ort und PLZ konnten nicht gemeinsam bestätigt werden"

    distance_km = best[0]
    address_ok = True
    coordinates_ok = distance_km * 1000 <= threshold_m
    note = f"Adress-Geocode bestätigt; Pin-Abweichung {distance_km * 1000:.0f} m"
    if not coordinates_ok:
        note += f" (über {threshold_m:.0f} m, manuelle Prüfung erforderlich)"
    return address_ok, coordinates_ok, note


def verify_staged_candidate(db: Session, candidate_id: int) -> StoreDiscoveryCandidate:
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    if candidate is None:
        raise ValueError("Marktkandidat nicht gefunden")
    official_reference = None
    if not candidate.source.startswith("official:"):
        references = db.query(StoreDiscoveryCandidate).filter(
            StoreDiscoveryCandidate.postal_code == candidate.postal_code,
            StoreDiscoveryCandidate.retailer == candidate.retailer,
            StoreDiscoveryCandidate.official_source_verified.is_(True),
            StoreDiscoveryCandidate.source.like("official:%"),
            StoreDiscoveryCandidate.id != candidate.id,
        ).all()
        if references:
            official_reference = min(
                references,
                key=lambda row: haversine_km(
                    candidate.latitude, candidate.longitude, row.latitude, row.longitude
                ),
            )
    address_ok, coordinates_ok, note = verify_candidate_address_coordinates(candidate, official_reference)
    candidate.address_verified = address_ok
    candidate.coordinates_verified = coordinates_ok
    if official_reference is not None:
        candidate.official_source_verified = address_ok
    candidate.verification_note = note
    candidate.status = "verified" if address_ok and coordinates_ok and candidate.official_source_verified else "discovered"
    candidate.verified_at = datetime.utcnow() if address_ok and coordinates_ok else None
    candidate.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(candidate)
    return candidate


def candidate_ready_for_promotion(candidate: StoreDiscoveryCandidate) -> bool:
    return bool(
        candidate.address
        and candidate.city
        and _POSTCODE_RE.fullmatch(candidate.postal_code or "")
        and candidate.address_verified
        and candidate.coordinates_verified
        and candidate.official_source_verified
        and candidate.status != "rejected"
    )


def _direct_store_reference_count(db: Session, store_id: int) -> int:
    """Count direct FK references to one Store without changing any data.

    This is used only when promotion finds multiple identity-equivalent legacy
    Store rows. A unique history-bearing row is safer to reuse than a zero-history
    duplicate, while genuinely ambiguous histories still fail closed.
    """
    schema = inspect(db.connection())
    total = 0
    for table_name in schema.get_table_names():
        for fk in schema.get_foreign_keys(table_name):
            if fk.get("referred_table") != "stores":
                continue
            columns = fk.get("constrained_columns") or []
            referred_columns = fk.get("referred_columns") or []
            if len(columns) != 1 or referred_columns != ["id"]:
                continue
            column_name = columns[0]
            total += int(
                db.execute(
                    text(
                        f'SELECT COUNT(*) FROM "{table_name}" '
                        f'WHERE "{column_name}" = :store_id'
                    ),
                    {"store_id": store_id},
                ).scalar_one()
            )
    return total


def _canonical_historical_store(db: Session, stores: list[Store]) -> Store | None:
    """Return a unique history-bearing Store when all sibling duplicates are empty."""
    if len(stores) == 1:
        return stores[0]
    reference_counts = {
        store.id: _direct_store_reference_count(db, store.id)
        for store in stores
    }
    history_bearing = [store for store in stores if reference_counts[store.id] > 0]
    if len(history_bearing) != 1:
        return None
    canonical = history_bearing[0]
    if any(
        reference_counts[store.id] > 0
        for store in stores
        if store.id != canonical.id
    ):
        return None
    return canonical


def promote_candidate_to_store(db: Session, candidate_id: int) -> Store:
    """Create/update a Store only after all identity gates have passed.

    Promotion is a physical-market operation, not a single-source-row operation.
    If an existing Store already matches another source row in the same physical
    candidate group, reuse that Store instead of creating a duplicate.
    """
    candidate = db.get(StoreDiscoveryCandidate, candidate_id)
    if candidate is None:
        raise ValueError("Marktkandidat nicht gefunden")
    if not candidate_ready_for_promotion(candidate):
        raise ValueError("Markt ist noch nicht vollständig verifiziert")

    from .market_identity_conflicts import weak_candidate_promotion_conflict

    conflict = weak_candidate_promotion_conflict(db, candidate)
    if conflict.blocked:
        raise ValueError(conflict.reason or "Möglicher physischer Doppelmarkt")

    # Local import avoids a module cycle: postcode_reconciliation imports the
    # normalization helpers from this module.
    from .postcode_reconciliation import group_physical_candidates, store_matches_candidate

    postcode_candidates = db.query(StoreDiscoveryCandidate).filter_by(
        postal_code=candidate.postal_code
    ).all()
    physical_members = [candidate]
    for group in group_physical_candidates(postcode_candidates):
        if any(member.id == candidate.id for member in group.members):
            physical_members = group.members
            break

    store = db.get(Store, candidate.matched_store_id) if candidate.matched_store_id else None
    if store is None:
        explicit_ids = {
            member.matched_store_id
            for member in physical_members
            if member.matched_store_id is not None
        }
        explicit_stores = [
            row for row in db.query(Store).filter(Store.id.in_(explicit_ids)).all()
        ] if explicit_ids else []
        if len(explicit_stores) > 1:
            raise ValueError("Mehrdeutige Store-Zuordnung im selben physischen Markt")
        if explicit_stores:
            store = explicit_stores[0]

    if store is None:
        postcode_stores = db.query(Store).filter(
            Store.retailer == candidate.retailer,
            Store.postal_code == candidate.postal_code,
        ).all()
        physical_matches = [
            row
            for row in postcode_stores
            if any(store_matches_candidate(row, member) for member in physical_members)
        ]
        if len(physical_matches) > 1:
            store = _canonical_historical_store(db, physical_matches)
            if store is None:
                raise ValueError(
                    "Mehrere bestehende Stores passen zu diesem physischen Markt; "
                    "Historienlage ist nicht eindeutig und muss manuell geprüft werden"
                )
        elif physical_matches:
            store = physical_matches[0]

    # Keep the historical single-row matching as a conservative fallback for
    # data sets where no secondary discovery member exists.
    if store is None and candidate.source_external_id:
        store = db.query(Store).filter(
            Store.retailer == candidate.retailer,
            Store.external_id == candidate.source_external_id,
        ).first()
    if store is None:
        candidate_identity = Store(
            id=0,
            retailer=candidate.retailer,
            name=candidate.name or candidate.retailer,
            postal_code=candidate.postal_code,
            city=candidate.city,
            address=candidate.address,
            latitude=candidate.latitude,
            longitude=candidate.longitude,
            active=False,
            benchmark_verified=False,
            external_id=candidate.source_external_id,
            source_url=candidate.source_url,
        )
        store = next(
            (
                row
                for row in db.query(Store).filter(
                    Store.retailer == candidate.retailer,
                    Store.postal_code == candidate.postal_code,
                ).all()
                if addresses_match(row.address, candidate.address)
                and not (
                    official_retailer_id(row)
                    and official_retailer_id(candidate_identity)
                    and official_retailer_id(row)
                    != official_retailer_id(candidate_identity)
                )
            ),
            None,
        )
    if store is None:
        base_name = candidate.name or candidate.retailer
        name = base_name
        suffix = 2
        while db.query(Store).filter_by(name=name).first():
            name = f"{base_name} ({suffix})"
            suffix += 1
        store = Store(
            retailer=candidate.retailer,
            name=name,
            postal_code=candidate.postal_code,
            city=candidate.city,
            address=candidate.address,
            latitude=candidate.latitude,
            longitude=candidate.longitude,
            active=True,
            benchmark_verified=False,
            external_id=candidate.source_external_id,
            source_url=candidate.source_url,
        )
        db.add(store)
        db.flush()
    else:
        store.postal_code = candidate.postal_code
        store.city = candidate.city
        store.address = candidate.address
        store.latitude = candidate.latitude
        store.longitude = candidate.longitude
        if not store.source_url:
            store.source_url = candidate.source_url

    now = datetime.utcnow()
    for member in physical_members:
        member.matched_store_id = store.id
        if candidate_ready_for_promotion(member):
            member.status = "promoted"
        member.updated_at = now

    candidate.matched_store_id = store.id
    candidate.status = "promoted"
    candidate.updated_at = now
    from .market_activation import register_promoted_store

    register_promoted_store(db, store, candidate)
    db.commit()
    db.refresh(store)
    return store
