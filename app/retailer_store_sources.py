from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import math
from typing import Iterable, Protocol

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .candidate_source_refresh import refresh_candidate_from_source
from .coverage_models import StoreDiscoveryCandidate
from .models import Store
from .postcode_coverage_service import addresses_match


SUPPORTED_RETAILERS: tuple[str, ...] = (
    "REWE",
    "Lidl",
    "ALDI SÜD",
    "Netto Marken-Discount",
    "EDEKA",
    "PENNY",
)

_COORDINATE_EVIDENCE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class RetailerStoreRecord:
    retailer: str
    name: str
    address: str
    postal_code: str
    city: str
    latitude: float | None
    longitude: float | None
    external_id: str | None
    source_url: str
    source_identifier: str


@dataclass(frozen=True)
class RetailerSourceResult:
    retailer: str
    status: str
    source_type: str
    source_url: str
    stores: tuple[RetailerStoreRecord, ...] = ()
    note: str = ""


class RetailerStoreSourceAdapter(Protocol):
    key: str
    retailer: str

    def stores_for_postcode(self, postal_code: str) -> RetailerSourceResult: ...


@dataclass(frozen=True)
class CuratedOfficialAdapter:
    key: str
    retailer: str
    directory_url: str
    records: tuple[RetailerStoreRecord, ...] = ()

    def stores_for_postcode(self, postal_code: str) -> RetailerSourceResult:
        matches = tuple(row for row in self.records if row.postal_code == postal_code)
        return RetailerSourceResult(
            retailer=self.retailer,
            status="manual_verification_required",
            source_type="official_retailer_directory",
            source_url=self.directory_url,
            stores=matches,
            note=(
                "Einzelne offizielle Marktseiten sind belastbar hinterlegt; "
                "die Vollständigkeit der PLZ muss im Händler-Filialfinder manuell bestätigt werden."
            ),
        )


CURATED_OFFICIAL_STORES: tuple[RetailerStoreRecord, ...] = (
    RetailerStoreRecord(
        retailer="REWE",
        name="REWE:XL Familie Hundertmark",
        address="Königsberger Str. 20-22",
        postal_code="56269",
        city="Dierdorf",
        latitude=50.5474,
        longitude=7.6506,
        external_id="321019",
        source_url="https://www.rewe.de/marktseite/dierdorf/321019/rewe-markt-koenigsberger-str-20-22/",
        source_identifier="rewe-market-321019",
    ),
    RetailerStoreRecord(
        retailer="REWE",
        name="PETZ REWE Bahnhofstr. 30",
        address="Bahnhofstr. 30",
        postal_code="57610",
        city="Altenkirchen",
        latitude=50.685665,
        longitude=7.638153,
        external_id="8534500",
        source_url="https://www.rewe.de/marktseite/altenkirchen/8534500/petz-rewe-bahnhofstr-30/",
        source_identifier="rewe-market-8534500",
    ),
    RetailerStoreRecord(
        retailer="REWE",
        name="PETZ REWE Dammweg 10",
        address="Dammweg 10",
        postal_code="57610",
        city="Altenkirchen",
        latitude=50.6894,
        longitude=7.64644,
        external_id="2500021",
        source_url="https://www.rewe.de/marktseite/altenkirchen/2500021/petz-rewe-dammweg-10/",
        source_identifier="rewe-market-2500021",
    ),
    RetailerStoreRecord(
        retailer="REWE",
        name="REWE Am Schwimmbad 1",
        address="Am Schwimmbad 1",
        postal_code="65618",
        city="Selters (Taunus)",
        latitude=50.333975,
        longitude=8.233875,
        external_id="240052",
        source_url="https://www.rewe.de/marktseite/selters-niederselters/240052/rewe-markt-am-schwimmbad-1/",
        source_identifier="rewe-market-240052",
    ),
    RetailerStoreRecord(
        retailer="REWE",
        name="REWE Dennis Weirich",
        address="Kirschbüchel 2",
        postal_code="56587",
        city="Straßenhaus",
        # Existing reviewed bootstrap/collection identity; REWE's market page
        # confirms the address and ID but does not publish a coordinate pair.
        latitude=50.5407,
        longitude=7.5187,
        external_id="1940425",
        source_url="https://www.rewe.de/marktseite/strassenhaus/1940425/rewe-markt-kirschbuechel-2/",
        source_identifier="rewe-market-1940425",
    ),
    RetailerStoreRecord(
        retailer="REWE",
        name="REWE Brotweg 1",
        address="Brotweg 1",
        postal_code="65606",
        city="Villmar",
        latitude=None,
        longitude=None,
        external_id="241184",
        source_url="https://www.rewe.de/marktseite/villmar/241184/rewe-markt-brotweg-1/",
        source_identifier="rewe-market-241184",
    ),
    RetailerStoreRecord(
        retailer="REWE",
        name="REWE In den Wallgärten 1",
        address="In den Wallgärten 1",
        postal_code="65611",
        city="Brechen",
        latitude=None,
        longitude=None,
        external_id="240076",
        source_url="https://www.rewe.de/marktseite/brechen-niederbrechen/240076/rewe-markt-in-den-wallgaerten-1/",
        source_identifier="rewe-market-240076",
    ),
    # ALDI SÜD's official environmental declaration lists these branches but
    # does not publish a retailer branch ID or coordinates. Coordinates are
    # therefore resolved from reviewed local evidence at staging time and the
    # external ID intentionally remains NULL. Where a concrete official branch
    # page is known, keep that stronger identity provenance on the record; the
    # page confirms branch/address identity, not the coordinate pair itself.
    *(
        RetailerStoreRecord(
            retailer="ALDI SÜD",
            name=f"ALDI SÜD {city}",
            address=address,
            postal_code=postal_code,
            city=city,
            latitude=None,
            longitude=None,
            external_id=None,
            source_url=source_url,
            source_identifier=f"aldi-sued-{postal_code}-{slug}",
        )
        for postal_code, city, address, slug, source_url in (
            (
                "56269",
                "Dierdorf",
                "Königsberger Straße 50",
                "koenigsberger-strasse-50",
                "https://s7g10.scene7.com/is/content/aldi/ALDI_SUED_Umwelterklaerung-2024.pdf",
            ),
            (
                "56587",
                "Oberhonnefeld-Gierend",
                "Über dem Stellweg 5",
                "ueber-dem-stellweg-5",
                "https://filialen.aldi-sued.de/rheinland-pfalz/oberhonnefeld-gierend/ueber-dem-stellweg-5",
            ),
            (
                "57610",
                "Altenkirchen",
                "Kölner Straße 30a",
                "koelner-strasse-30a",
                "https://s7g10.scene7.com/is/content/aldi/ALDI_SUED_Umwelterklaerung-2024.pdf",
            ),
            (
                "65611",
                "Brechen",
                "Kapellenstraße 88",
                "kapellenstrasse-88",
                "https://s7g10.scene7.com/is/content/aldi/ALDI_SUED_Umwelterklaerung-2024.pdf",
            ),
        )
    ),
    RetailerStoreRecord(
        retailer="Lidl",
        name="Lidl Puderbach",
        address="Urbacherstraße L264",
        postal_code="56305",
        city="Puderbach",
        latitude=50.592225,
        longitude=7.608542,
        external_id="lidl-puderbach-urbacherstr-l264",
        source_url="https://www.lidl.de/s/de-DE/filialen/puderbach/urbacherstr-l264/",
        source_identifier="lidl-puderbach-urbacherstr-l264",
    ),
    RetailerStoreRecord(
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        address="Urbacher Straße 35",
        postal_code="56305",
        city="Puderbach",
        latitude=50.591497,
        longitude=7.607809,
        external_id="071378",
        source_url="https://www.edeka.de/maerkte/071378/",
        source_identifier="edeka-market-071378",
    ),
)


def default_retailer_adapters() -> tuple[RetailerStoreSourceAdapter, ...]:
    directory_urls = {
        "REWE": "https://www.rewe.de/marktsuche",
        "Lidl": "https://www.lidl.de/c/filialsuche/s10007744",
        "ALDI SÜD": "https://www.aldi-sued.de/filialen.html",
        "Netto Marken-Discount": "https://www.netto-online.de/filialfinder",
        "EDEKA": "https://www.edeka.de/marktsuche.jsp",
        "PENNY": "https://www.penny.de/marktsuche/",
    }
    return tuple(
        CuratedOfficialAdapter(
            key=retailer.lower().replace(" ", "_").replace("-", "_").replace("ü", "ue"),
            retailer=retailer,
            directory_url=directory_urls[retailer],
            records=tuple(row for row in CURATED_OFFICIAL_STORES if row.retailer == retailer),
        )
        for retailer in SUPPORTED_RETAILERS
    )


def retailer_source_results(
    postal_code: str,
    adapters: Iterable[RetailerStoreSourceAdapter] | None = None,
) -> tuple[RetailerSourceResult, ...]:
    selected = tuple(default_retailer_adapters() if adapters is None else adapters)
    results: list[RetailerSourceResult] = []
    for adapter in selected:
        try:
            results.append(adapter.stores_for_postcode(postal_code))
        except Exception as exc:
            results.append(RetailerSourceResult(
                retailer=adapter.retailer,
                status="source_unavailable",
                source_type="official_retailer_source",
                source_url="",
                note=f"Adapter nicht verfügbar: {type(exc).__name__}",
            ))
    return tuple(results)


def _official_candidate_key(adapter_key: str, record: RetailerStoreRecord) -> str:
    raw = f"official|{adapter_key}|{record.source_identifier}|{record.retailer}".encode("utf-8")
    return sha256(raw).hexdigest()


def _unique_coordinates(
    rows: Iterable[Store | StoreDiscoveryCandidate],
    *,
    record: RetailerStoreRecord,
    evidence_label: str,
) -> tuple[float, float] | None:
    coordinate_pairs = [
        (float(row.latitude), float(row.longitude))
        for row in rows
        if row.latitude is not None and row.longitude is not None
    ]
    if not coordinate_pairs:
        return None

    preferred = coordinate_pairs[0]
    if all(
        math.isclose(lat, preferred[0], rel_tol=0.0, abs_tol=_COORDINATE_EVIDENCE_TOLERANCE)
        and math.isclose(lon, preferred[1], rel_tol=0.0, abs_tol=_COORDINATE_EVIDENCE_TOLERANCE)
        for lat, lon in coordinate_pairs[1:]
    ):
        return preferred

    raise RuntimeError(
        "Official source has no unique reviewed coordinate evidence for "
        f"{record.retailer} {record.postal_code} {record.address!r} "
        f"at tier {evidence_label}; conflicting {len(coordinate_pairs)} coordinate rows"
    )


def _record_coordinates(db: Session, record: RetailerStoreRecord) -> tuple[float, float]:
    """Resolve missing official coordinates from reviewed local identity data.

    Curated source data must never invent a pin. Evidence is first restricted to
    the concrete physical identity (retailer ID, exact reviewed address or a
    store-specific official URL when a real retailer ID exists). Within that
    identity, already public/benchmark-verified Stores stay canonical.

    A reviewed/locked candidate is next strongest. A current discovery candidate
    that matches both the exact address and the same store-specific official URL
    may outrank an inactive, unverified legacy Store: the URL corroborates which
    branch the candidate represents, while its coordinates still come from the
    discovery row. Conflicts inside the selected evidence tier remain fail-closed.
    """
    if record.latitude is not None and record.longitude is not None:
        return float(record.latitude), float(record.longitude)

    candidates = db.query(StoreDiscoveryCandidate).filter(
        StoreDiscoveryCandidate.retailer == record.retailer,
        StoreDiscoveryCandidate.postal_code == record.postal_code,
        StoreDiscoveryCandidate.status != "rejected",
    ).all()
    stores = db.query(Store).filter(
        Store.retailer == record.retailer,
        Store.postal_code == record.postal_code,
    ).all()

    record_source_url = (record.source_url or "").strip()

    def identity_match(row: Store | StoreDiscoveryCandidate) -> bool:
        return bool(
            (
                record.external_id
                and getattr(row, "source_external_id", None) == record.external_id
            )
            or (
                record.external_id
                and getattr(row, "external_id", None) == record.external_id
            )
            or addresses_match(getattr(row, "address", None), record.address)
            or (
                record.external_id
                and record_source_url
                and (getattr(row, "source_url", None) or "").strip() == record_source_url
            )
        )

    exact_stores = [row for row in stores if identity_match(row)]
    exact_candidates = [row for row in candidates if identity_match(row)]
    if not exact_stores and not exact_candidates:
        raise RuntimeError(
            "Official source has no unique reviewed coordinate evidence for "
            f"{record.retailer} {record.postal_code} {record.address!r}; no identity-matched rows"
        )

    canonical_stores = [
        row for row in exact_stores
        if bool(row.benchmark_verified)
    ]
    accepted_candidates = [
        row for row in exact_candidates
        if (
            row.matched_store_id is not None
            or row.status in {"verified", "promoted"}
            or row.address_verified
            or row.coordinates_verified
        )
    ]
    source_confirmed_candidates = [
        row for row in exact_candidates
        if (
            record_source_url
            and (row.source_url or "").strip() == record_source_url
            and addresses_match(row.address, record.address)
        )
    ]

    for label, evidence in (
        ("canonical_store", canonical_stores),
        ("accepted_candidate", accepted_candidates),
        ("source_confirmed_candidate", source_confirmed_candidates),
        ("identity_match", [*exact_stores, *exact_candidates]),
    ):
        resolved = _unique_coordinates(
            evidence,
            record=record,
            evidence_label=label,
        )
        if resolved is not None:
            return resolved

    raise RuntimeError(
        "Official source has no unique reviewed coordinate evidence for "
        f"{record.retailer} {record.postal_code} {record.address!r}; no coordinate rows"
    )


def _safe_staging_error(exc: Exception) -> str:
    """Return an operator-useful staging error without leaking SQL or parameters."""
    if isinstance(exc, IntegrityError):
        return "IntegrityError: Datenbank-Constraint verletzt"
    if isinstance(exc, SQLAlchemyError):
        return f"{type(exc).__name__}: Datenbankfehler"
    message = str(exc).strip()
    if isinstance(exc, RuntimeError) and message.startswith("Official source has "):
        return f"RuntimeError: {message}"
    if isinstance(exc, ValueError) and message:
        return f"ValueError: {message[:240]}"
    return type(exc).__name__


def stage_official_store_candidates(
    db: Session,
    postal_code: str,
    adapters: Iterable[RetailerStoreSourceAdapter] | None = None,
) -> tuple[int, int, tuple[RetailerSourceResult, ...]]:
    """Stage curated identities without one bad market blocking its siblings.

    Every retailer/market record runs in its own SAVEPOINT. A coordinate or
    refresh failure is reported in that retailer's returned source result while
    successful records are still committed. This keeps fail-closed identity
    validation at market level without making an entire postcode all-or-nothing.
    """
    created = updated = 0
    selected = tuple(default_retailer_adapters() if adapters is None else adapters)
    results = retailer_source_results(postal_code, selected)
    adapters_by_retailer = {adapter.retailer: adapter for adapter in selected}
    issues: dict[str, list[str]] = {}

    for result in results:
        adapter = adapters_by_retailer[result.retailer]
        for record in result.stores:
            if record.postal_code != postal_code:
                continue
            staged_action: str | None = None
            try:
                with db.begin_nested():
                    key = _official_candidate_key(adapter.key, record)
                    row = db.query(StoreDiscoveryCandidate).filter_by(discovery_key=key).first()
                    latitude, longitude = _record_coordinates(db, record)
                    values = {
                        "postal_code": record.postal_code,
                        "retailer": record.retailer,
                        "name": record.name,
                        "address": record.address,
                        "city": record.city,
                        "latitude": latitude,
                        "longitude": longitude,
                        "source": f"official:{adapter.key}",
                        # source_identifier is internal provenance, never a retailer ID.
                        "source_external_id": record.external_id,
                        "source_url": record.source_url,
                    }
                    if row is None:
                        row = StoreDiscoveryCandidate(
                            discovery_key=key,
                            official_source_verified=True,
                            verification_note=(
                                "Einzelmarkt aus offizieller Händlerseite; "
                                "PLZ-Vollständigkeit separat prüfen."
                            ),
                            **values,
                        )
                        db.add(row)
                        staged_action = "created"
                    else:
                        refresh_candidate_from_source(
                            row,
                            values,
                            reset_verification_on_identity_change=True,
                        )
                        row.official_source_verified = True
                        staged_action = "updated"
                    db.flush()
                if staged_action == "created":
                    created += 1
                elif staged_action == "updated":
                    updated += 1
            except Exception as exc:
                issues.setdefault(result.retailer, []).append(
                    f"{record.name} [{record.source_identifier}]: {_safe_staging_error(exc)}"
                )

    db.commit()

    enriched_results: list[RetailerSourceResult] = []
    for result in results:
        retailer_issues = issues.get(result.retailer, [])
        if not retailer_issues:
            enriched_results.append(result)
            continue
        issue_note = "Staging-Fehler: " + " | ".join(retailer_issues)
        note = f"{result.note} {issue_note}".strip()
        enriched_results.append(replace(result, status="partial_failure", note=note))

    return created, updated, tuple(enriched_results)
