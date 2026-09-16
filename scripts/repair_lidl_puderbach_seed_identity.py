#!/usr/bin/env python3
"""Repair the narrowly verified Lidl Puderbach identity damaged by startup seed data.

The production migration correctly established Store 16 from the official Lidl
candidate. A subsequent application startup then reapplied legacy bootstrap seed
coordinates and a ``None`` external ID. This operator script restores only those
identity fields from the already verified official candidate.

The script is dry-run by default and fails closed if the production evidence no
longer matches the reviewed state. Pass ``--apply`` for the single transactional
update after the seed overwrite bug itself has been deployed.
"""

from __future__ import annotations

import argparse
import math

from sqlalchemy import text

from app.db import SessionLocal


STORE_ID = 16
POSTAL_CODE = "56305"
RETAILER = "Lidl"
NAME = "Lidl Puderbach"
ADDRESS = "Urbacherstraße L264"
EXTERNAL_ID = "lidl-puderbach-urbacherstr-l264"
LEGACY_SEED_LATITUDE = 50.598
LEGACY_SEED_LONGITUDE = 7.615


def _close(left: float | None, right: float, *, tolerance: float = 1e-7) -> bool:
    return left is not None and math.isclose(float(left), right, abs_tol=tolerance)


def _abort(message: str) -> None:
    raise RuntimeError(message)


def _load_store(db):
    return db.execute(
        text(
            """
            SELECT id, retailer, name, postal_code, city, address, latitude,
                   longitude, active, benchmark_verified, external_id, source_url
            FROM stores
            WHERE id = :store_id
            """
        ),
        {"store_id": STORE_ID},
    ).mappings().first()


def _load_official_candidate(db):
    rows = db.execute(
        text(
            """
            SELECT id, matched_store_id, retailer, name, postal_code, city,
                   address, latitude, longitude, source, source_external_id,
                   source_url, status, address_verified, coordinates_verified,
                   official_source_verified
            FROM store_discovery_candidates
            WHERE matched_store_id = :store_id
              AND source_external_id = :external_id
            ORDER BY id
            """
        ),
        {"store_id": STORE_ID, "external_id": EXTERNAL_ID},
    ).mappings().all()
    if len(rows) != 1:
        _abort(
            "Expected exactly one official candidate for canonical Lidl Puderbach; "
            f"found {len(rows)}"
        )
    return rows[0]


def _validate(db, store, candidate) -> None:
    if store is None:
        _abort("Canonical Store 16 is missing")
    if store["retailer"] != RETAILER or store["postal_code"] != POSTAL_CODE:
        _abort(f"Store 16 identity changed unexpectedly: {dict(store)!r}")
    if store["name"] != NAME or store["address"] != ADDRESS:
        _abort(f"Store 16 name/address changed unexpectedly: {dict(store)!r}")
    if not bool(store["active"]) or bool(store["benchmark_verified"]):
        _abort("Store 16 activation flags no longer match the reviewed promoted state")
    if store["external_id"] not in {None, EXTERNAL_ID}:
        _abort(f"Store 16 has an unexpected external_id: {store['external_id']!r}")

    candidate_ok = (
        candidate["retailer"] == RETAILER
        and candidate["postal_code"] == POSTAL_CODE
        and candidate["name"] == NAME
        and candidate["address"] == ADDRESS
        and str(candidate["source"] or "").startswith("official:")
        and candidate["source_external_id"] == EXTERNAL_ID
        and candidate["status"] == "promoted"
        and bool(candidate["address_verified"])
        and bool(candidate["coordinates_verified"])
        and bool(candidate["official_source_verified"])
        and candidate["latitude"] is not None
        and candidate["longitude"] is not None
        and bool(candidate["source_url"])
    )
    if not candidate_ok:
        _abort(f"Official candidate no longer matches reviewed evidence: {dict(candidate)!r}")

    activation = db.execute(
        text(
            """
            SELECT lifecycle_status, identity_verified, last_test_run_id, published_at
            FROM store_activation_states
            WHERE store_id = :store_id
            """
        ),
        {"store_id": STORE_ID},
    ).mappings().first()
    if activation is None:
        _abort("Store 16 activation state is missing")
    if not (
        activation["lifecycle_status"] == "promoted"
        and bool(activation["identity_verified"])
        and activation["last_test_run_id"] is None
        and activation["published_at"] is None
    ):
        _abort(f"Store 16 activation state changed: {dict(activation)!r}")

    desired_lat = float(candidate["latitude"])
    desired_lon = float(candidate["longitude"])
    coords_are_desired = _close(store["latitude"], desired_lat) and _close(
        store["longitude"], desired_lon
    )
    coords_are_known_seed_damage = _close(
        store["latitude"], LEGACY_SEED_LATITUDE
    ) and _close(store["longitude"], LEGACY_SEED_LONGITUDE)
    if not (coords_are_desired or coords_are_known_seed_damage):
        _abort(
            "Store 16 coordinates are neither the verified candidate nor the known "
            f"legacy seed values: ({store['latitude']}, {store['longitude']})"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the reviewed one-row repair; otherwise run read-only validation.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        store = _load_store(db)
        candidate = _load_official_candidate(db)
        _validate(db, store, candidate)

        desired = {
            "external_id": candidate["source_external_id"],
            "latitude": float(candidate["latitude"]),
            "longitude": float(candidate["longitude"]),
            "source_url": candidate["source_url"],
        }
        print("validated_store=", dict(store))
        print("verified_candidate=", dict(candidate))
        print("desired_identity=", desired)

        already_correct = (
            store["external_id"] == desired["external_id"]
            and _close(store["latitude"], desired["latitude"])
            and _close(store["longitude"], desired["longitude"])
            and store["source_url"] == desired["source_url"]
        )
        if already_correct:
            print("action=no-op; Store 16 is already canonical")
            return 0

        if not args.apply:
            print("action=dry-run; re-run with --apply after deploying the seed fix")
            return 0

        result = db.execute(
            text(
                """
                UPDATE stores
                SET external_id = :external_id,
                    latitude = :latitude,
                    longitude = :longitude,
                    source_url = :source_url
                WHERE id = :store_id
                """
            ),
            {"store_id": STORE_ID, **desired},
        )
        if result.rowcount not in {1, -1}:
            _abort(f"Unexpected Store 16 update count: {result.rowcount}")
        db.commit()

        repaired = _load_store(db)
        if not (
            repaired is not None
            and repaired["external_id"] == desired["external_id"]
            and _close(repaired["latitude"], desired["latitude"])
            and _close(repaired["longitude"], desired["longitude"])
            and repaired["source_url"] == desired["source_url"]
        ):
            _abort(f"Post-repair verification failed: {dict(repaired) if repaired else None!r}")

        print("action=applied")
        print("repaired_store=", dict(repaired))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
