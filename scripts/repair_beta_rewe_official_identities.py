#!/usr/bin/env python3
"""Fail-closed in-place repair for the reviewed public REWE stores 11 and 12.

Run without arguments for read-only validation. ``--apply`` changes only the
canonical Store identity, restores the legacy public ``active`` projection when
there is durable publication proof, and links the already staged official
candidate. No Store or history row is created, moved, or deleted.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import SessionLocal


@dataclass(frozen=True)
class RepairSpec:
    store_id: int
    postal_code: str
    city: str
    old_address: str
    old_external_id: str
    address: str
    external_id: str
    source_url: str


REPAIRS = (
    RepairSpec(
        store_id=11,
        postal_code="65606",
        city="Villmar",
        old_address="Brotweg 1",
        old_external_id="way/28313159",
        address="Brotweg 1",
        external_id="241184",
        source_url="https://www.rewe.de/marktseite/villmar/241184/rewe-markt-brotweg-1/",
    ),
    RepairSpec(
        store_id=12,
        postal_code="65611",
        city="Brechen",
        old_address="In den Wallgärten 4-8",
        old_external_id="way/28653743",
        address="In den Wallgärten 1",
        external_id="240076",
        source_url="https://www.rewe.de/marktseite/brechen-niederbrechen/240076/rewe-markt-in-den-wallgaerten-1/",
    ),
)


def _abort(message: str) -> None:
    raise RuntimeError(message)


def _store(db: Session, store_id: int):
    return db.execute(
        text(
            """SELECT id, retailer, name, postal_code, city, address, latitude,
                      longitude, active, benchmark_verified, external_id, source_url
               FROM stores WHERE id = :store_id"""
        ),
        {"store_id": store_id},
    ).mappings().first()


def _official_candidate(db: Session, spec: RepairSpec):
    rows = db.execute(
        text(
            """SELECT id, matched_store_id, retailer, postal_code, city, address,
                      latitude, longitude, source, source_external_id, source_url,
                      status, address_verified, coordinates_verified,
                      official_source_verified
               FROM store_discovery_candidates
               WHERE retailer = 'REWE' AND postal_code = :postal_code
                 AND source LIKE 'official:%' AND source_external_id = :external_id
               ORDER BY id"""
        ),
        {"postal_code": spec.postal_code, "external_id": spec.external_id},
    ).mappings().all()
    if len(rows) != 1:
        _abort(
            f"Store {spec.store_id}: expected exactly one official candidate "
            f"{spec.external_id}; found {len(rows)}"
        )
    return rows[0]


def _activation(db: Session, store_id: int):
    return db.execute(
        text(
            """SELECT store_id, lifecycle_status, identity_verified,
                      last_test_run_id, published_at, manually_suspended
               FROM store_activation_states WHERE store_id = :store_id"""
        ),
        {"store_id": store_id},
    ).mappings().first()


def _history_counts(db: Session, store_id: int) -> dict[str, int]:
    """Count every registered table that has a direct FK to stores.id."""
    # Inspect through the Session's current connection. Opening a second
    # inspector connection can interfere with an in-memory SQLite transaction.
    schema = inspect(db.connection())
    counts: dict[str, int] = {}
    for table_name in schema.get_table_names():
        columns = {column["name"] for column in schema.get_columns(table_name)}
        if "store_id" not in columns:
            continue
        foreign_keys = schema.get_foreign_keys(table_name)
        if not any(
            fk.get("referred_table") == "stores"
            and "store_id" in (fk.get("constrained_columns") or [])
            for fk in foreign_keys
        ):
            continue
        counts[table_name] = int(
            db.execute(
                text(f'SELECT COUNT(*) FROM "{table_name}" WHERE store_id = :store_id'),
                {"store_id": store_id},
            ).scalar_one()
        )
    return counts


def _validate(db: Session, spec: RepairSpec):
    store = _store(db, spec.store_id)
    if store is None:
        _abort(f"Store {spec.store_id} is missing")
    if store["retailer"] != "REWE":
        _abort(f"Store {spec.store_id} has unexpected retailer {store['retailer']!r}")
    if store["postal_code"] != spec.postal_code:
        _abort(f"Store {spec.store_id} has unexpected postcode {store['postal_code']!r}")
    if store["city"] != spec.city:
        _abort(f"Store {spec.store_id} has unexpected city {store['city']!r}")
    allowed_identities = {
        (spec.old_external_id, spec.old_address),
        (spec.external_id, spec.address),
    }
    if (store["external_id"], store["address"]) not in allowed_identities:
        _abort(f"Store {spec.store_id} identity is outside the reviewed states: {dict(store)!r}")
    if not bool(store["benchmark_verified"]):
        _abort(f"Store {spec.store_id} is no longer benchmark/public verified")

    activation = _activation(db, spec.store_id)
    if activation is None:
        _abort(f"Store {spec.store_id} activation state is missing")
    if not (
        activation["lifecycle_status"] == "public"
        and bool(activation["identity_verified"])
        and activation["published_at"] is not None
        and not bool(activation["manually_suspended"])
    ):
        _abort(f"Store {spec.store_id} activation state is not reviewed-public: {dict(activation)!r}")

    # Historical releases could leave Store.active=0 even though publication is
    # durably recorded in StoreActivationState and benchmark_verified stayed set.
    # That exact projection mismatch is repairable; any missing publication
    # evidence above still aborts before we touch the row.
    legacy_inactive_public_projection = not bool(store["active"])

    candidate = _official_candidate(db, spec)
    if candidate["matched_store_id"] not in {None, spec.store_id}:
        _abort(
            f"Official candidate {candidate['id']} is linked to unexpected "
            f"Store {candidate['matched_store_id']}"
        )
    if not (
        candidate["address"] == spec.address
        and candidate["city"] == spec.city
        and candidate["source_url"] == spec.source_url
        and bool(candidate["official_source_verified"])
        and candidate["latitude"] is not None
        and candidate["longitude"] is not None
    ):
        _abort(f"Official candidate {candidate['id']} is outside reviewed identity: {dict(candidate)!r}")
    return store, activation, candidate, legacy_inactive_public_projection


def _repair_beta_rewe_identities(db: Session, *, apply: bool = False) -> list[dict]:
    reports: list[dict] = []
    for spec in REPAIRS:
        store, activation, candidate, legacy_inactive_public_projection = _validate(db, spec)
        history_before = _history_counts(db, spec.store_id)
        activation_before = dict(activation)
        already_correct = (
            bool(store["active"])
            and store["external_id"] == spec.external_id
            and store["address"] == spec.address
            and store["source_url"] == spec.source_url
            and candidate["matched_store_id"] == spec.store_id
            and candidate["status"] == "promoted"
            and bool(candidate["address_verified"])
            and bool(candidate["coordinates_verified"])
        )
        reports.append({
            "store_id": spec.store_id,
            "before": dict(store),
            "candidate_id": candidate["id"],
            "legacy_inactive_public_projection": legacy_inactive_public_projection,
            "already_correct": already_correct,
        })
        if not apply or already_correct:
            continue

        db.execute(
            text(
                """UPDATE stores
                   SET address = :address, external_id = :external_id,
                       source_url = :source_url, active = 1
                   WHERE id = :store_id"""
            ),
            {
                "store_id": spec.store_id,
                "address": spec.address,
                "external_id": spec.external_id,
                "source_url": spec.source_url,
            },
        )
        db.execute(
            text(
                """UPDATE store_discovery_candidates
                   SET matched_store_id = :store_id, status = 'promoted',
                       address_verified = 1, coordinates_verified = 1,
                       official_source_verified = 1,
                       verification_note = :verification_note
                   WHERE id = :candidate_id"""
            ),
            {
                "store_id": spec.store_id,
                "candidate_id": candidate["id"],
                "verification_note": (
                    "Offizielle REWE-Identität geprüft; vorhandener Pin des bereits "
                    "veröffentlichten Store wurde unverändert übernommen, da die "
                    "Marktseite keine offiziellen Koordinaten veröffentlicht."
                ),
            },
        )
        db.flush()

        repaired, activation_after, repaired_candidate, projection_mismatch_after = _validate(db, spec)
        if projection_mismatch_after:
            _abort(f"Store {spec.store_id} active/public projection was not restored")
        if _history_counts(db, spec.store_id) != history_before:
            _abort(f"Store {spec.store_id} history/FK row counts changed unexpectedly")
        if dict(activation_after) != activation_before:
            _abort(f"Store {spec.store_id} activation/publication state changed")
        if not (
            bool(repaired["active"])
            and bool(repaired["benchmark_verified"])
            and repaired["external_id"] == spec.external_id
            and repaired["address"] == spec.address
            and repaired["source_url"] == spec.source_url
            and repaired_candidate["matched_store_id"] == spec.store_id
            and repaired_candidate["status"] == "promoted"
        ):
            _abort(f"Store {spec.store_id} post-repair validation failed")

    if apply:
        foreign_key_errors = db.execute(text("PRAGMA foreign_key_check")).all()
        if foreign_key_errors:
            _abort(f"foreign_key_check failed: {foreign_key_errors!r}")
        db.commit()
        db.expire_all()
    else:
        db.rollback()
        db.expire_all()
    return reports


def repair_beta_rewe_identities(db: Session, *, apply: bool = False) -> list[dict]:
    """Run the repair atomically, rolling back every failure for library callers."""
    try:
        return _repair_beta_rewe_identities(db, apply=apply)
    except Exception:
        db.rollback()
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        reports = repair_beta_rewe_identities(db, apply=args.apply)
        for report in reports:
            print(report)
        print("action=applied" if args.apply else "action=dry-run; no changes written")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
