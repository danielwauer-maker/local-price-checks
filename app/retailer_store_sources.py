from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable, Protocol

from sqlalchemy.orm import Session

from .coverage_models import StoreDiscoveryCandidate


SUPPORTED_RETAILERS: tuple[str, ...] = (
    "REWE",
    "Lidl",
    "ALDI SÜD",
    "Netto Marken-Discount",
    "EDEKA",
    "PENNY",
)


@dataclass(frozen=True)
class RetailerStoreRecord:
    retailer: str
    name: str
    address: str
    postal_code: str
    city: str
    latitude: float
    longitude: float
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
        retailer="Lidl",
        name="Lidl Puderbach",
        address="Urbacherstraße L264",
        postal_code="56305",
        city="Puderbach",
        latitude=50.5980,
        longitude=7.6150,
        external_id=None,
        source_url="https://www.lidl.de/s/de-DE/filialen/puderbach/urbacherstr-l264/",
        source_identifier="lidl-puderbach-urbacherstr-l264",
    ),
    RetailerStoreRecord(
        retailer="EDEKA",
        name="EDEKA Fellenzer",
        address="Urbacher Straße 35",
        postal_code="56305",
        city="Puderbach",
        latitude=50.6000,
        longitude=7.6110,
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


def stage_official_store_candidates(
    db: Session,
    postal_code: str,
    adapters: Iterable[RetailerStoreSourceAdapter] | None = None,
) -> tuple[int, int, tuple[RetailerSourceResult, ...]]:
    created = updated = 0
    selected = tuple(default_retailer_adapters() if adapters is None else adapters)
    results = retailer_source_results(postal_code, selected)
    adapters_by_retailer = {adapter.retailer: adapter for adapter in selected}
    for result in results:
        adapter = adapters_by_retailer[result.retailer]
        for record in result.stores:
            if record.postal_code != postal_code:
                continue
            key = _official_candidate_key(adapter.key, record)
            row = db.query(StoreDiscoveryCandidate).filter_by(discovery_key=key).first()
            values = {
                "postal_code": record.postal_code,
                "retailer": record.retailer,
                "name": record.name,
                "address": record.address,
                "city": record.city,
                "latitude": record.latitude,
                "longitude": record.longitude,
                "source": f"official:{adapter.key}",
                "source_external_id": record.external_id or record.source_identifier,
                "source_url": record.source_url,
            }
            if row is None:
                row = StoreDiscoveryCandidate(
                    discovery_key=key,
                    official_source_verified=True,
                    verification_note="Einzelmarkt aus offizieller Händlerseite; PLZ-Vollständigkeit separat prüfen.",
                    **values,
                )
                db.add(row)
                created += 1
            else:
                identity_changed = any(getattr(row, field) != value for field, value in values.items())
                for field, value in values.items():
                    setattr(row, field, value)
                if identity_changed:
                    row.address_verified = False
                    row.coordinates_verified = False
                    row.status = "discovered"
                row.official_source_verified = True
                updated += 1
    db.commit()
    return created, updated, results
